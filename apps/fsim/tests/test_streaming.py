from __future__ import annotations

import unittest

from pingo_terrain.streaming import (
    DEFAULT_TERRAIN_SLOTS,
    DirectMappedTerrainRing,
    FloatingOriginPosition,
    POSITION_Q8_PER_METRE,
    RegionalGrid,
    TerrainResidentSet,
    assert_scene_budget,
    direct_mapped_terrain_slot,
    desired_tile_order,
    locate_absolute_q8,
    hex_radius_five_slot,
    tile_center_pingo_translation,
)


GRID = RegionalGrid(
    origin_east_m=521_728,
    origin_north_m=4_100_096,
    columns=201,
    rows=252,
)


class FloatingOriginTests(unittest.TestCase):
    def test_regional_grid_pins_power_of_two_runtime_units(self) -> None:
        self.assertEqual(GRID.tile_counts, 8192)
        self.assertEqual(GRID.tile_position_q8, 0x200000)
        self.assertEqual(GRID.half_tile_position_q8, 0x100000)

    def test_absolute_round_trip_and_boundary_convention(self) -> None:
        points = (
            (GRID.origin_east_m, GRID.origin_north_m),
            (GRID.origin_east_m + 256, GRID.origin_north_m + 256),
            (GRID.origin_east_m + 512, GRID.origin_north_m + 512),
            (GRID.origin_east_m + 12_345, GRID.origin_north_m + 54_321),
        )
        for east_m, north_m in points:
            with self.subTest(east_m=east_m, north_m=north_m):
                absolute = (
                    east_m * POSITION_Q8_PER_METRE,
                    north_m * POSITION_Q8_PER_METRE,
                )
                position = locate_absolute_q8(GRID, *absolute)
                self.assertTrue(position.is_canonical(GRID))
                self.assertEqual(position.absolute_q8(GRID), absolute)

        southwest = locate_absolute_q8(
            GRID,
            GRID.origin_east_m * POSITION_Q8_PER_METRE,
            GRID.origin_north_m * POSITION_Q8_PER_METRE,
        )
        self.assertEqual((southwest.tile_x, southwest.tile_y), (0, 0))
        self.assertEqual(
            (southwest.east_q8, southwest.north_q8),
            (-GRID.half_tile_position_q8, -GRID.half_tile_position_q8),
        )

    def test_integration_rebases_by_whole_cells_without_a_jump(self) -> None:
        start = FloatingOriginPosition(50, 80, 0, 0)
        before = start.absolute_q8(GRID)
        delta_x = GRID.tile_position_q8 * 2 + 123
        delta_z = -(GRID.tile_position_q8 + 456)
        end, displacement = start.integrate_pingo_q8(GRID, delta_x, delta_z)
        self.assertEqual(displacement, (1, 2))
        self.assertEqual(end.east_q8, 456)
        self.assertEqual(end.north_q8, 123)
        after = end.absolute_q8(GRID)
        self.assertEqual(after[0] - before[0], -delta_z)
        self.assertEqual(after[1] - before[1], delta_x)

    def test_pingo_camera_and_tile_axes_are_north_up_minus_east(self) -> None:
        position = FloatingOriginPosition(
            100,
            120,
            32 * 256,
            -48 * 256,
        )
        self.assertEqual(position.pingo_x_count, -48)
        self.assertEqual(position.pingo_z_count, -32)
        self.assertEqual(
            tile_center_pingo_translation(GRID, position, 102, 119),
            (-8192, -16384),
        )

    def test_transform_window_rejects_a_four_cell_offset(self) -> None:
        position = FloatingOriginPosition(100, 120, 0, 0)
        self.assertEqual(
            tile_center_pingo_translation(GRID, position, 103, 123),
            (24576, -24576),
        )
        with self.assertRaises(OverflowError):
            tile_center_pingo_translation(GRID, position, 96, 120)


class StreamingPolicyTests(unittest.TestCase):
    def test_world_path_is_row_major_and_8_3_safe(self) -> None:
        self.assertEqual(str(GRID.terrain_path(0, 0, 0)), "TRN/L0/00/00.AGN")
        tile_id = 200 * GRID.columns + 123
        self.assertEqual(
            str(GRID.terrain_path(2, 123, 200)),
            f"TRN/L2/{tile_id >> 8:02X}/{tile_id & 255:02X}.AGN",
        )

    def test_desired_order_prioritizes_current_then_predicted_cell(self) -> None:
        position = FloatingOriginPosition(100, 120, 0, 0)
        eastbound = desired_tile_order(
            GRID,
            position,
            velocity_east_q8=1,
            radius=2,
            limit=DEFAULT_TERRAIN_SLOTS,
        )
        self.assertEqual(eastbound[0], (100, 120))
        self.assertEqual(eastbound[1], (101, 120))
        self.assertEqual(len(eastbound), 25)

        northwest = desired_tile_order(
            GRID,
            position,
            velocity_east_q8=-1,
            velocity_north_q8=1,
            radius=2,
            limit=3,
        )
        self.assertEqual(northwest[:2], ((100, 120), (99, 121)))

    def test_world_edges_clip_without_duplicate_tiles(self) -> None:
        corner = FloatingOriginPosition(0, 0, 0, 0)
        desired = desired_tile_order(GRID, corner, radius=2, limit=25)
        self.assertEqual(len(desired), 9)
        self.assertEqual(len(desired), len(set(desired)))
        self.assertTrue(all(GRID.contains(*tile) for tile in desired))

        outside = FloatingOriginPosition(-4, -4, 0, 0)
        self.assertEqual(desired_tile_order(GRID, outside, radius=2), ())

    def test_slot_publication_and_abort_are_transactional(self) -> None:
        residents = TerrainResidentSet(slot_count=2)
        first = residents.plan_one(((10, 10), (11, 10)))
        self.assertIsNotNone(first)
        residents.commit(first)  # type: ignore[arg-type]
        second = residents.plan_one(((10, 10), (11, 10)))
        residents.commit(second)  # type: ignore[arg-type]
        self.assertEqual(residents.resident_tiles(), {(10, 10), (11, 10)})

        replacement = residents.plan_one(((12, 10), (11, 10)))
        self.assertEqual(replacement.evicted_tile, (10, 10))  # type: ignore[union-attr]
        snapshot = residents.slots
        residents.abort(replacement)  # type: ignore[arg-type]
        self.assertEqual(residents.slots, snapshot)

        replacement = residents.plan_one(((12, 10), (11, 10)))
        residents.commit(replacement)  # type: ignore[arg-type]
        self.assertEqual(residents.resident_tiles(), {(12, 10), (11, 10)})

        deactivate = residents.plan_one(((12, 10),))
        self.assertFalse(deactivate.is_load)  # type: ignore[union-attr]
        residents.commit(deactivate)  # type: ignore[arg-type]
        self.assertEqual(residents.resident_tiles(), {(12, 10)})

    def test_slot_service_loads_at_most_one_missing_tile(self) -> None:
        residents = TerrainResidentSet(slot_count=3)
        desired = ((5, 5), (6, 5), (7, 5))
        for expected_count in (1, 2, 3):
            plan = residents.plan_one(desired)
            self.assertIsNotNone(plan)
            residents.commit(plan)  # type: ignore[arg-type]
            self.assertEqual(len(residents.resident_tiles()), expected_count)
        self.assertIsNone(residents.plan_one(desired))

    def test_active_scene_budget_is_explicit(self) -> None:
        assert_scene_budget(25, 6, 1)
        assert_scene_budget(121, 7, 1, 4)
        assert_scene_budget(65_535, 1, 0)
        with self.assertRaisesRegex(ValueError, "65537 objects"):
            assert_scene_budget(65_535, 1, 1)

    def test_hex_radius_five_has_a_perfect_translation_stable_slot_map(self) -> None:
        offsets = tuple(
            (q, r)
            for q in range(-5, 6)
            for r in range(-5, 6)
            if max(abs(q), abs(r), abs(-q - r)) <= 5
        )
        self.assertEqual(len(offsets), 91)
        for center in ((0, 0), (90, 121), (213, 127), (-17, 400)):
            slots = {
                hex_radius_five_slot(center[0] + q, center[1] + r)
                for q, r in offsets
            }
            self.assertEqual(slots, set(range(91)))

    def test_direct_mapped_five_by_five_neighborhood_is_injective(self) -> None:
        for center_x, center_y in ((2, 2), (94, 146), (198, 249)):
            slots = {
                direct_mapped_terrain_slot(center_x + dx, center_y + dy)
                for dy in range(-2, 3)
                for dx in range(-2, 3)
            }
            self.assertEqual(slots, set(range(25)))

    def test_direct_ring_follows_priority_and_retains_old_slot_on_abort(self) -> None:
        position = FloatingOriginPosition(94, 146, 0, 0)
        desired = desired_tile_order(
            GRID,
            position,
            velocity_east_q8=-1,
            velocity_north_q8=1,
        )
        ring = DirectMappedTerrainRing()
        first = ring.plan_one(desired)
        self.assertEqual(first.tile, (94, 146))  # type: ignore[union-attr]
        ring.commit(first)  # type: ignore[arg-type]
        second = ring.plan_one(desired)
        self.assertEqual(second.tile, (93, 147))  # type: ignore[union-attr]
        snapshot = ring.slots
        ring.abort(second)  # type: ignore[arg-type]
        self.assertEqual(ring.slots, snapshot)

    def test_direct_ring_replaces_only_new_edge_then_deactivates_obsolete(self) -> None:
        ring = DirectMappedTerrainRing()
        old = tuple((x, y) for y in range(10, 15) for x in range(10, 15))
        while (plan := ring.plan_one(old)) is not None:
            ring.commit(plan)
        self.assertEqual(ring.resident_tiles(), set(old))

        new = tuple((x, y) for y in range(10, 15) for x in range(11, 16))
        replacement_count = 0
        while (plan := ring.plan_one(new)) is not None:
            if plan.tile is not None:
                replacement_count += 1
            ring.commit(plan)
        self.assertEqual(replacement_count, 5)
        self.assertEqual(ring.resident_tiles(), set(new))

        clipped = tuple(tile for tile in new if tile[1] <= 12)
        deactivation_count = 0
        while (plan := ring.plan_one(clipped)) is not None:
            self.assertIsNone(plan.tile)
            deactivation_count += 1
            ring.commit(plan)
        self.assertEqual(deactivation_count, 10)
        self.assertEqual(ring.resident_tiles(), set(clipped))


if __name__ == "__main__":
    unittest.main()
