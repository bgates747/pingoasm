from __future__ import annotations

from pathlib import Path
import io
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import trace_regular_lod_staged_north_transitions as trace  # noqa: E402


def activity(object_id: int, active: int) -> str:
    return f"PINGO_STREAM object_active=ok oid={object_id} active={active}\n"


def replacement(object_id: int) -> str:
    return (
        "PINGO_STREAM mesh_replace=ok stage=29696 "
        f"mid={object_id} bytes=580 v=22 i=96 u=16 t=96 us=12\n"
    )


def pose(object_id: int) -> str:
    return (
        "PINGO_WIDE object_translation=ok "
        f"oid={object_id} raw_x=0 raw_y=9728 raw_z=0\n"
    )


def valid_transition_log() -> tuple[str, int]:
    lines: list[str] = []
    for object_id in range(1, trace.SLOT_COUNT + 1):
        lines.append(activity(object_id, 0))
    for object_id in range(1, trace.COLD_ACTIVE_COUNT + 1):
        lines.append(activity(object_id, 1))
    start = sum(len(line) for line in lines)

    active = set(range(1, trace.COLD_ACTIVE_COUNT + 1))
    inactive = set(range(trace.COLD_ACTIVE_COUNT + 1, trace.SLOT_COUNT + 1))
    sequence = trace.COLD_SEQUENCE + 1
    for transition in trace.expected_group_shapes():
        for retire_count, enter_count in transition:
            entering = sorted(inactive)[:enter_count]
            retiring = sorted(active)[:retire_count]
            if len(entering) != enter_count or len(retiring) != retire_count:
                raise AssertionError("synthetic schedule exceeded slot capacity")
            for object_id in entering:
                lines.append(replacement(object_id))
                lines.append(pose(object_id))
            for object_id in retiring:
                lines.append(activity(object_id, 0))
                active.remove(object_id)
                inactive.add(object_id)
            for object_id in entering:
                lines.append(activity(object_id, 1))
                inactive.remove(object_id)
                active.add(object_id)
            lines.append(f"PINGO_RENDER seq={sequence} bmid=257\n")
            sequence += 1
    return "".join(lines), start


def valid_radius_restart_log() -> tuple[str, int, list[int]]:
    lines: list[str] = []
    pre_restart = list(range(1, trace.EXPECTED_FINAL_ACTIVE_COUNT + 1))
    for object_id in range(1, trace.SLOT_COUNT + 1):
        lines.append(activity(object_id, 0))
    for object_id in pre_restart:
        lines.append(activity(object_id, 1))
    start = sum(len(line) for line in lines)
    for object_id in pre_restart:
        lines.append(activity(object_id, 0))
    for object_id in range(1, trace.RESTART_ACTIVE_COUNT + 1):
        lines.append(replacement(object_id))
        lines.append(pose(object_id))
        lines.append(activity(object_id, 1))
        lines.append(f"PINGO_RENDER seq={400 + object_id} bmid=257\n")
    return "".join(lines), start, pre_restart


class StagedNorthTransitionParserTests(unittest.TestCase):
    def test_policy_abi_allows_explicit_mode_zero_without_diagnostics(self) -> None:
        self.assertEqual(
            trace.classify_policy_abi(
                {trace.POLICY_MODE_SYMBOL: trace.POLICY_MODE_ASM_ONLY}
            ),
            (False, trace.POLICY_MODE_ASM_ONLY),
        )

    def test_policy_abi_rejects_mode_zero_with_stray_diagnostic(self) -> None:
        with self.assertRaisesRegex(SystemExit, "partial policy ABI"):
            trace.classify_policy_abi(
                {
                    trace.POLICY_MODE_SYMBOL: trace.POLICY_MODE_ASM_ONLY,
                    "regular_policy_module_status": 0x060000,
                }
            )

    def test_policy_abi_rejects_nonzero_mode_without_diagnostics(self) -> None:
        for mode in (
            trace.POLICY_MODE_DUAL_STRICT,
            trace.POLICY_MODE_C_GUARDED,
            trace.POLICY_MODE_ASM_CACHED,
        ):
            with self.subTest(mode=mode), self.assertRaisesRegex(
                SystemExit, "partial policy ABI"
            ):
                trace.classify_policy_abi({trace.POLICY_MODE_SYMBOL: mode})

    def test_policy_abi_accepts_complete_policy_diagnostics(self) -> None:
        symbols = {
            name: 0x060000 + index
            for index, name in enumerate(sorted(trace.POLICY_SYMBOLS))
        }
        symbols[trace.POLICY_MODE_SYMBOL] = trace.POLICY_MODE_C_GUARDED
        self.assertEqual(
            trace.classify_policy_abi(symbols),
            (True, trace.POLICY_MODE_C_GUARDED),
        )

    def test_policy_snapshot_contract_distinguishes_dual_guarded_and_fallback(self) -> None:
        dual = {
            "mode": trace.POLICY_MODE_DUAL_STRICT,
            "module_status": trace.POLICY_STATUS_READY,
            "qualification_failure": 0,
            "selector_calls": 84,
            "selector_matches": 84,
        }
        self.assertTrue(
            trace.validate_policy_state(
                dual,
                expected_available=True,
                expected_group_calls=84,
                expected_status=trace.POLICY_STATUS_READY,
            )["selector_counter_contract"]
        )
        guarded = {
            "mode": trace.POLICY_MODE_C_GUARDED,
            "module_status": trace.POLICY_STATUS_READY,
            "qualification_failure": 0,
            "selector_calls": 84,
            "selector_matches": 0,
        }
        self.assertTrue(
            trace.validate_policy_state(
                guarded, expected_available=True, expected_group_calls=84
            )["c_guarded_healthy_path_has_no_asm_oracle"]
        )
        cached = {
            "mode": trace.POLICY_MODE_ASM_CACHED,
            "module_status": 0,
            "qualification_failure": 0,
            "selector_calls": 84,
            "selector_matches": 0,
        }
        cached_state = trace.validate_policy_state(
            cached, expected_available=False, expected_group_calls=84
        )
        self.assertTrue(cached_state["asm_cached_has_no_module_dependency"])
        self.assertFalse(cached_state["module_required"])
        cached["module_status"] = trace.POLICY_STATUS_READY
        with self.assertRaisesRegex(trace.EvidenceError, "touched"):
            trace.validate_policy_state(
                cached, expected_available=False, expected_group_calls=84
            )
        cached["module_status"] = 0
        unavailable = {
            "mode": trace.POLICY_MODE_C_GUARDED,
            "module_status": 3,
            "qualification_failure": 0,
            "selector_calls": 0,
            "selector_matches": 0,
        }
        self.assertFalse(
            trace.validate_policy_state(
                unavailable,
                expected_available=False,
                expected_group_calls=84,
                expected_status=trace.POLICY_STATUS_MOS_ERROR,
            )["module_expected_available"]
        )
        with self.assertRaisesRegex(trace.EvidenceError, "status changed"):
            trace.validate_policy_state(
                unavailable,
                expected_available=False,
                expected_group_calls=84,
                expected_status=trace.POLICY_STATUS_HEADER,
            )
        guarded["selector_matches"] = 84
        with self.assertRaisesRegex(trace.EvidenceError, "counters changed"):
            trace.validate_policy_state(
                guarded, expected_available=True, expected_group_calls=84
            )

    def test_stage_fixture_explicitly_overrides_or_omits_installed_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "fixture"
            fixture.mkdir()
            installed_program = fixture / "P3DRGL.BIN"
            installed_policy = fixture / trace.POLICY_MODULE_NAME
            resource = fixture / "RESOURCE.BIN"
            explicit_program = root / "explicit-program.bin"
            explicit_policy = root / "explicit-policy.bin"
            for path, payload in (
                (installed_program, b"installed-program"),
                (installed_policy, b"installed-policy"),
                (resource, b"resource"),
                (explicit_program, b"explicit-program"),
                (explicit_policy, b"explicit-policy"),
            ):
                path.write_bytes(payload)

            staged_override = root / "override"
            staged_override.mkdir()
            with mock.patch.object(trace, "FIXTURE", fixture):
                trace.stage_fixture(
                    staged_override, explicit_program, explicit_policy
                )
            survey_override = staged_override / "survey"
            self.assertEqual(
                (survey_override / "P3DRGL.BIN").resolve(), explicit_program
            )
            self.assertEqual(
                (survey_override / trace.POLICY_MODULE_NAME).resolve(),
                explicit_policy,
            )
            self.assertEqual((survey_override / resource.name).resolve(), resource)

            staged_omit = root / "omit"
            staged_omit.mkdir()
            with mock.patch.object(trace, "FIXTURE", fixture):
                trace.stage_fixture(staged_omit, explicit_program)
            survey_omit = staged_omit / "survey"
            self.assertFalse((survey_omit / trace.POLICY_MODULE_NAME).exists())

            staged_crc = root / "crc"
            staged_crc.mkdir()
            explicit_policy.write_bytes(bytes(range(64)))
            with mock.patch.object(trace, "FIXTURE", fixture):
                trace.stage_fixture(
                    staged_crc,
                    explicit_program,
                    explicit_policy,
                    corrupt_policy_body=True,
                )
            corrupted = staged_crc / "survey" / trace.POLICY_MODULE_NAME
            self.assertFalse(corrupted.is_symlink())
            self.assertEqual(corrupted.read_bytes()[:-1], explicit_policy.read_bytes()[:-1])
            self.assertEqual(
                corrupted.read_bytes()[-1], explicit_policy.read_bytes()[-1] ^ 1
            )

    def test_selector_call_span_resolves_unique_adl_call(self) -> None:
        target = trace.PROGRAM_LOAD_ADDRESS + 0x1234
        payload = b"abcde" + bytes((0xCD,)) + target.to_bytes(3, "little") + b"z"
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "probe.bin"
            program.write_bytes(payload)
            self.assertEqual(
                trace.selector_call_span(program, target),
                (
                    trace.PROGRAM_LOAD_ADDRESS + 5,
                    trace.PROGRAM_LOAD_ADDRESS + 9,
                ),
            )
            program.write_bytes(payload + payload[5:9])
            with self.assertRaises(SystemExit):
                trace.selector_call_span(program, target)

    def test_selector_cycle_profiler_drives_exact_call_return_pair(self) -> None:
        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        process = Process()
        profiler = trace.SelectorCycleProfiler(
            process, 0x05FD96, 0x05FD9A, 0, 1
        )
        contents = "CPU paused (breakpoint)\n* 05fd96: CALL.L $05f9ac\n"
        profiler.service(contents)
        self.assertTrue(process.stdin.getvalue().endswith(b"state\n"))
        contents += (
            "* 05fd96: CALL.L $05f9ac\n"
            "Cycles since last break: 999 Cycles per instruction: 4.0\n"
        )
        profiler.service(contents)
        self.assertTrue(process.stdin.getvalue().endswith(b"continue\n"))
        contents += "CPU paused (breakpoint)\n* 05fd9a: RET C\n"
        profiler.service(contents)
        contents += (
            "* 05fd9a: RET C\n"
            "Cycles since last break: 42 Cycles per instruction: 3.0\n"
        )
        profiler.service(contents)

        self.assertEqual(profiler.require_complete()["cycles"], [42])
        self.assertIn(b"delete 0x5fd96\n", process.stdin.getvalue())
        self.assertIn(b"delete 0x5fd9a\n", process.stdin.getvalue())

    def test_host_schedule_has_exact_four_crossing_shape(self) -> None:
        shapes = trace.expected_group_shapes()
        self.assertEqual([len(item) for item in shapes], [29, 21, 17, 17])
        self.assertEqual(
            [sum(enter for _, enter in item) for item in shapes],
            [33, 36, 32, 29],
        )
        self.assertEqual(
            [sum(retire for retire, _ in item) for item in shapes],
            [31, 35, 23, 41],
        )

    def test_accepts_exact_inactive_staging_and_atomic_groups(self) -> None:
        contents, start = valid_transition_log()
        evidence = trace.validate_transition_stream(contents, start)
        self.assertEqual(evidence["command50_count"], 130)
        self.assertTrue(evidence["command50_all_inactive"])
        self.assertEqual(evidence["entering_count"], 130)
        self.assertEqual(evidence["retiring_count"], 130)
        self.assertEqual(evidence["group_count"], 84)
        self.assertTrue(evidence["retire_before_enter"])
        self.assertFalse(evidence["render_inside_group_commit"])
        self.assertEqual(len(evidence["final_active_ids"]), 227)

    def test_rejects_command50_against_active_object(self) -> None:
        contents, start = valid_transition_log()
        broken = contents[:start] + replacement(1) + contents[start:]
        with self.assertRaisesRegex(
            trace.EvidenceError, "command 50 replaced active OID 1"
        ):
            trace.validate_transition_stream(broken, start)

    def test_rejects_activation_without_staged_pose(self) -> None:
        contents, start = valid_transition_log()
        first_pose = contents.find("PINGO_WIDE object_translation=ok", start)
        end = contents.find("\n", first_pose) + 1
        broken = contents[:first_pose] + contents[end:]
        with self.assertRaisesRegex(trace.EvidenceError, "without staged command-52"):
            trace.validate_transition_stream(broken, start)

    def test_camera_unwrap_is_exact_and_monotone(self) -> None:
        positions = [4307, 4627, -4141, 4627, -4141, 4627, -4141, 4627, -4141]
        contents = "".join(
            "PINGO_POSE camera_translation "
            f"raw_x={x} raw_y=8000 raw_z=-466\n"
            for x in positions
        )
        evidence = trace.validate_camera(contents, 0)
        self.assertEqual(evidence["wrap_count"], 4)
        self.assertEqual(evidence["wrap_deltas"], [-8768] * 4)

    def test_accepts_complete_cold_shutdown_then_inactive_refill(self) -> None:
        contents, start, pre_restart = valid_radius_restart_log()
        evidence = trace.validate_radius_restart_stream(
            contents, start, pre_restart
        )
        self.assertEqual(evidence["shutdown_count"], 227)
        self.assertTrue(evidence["shutdown_complete_before_first_replace"])
        self.assertFalse(evidence["render_inside_shutdown"])
        self.assertEqual(evidence["command50_count"], 196)
        self.assertTrue(evidence["command50_all_inactive"])
        self.assertEqual(evidence["refill_activation_count"], 196)

    def test_rejects_radius_refill_before_complete_shutdown(self) -> None:
        contents, start, pre_restart = valid_radius_restart_log()
        last_shutdown = contents.rfind(activity(pre_restart[-1], 0), start)
        broken = (
            contents[:last_shutdown]
            + replacement(228)
            + pose(228)
            + contents[last_shutdown:]
        )
        with self.assertRaisesRegex(
            trace.EvidenceError, "did not deactivate every old active"
        ):
            trace.validate_radius_restart_stream(broken, start, pre_restart)

    def test_rejects_active_slot_replace_during_radius_refill(self) -> None:
        contents, start, pre_restart = valid_radius_restart_log()
        first_shutdown_end = contents.find("\n", start) + 1
        broken = (
            contents[:first_shutdown_end]
            + replacement(pre_restart[-1])
            + contents[first_shutdown_end:]
        )
        with self.assertRaisesRegex(
            trace.EvidenceError,
            "did not deactivate every old active|replaced active",
        ):
            trace.validate_radius_restart_stream(broken, start, pre_restart)

    def test_radius_four_endpoint_has_196_owners(self) -> None:
        plan = trace.build_terrain_owner_plan(*trace.FINAL_ORIGIN, 4)
        self.assertEqual(len(plan.near_entries), 61)
        self.assertEqual(len(plan.coarse_entries), 135)
        self.assertEqual(len(plan.owners), trace.RESTART_ACTIVE_COUNT)


if __name__ == "__main__":
    unittest.main()
