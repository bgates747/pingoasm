from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import capture_terrain_manager_survey as survey  # noqa: E402
import trace_natural_terrain_manager_rings as natural_trace  # noqa: E402


class NaturalManagerRingTraceTests(unittest.TestCase):
    def test_wrapper_binds_generic_trace_to_natural_fixture(self) -> None:
        original = (
            survey.FIXTURE,
            survey.PROGRAM_NAME,
            natural_trace.trace.TRACE_SCHEMA,
            natural_trace.trace.TRACE_REPORT_NAME,
            natural_trace.trace.TRACE_LABEL,
        )
        try:
            natural_trace.configure_shared_trace()
            self.assertEqual(survey.FIXTURE, natural_trace.natural.FIXTURE)
            self.assertEqual(survey.PROGRAM_NAME, "P3DNAT.BIN")
            self.assertEqual(
                natural_trace.trace.TRACE_SCHEMA,
                "pingo-terrain-natural-manager-ring-trace-v1",
            )
            self.assertEqual(
                natural_trace.trace.TRACE_REPORT_NAME,
                "natural-terrain-manager-ring-trace.json",
            )
            self.assertIn("natural", natural_trace.trace.TRACE_LABEL)
        finally:
            (
                survey.FIXTURE,
                survey.PROGRAM_NAME,
                natural_trace.trace.TRACE_SCHEMA,
                natural_trace.trace.TRACE_REPORT_NAME,
                natural_trace.trace.TRACE_LABEL,
            ) = original


if __name__ == "__main__":
    unittest.main()
