from __future__ import annotations

import math
import unittest

from pingo_terrain.hex_terrain import (
    COUNTS_PER_METRE,
    HEX_AREA_M2,
    HEX_BASIS_Q_EAST_M,
    HEX_BASIS_Q_NORTH_M,
    HEX_BASIS_R_NORTH_M,
    HEX_CELL_COUNT,
    HEX_EVEN_COLUMN_ROWS,
    HEX_MODEL_HALF_EXTENT_M,
    HEX_OBJECT_SCALE_Q8_8,
    HEX_ODD_COLUMN_ROWS,
    HEX_Q_MAX,
    HEX_SIDE_M,
    SQUARE_CONTROL_AREA_M2,
    HexCell,
    build_hex_terrain_cell,
    cell_from_id,
    disk_offsets,
    hex_distance,
    hex_corners_counts,
    hex_topology,
    iter_cells,
    locate_hex_cell,
    locate_hex_cell_counts,
    ring_offsets,
    rows_for_q,
)
from pingo_terrain.p3dm import make_container, make_data, parse_container
from pingo_terrain.regional_terrain import (
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
)


class HexGridTests(unittest.TestCase):
    def test_profile_is_near_equal_area_and_p3dm_v1_exact(self) -> None:
        self.assertEqual(HEX_SIDE_M, 320)
        self.assertEqual(
            (HEX_BASIS_Q_EAST_M, HEX_BASIS_Q_NORTH_M, HEX_BASIS_R_NORTH_M),
            (480, 275, 550),
        )
        self.assertLess(abs(HEX_AREA_M2 / SQUARE_CONTROL_AREA_M2 - 1.0), 0.008)
        self.assertEqual(HEX_MODEL_HALF_EXTENT_M, 1024)
        self.assertEqual(HEX_OBJECT_SCALE_Q8_8, 32768)

    def test_dense_cell_id_is_a_complete_bijection(self) -> None:
        cells = tuple(iter_cells())
        self.assertEqual(len(cells), HEX_CELL_COUNT)
        self.assertEqual(len(set(cells)), HEX_CELL_COUNT)
        self.assertEqual(
            HEX_CELL_COUNT,
            ((HEX_Q_MAX + 2) // 2) * HEX_EVEN_COLUMN_ROWS
            + ((HEX_Q_MAX + 1) // 2) * HEX_ODD_COLUMN_ROWS,
        )
        self.assertEqual([cell.cell_id for cell in cells], list(range(HEX_CELL_COUNT)))
        for cell_id in (0, 234, 235, 468, 469, 25_091, HEX_CELL_COUNT - 1):
            self.assertEqual(cell_from_id(cell_id).cell_id, cell_id)

    def test_axial_rows_are_staggered_without_coverage_holes(self) -> None:
        for q in range(HEX_Q_MAX + 1):
            expected = HEX_ODD_COLUMN_ROWS if q & 1 else HEX_EVEN_COLUMN_ROWS
            self.assertEqual(rows_for_q(q), expected)
            column = [cell for cell in iter_cells() if cell.q == q]
            self.assertEqual(len(column), expected)
            northings = [cell.center_m[1] for cell in column]
            self.assertEqual(
                northings,
                list(range(northings[0], northings[0] + expected * 550, 550)),
            )

    def test_rings_and_disks_are_complete_and_center_first(self) -> None:
        for radius in range(6):
            ring = ring_offsets(radius)
            disk = disk_offsets(radius)
            self.assertEqual(len(ring), 1 if radius == 0 else 6 * radius)
            self.assertEqual(len(disk), 1 + 3 * radius * (radius + 1))
            self.assertEqual(disk[0], (0, 0))
            self.assertEqual(len(set(disk)), len(disk))
            self.assertTrue(
                all(hex_distance((0, 0), offset) <= radius for offset in disk)
            )

    def test_position_lookup_uses_exact_polygons_and_lexicographic_ties(self) -> None:
        cell = HexCell(90, 121)
        self.assertEqual(locate_hex_cell(*cell.center_m), cell)
        # The accepted Campanile start lies inside this axial cell.
        self.assertEqual(locate_hex_cell(565_276.625, 4_191_883.9375), cell)

        neighbor = HexCell(cell.q + 1, cell.r)
        shared = sorted(
            set(hex_corners_counts(cell.q, cell.r))
            & set(hex_corners_counts(neighbor.q, neighbor.r))
        )
        self.assertEqual(len(shared), 2)
        midpoint = tuple((first + second) // 2 for first, second in zip(*shared))
        self.assertEqual(
            locate_hex_cell_counts(*midpoint),
            min(cell, neighbor, key=lambda item: (item.q, item.r)),
        )


class HexTopologyTests(unittest.TestCase):
    CELL = HexCell(100, 50)

    def test_n5_topology_has_expected_budget_and_upward_winding(self) -> None:
        topology = hex_topology(self.CELL.q, self.CELL.r)
        self.assertEqual(len(topology.keys), 91)
        self.assertEqual(len(topology.faces), 150)
        self.assertEqual(len(topology.boundary_edges), 30)
        for face in topology.faces:
            a, b, c = (topology.keys[index] for index in face)
            ab_x, ab_z = b[1] - a[1], -(b[0] - a[0])
            ac_x, ac_z = c[1] - a[1], -(c[0] - a[0])
            self.assertGreater(ab_z * ac_x - ab_x * ac_z, 0)

    def test_all_six_neighbors_share_six_exact_count_keys(self) -> None:
        topology = hex_topology(self.CELL.q, self.CELL.r)
        keys = set(topology.keys)
        for dq, dr in ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)):
            neighbor = hex_topology(self.CELL.q + dq, self.CELL.r + dr)
            self.assertEqual(len(keys.intersection(neighbor.keys)), 6)

    def test_each_runtime_boundary_side_is_straight_not_sawtoothed(self) -> None:
        topology = hex_topology(self.CELL.q, self.CELL.r)
        corners = hex_corners_counts(self.CELL.q, self.CELL.r)
        boundary_pairs = {
            frozenset((topology.keys[start], topology.keys[end]))
            for start, end, _owner in topology.boundary_edges
        }
        claimed_edges: set[frozenset[tuple[int, int]]] = set()
        for first, second in zip(corners, corners[1:] + corners[:1], strict=True):
            delta = second[0] - first[0], second[1] - first[1]
            vertices = []
            for point in topology.keys:
                relative = point[0] - first[0], point[1] - first[1]
                cross = delta[0] * relative[1] - delta[1] * relative[0]
                dot = delta[0] * relative[0] + delta[1] * relative[1]
                if cross == 0 and 0 <= dot <= delta[0] ** 2 + delta[1] ** 2:
                    vertices.append((dot, point))
            vertices.sort()
            self.assertEqual(len(vertices), 6)
            side_edges = {
                frozenset((vertices[index][1], vertices[index + 1][1]))
                for index in range(5)
            }
            self.assertTrue(side_edges <= boundary_pairs)
            claimed_edges.update(side_edges)
        self.assertEqual(claimed_edges, boundary_pairs)

    def test_three_cell_corner_uses_one_canonical_key(self) -> None:
        first = set(hex_topology(self.CELL.q, self.CELL.r).keys)
        second = set(hex_topology(self.CELL.q + 1, self.CELL.r).keys)
        third = set(hex_topology(self.CELL.q, self.CELL.r + 1).keys)
        self.assertEqual(len(first & second & third), 1)

    def test_encoded_shared_vertices_reconstruct_identically_in_pingo(self) -> None:
        cells = (self.CELL, HexCell(self.CELL.q + 1, self.CELL.r))
        built = []
        for cell in cells:
            topology = hex_topology(cell.q, cell.r)
            elevations = [
                100.0 + ((east // 16 + north // 16) % 7) / 16.0
                for east, north in topology.keys
            ]
            built.append(
                (topology, build_hex_terrain_cell(
                    cell.q,
                    cell.r,
                    elevations_m=elevations,
                    surface_materials=[0] * len(topology.faces),
                ))
            )
        shared = set(built[0][0].keys) & set(built[1][0].keys)
        self.assertEqual(len(shared), 6)
        reconstructed = []
        for topology, result in built:
            center_east_count = (
                result.tile.meta.center_east_m + REGIONAL_ORIGIN_EAST_M
            ) * COUNTS_PER_METRE
            center_north_count = (
                result.tile.meta.center_north_m + REGIONAL_ORIGIN_NORTH_M
            ) * COUNTS_PER_METRE
            by_key = {}
            for index, key in enumerate(topology.keys):
                x, _y, z = result.tile.positions[index]
                # Common denominator 32767: command-52 contributes count*256;
                # scale 32768 contributes encoded vertex*128.
                by_key[key] = (
                    center_north_count * 256 + x * 128,
                    -center_east_count * 256 + z * 128,
                )
            reconstructed.append(by_key)
        for key in shared:
            self.assertEqual(reconstructed[0][key], reconstructed[1][key])

    def test_p3dm_round_trip_and_exact_size_budget(self) -> None:
        topology = hex_topology(self.CELL.q, self.CELL.r)
        built = build_hex_terrain_cell(
            self.CELL.q,
            self.CELL.r,
            elevations_m=[100.0] * len(topology.keys),
            surface_materials=[0] * len(topology.faces),
        )
        self.assertEqual(len(built.tile.positions), 121)
        self.assertEqual(len(built.tile.position_indices) // 3, 210)
        self.assertEqual(len(make_data(built.tile)), 3310)
        container = make_container(built.tile)
        self.assertEqual(len(container), 3412)
        self.assertEqual(parse_container(container), built.tile)
        self.assertTrue(math.isfinite(built.mesh_minimum_elevation_m))


if __name__ == "__main__":
    unittest.main()
