from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = ROOT / "scripts/audit_regular_lod_transition_recipes.py"


def load_audit():
    spec = importlib.util.spec_from_file_location(
        "audit_regular_lod_transition_recipes",
        AUDIT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_audit()


class RegularLodTransitionRecipeAuditTests(unittest.TestCase):
    def test_pinned_report_accepts_only_nonnegative_elapsed_time(self) -> None:
        report = {**audit.EXPECTED_REPORT, "elapsed_seconds": 0.0}
        audit.verify_report(report)
        report["elapsed_seconds"] = 12.805
        audit.verify_report(report)
        for invalid in (-0.001, None, "fast"):
            with self.subTest(invalid=invalid):
                report["elapsed_seconds"] = invalid
                with self.assertRaisesRegex(RuntimeError, "elapsed_seconds"):
                    audit.verify_report(report)

    def test_witness_drift_is_fail_closed(self) -> None:
        for field in (
            "origins",
            "valid_directed_transitions",
            "nonempty_filtered_groups",
            "minimum_staging_margin",
            "provider_reordered_groups",
            "table_sha256",
        ):
            with self.subTest(field=field):
                report = {**audit.EXPECTED_REPORT, "elapsed_seconds": 1.0}
                report[field] = "changed"
                with self.assertRaisesRegex(RuntimeError, field):
                    audit.verify_report(report)


if __name__ == "__main__":
    unittest.main()
