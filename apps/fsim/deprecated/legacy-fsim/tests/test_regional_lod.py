from __future__ import annotations

import math
from pathlib import PurePosixPath
import unittest

from pingo_terrain.regional_lod import (
    DISTANT_MODEL_HALF_EXTENT_M,
    PINGO_CURRENT_FAR_METRES,
    SuperTileGrid,
    active_plan,
    build_component,
    component_specs,
    make_bundle,
    parse_bundle,
    rectangular_topology,
    wide_wire_witness,
)
from pingo_terrain.regional_terrain import WorldGrid


def surface_area(topology) -> float:
    area = 0.0
    for face in topology.faces:
        points = [topology.points[index] for index in face]
        area += abs(
            sum(
                first[0] * second[1] - second[0] * first[1]
                for first, second in zip(points, points[1:] + points[:1], strict=True)
            )
        ) / 2.0
    return area


class RegionalLodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = WorldGrid()
        self.grid = SuperTileGrid(self.base)
        self.koak = self.grid.supertile(23, 36)

    def test_world_grouping_and_83_path_cover_residual_east_strip(self) -> None:
        self.assertEqual((self.grid.columns, self.grid.rows), (51, 63))
        self.assertEqual(self.grid.columns * self.grid.rows, 3_213)
        final = self.grid.supertile(50, 62)
        self.assertEqual(
            (final.rectangle.width_cells, final.rectangle.height_cells),
            (1, 4),
        )
        self.assertEqual(self.grid.path(50, 62), PurePosixPath("RGN/0C/8C.AGN"))
        for part in self.grid.path(50, 62).parts:
            if "." in part:
                stem, suffix = part.split(".")
                self.assertLessEqual(len(stem), 8)
                self.assertLessEqual(len(suffix), 3)
            else:
                self.assertLessEqual(len(part), 8)

    def test_family_has_two_coarse_records_then_eight_bounded_near_strips(self) -> None:
        specs = component_specs(self.koak)
        self.assertEqual([spec.key for spec in specs[:2]], ["D2", "D1"])
        self.assertEqual(len(specs), 10)
        self.assertTrue(
            all(
                spec.model_half_extent_m == DISTANT_MODEL_HALF_EXTENT_M
                for spec in specs[:2]
            )
        )
        near = specs[2:]
        self.assertEqual(len(near), 8)
        self.assertTrue(
            all(
                (spec.rectangle.width_cells, spec.rectangle.height_cells) == (2, 1)
                for spec in near
            )
        )

    def test_rectangular_topology_has_exact_area_and_shared_boundary(self) -> None:
        west, east = component_specs(self.koak)[2:4]
        left = rectangular_topology(self.base, west.rectangle, 0)
        right = rectangular_topology(self.base, east.rectangle, 0)
        expected = 1_024 * 512
        self.assertAlmostEqual(surface_area(left), expected, places=3)
        self.assertAlmostEqual(surface_area(right), expected, places=3)
        boundary_east = self.base.origin_east_m + 94 * 512
        left_keys = {
            key
            for key, point in zip(left.keys, left.points, strict=True)
            if math.isclose(point[0], boundary_east, abs_tol=1e-6)
        }
        right_keys = {
            key
            for key, point in zip(right.keys, right.points, strict=True)
            if math.isclose(point[0], boundary_east, abs_tol=1e-6)
        }
        self.assertEqual(left_keys, right_keys)

    def test_pinned_layout_round_trips_as_multi_record_agnb(self) -> None:
        built = []
        for spec in component_specs(self.koak):
            topology = rectangular_topology(self.base, spec.rectangle, spec.lod)
            built.append(
                build_component(
                    self.base,
                    spec,
                    elevations_m=[3.0] * len(topology.points),
                    surface_materials=[0] * len(topology.faces),
                )
            )
        bundle = make_bundle(tuple(item.tile for item in built))
        parsed, spans = parse_bundle(bundle)
        self.assertEqual(parsed, tuple(item.tile for item in built))
        self.assertEqual(len(spans), 10)
        self.assertEqual([tile.meta.lod for tile in parsed[:2]], [2, 1])
        self.assertTrue(all(span.data_bytes <= 16_384 for span in spans))
        self.assertTrue(
            all(
                span.list_offset < span.data_offset < len(bundle)
                for span in spans
            )
        )
        corrupted = bytearray(bundle)
        corrupted[spans[0].data_offset] ^= 0x01
        with self.assertRaisesRegex(ValueError, "CRC"):
            parse_bundle(bytes(corrupted))
        with self.assertRaisesRegex(ValueError, "size"):
            parse_bundle(bundle[:-1])

    def test_active_plan_preserves_scene_headroom_and_lod_transition(self) -> None:
        plan = active_plan(self.grid, 23, 36, heading_east=1.0)
        self.assertEqual(
            (len(plan.near), len(plan.transition), len(plan.distant)),
            (8, 8, 8),
        )
        self.assertEqual(plan.terrain_count, 24)
        self.assertEqual(plan.scene_count(), 27)
        self.assertEqual(
            plan.scene_count(airport_components=6, landmark_components=1),
            32,
        )
        self.assertTrue(
            all(
                max(abs(item.super_x - 23), abs(item.super_y - 36)) == 1
                for item in plan.transition
            )
        )
        self.assertTrue(
            all(
                max(abs(item.super_x - 23), abs(item.super_y - 36)) >= 2
                for item in plan.distant
            )
        )
        with self.assertRaisesRegex(ValueError, "exceed"):
            plan.scene_count(airport_components=6, landmark_components=2)

    def test_whole_bay_requires_wider_translations_and_far_plane(self) -> None:
        # KOAK threshold to Mount Diablo, rounded from the pinned UTM witnesses.
        witness = wide_wire_witness(25_512, 17_936)
        self.assertFalse(witness.fits_signed_word)
        self.assertTrue(witness.fits_signed_24)
        self.assertGreater(witness.distance_m, PINGO_CURRENT_FAR_METRES)
        self.assertFalse(witness.inside_current_far_plane)


if __name__ == "__main__":
    unittest.main()
