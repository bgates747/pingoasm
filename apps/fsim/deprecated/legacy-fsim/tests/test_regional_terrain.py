from __future__ import annotations

import math
import unittest

from pingo_terrain.p3dm import make_container, parse_container
from pingo_terrain.regional_terrain import (
    BASE_TRIANGULAR_SPACING_M,
    CHUNK_WIDTH_M,
    MODEL_HALF_EXTENT_M,
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    REGIONAL_VERTICAL_ORIGIN_M,
    SKIRT_FLOOR_ELEVATION_M,
    WORLD_COLUMNS,
    WORLD_ROWS,
    WorldGrid,
    build_terrain_tile,
    lattice_point,
    lod_spec,
    predominant_category,
    selector_uv_words,
    triangular_topology,
)


def boundary_keys(topology):
    return {
        tuple(sorted((topology.keys[start], topology.keys[end])))
        for start, end, _ in topology.boundary_edges
    }


class RegionalTerrainTests(unittest.TestCase):
    def test_world_grid_and_row_major_identity_are_fixed(self) -> None:
        grid = WorldGrid()
        self.assertEqual(
            (grid.origin_east_m, grid.origin_north_m),
            (REGIONAL_ORIGIN_EAST_M, REGIONAL_ORIGIN_NORTH_M),
        )
        self.assertEqual((grid.columns, grid.rows), (WORLD_COLUMNS, WORLD_ROWS))
        self.assertEqual(grid.tile_id(0, 0), 0)
        self.assertEqual(grid.tile_id(WORLD_COLUMNS - 1, WORLD_ROWS - 1), 50_651)
        self.assertEqual(
            grid.tile_bounds(94, 146),
            (569_856, 4_174_848, 570_368, 4_175_360),
        )

    def test_lods_are_nested_global_hex_offset_lattices(self) -> None:
        grid = WorldGrid()
        self.assertAlmostEqual(BASE_TRIANGULAR_SPACING_M, 68.772476, places=5)
        for coarse_lod in (1, 2):
            coarse = lod_spec(coarse_lod)
            fine = lod_spec(coarse_lod - 1)
            for gy, gx in ((0, 0), (1, 3), (8, -2), (-5, 7)):
                coarse_point = lattice_point(grid, coarse, gy, gx)
                fine_point = lattice_point(
                    grid, fine, gy * 2, gx * 2 + (gy & 1)
                )
                self.assertAlmostEqual(coarse_point[0], fine_point[0], places=8)
                self.assertAlmostEqual(coarse_point[1], fine_point[1], places=8)

    def test_adjacent_chunks_share_exact_global_boundary_edges(self) -> None:
        grid = WorldGrid()
        for lod in range(3):
            with self.subTest(lod=lod):
                west = triangular_topology(grid, 93, 146, lod)
                east = triangular_topology(grid, 94, 146, lod)
                shared = boundary_keys(west) & boundary_keys(east)
                self.assertGreater(len(shared), 0)
                west_points = dict(zip(west.keys, west.points, strict=True))
                east_points = dict(zip(east.keys, east.points, strict=True))
                for edge in shared:
                    for key in edge:
                        self.assertEqual(west_points[key], east_points[key])

    def test_every_lod_clips_to_one_complete_nonoverlapping_square(self) -> None:
        grid = WorldGrid()
        tile_x, tile_y = 94, 146
        west, south, east, north = grid.tile_bounds(tile_x, tile_y)
        for lod in range(3):
            with self.subTest(lod=lod):
                topology = triangular_topology(grid, tile_x, tile_y, lod)
                area = 0.0
                for face in topology.faces:
                    a, b, c = (topology.points[index] for index in face)
                    area += abs(
                        (b[0] - a[0]) * (c[1] - a[1])
                        - (b[1] - a[1]) * (c[0] - a[0])
                    ) / 2.0
                self.assertAlmostEqual(area, CHUNK_WIDTH_M**2, places=3)
                for start, end, _owner in topology.boundary_edges:
                    for point in (topology.points[start], topology.points[end]):
                        self.assertTrue(
                            math.isclose(point[0], west, abs_tol=1e-6)
                            or math.isclose(point[0], east, abs_tol=1e-6)
                            or math.isclose(point[1], south, abs_tol=1e-6)
                            or math.isclose(point[1], north, abs_tol=1e-6)
                        )

    def test_tile_normalization_skirts_and_maximum_height_round_trip(self) -> None:
        grid = WorldGrid()
        topology = triangular_topology(grid, 94, 146, 0)
        elevations = tuple(
            2.0 + (east - 569_856) / 1000.0 + (north - 4_174_848) / 2000.0
            for east, north in topology.points
        )
        materials = tuple(index % 15 for index in range(len(topology.faces)))
        built = build_terrain_tile(
            grid,
            94,
            146,
            0,
            elevations_m=elevations,
            surface_materials=materials,
        )
        self.assertEqual(built.tile.meta.model_half_extent_m, MODEL_HALF_EXTENT_M)
        self.assertEqual(built.tile.meta.center_east_m, 94 * CHUNK_WIDTH_M + 256)
        self.assertEqual(built.tile.meta.center_north_m, 146 * CHUNK_WIDTH_M + 256)
        self.assertEqual(
            built.tile.meta.maximum_elevation_dm, math.ceil(max(elevations) * 10)
        )
        self.assertEqual(
            built.skirt_triangle_count, len(topology.boundary_edges) * 2
        )
        self.assertEqual(parse_container(make_container(built.tile)), built.tile)
        self.assertEqual(
            len(built.tile.uv_indices), len(built.tile.position_indices)
        )
        self.assertTrue(
            all(
                built.tile.uv_indices[index]
                == built.tile.uv_indices[index + 1]
                == built.tile.uv_indices[index + 2]
                for index in range(0, len(built.tile.uv_indices), 3)
            )
        )
        skirt_index_offset = len(topology.faces) * 3
        west, south, east, north = grid.tile_bounds(94, 146)
        for edge_index, (start, end, _owner) in enumerate(topology.boundary_edges):
            face_offset = skirt_index_offset + edge_index * 6
            face = built.tile.position_indices[face_offset : face_offset + 3]
            a, b, c = (built.tile.positions[index] for index in face)
            ab = tuple(b[index] - a[index] for index in range(3))
            ac = tuple(c[index] - a[index] for index in range(3))
            normal = (
                ab[1] * ac[2] - ab[2] * ac[1],
                ab[2] * ac[0] - ab[0] * ac[2],
                ab[0] * ac[1] - ab[1] * ac[0],
            )
            first, second = topology.points[start], topology.points[end]
            if math.isclose(first[0], west) and math.isclose(second[0], west):
                outward = (0, 0, 1)
            elif math.isclose(first[0], east) and math.isclose(second[0], east):
                outward = (0, 0, -1)
            elif math.isclose(first[1], south) and math.isclose(second[1], south):
                outward = (-1, 0, 0)
            else:
                self.assertTrue(math.isclose(first[1], north))
                self.assertTrue(math.isclose(second[1], north))
                outward = (1, 0, 0)
            self.assertGreater(
                sum(normal[index] * outward[index] for index in range(3)), 0
            )

    def test_uniform_extent_contains_regional_vertical_contract(self) -> None:
        for elevation in (-114.779747, 1335.914551):
            self.assertLessEqual(
                abs(elevation - REGIONAL_VERTICAL_ORIGIN_M), MODEL_HALF_EXTENT_M
            )

        grid = WorldGrid()
        topology = triangular_topology(grid, 94, 146, 2)
        built = build_terrain_tile(
            grid,
            94,
            146,
            2,
            elevations_m=(-114.779747,) * len(topology.points),
            surface_materials=(0,) * len(topology.faces),
        )
        self.assertEqual(built.mesh_minimum_elevation_m, SKIRT_FLOOR_ELEVATION_M)
        self.assertGreater(built.clamped_skirt_vertices, 0)

    def test_selector_words_resolve_to_all_fifteen_materials(self) -> None:
        def resolve(words: tuple[int, int]) -> int:
            u, v = words
            return ((65535 - v) * 3 // 65535) * 4 + (u * 3 // 65535)

        self.assertEqual(
            [resolve(selector_uv_words(material)) for material in range(15)],
            list(range(15)),
        )

    def test_predominant_category_uses_lowest_stable_tie_and_centroid(self) -> None:
        triangle = ((0.0, 0.0), (4.0, 0.0), (0.0, 4.0))
        category, nodata = predominant_category(
            triangle,
            (
                (0.5, 0.5, 42, False),
                (1.5, 0.5, 11, False),
                (3.5, 3.5, 95, False),
            ),
            centroid_lookup=lambda _x, _y: 24,
        )
        self.assertEqual(category, 11)
        self.assertFalse(nodata)
        fallback, _ = predominant_category(
            triangle,
            ((5.0, 5.0, 42, False),),
            centroid_lookup=lambda _x, _y: 24,
        )
        self.assertEqual(fallback, 24)


if __name__ == "__main__":
    unittest.main()
