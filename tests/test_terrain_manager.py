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
            "pingo_set_object_active",
        ):
            self.assertIn(f"call {hook}", self.source)

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
            "terrain_manager_commit_candidate",
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

    def test_rebase_retires_stale_cells_before_positioning_overlap(self) -> None:
        rebase = routine(
            self.source,
            "terrain_manager_reposition_active",
            "terrain_manager_query",
        )
        desired = rebase.index("call terrain_provider_candidate_is_desired")
        placement = rebase.index("call terrain_provider_position_candidate")
        clear_dirty = rebase.index("ld (terrain_manager_origin_dirty),a")
        self.assertLess(desired, placement)
        self.assertLess(placement, clear_dirty)
        self.assertIn("call pingo_set_object_active", rebase)
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
        self.assertEqual(self.source.count("call terrain_provider_load_candidate"), 1)
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

    .assume adl=1
    .org 040000h
    jp harness_start
    include "terrain-manager.inc"

terrain_provider_ring_count:
    ld a,1
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
