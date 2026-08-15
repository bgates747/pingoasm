from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import qualify_regular_lod_c_policy_fault_latch as fault  # noqa: E402


class FaultLatchQualificationTests(unittest.TestCase):
    def test_client_transform_is_exact_and_injects_only_guarded_call(self) -> None:
        base, transformed = fault.fault_client_source()
        self.assertEqual(transformed.count("call regular_policy_fault_inject_invalid_once"), 1)
        self.assertEqual(transformed.count(fault.DIAGNOSTIC_ROUTINES), 1)
        self.assertEqual(
            base.count("jp regular_transition_select_feasible_group_asm") + 1,
            transformed.count("jp regular_transition_select_feasible_group_asm"),
        )
        self.assertIn(fault.CALL_INJECTION_REPLACEMENT, transformed)
        self.assertIn(fault.CANDIDATE_FALLBACK_REPLACEMENT, transformed)

    def test_mode_transform_redirects_only_the_latched_branch(self) -> None:
        base, transformed = fault.fault_mode_source()
        self.assertEqual(base.count(fault.MODE_LATCH_ANCHOR), 1)
        self.assertNotIn(fault.MODE_LATCH_ANCHOR, transformed)
        self.assertEqual(transformed.count(fault.MODE_LATCH_REPLACEMENT), 1)

    def test_first_breakpoint_requires_invalid_result_and_latched_failure(self) -> None:
        snapshot = {
            "module_status": fault.staged.POLICY_STATUS_READY,
            "qualification_failure": 1,
            "selector_calls": 1,
            "candidate_failure_fallbacks": 0,
            "latched_fallbacks": 0,
            "invalid_injections": 1,
            "c_result": fault.INVALID_RESULT,
            "injected_flag": 1,
        }
        evidence = fault.validate_first_failure_snapshot(snapshot)
        self.assertTrue(evidence["first_c_result_forced_invalid"])
        self.assertTrue(evidence["qualification_failure_already_latched"])
        broken = dict(snapshot, qualification_failure=0)
        with self.assertRaisesRegex(
            fault.FaultLatchQualificationError,
            "first candidate-failure snapshot changed",
        ):
            fault.validate_first_failure_snapshot(broken)

    def test_final_policy_requires_one_candidate_and_all_latched_fallbacks(self) -> None:
        group_count = int(
            fault.edge.edge_host_contract()["recipe"]["raw_group_count"]
        )
        packed = 1 | ((group_count - 1) << 8) | (1 << 16)
        policy = {
            "mode": fault.POLICY_MODE_VALUE,
            "module_status": fault.staged.POLICY_STATUS_READY,
            "qualification_failure": 1,
            "selector_calls": 1,
            "selector_matches": packed,
        }
        evidence = fault.validate_final_policy(
            policy, expected_selector_groups=group_count
        )
        self.assertEqual(evidence["accepted_assembly_fallback_calls"], 26)
        self.assertEqual(
            evidence["diagnostic_counters"],
            {
                "candidate_failure_fallbacks": 1,
                "latched_fallbacks": 25,
                "invalid_injections": 1,
            },
        )
        self.assertTrue(evidence["c_was_not_called_after_latch"])

    def test_diagnostic_counter_byte_order_is_pinned(self) -> None:
        self.assertEqual(
            fault.diagnostic_counter_bytes(0x031201),
            {
                "candidate_failure_fallbacks": 1,
                "latched_fallbacks": 0x12,
                "invalid_injections": 3,
            },
        )


if __name__ == "__main__":
    unittest.main()
