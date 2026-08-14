from __future__ import annotations

import struct
import unittest

from pingo_terrain.hex_terrain import ring_offsets
from pingo_terrain.regular_lod import (
    COARSE_SLOT_COUNT,
    COARSE_SLOT_FIRST,
    MANAGER_SLOT_COUNT,
    offset_row,
)
from pingo_terrain.regular_lod_runtime import (
    PHASE_COUNT,
    PHASE_PLAN_COUNT,
    PLAN_RECORD_BYTES,
    PROTECTED_MASK_BYTES,
    UNASSIGNED_SLOT,
    AllocatorSnapshot,
    ProtectedSlotAllocator,
    all_phase_plans,
    allocate_coarse_plan,
    build_coarse_plan,
    build_near_plan,
    build_phase_plan,
    build_runtime_plan,
    emit_plan_include,
    emit_phase_include,
    encode_allocated_plan,
    encode_phase_table,
    encode_plan_template,
    protected_mask_contains,
    resolve_phase_plan,
)


REFERENCE_Q = 80
REFERENCE_ROW = 120


def origin(phase_q: int, phase_row: int) -> tuple[int, int]:
    q = REFERENCE_Q + phase_q
    row = REFERENCE_ROW + phase_row
    return q, row - q // 2


class RegularLodRuntimeTests(unittest.TestCase):
    def test_all_radius_phase_plans_are_complete_and_deterministic(self) -> None:
        plans = all_phase_plans()
        self.assertEqual(len(plans), PHASE_PLAN_COUNT)
        self.assertEqual(tuple(plan.index for plan in plans), tuple(range(192)))
        expected_ranges = {
            0: (106, 118),
            1: (107, 126),
            2: (117, 129),
            3: (122, 142),
            4: (128, 143),
            5: (126, 159),
        }
        for near_radius, expected in expected_ranges.items():
            counts = [
                len(plan.entries)
                for plan in plans[near_radius * PHASE_COUNT : (near_radius + 1) * PHASE_COUNT]
            ]
            self.assertEqual((min(counts), max(counts)), expected)
        self.assertEqual(sum(len(plan.entries) for plan in plans), 24_294)
        self.assertEqual(all_phase_plans(), plans)

    def test_phase_resolution_is_byte_for_byte_direct_selection(self) -> None:
        translations = ((0, 0), (8, 4), (-8, -4), (24, -8))
        for near_radius in range(6):
            for phase_q in range(8):
                for phase_row in range(4):
                    for translate_q, translate_row in translations:
                        q, r = origin(phase_q, phase_row)
                        row = offset_row(q, r)
                        q += translate_q
                        row += translate_row
                        r = row - q // 2
                        with self.subTest(
                            radius=near_radius,
                            phase_q=phase_q,
                            phase_row=phase_row,
                            translate=(translate_q, translate_row),
                        ):
                            self.assertEqual(
                                resolve_phase_plan(
                                    q, r, near_radius, clip_to_region=False
                                ),
                                build_coarse_plan(
                                    q, r, near_radius, clip_to_region=False
                                ),
                            )

    def test_phase_offsets_fit_compact_signed_bytes(self) -> None:
        offsets = [
            (entry.anchor_q_offset, entry.anchor_offset_row_offset)
            for plan in all_phase_plans()
            for entry in plan.entries
        ]
        self.assertEqual(
            (
                min(value[0] for value in offsets),
                max(value[0] for value in offsets),
                min(value[1] for value in offsets),
                max(value[1] for value in offsets),
            ),
            (-37, 30, -33, 30),
        )

    def test_near_pool_is_stable_disjoint_and_exact(self) -> None:
        expected_counts = (1, 7, 19, 37, 61, 91)
        q, r = origin(3, 2)
        for radius, expected_count in enumerate(expected_counts):
            entries = build_near_plan(q, r, radius, clip_to_region=False)
            self.assertEqual(len(entries), expected_count)
            self.assertEqual(len({entry.slot for entry in entries}), expected_count)
            self.assertTrue(all(entry.slot < COARSE_SLOT_FIRST for entry in entries))
        slots = {entry.slot for entry in build_near_plan(q, r, 5, clip_to_region=False)}
        self.assertEqual(slots, set(range(91)))

    def test_allocator_preserves_overlap_and_only_uses_unprotected_slots(self) -> None:
        q, r = origin(0, 0)
        first_plan = build_coarse_plan(q, r, 5, clip_to_region=False)
        allocator = ProtectedSlotAllocator()
        first = allocator.reconcile(first_plan)
        old_slots = {entry.identity: entry.slot for entry in first.entries}

        second_q, second_r = q + 1, r
        second_plan = build_coarse_plan(second_q, second_r, 4, clip_to_region=False)
        second = allocator.reconcile(second_plan)
        new_slots = {entry.identity: entry.slot for entry in second.entries}
        overlap = set(old_slots) & set(new_slots)
        self.assertTrue(overlap)
        self.assertTrue(all(old_slots[key] == new_slots[key] for key in overlap))
        self.assertEqual(set(second.preserved_slots), {old_slots[key] for key in overlap})
        self.assertTrue(set(second.loaded_slots).isdisjoint(second.preserved_slots))
        self.assertTrue(set(second.loaded_slots).isdisjoint(second.reactivated_slots))
        self.assertEqual(len(second.protected_mask), PROTECTED_MASK_BYTES)
        self.assertTrue(
            all(
                protected_mask_contains(second.protected_mask, entry.slot)
                for entry in second.entries
            )
        )

    def test_inactive_resident_is_protected_and_reactivated_in_place(self) -> None:
        q, r = origin(5, 2)
        allocator = ProtectedSlotAllocator()
        first = allocator.reconcile(
            build_coarse_plan(q, r, 5, clip_to_region=False)
        )
        remembered = first.entries[-1]
        empty = allocator.reconcile(
            type(first.plan)(q, r, 5, ())
        )
        self.assertFalse(empty.snapshot.slots[remembered.slot - COARSE_SLOT_FIRST].active)
        restored = allocator.reconcile(
            type(first.plan)(q, r, 5, (remembered.identity,))
        )
        self.assertEqual(restored.entries[0].slot, remembered.slot)
        self.assertEqual(restored.reactivated_slots, (remembered.slot,))
        self.assertEqual(restored.loaded_slots, ())

    def test_all_adjacent_phase_and_radius_transitions_fit_the_pool(self) -> None:
        # Every 8x4 root phase, every axial neighbor, and every ordered pair of
        # radius settings.  A fresh A snapshot makes each A->B proof independent.
        neighbors = ring_offsets(1)
        plans = {}

        def plan(q: int, r: int, radius: int):
            key = q, r, radius
            if key not in plans:
                plans[key] = build_coarse_plan(
                    q, r, radius, clip_to_region=False
                )
            return plans[key]

        transitions = 0
        for phase_q in range(8):
            for phase_row in range(4):
                q, r = origin(phase_q, phase_row)
                for radius_a in range(6):
                    initial = allocate_coarse_plan(AllocatorSnapshot.empty(), plan(q, r, radius_a))
                    initial_slots = {
                        entry.identity: entry.slot for entry in initial.entries
                    }
                    for delta_q, delta_r in neighbors:
                        for radius_b in range(6):
                            result = allocate_coarse_plan(
                                initial.snapshot,
                                plan(q + delta_q, r + delta_r, radius_b),
                            )
                            self.assertLessEqual(len(result.entries), COARSE_SLOT_COUNT)
                            self.assertEqual(result.snapshot.active_count, len(result.entries))
                            self.assertTrue(
                                all(
                                    COARSE_SLOT_FIRST <= entry.slot < MANAGER_SLOT_COUNT
                                    for entry in result.entries
                                )
                            )
                            final_slots = {
                                entry.identity: entry.slot for entry in result.entries
                            }
                            for identity in set(initial_slots) & set(final_slots):
                                self.assertEqual(
                                    initial_slots[identity], final_slots[identity]
                                )
                            transitions += 1
        self.assertEqual(transitions, 32 * 6 * 6 * 6)

    def test_complete_runtime_plan_models_all_255_slots(self) -> None:
        q, r = origin(7, 3)
        runtime = build_runtime_plan(
            ProtectedSlotAllocator(),
            q,
            r,
            5,
            clip_to_region=False,
        )
        self.assertEqual(len(runtime.near_entries), 91)
        self.assertLessEqual(len(runtime.coarse.entries), 159)
        self.assertLessEqual(runtime.active_count, 250)
        self.assertTrue(all(entry.slot <= 90 for entry in runtime.near_entries))
        self.assertTrue(all(entry.slot >= 91 for entry in runtime.coarse.entries))

    def test_provider_encodings_have_explicit_runtime_slot_ownership(self) -> None:
        q, r = origin(1, 3)
        plan = build_coarse_plan(q, r, 5, clip_to_region=False)
        template = encode_plan_template(plan)
        self.assertEqual(len(template), 1 + len(plan.entries) * PLAN_RECORD_BYTES)
        self.assertEqual(template[0], len(plan.entries))
        decoded = [
            struct.unpack_from("<BhhB", template, 1 + index * PLAN_RECORD_BYTES)
            for index in range(len(plan.entries))
        ]
        self.assertEqual(
            tuple(record[:3] for record in decoded),
            tuple(entry.identity for entry in plan.entries),
        )
        self.assertTrue(all(record[3] == UNASSIGNED_SLOT for record in decoded))

        allocated = ProtectedSlotAllocator().reconcile(plan)
        live = encode_allocated_plan(allocated)
        self.assertEqual(live[0], len(plan.entries))
        self.assertEqual(
            tuple(
                struct.unpack_from("<BhhB", live, 1 + index * PLAN_RECORD_BYTES)[3]
                for index in range(len(plan.entries))
            ),
            tuple(entry.slot for entry in allocated.entries),
        )

        include = emit_plan_include(plan, "survey_plan")
        self.assertIn("survey_plan_record_bytes: equ 6", include)
        self.assertIn(f"survey_plan_count:\n    db {len(plan.entries)}", include)
        self.assertEqual(include.count("    db 0ffh"), len(plan.entries))

    def test_phase_table_is_random_access_and_has_exact_budget(self) -> None:
        plans = all_phase_plans()
        blob = encode_phase_table(plans)
        # 192 u24 offsets, one count byte per plan, and 3 bytes per entry.
        self.assertEqual(len(blob), 192 * 3 + 192 + 24_294 * 3)
        for index, plan in enumerate(plans):
            offset = int.from_bytes(blob[index * 3 : index * 3 + 3], "little")
            self.assertEqual(blob[offset], len(plan.entries))
            if index + 1 < len(plans):
                following = int.from_bytes(
                    blob[index * 3 + 3 : index * 3 + 6], "little"
                )
                self.assertEqual(
                    following - offset,
                    1 + len(plan.entries) * 3,
                )

    def test_phase_include_has_pointer_directory_and_slot_free_profiles(self) -> None:
        include = emit_phase_include()
        self.assertIn("regular_lod_phase_count: equ 192", include)
        self.assertIn("regular_lod_phase_record_bytes: equ 3", include)
        self.assertIn("regular_lod_phase_offsets:\n", include)
        self.assertIn("regular_lod_phase_payload:\n", include)
        self.assertEqual(include.count("    dl regular_lod_phase_r"), 192)
        self.assertEqual(
            sum(
                line.startswith("regular_lod_phase_r") and line.endswith(":")
                for line in include.splitlines()
            ),
            192,
        )
        self.assertEqual(include.count("\n    db "), 192 + 24_294)
        self.assertNotIn("record_slot", include)


if __name__ == "__main__":
    unittest.main()
