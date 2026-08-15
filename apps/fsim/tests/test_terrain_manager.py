from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure


ROOT = Path(__file__).resolve().parent.parent
MANAGER = ROOT / "runtime/ez80/terrain-manager.inc"


def code_only() -> str:
    """Return normalized assembly with comments removed."""

    lines = []
    for raw in MANAGER.read_text(encoding="utf-8").splitlines():
        line = raw.split(";", 1)[0].strip().lower()
        if line:
            lines.append(re.sub(r"\s+", " ", line))
    return "\n".join(lines)


def routine(source: str, start: str, end: str) -> str:
    first = source.index(f"{start.lower()}:")
    last = source.index(f"{end.lower()}:", first)
    return source[first:last]


class TerrainManagerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = code_only()

    def test_public_api_and_link_time_provider_contract_are_explicit(self) -> None:
        for symbol in (
            "terrain_manager_initialize",
            "terrain_manager_submit_origin",
            "terrain_manager_update_position",
            "terrain_manager_set_ring",
            "terrain_manager_service_idle",
            "terrain_manager_stage_candidate",
            "terrain_manager_commit_staged_group",
            "terrain_manager_query",
            "terrain_manager_shutdown_idle",
        ):
            self.assertIn(f"{symbol}:", self.source)

        for hook in (
            "terrain_provider_ring_count",
            "terrain_provider_desired_at",
            "terrain_provider_load_candidate",
            "terrain_provider_position_candidate",
            "terrain_provider_candidate_is_desired",
            "terrain_provider_normalize_position",
            "terrain_provider_transition_busy",
            "terrain_provider_ring_change_allowed",
            "pingo_set_object_active",
        ):
            self.assertIn(f"call {hook}", self.source)
        self.assertIn(
            "jp nz,terrain_provider_service_transition", self.source
        )

        # Topology, path construction, and corpus bounds belong to providers.
        for forbidden in ("square", "chebyshev", "mod 91", "5*q", "11*r"):
            self.assertNotIn(forbidden, self.source)

    def test_status_block_has_stable_exact_offsets(self) -> None:
        expected = {
            "state": 0,
            "ring": 1,
            "desired_count": 2,
            "resident_count": 3,
            "active_count": 4,
            "converged": 5,
            "last_operation": 6,
            "last_error": 7,
            "origin_q": 8,
            "origin_r": 10,
            "last_slot": 12,
            "last_q": 13,
            "last_r": 15,
            "generation": 17,
        }
        for name, offset in expected.items():
            self.assertRegex(
                self.source,
                rf"terrain_manager_status_{name}: equ {offset}(?:\n|$)",
            )
        self.assertIn("terrain_manager_status_size: equ 19", self.source)
        query = routine(
            self.source, "terrain_manager_query", "terrain_manager_shutdown_idle"
        )
        self.assertIn("ld ix,terrain_manager_status\nxor a\nret", query)

    def test_ids_are_exact_u16_and_configuration_rejects_overflow(self) -> None:
        initialize = routine(
            self.source, "terrain_manager_initialize", "terrain_manager_bad_config"
        )
        self.assertEqual(initialize.count("ld de,65536"), 2)
        # Slot-capacity and ring bounds plus the two inclusive u16 ranges.
        self.assertEqual(initialize.count("jp nc,terrain_manager_bad_config"), 4)

        ids = routine(
            self.source,
            "terrain_manager_prepare_work_ids",
            "terrain_manager_load_candidate_from_slot",
        )
        self.assertIn("ld de,0\nld a,(terrain_manager_candidate_slot)\nld e,a", ids)
        self.assertIn("ld hl,terrain_manager_mesh_id_base\nadd hl,de", ids)
        self.assertIn("ld hl,terrain_manager_object_id_base\nadd hl,de", ids)
        self.assertNotRegex(ids, r"add a,terrain_manager_(?:mesh|object)_id_base")

    def test_public_position_update_reserves_carry_for_errors(self) -> None:
        update = routine(
            self.source,
            "terrain_manager_update_position",
            "terrain_manager_set_ring",
        )
        self.assertIn("call terrain_provider_normalize_position\njr c,@changed", update)
        self.assertIn("jr c,@changed\nxor a\nret\n@changed:", update)
        self.assertTrue(update.endswith("ld a,1\nor a\nret\n"))
        self.assertNotIn("scf", update)

    def test_group_profile_rejects_changed_direct_origin_submit(self) -> None:
        submit = routine(
            self.source,
            "terrain_manager_submit_origin",
            "terrain_manager_update_position",
        )
        changed = submit.index("@changed:")
        reject = submit.index("jp terrain_manager_bad_group", changed)
        store = submit.index(
            "terrain_manager_store_u16_bc terrain_manager_origin_q", changed
        )
        self.assertLess(reject, store)
        self.assertIn("@first:", submit)

    def test_load_publication_order_and_failure_retention_are_locked(self) -> None:
        load = routine(
            self.source,
            "terrain_manager_load_candidate",
            "terrain_manager_record_load_failure",
        )
        ordered = (
            "call terrain_provider_load_candidate",
            "call terrain_provider_position_candidate",
            "call pingo_set_object_active",
            "call terrain_manager_commit_candidate",
        )
        positions = [load.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))

        failed_load = routine(
            self.source,
            "terrain_manager_record_load_failure",
            "terrain_manager_record_position_failure",
        )
        for forbidden in (
            "terrain_manager_slot_flags_pointer",
            "terrain_manager_resident_q",
            "terrain_manager_resident_r",
            "terrain_manager_resident_count",
            "terrain_manager_active_count",
            "pingo_set_object_active",
            "terrain_manager_commit_candidate",
        ):
            self.assertNotIn(forbidden, failed_load)

    def test_cached_activation_failure_preserves_residency_and_counts(self) -> None:
        activate = routine(
            self.source,
            "terrain_manager_activate_candidate",
            "terrain_manager_record_activation_position_failure",
        )
        self.assertIn(
            "jr nz,terrain_manager_record_activation_position_failure", activate
        )
        failure = routine(
            self.source,
            "terrain_manager_record_activation_position_failure",
            "terrain_manager_stage_candidate",
        )
        self.assertIn("call terrain_manager_slot_error_pointer", failure)
        for forbidden in (
            "terrain_manager_previous_flags",
            "terrain_manager_slot_flags_pointer",
            "terrain_manager_resident_count",
            "terrain_manager_active_count",
            "pingo_set_object_active",
        ):
            self.assertNotIn(forbidden, failure)

    def test_staging_never_publishes_into_an_active_slot_or_activates(self) -> None:
        stage = routine(
            self.source,
            "terrain_manager_stage_candidate",
            "terrain_manager_commit_staged_candidate",
        )
        active_guard = stage.index("and terrain_manager_flag_active+terrain_manager_flag_staged")
        load = stage.index("call terrain_provider_load_candidate")
        position = stage.index("call terrain_provider_position_candidate", load)
        commit = stage.index("call terrain_manager_commit_staged_candidate", position)
        self.assertLess(active_guard, load)
        self.assertLess(load, position)
        self.assertLess(position, commit)
        self.assertNotIn("call pingo_set_object_active", stage)

        staged_commit = routine(
            self.source,
            "terrain_manager_commit_staged_candidate",
            "terrain_manager_commit_staged_group",
        )
        self.assertIn(
            "ld (hl),terrain_manager_flag_resident+terrain_manager_flag_staged",
            staged_commit,
        )
        self.assertIn("inc (hl)", staged_commit)
        self.assertNotIn("terrain_manager_active_count", staged_commit)
        self.assertNotIn("pingo_set_object_active", staged_commit)

    def test_group_commit_preflights_then_retires_before_entering(self) -> None:
        commit = routine(
            self.source,
            "terrain_manager_commit_staged_group",
            "terrain_manager_validate_staged_group",
        )
        self.assertIn("call terrain_manager_validate_staged_group", commit)
        retire = commit.index("@retire:")
        enter = commit.index("@enter:")
        self.assertLess(retire, enter)
        self.assertIn("call pingo_set_object_active", commit[retire:enter])
        self.assertIn("call pingo_set_object_active", commit[enter:])

        preflight = routine(
            self.source,
            "terrain_manager_validate_staged_group",
            "terrain_manager_group_mark_slot",
        )
        self.assertIn("call terrain_manager_group_mark_slot", preflight)
        self.assertIn(
            "and terrain_manager_flag_resident+terrain_manager_flag_active+terrain_manager_flag_staged",
            preflight,
        )
        self.assertIn(
            "cp terrain_manager_flag_resident+terrain_manager_flag_active",
            preflight,
        )
        self.assertNotIn("call pingo_set_object_active", preflight)
        self.assertNotIn("call terrain_provider_load_candidate", preflight)

    def test_rebase_has_explicit_immediate_and_deferred_retirement_profiles(self) -> None:
        rebase = routine(
            self.source,
            "terrain_manager_reposition_active",
            "terrain_manager_query",
        )
        deferred = rebase.index(".if terrain_manager_defer_stale_rebase")
        deferred_placement = rebase.index(
            "call terrain_provider_position_candidate", deferred
        )
        legacy = rebase.index(".else", deferred)
        desired = rebase.index("call terrain_provider_candidate_is_desired", legacy)
        legacy_placement = rebase.index(
            "call terrain_provider_position_candidate", legacy
        )
        deactivate = rebase.index("call pingo_set_object_active", legacy)
        clear_dirty = rebase.index("ld (terrain_manager_origin_dirty),a")
        self.assertLess(deferred, deferred_placement)
        self.assertLess(deferred_placement, legacy)
        self.assertLess(desired, legacy_placement)
        self.assertLess(legacy_placement, deactivate)
        self.assertLess(deactivate, clear_dirty)
        self.assertIn("and terrain_manager_flag_resident", rebase)
        self.assertIn("call terrain_manager_decrement_active_count", rebase)
        self.assertNotIn("call terrain_provider_load_candidate", rebase)

    def test_clipped_centre_is_bad_origin_but_clipped_edges_are_skipped(self) -> None:
        service = routine(
            self.source,
            "terrain_manager_service_idle",
            "terrain_manager_provider_error",
        )
        witness = (
            "call terrain_provider_desired_at\n"
            "jr nc,@candidate_ready\n"
            "ld a,(terrain_manager_candidate_ordinal)\n"
            "or a\n"
            "jp z,terrain_manager_bad_origin\n"
            "jr @next"
        )
        self.assertIn(witness, service)

    def test_service_has_one_mesh_publication_path_per_idle_call(self) -> None:
        # Rebase intentionally positions/deactivates all active slots atomically;
        # ordinary convergence reaches one load/activate/deactivate and returns.
        # Ordinary convergence and explicit inactive staging are the only mesh
        # publication callers.  The staged path never activates its object.
        self.assertEqual(self.source.count("call terrain_provider_load_candidate"), 2)
        for operation in (
            "terrain_manager_load_candidate",
            "terrain_manager_activate_candidate",
            "terrain_manager_deactivate_one_stale",
        ):
            body = routine(
                self.source,
                operation,
                {
                    "terrain_manager_load_candidate": "terrain_manager_record_load_failure",
                    "terrain_manager_activate_candidate": "terrain_manager_record_activation_position_failure",
                    "terrain_manager_deactivate_one_stale": "terrain_manager_reposition_active",
                }[operation],
            )
            self.assertRegex(body, r"or a\nret(?:\n|$)")

    def test_group_dispatch_precedes_ordinary_convergence_and_fails_closed(self) -> None:
        service = routine(
            self.source,
            "terrain_manager_service_idle",
            "terrain_manager_provider_error",
        )
        rebase = service.index("jp nz,terrain_manager_reposition_active")
        busy = service.index("call terrain_provider_transition_busy")
        dispatch = service.index("jp nz,terrain_provider_service_transition")
        staged = service.index("ld a,(terrain_manager_staged_count)")
        ordinary = service.index("call terrain_provider_ring_count")
        self.assertLess(rebase, busy)
        self.assertLess(busy, dispatch)
        self.assertLess(dispatch, staged)
        self.assertLess(staged, ordinary)
        self.assertIn("jp nz,terrain_manager_bad_group", service[staged:ordinary])

        update = routine(
            self.source,
            "terrain_manager_update_position",
            "terrain_manager_set_ring",
        )
        self.assertLess(
            update.index("call terrain_provider_transition_busy"),
            update.index("ld a,(terrain_manager_converged)"),
        )
        self.assertLess(
            update.index("ld a,(terrain_manager_converged)"),
            update.index("call terrain_provider_normalize_position"),
        )

    def test_slot_storage_is_generic_u8_capacity_not_radius_specific(self) -> None:
        self.assertIn("terrain_manager_slot_count", self.source)
        self.assertIn("ds terrain_manager_slot_count*2", self.source)
        self.assertEqual(self.source.count("ds terrain_manager_slot_count*2"), 2)
        self.assertEqual(self.source.count("ds terrain_manager_slot_count\n"), 5)
        self.assertNotIn("ds 91", self.source)

    def test_real_fixture_include_closure_is_adl_width_clean(self) -> None:
        main = ROOT / "fixtures/terrain-manager-survey/src/terrain-manager-survey.asm"
        if not main.is_file():
            self.skipTest("terrain-manager survey fixture has not landed")
        result = audit_paths(include_closure([main]))
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_core_links_and_assembles_against_minimal_provider(self) -> None:
        harness = """\
terrain_manager_slot_count: equ 91
terrain_manager_max_ring: equ 5
terrain_manager_initial_ring: equ 2
terrain_manager_mesh_id_base: equ 65445
terrain_manager_object_id_base: equ 65445
terrain_manager_defer_stale_rebase: equ 0
terrain_manager_group_staging: equ 1

    .assume adl=1
    .org 040000h
    jp harness_start
    include "terrain-manager.inc"

terrain_provider_ring_count:
    ld a,1
    ret
terrain_provider_transition_busy:
    xor a
    ret
terrain_provider_ring_change_allowed:
    xor a
    ret
terrain_provider_service_transition:
    xor a
    ret
terrain_provider_desired_at:
    xor a
    ld (terrain_manager_candidate_q+0),a
    ld (terrain_manager_candidate_q+1),a
    ld (terrain_manager_candidate_r+0),a
    ld (terrain_manager_candidate_r+1),a
    ld (terrain_manager_candidate_slot),a
    ld (terrain_manager_candidate_lod),a
    ret
terrain_provider_load_candidate:
    xor a
    ret
terrain_provider_position_candidate:
    xor a
    ret
terrain_provider_candidate_is_desired:
    xor a
    ret
terrain_provider_normalize_position:
    xor a
    ret
pingo_set_object_active:
    ret

harness_start:
    call terrain_manager_initialize
    ld bc,0
    ld de,0
    call terrain_manager_submit_origin
    ld ix,harness_camera
    call terrain_manager_update_position
    ld a,5
    call terrain_manager_set_ring
    call terrain_manager_service_idle
    call terrain_manager_query
    call terrain_manager_shutdown_idle
    ret
harness_camera:
    ds 16
"""
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            scratch = Path(directory)
            shutil.copy2(MANAGER, scratch / MANAGER.name)
            source = scratch / "harness.asm"
            source.write_text(harness, encoding="utf-8")
            output = scratch / "harness.bin"
            completed = subprocess.run(
                ["ez80asm", source.name, str(output), "-c"],
                cwd=scratch,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            self.assertGreater(output.stat().st_size, 819)


if __name__ == "__main__":
    unittest.main()
