from __future__ import annotations

import hashlib
import struct
import unittest

from pingo_terrain.hex_terrain import ring_offsets, rows_for_q, validate_cell
from pingo_terrain.regular_lod import (
    COARSE_SLOT_COUNT,
    COARSE_SLOT_FIRST,
    MANAGER_SLOT_COUNT,
    bounded_node_cells,
    offset_row,
)
from pingo_terrain.regular_lod_runtime import (
    PHASE_COUNT,
    PHASE_PLAN_COUNT,
    PLAN_RECORD_BYTES,
    PROTECTED_MASK_BYTES,
    TRANSITION_DIRECTION_NAMES,
    TRANSITION_DIRECTION_STEPS,
    TRANSITION_RECIPE_COUNT,
    UNASSIGNED_SLOT,
    AllocatorSnapshot,
    CoarsePlanEntry,
    NearPlanEntry,
    ProtectedSlotAllocator,
    all_phase_plans,
    all_terrain_transition_recipes,
    allocate_coarse_plan,
    build_coarse_transition_groups,
    build_coarse_plan,
    build_near_plan,
    build_phase_plan,
    build_runtime_plan,
    build_terrain_owner_plan,
    build_terrain_transition_groups,
    decode_transition_recipe,
    emit_plan_include,
    emit_phase_include,
    emit_runtime_include,
    emit_transition_include,
    encode_allocated_plan,
    encode_phase_table,
    encode_plan_template,
    encode_transition_recipe,
    encode_transition_table,
    protected_mask_contains,
    resolve_phase_plan,
    resolve_transition_recipe_groups,
    schedule_coarse_transition,
    schedule_terrain_transition,
    transition_recipe_ordinal_groups,
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

    def test_marina_north_transition_stages_coarse_newcomers_in_inactive_slots(self) -> None:
        allocator = ProtectedSlotAllocator()
        first = build_runtime_plan(allocator, 80, 125, 5)
        active_before = {
            COARSE_SLOT_FIRST + local
            for local, resident in enumerate(first.coarse.snapshot.slots)
            if resident.active
        }
        second = build_runtime_plan(allocator, 80, 126, 5)

        self.assertEqual(len(first.coarse.entries), 136)
        self.assertEqual(len(second.coarse.entries), 138)
        self.assertEqual(len(second.coarse.preserved_slots), 116)
        self.assertEqual(len(second.coarse.loaded_slots), 22)
        self.assertTrue(
            active_before.isdisjoint(second.coarse.loaded_slots),
            "a newcomer replaced still-visible fallback terrain despite free slots",
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

    def test_group_handoff_schedules_a_plan_union_larger_than_the_pool(self) -> None:
        old = resolve_phase_plan(80, 125, 5, clip_to_region=False)
        new = resolve_phase_plan(80, 124, 5, clip_to_region=False)
        self.assertEqual((len(old.entries), len(new.entries)), (136, 148))
        self.assertEqual(len(set(old.entries) | set(new.entries)), 166)
        self.assertGreater(
            len(set(old.entries) | set(new.entries)),
            COARSE_SLOT_COUNT,
        )

        schedule = schedule_coarse_transition(old, new)
        self.assertEqual(len(schedule.preserved), 118)
        self.assertEqual(schedule.initial_free_slots, 28)
        self.assertEqual(schedule.final_free_slots, 16)
        self.assertEqual(schedule.minimum_staging_margin, 15)
        self.assertEqual(
            [(step.group.retiring_count, step.group.entering_count)
             for step in schedule.steps[-4:]],
            [(1, 3), (1, 4), (1, 6), (1, 7)],
        )

    def test_transition_groups_are_exact_disjoint_coverage_components(self) -> None:
        old = resolve_phase_plan(80, 125, 5, clip_to_region=False)
        new = resolve_phase_plan(80, 124, 5, clip_to_region=False)
        groups = build_coarse_transition_groups(old, new)
        old_difference = set(old.entries) - set(new.entries)
        new_difference = set(new.entries) - set(old.entries)
        retiring = tuple(entry for group in groups for entry in group.retiring)
        entering = tuple(entry for group in groups for entry in group.entering)
        self.assertEqual(set(retiring), old_difference)
        self.assertEqual(set(entering), new_difference)
        self.assertEqual(len(retiring), len(set(retiring)))
        self.assertEqual(len(entering), len(set(entering)))

        # Cross-group old/new footprints must not overlap.  Such an overlap
        # would mean the graph partition separated dependent coverage owners.
        for left_index, left in enumerate(groups):
            left_old_cells = {
                cell
                for entry in left.retiring
                for cell in bounded_node_cells(entry.node)
            }
            for right in groups[left_index + 1 :]:
                right_new_cells = {
                    cell
                    for entry in right.entering
                    for cell in bounded_node_cells(entry.node)
                }
                self.assertTrue(left_old_cells.isdisjoint(right_new_cells))
                right_old_cells = {
                    cell
                    for entry in right.retiring
                    for cell in bounded_node_cells(entry.node)
                }
                left_new_cells = {
                    cell
                    for entry in left.entering
                    for cell in bounded_node_cells(entry.node)
                }
                self.assertTrue(right_old_cells.isdisjoint(left_new_cells))

    def test_every_adjacent_radius_five_phase_has_a_staged_group_schedule(self) -> None:
        schedules = 0
        union_overflows = 0
        maximum_union = 0
        maximum_entering_group = 0
        maximum_retiring_group = 0
        minimum_margin = COARSE_SLOT_COUNT
        for phase_q in range(8):
            for phase_row in range(4):
                q, r = origin(phase_q, phase_row)
                old = resolve_phase_plan(q, r, 5, clip_to_region=False)
                for delta_q, delta_r in ring_offsets(1):
                    new = resolve_phase_plan(
                        q + delta_q,
                        r + delta_r,
                        5,
                        clip_to_region=False,
                    )
                    schedule = schedule_coarse_transition(old, new)
                    active = set(old.entries)
                    for step in schedule.steps:
                        retiring = set(step.group.retiring)
                        entering = set(step.group.entering)
                        self.assertTrue(retiring <= active)
                        self.assertTrue(entering.isdisjoint(active))
                        # Entering meshes are resident but inactive here; the
                        # complete retiring group is still visible.
                        self.assertLessEqual(
                            len(active) + len(entering),
                            COARSE_SLOT_COUNT,
                        )
                        active.difference_update(retiring)
                        active.update(entering)
                    self.assertEqual(active, set(new.entries))
                    union_count = len(set(old.entries) | set(new.entries))
                    union_overflows += union_count > COARSE_SLOT_COUNT
                    maximum_union = max(maximum_union, union_count)
                    maximum_entering_group = max(
                        maximum_entering_group,
                        max(
                            (step.group.entering_count for step in schedule.steps),
                            default=0,
                        ),
                    )
                    maximum_retiring_group = max(
                        maximum_retiring_group,
                        max(
                            (step.group.retiring_count for step in schedule.steps),
                            default=0,
                        ),
                    )
                    minimum_margin = min(
                        minimum_margin,
                        schedule.minimum_staging_margin,
                    )
                    self.assertEqual(
                        schedule.final_free_slots,
                        COARSE_SLOT_COUNT - len(new.entries),
                    )
                    schedules += 1

        self.assertEqual(schedules, 32 * 6)
        self.assertEqual(union_overflows, 68)
        self.assertEqual(maximum_union, 180)
        self.assertEqual(maximum_entering_group, 10)
        self.assertEqual(maximum_retiring_group, 10)
        self.assertEqual(minimum_margin, 4)

    def test_full_owner_plan_exposes_near_slot_collision_during_crossing(self) -> None:
        old = build_terrain_owner_plan(80, 125, 5, clip_to_region=False)
        new = build_terrain_owner_plan(80, 126, 5, clip_to_region=False)
        old_near = {(entry.q, entry.r): entry for entry in old.near_entries}
        new_near = {(entry.q, entry.r): entry for entry in new.near_entries}
        old_by_slot = {entry.slot: entry for entry in old.near_entries}
        incoming = tuple(
            entry for identity, entry in new_near.items() if identity not in old_near
        )

        self.assertEqual((len(old.near_entries), len(new.near_entries)), (91, 91))
        self.assertEqual(len(set(old_near) & set(new_near)), 80)
        self.assertEqual(len(incoming), 11)
        self.assertEqual(
            len(
                [
                    entry
                    for entry in incoming
                    if old_by_slot[entry.slot] != entry
                ]
            ),
            11,
            "every incoming stable near slot still owns a different visible cell",
        )

        # Treating near and coarse as one staging pool makes this otherwise
        # impossible whole-plan union schedulable without overwriting a live
        # near object or dropping its coarse fallback.
        self.assertEqual((len(old.owners), len(new.owners)), (227, 229))
        self.assertEqual(len(set(old.owners) | set(new.owners)), 260)
        schedule = schedule_terrain_transition(old, new)
        self.assertEqual(len(schedule.preserved), 196)
        self.assertEqual(schedule.initial_free_slots, 28)
        self.assertEqual(schedule.final_free_slots, 26)
        self.assertEqual(schedule.minimum_staging_margin, 25)

    def test_full_owner_groups_are_exact_disjoint_coverage_components(self) -> None:
        old = build_terrain_owner_plan(80, 125, 5, clip_to_region=False)
        new = build_terrain_owner_plan(80, 124, 5, clip_to_region=False)
        groups = build_terrain_transition_groups(old, new)
        old_difference = set(old.owners) - set(new.owners)
        new_difference = set(new.owners) - set(old.owners)
        retiring = tuple(owner for group in groups for owner in group.retiring)
        entering = tuple(owner for group in groups for owner in group.entering)
        self.assertEqual(set(retiring), old_difference)
        self.assertEqual(set(entering), new_difference)
        self.assertEqual(len(retiring), len(set(retiring)))
        self.assertEqual(len(entering), len(set(entering)))

        def cells(owner: NearPlanEntry | CoarsePlanEntry) -> set[tuple[int, int]]:
            if isinstance(owner, NearPlanEntry):
                return {(owner.q, owner.r)}
            return {(cell.q, cell.r) for cell in bounded_node_cells(owner.node)}

        # No old/new dependency edge may cross a component boundary.
        for left_index, left in enumerate(groups):
            left_old_cells = {
                cell for owner in left.retiring for cell in cells(owner)
            }
            left_new_cells = {
                cell for owner in left.entering for cell in cells(owner)
            }
            for right in groups[left_index + 1 :]:
                right_old_cells = {
                    cell for owner in right.retiring for cell in cells(owner)
                }
                right_new_cells = {
                    cell for owner in right.entering for cell in cells(owner)
                }
                self.assertTrue(left_old_cells.isdisjoint(right_new_cells))
                self.assertTrue(right_old_cells.isdisjoint(left_new_cells))

    def test_every_adjacent_radius_five_full_owner_transition_fits_255_slots(self) -> None:
        schedules = 0
        union_overflows = 0
        maximum_union = 0
        minimum_endpoint = MANAGER_SLOT_COUNT
        maximum_endpoint = 0
        maximum_entering_group = 0
        maximum_retiring_group = 0
        maximum_group_total = 0
        minimum_margin = MANAGER_SLOT_COUNT
        has_one_to_fourteen = False
        has_fourteen_to_one = False

        for phase_q in range(8):
            for phase_row in range(4):
                q, r = origin(phase_q, phase_row)
                old = build_terrain_owner_plan(q, r, 5, clip_to_region=False)
                for delta_q, delta_r in ring_offsets(1):
                    new = build_terrain_owner_plan(
                        q + delta_q,
                        r + delta_r,
                        5,
                        clip_to_region=False,
                    )
                    schedule = schedule_terrain_transition(old, new)
                    active = set(old.owners)
                    for step in schedule.steps:
                        retiring = set(step.group.retiring)
                        entering = set(step.group.entering)
                        self.assertTrue(retiring <= active)
                        self.assertTrue(entering.isdisjoint(active))
                        # Entering owners are loaded but remain inactive while
                        # every retiring owner is still visible.
                        self.assertLessEqual(
                            len(active) + len(entering),
                            MANAGER_SLOT_COUNT,
                        )
                        active.difference_update(retiring)
                        active.update(entering)
                        pair = (
                            step.group.retiring_count,
                            step.group.entering_count,
                        )
                        maximum_retiring_group = max(
                            maximum_retiring_group,
                            pair[0],
                        )
                        maximum_entering_group = max(
                            maximum_entering_group,
                            pair[1],
                        )
                        maximum_group_total = max(
                            maximum_group_total,
                            sum(pair),
                        )
                        has_one_to_fourteen |= pair == (1, 14)
                        has_fourteen_to_one |= pair == (14, 1)
                    self.assertEqual(active, set(new.owners))

                    endpoints = (len(old.owners), len(new.owners))
                    minimum_endpoint = min(minimum_endpoint, *endpoints)
                    maximum_endpoint = max(maximum_endpoint, *endpoints)
                    owner_union = len(set(old.owners) | set(new.owners))
                    union_overflows += owner_union > MANAGER_SLOT_COUNT
                    maximum_union = max(maximum_union, owner_union)
                    minimum_margin = min(
                        minimum_margin,
                        schedule.minimum_staging_margin,
                    )
                    self.assertEqual(
                        schedule.final_free_slots,
                        MANAGER_SLOT_COUNT - len(new.owners),
                    )
                    schedules += 1

        self.assertEqual(schedules, 32 * 6)
        self.assertEqual(union_overflows, 152)
        self.assertEqual(maximum_union, 282)
        self.assertEqual((minimum_endpoint, maximum_endpoint), (217, 250))
        self.assertEqual(maximum_entering_group, 14)
        self.assertEqual(maximum_retiring_group, 14)
        self.assertEqual(maximum_group_total, 15)
        self.assertTrue(has_one_to_fourteen)
        self.assertTrue(has_fourteen_to_one)
        self.assertEqual(minimum_margin, 4)

    def test_transition_recipe_direction_order_matches_provider_abi(self) -> None:
        self.assertEqual(
            TRANSITION_DIRECTION_NAMES,
            (
                "north",
                "south",
                "northeast",
                "southeast",
                "northwest",
                "southwest",
            ),
        )
        self.assertEqual(
            TRANSITION_DIRECTION_STEPS,
            (
                (0, 1),
                (0, -1),
                (1, 0),
                (1, -1),
                (-1, 1),
                (-1, 0),
            ),
        )
        recipes = all_terrain_transition_recipes()
        self.assertEqual(len(recipes), TRANSITION_RECIPE_COUNT)
        self.assertEqual(tuple(recipe.index for recipe in recipes), tuple(range(192)))
        self.assertEqual(
            tuple(
                (
                    recipe.phase_q,
                    recipe.phase_offset_row,
                    recipe.direction_index,
                )
                for recipe in recipes[:6]
            ),
            tuple((0, 0, direction) for direction in range(6)),
        )

    def test_transition_recipe_table_round_trips_every_group_and_endpoint(self) -> None:
        recipes = all_terrain_transition_recipes()
        encoded = encode_transition_table(recipes)
        offsets = tuple(
            int.from_bytes(encoded[index * 3 : index * 3 + 3], "little")
            for index in range(TRANSITION_RECIPE_COUNT)
        )
        self.assertEqual(offsets[0], TRANSITION_RECIPE_COUNT * 3)
        self.assertEqual(tuple(sorted(offsets)), offsets)

        reconstructed_groups = 0
        for index, recipe in enumerate(recipes):
            end = (
                offsets[index + 1]
                if index + 1 < len(offsets)
                else len(encoded)
            )
            payload = encoded[offsets[index] : end]
            decoded = decode_transition_recipe(payload)
            expected = transition_recipe_ordinal_groups(recipe)
            self.assertEqual(decoded, expected)
            self.assertEqual(payload, encode_transition_recipe(recipe))

            old_owners = recipe.schedule.old_plan.owners
            new_owners = recipe.schedule.new_plan.owners
            active = set(old_owners)
            for group in decoded:
                retiring = {old_owners[ordinal] for ordinal in group.retiring_ordinals}
                entering = {new_owners[ordinal] for ordinal in group.entering_ordinals}
                self.assertTrue(retiring <= active)
                self.assertTrue(entering.isdisjoint(active))
                self.assertLessEqual(
                    len(active) + len(entering),
                    MANAGER_SLOT_COUNT,
                )
                active.difference_update(retiring)
                active.update(entering)
                reconstructed_groups += 1
            self.assertEqual(active, set(new_owners))
        self.assertEqual(reconstructed_groups, 4_176)

        with self.assertRaisesRegex(ValueError, "empty"):
            decode_transition_recipe(b"")
        with self.assertRaisesRegex(ValueError, "trailing"):
            decode_transition_recipe(encode_transition_recipe(recipes[0]) + b"\x00")
        with self.assertRaisesRegex(ValueError, "inside"):
            decode_transition_recipe(encode_transition_recipe(recipes[0])[:-1])

    def test_transition_recipe_table_schema_size_hash_and_include_are_pinned(self) -> None:
        encoded = encode_transition_table()
        self.assertEqual(len(encoded), 21_504)
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            "34fd0c448e6b653d4ab25883eb283a328dc5825cd6232591866059cbd2b6a79d",
        )
        self.assertEqual(TRANSITION_RECIPE_COUNT * 3, 576)
        self.assertEqual(len(encoded) - 576, 20_928)

        include = emit_transition_include()
        for literal in (
            "regular_lod_transition_near_radius: equ 5",
            "regular_lod_transition_direction_count: equ 6",
            "regular_lod_transition_count: equ 192",
            "regular_lod_transition_directory_bytes: equ 576",
            "regular_lod_transition_payload_bytes: equ 20928",
            "regular_lod_transition_table_bytes: equ 21504",
            "regular_lod_transition_maximum_groups: equ 38",
            "regular_lod_transition_maximum_retiring: equ 14",
            "regular_lod_transition_maximum_entering: equ 14",
            "regular_lod_transition_minimum_staging_margin: equ 4",
            "regular_lod_transition_recipe_group_count: equ 0",
            "regular_lod_transition_group_retiring_count: equ 0",
            "regular_lod_transition_group_entering_count: equ 1",
            "regular_lod_transition_group_ordinals: equ 2",
            "Canonical offset-table SHA-256: "
            "34fd0c448e6b653d4ab25883eb283a328dc5825cd6232591866059cbd2b6a79d",
        ):
            self.assertIn(literal, include)
        self.assertEqual(include.count("\n    dl regular_lod_transition_"), 192)
        self.assertEqual(len(include.encode("ascii")), 109_831)
        self.assertEqual(
            hashlib.sha256(include.encode("ascii")).hexdigest(),
            "aa6a3d152370f59fc2cefceacc46766bfc3425cb012be927beb5a758788de749",
        )
        self.assertEqual(
            emit_runtime_include(),
            emit_phase_include() + "\n" + include,
        )

    def test_source_ordinals_skip_clipped_edge_owners_without_renumbering(self) -> None:
        # Exercise both ends and both row boundaries, including alternating
        # even/odd regional column heights.  Recipes remain those generated at
        # the interior reference phase; only source-ordinal presence changes.
        boundary_cells = set()
        for q in (0, 1, 106, 107, 212, 213):
            rows = rows_for_q(q)
            for row in (0, 1, rows // 2, rows - 2, rows - 1):
                boundary_cells.add((q, row - q // 2))

        transitions = 0
        clipped_endpoints = 0
        for q, r in sorted(boundary_cells):
            for direction, (delta_q, delta_r) in enumerate(
                TRANSITION_DIRECTION_STEPS
            ):
                try:
                    validate_cell(q + delta_q, r + delta_r)
                except ValueError:
                    continue
                recipe = all_terrain_transition_recipes()[
                    ((q & 7) * 4 + (offset_row(q, r) & 3)) * 6 + direction
                ]
                groups = resolve_transition_recipe_groups(recipe, q, r)
                old = build_terrain_owner_plan(q, r, 5)
                new = build_terrain_owner_plan(q + delta_q, r + delta_r, 5)
                old_source = build_terrain_owner_plan(
                    q, r, 5, clip_to_region=False
                )
                new_source = build_terrain_owner_plan(
                    q + delta_q,
                    r + delta_r,
                    5,
                    clip_to_region=False,
                )
                clipped_endpoints += (
                    len(old.owners) < len(old_source.owners)
                    or len(new.owners) < len(new_source.owners)
                )

                active = set(old.owners)
                for group in groups:
                    retiring = set(group.retiring)
                    entering = set(group.entering)
                    self.assertTrue(retiring <= active)
                    self.assertTrue(entering.isdisjoint(active))
                    self.assertLessEqual(
                        len(active) + len(entering),
                        MANAGER_SLOT_COUNT,
                    )
                    active.difference_update(retiring)
                    active.update(entering)
                self.assertEqual(active, set(new.owners))
                transitions += 1

        self.assertGreaterEqual(transitions, 100)
        self.assertGreaterEqual(clipped_endpoints, 100)
        self.assertLess(clipped_endpoints, transitions)

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

    def test_adjacent_transition_retains_coarse_fallback_until_near_is_ready(self) -> None:
        allocator = ProtectedSlotAllocator()
        old = build_runtime_plan(allocator, 80, 125, 5)
        new = build_runtime_plan(allocator, 80, 124, 5)

        active = {
            entry.slot: ("near", entry.q, entry.r)
            for entry in old.near_entries
        }
        active.update(
            {
                entry.slot: ("coarse", *entry.identity.identity)
                for entry in old.coarse.entries
            }
        )
        old_coarse = {
            entry.slot: active[entry.slot] for entry in old.coarse.entries
        }

        # The manager's deferred rebase changes transforms, not active
        # ownership. Desired ordinals publish every L0 cell before coarse
        # newcomers are allowed to reuse a fallback slot.
        for entry in new.near_entries:
            active[entry.slot] = ("near", entry.q, entry.r)
            self.assertTrue(
                all(
                    active.get(slot) == identity
                    for slot, identity in old_coarse.items()
                )
            )

        for entry in new.coarse.entries:
            active[entry.slot] = ("coarse", *entry.identity.identity)

        desired = {
            entry.slot: ("near", entry.q, entry.r)
            for entry in new.near_entries
        }
        desired.update(
            {
                entry.slot: ("coarse", *entry.identity.identity)
                for entry in new.coarse.entries
            }
        )
        self.assertTrue(
            all(
                active.get(slot) == identity
                for slot, identity in desired.items()
            )
        )

        # Only now does ordinary stale eviction remove preceding-plan owners.
        active = {
            slot: identity
            for slot, identity in active.items()
            if slot in desired
        }
        self.assertEqual(active, desired)

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
