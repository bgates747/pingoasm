from __future__ import annotations

import unittest

from pingo_terrain.family_transition import (
    FixedTransitionRuntime,
    KOAK_CURRENT_FAMILY,
    KOAK_NEXT_WEST_FAMILY,
    assembly_include,
    build_fixed_west_transition,
    component_wire_request,
)
from pingo_terrain.regional_lod import ActiveComponent, SuperTileGrid


class FixedWestFamilyTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = SuperTileGrid()
        self.transition = build_fixed_west_transition(self.grid)

    def test_wire_identities_paths_and_record_order_are_exact(self) -> None:
        distant = component_wire_request(
            self.grid, ActiveComponent("distant", 23, 36, "D2")
        )
        transition = component_wire_request(
            self.grid, ActiveComponent("transition", 23, 36, "D1")
        )
        near = component_wire_request(
            self.grid, ActiveComponent("near", 23, 36, "N06")
        )
        self.assertEqual(distant.path.as_posix(), "RGN/07/43.AGN")
        self.assertEqual(
            (distant.record_index, transition.record_index, near.record_index),
            (0, 1, 8),
        )
        self.assertEqual(
            (distant.expected.lod, transition.expected.lod, near.expected.lod),
            (2, 1, 0),
        )
        self.assertEqual(
            (distant.expected.tile_x, distant.expected.tile_y), (92, 144)
        )
        self.assertEqual((near.expected.tile_x, near.expected.tile_y), (92, 147))
        self.assertEqual(
            (
                distant.expected.layer_kind,
                distant.expected.shading_mode,
                distant.expected.illumination,
                distant.expected.material_set,
            ),
            (0, 2, 0, 0),
        )

    def test_fixed_slot_layout_and_required_family_union_are_pinned(self) -> None:
        plan = self.transition
        self.assertEqual([item.slot for item in plan.boot_near], list(range(1, 9)))
        self.assertEqual(
            [item.slot for item in plan.preload_next_near], list(range(9, 17))
        )
        self.assertEqual(
            [item.slot for item in plan.reconcile_transition], list(range(17, 25))
        )
        self.assertEqual(
            [item.slot for item in plan.preload_plan_delta], [25, 26, 27, 28, 37]
        )
        self.assertEqual(
            [item.slot for item in plan.reconcile_distant], list(range(29, 37))
        )
        self.assertEqual(len(plan.load_entries), 37)
        self.assertEqual(len(plan.required_families), 20)
        self.assertEqual(plan.required_families[0], (21, 35))
        self.assertEqual(plan.required_families[-1], (24, 37))

    def test_render_idle_swap_is_hole_free_and_never_exceeds_24_terrain(self) -> None:
        plan = self.transition
        resident = {entry.slot: entry.request.component for entry in plan.load_entries}
        active = {
            entry.slot
            for entry in plan.load_entries
            if entry.activate_after_load
        }
        self.assertEqual(len(active), 24)
        self.assertEqual(
            {resident[slot] for slot in active},
            set(
                plan.current_plan.near
                + plan.current_plan.transition
                + plan.current_plan.distant
            ),
        )

        maximum_active = len(active)
        for slot in plan.swap.deactivations:
            self.assertIn(slot, active)
            active.remove(slot)
            maximum_active = max(maximum_active, len(active))
        for slot in plan.swap.activations:
            self.assertNotIn(slot, active)
            active.add(slot)
            maximum_active = max(maximum_active, len(active))
        self.assertEqual(maximum_active, 24)
        self.assertEqual(len(active), 24)
        self.assertEqual(
            {resident[slot] for slot in active},
            set(plan.next_plan.near + plan.next_plan.transition + plan.next_plan.distant),
        )

    def test_exact_cardinal_west_delta_matches_runtime_command_group(self) -> None:
        swap = self.transition.swap
        self.assertEqual(swap.deactivate_distant, (29,))
        self.assertEqual(swap.deactivate_transition, (19, 20, 21, 24))
        self.assertEqual(swap.deactivate_near, tuple(range(1, 9)))
        self.assertEqual(swap.activate_near, tuple(range(9, 17)))
        self.assertEqual(swap.activate_transition, (25, 26, 27, 28))
        self.assertEqual(swap.activate_distant, (37,))
        self.assertTrue(
            all(
                item.request.component.super_x == KOAK_NEXT_WEST_FAMILY[0]
                and item.request.component.super_y == KOAK_NEXT_WEST_FAMILY[1]
                for item in self.transition.preload_next_near
            )
        )
        self.assertEqual(KOAK_CURRENT_FAMILY, (23, 36))

    def test_failed_preload_enters_hold_without_changing_displayed_plan(self) -> None:
        runtime = FixedTransitionRuntime(self.transition)
        # Publish the complete initial 8/8/8 plan, then stop on the first
        # inactive next-bank load as a selected-record CRC failure would.
        for _ in range(24):
            entry = runtime.plan_one_load()
            self.assertIsNotNone(entry)
            runtime.commit_load(entry)  # type: ignore[arg-type]
        displayed = runtime.active_components
        resident = runtime.resident
        failed = runtime.plan_one_load()
        self.assertEqual(failed.slot, 9)  # type: ignore[union-attr]
        runtime.abort_load(failed)  # type: ignore[arg-type]
        self.assertTrue(runtime.error_hold)
        self.assertFalse(runtime.armed)
        self.assertEqual(runtime.active_components, displayed)
        self.assertEqual(runtime.resident, resident)
        self.assertFalse(runtime.swap_if_crossed(91))

    def test_runtime_arms_only_after_every_inactive_delta_then_swaps(self) -> None:
        runtime = FixedTransitionRuntime(self.transition)
        while (entry := runtime.plan_one_load()) is not None:
            runtime.commit_load(entry)
        self.assertTrue(runtime.armed)
        self.assertEqual(len(runtime.active_slots), 24)
        self.assertFalse(runtime.swap_if_crossed(92))
        self.assertTrue(runtime.swap_if_crossed(91))
        self.assertTrue(runtime.swapped)
        self.assertEqual(len(runtime.active_slots), 24)
        self.assertFalse(runtime.swap_if_crossed(90))

    def test_generated_assembly_table_is_fixed_width_and_complete(self) -> None:
        source = assembly_include(self.transition)
        self.assertIn("family_plan_entry_size: equ 17", source)
        self.assertIn("family_plan_total_count: equ 37", source)
        self.assertEqual(source.count("\n    ; "), 37)
        self.assertEqual(source.count("\n    dl "), 74)
        self.assertIn(
            "family_swap_deactivate_ids:\n"
            "    db 29,19,20,21,24,1,2,3,4,5,6,7,8",
            source,
        )
        self.assertIn(
            "family_swap_activate_ids:\n"
            "    db 9,10,11,12,13,14,15,16,25,26,27,28,37",
            source,
        )


if __name__ == "__main__":
    unittest.main()
