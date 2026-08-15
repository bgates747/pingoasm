from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_regular_lod_policy_ab as policy_ab  # noqa: E402


def write_artifact(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": str(path.resolve()),
        "sha256": policy_ab.sha256(path),
    }


def selector_log(role: str, call: int, returned: int, cycles: list[int]) -> str:
    lines = [f"synthetic independent process {role}\n"]
    for value in cycles:
        lines.extend(
            (
                f"* {call:06x}: CALL.L selector\n",
                "Cycles since last break: 17 Cycles per instruction: 1.0\n",
                f"* {returned:06x}: next\n",
                f"Cycles since last break: {value} "
                "Cycles per instruction: 1.0\n",
            )
        )
    return "".join(lines)


def transition_stream() -> dict[str, object]:
    # 84 ABI-bounded groups that conserve the route's exact 130 retirees and
    # 130 entrants. The analyzer also requires the four exact partitions.
    flat = [[14, 14], [14, 14], [14, 14], [8, 8], *([[1, 1]] * 80)]
    partitions = []
    cursor = 0
    for count in policy_ab.EXPECTED_CROSSING_GROUPS:
        partitions.append(flat[cursor : cursor + count])
        cursor += count
    return {
        "command50_all_inactive": True,
        "command50_count": 130,
        "entering_count": 130,
        "final_active_ids": list(range(1, 228)),
        "group_count": 84,
        "group_shapes_by_transition": partitions,
        "render_inside_group_commit": False,
        "retire_before_enter": True,
        "retiring_count": 130,
    }


def final_state(role: str) -> dict[str, object]:
    policy = None
    if role in {"dual_strict", "c_guarded", "asm_cached"}:
        guarded = role == "c_guarded"
        cached = role == "asm_cached"
        policy = {
            "asm_cached_has_no_module_dependency": cached,
            "c_guarded_healthy_path_has_no_asm_oracle": guarded,
            "mode": 3 if cached else 2 if guarded else 1,
            "module_expected_available": not cached,
            "module_expected_status": None if cached else 1,
            "module_required": not cached,
            "module_status": 0 if cached else 1,
            "qualification_failure": 0,
            "selector_calls": 84,
            "selector_counter_contract": True,
            "selector_matches": 0 if guarded or cached else 84,
        }
    return {
        "manager": dict(policy_ab._EXPECTED_MANAGER),
        "provider": dict(policy_ab._EXPECTED_PROVIDER),
        "slots": {
            "active_count_from_flags": 227,
            "active_ids": list(range(1, 228)),
            "coarse_map_exact": True,
            "flags_sha256": "f" * 64,
            "near_map_exact": True,
            "owner_set_exact": True,
            "resident_count_from_flags": 240,
        },
        "policy": policy,
    }


class SyntheticEvidence:
    def __init__(self, root: Path) -> None:
        self.root = root
        shared = root / "shared"
        self.vdp = write_artifact(shared / "vdp.so", b"vdp")
        self.emulator = write_artifact(shared / "emulator", b"emulator")
        self.mos = write_artifact(shared / "mos.bin", b"mos")
        self.module = write_artifact(shared / "CPOLICY.BIN", b"policy")
        self.paths = {
            "accepted_asm": self._variant("accepted_asm", 100, 0x050100),
            "dual_strict": self._variant("dual_strict", 110, 0x050200),
            "c_guarded": self._variant("c_guarded", 110, 0x050300),
            "asm_cached": self._variant("asm_cached", 90, 0x050400),
        }

    def _variant(self, role: str, cycle: int, target: int) -> Path:
        root = self.root / role
        root.mkdir()
        call = policy_ab.PROGRAM_LOAD_ADDRESS + 8
        returned = call + 4
        program = write_artifact(
            root / "program.bin",
            (b"\x00" * 8) + bytes((0xCD,)) + target.to_bytes(3, "little") + b"\x00",
        )
        symbols = write_artifact(
            root / "program.symbols",
            (
                "regular_transition_select_feasible_group "
                f"${target:06x}\n"
            ).encode("ascii"),
        )
        proxy = write_artifact(root / "vdp_input_trace_proxy.so", b"proxy")
        cycles = [cycle] * policy_ab.EXPECTED_SELECTOR_SAMPLES
        log = root / "emulator.log"
        log.write_text(
            selector_log(role, call, returned, cycles), encoding="utf-8"
        )
        module_enabled = role in {"dual_strict", "c_guarded"}
        report = {
            "schema": policy_ab.TRACE_SCHEMA,
            "mode": "four-crossing",
            "qualified": True,
            "program": program,
            "symbols": symbols,
            "policy_module": self.module if module_enabled else None,
            "policy_module_required": module_enabled,
            "policy_expected_available": module_enabled,
            "policy_expected_status": 1 if module_enabled else None,
            "policy_body_corrupted": False,
            "vdp": self.vdp,
            "emulator": self.emulator,
            "mos": self.mos,
            "proxy": {
                "sha256": proxy["sha256"],
                "exports": ["one", "two"],
            },
            "selector_profile": {
                "call": call,
                "cycles": cycles,
                "measurement": "paused-debugger-call-to-post-call",
                "method": "automated-pausing-debugger-breakpoints",
                "return": returned,
                "sample_count": 84,
                "target": target,
            },
            "transition_stream": transition_stream(),
            "radius_input": None,
            "radius_restart_stream": None,
            "final_state": final_state(role),
            "shutdown": "debugger-memory-exit",
            "emulator_exit_status": 0,
            "log_sha256": policy_ab.sha256(log),
        }
        path = root / "regular-lod-staged-north-transitions.json"
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def analyze(self) -> dict[str, object]:
        return policy_ab.analyze_reports(
            self.paths["accepted_asm"],
            self.paths["dual_strict"],
            self.paths["c_guarded"],
            self.paths["asm_cached"],
        )

    def document(self, role: str) -> dict[str, object]:
        return json.loads(self.paths[role].read_text(encoding="utf-8"))

    def replace_document(self, role: str, document: dict[str, object]) -> None:
        self.paths[role].write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class RegularLodPolicyABTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.evidence = SyntheticEvidence(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_qualifies_exact_profiles_and_uses_shared_summary_convention(self) -> None:
        result = self.evidence.analyze()

        self.assertTrue(result["qualified"])
        self.assertEqual(
            result["scope"]["crossing_group_counts"], [29, 21, 17, 17]
        )
        self.assertEqual(
            result["variants"]["accepted_asm"]["selector"]["summary"],
            {
                "count": 84,
                "total": 8400,
                "minimum": 100,
                "maximum": 100,
                "mean": 100.0,
                "median": 100.0,
                "p95": 100.0,
            },
        )
        self.assertEqual(
            result["comparisons"]["c_guarded_vs_accepted_asm"][
                "overall_percent"
            ],
            {
                "total": 10.0,
                "minimum": 10.0,
                "maximum": 10.0,
                "mean": 10.0,
                "median": 10.0,
                "p95": 10.0,
            },
        )
        self.assertEqual(
            result["comparisons"]["asm_cached_vs_accepted_asm"][
                "overall_percent"
            ]["total"],
            -10.0,
        )
        self.assertEqual(
            result["comparisons"]["asm_cached_vs_c_guarded"][
                "overall_percent"
            ]["total"],
            -18.181818,
        )
        self.assertEqual(
            result["resident_image_size"]["comparisons_signed_bytes"][
                "asm_cached_vs_c_guarded"
            ]["resident_image_bytes"],
            -len(b"policy"),
        )
        self.assertIn(
            "unreachable common",
            result["resident_image_size"]["caveat"],
        )
        self.assertTrue(
            result["qualification"]["transition_stream_equivalent"]
        )
        self.assertTrue(
            result["qualification"]["final_owner_state_equivalent"]
        )
        self.assertIn("only selector call-site guest cycles", result["limitations"][0])

    def test_analysis_is_byte_deterministic_for_the_same_inputs(self) -> None:
        first = json.dumps(self.evidence.analyze(), indent=2, sort_keys=True) + "\n"
        second = json.dumps(self.evidence.analyze(), indent=2, sort_keys=True) + "\n"

        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))

    def test_rejects_incomplete_cycle_samples(self) -> None:
        document = self.evidence.document("c_guarded")
        document["selector_profile"]["cycles"].pop()
        self.evidence.replace_document("c_guarded", document)

        with self.assertRaisesRegex(policy_ab.PolicyABError, "83 samples"):
            self.evidence.analyze()

    def test_rejects_crossing_partition_drift(self) -> None:
        document = self.evidence.document("dual_strict")
        document["transition_stream"]["group_shapes_by_transition"][0].pop()
        self.evidence.replace_document("dual_strict", document)

        with self.assertRaisesRegex(policy_ab.PolicyABError, "group counts"):
            self.evidence.analyze()

    def test_rejects_policy_counter_drift(self) -> None:
        document = self.evidence.document("dual_strict")
        document["final_state"]["policy"]["selector_matches"] = 83
        self.evidence.replace_document("dual_strict", document)

        with self.assertRaisesRegex(policy_ab.PolicyABError, "selector_matches"):
            self.evidence.analyze()

    def test_accepts_same_schema_before_redundant_status_receipts(self) -> None:
        for role in ("dual_strict", "c_guarded"):
            document = self.evidence.document(role)
            del document["policy_expected_status"]
            del document["policy_body_corrupted"]
            del document["final_state"]["policy"]["module_expected_status"]
            self.evidence.replace_document(role, document)

        self.assertTrue(self.evidence.analyze()["qualified"])

    def test_rejects_explicitly_corrupt_policy_profile(self) -> None:
        document = self.evidence.document("c_guarded")
        document["policy_body_corrupted"] = True
        self.evidence.replace_document("c_guarded", document)

        with self.assertRaisesRegex(policy_ab.PolicyABError, "corrupt policy"):
            self.evidence.analyze()

    def test_rejects_semantic_final_owner_drift(self) -> None:
        document = self.evidence.document("c_guarded")
        document["final_state"]["slots"]["flags_sha256"] = "e" * 64
        self.evidence.replace_document("c_guarded", document)

        with self.assertRaisesRegex(policy_ab.PolicyABError, "final owner states"):
            self.evidence.analyze()

    def test_rejects_shared_runtime_identity_drift(self) -> None:
        document = self.evidence.document("c_guarded")
        replacement = write_artifact(
            Path(self.temporary.name) / "c_guarded" / "other-vdp.so", b"other"
        )
        document["vdp"] = replacement
        self.evidence.replace_document("c_guarded", document)

        with self.assertRaisesRegex(policy_ab.PolicyABError, "different vdp"):
            self.evidence.analyze()

    def test_rejects_stale_program_artifact(self) -> None:
        document = self.evidence.document("accepted_asm")
        Path(document["program"]["path"]).write_bytes(b"changed")

        with self.assertRaisesRegex(policy_ab.PolicyABError, "changed after capture"):
            self.evidence.analyze()

    def test_rejects_non_distinct_process_logs(self) -> None:
        dual_log = self.evidence.paths["dual_strict"].parent / "emulator.log"
        guarded_log = self.evidence.paths["c_guarded"].parent / "emulator.log"
        guarded_log.write_bytes(dual_log.read_bytes())
        document = self.evidence.document("c_guarded")
        document["log_sha256"] = policy_ab.sha256(guarded_log)
        self.evidence.replace_document("c_guarded", document)

        with self.assertRaisesRegex(policy_ab.PolicyABError, "distinct processes"):
            self.evidence.analyze()


if __name__ == "__main__":
    unittest.main()
