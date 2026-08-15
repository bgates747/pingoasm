from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_regular_lod_crc_nibble_cumulative as analysis  # noqa: E402


class CrcNibbleCumulativeAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.receipt = analysis.analyze(
            analysis.DEFAULT_BASELINE_REPORT,
            analysis.DEFAULT_CANDIDATE_REPORT,
        )

    def test_exact_reports_raw_logs_and_identity_join_reparse(self) -> None:
        receipt = self.receipt
        self.assertTrue(receipt["qualified"])
        self.assertFalse(receipt["scope"]["emulator_run"])
        self.assertEqual(
            receipt["identity"]["baseline_report"]["sha256"],
            analysis.BASELINE_REPORT_SHA256,
        )
        self.assertEqual(
            receipt["identity"]["candidate_report"]["sha256"],
            analysis.CANDIDATE_REPORT_SHA256,
        )
        self.assertEqual(
            receipt["raw_reparse"]["baseline_log"]["sha256"],
            analysis.BASELINE_LOG_SHA256,
        )
        self.assertEqual(
            receipt["raw_reparse"]["candidate_log"]["sha256"],
            analysis.CANDIDATE_LOG_SHA256,
        )
        self.assertEqual(receipt["raw_reparse"]["baseline_records"], 227)
        self.assertEqual(receipt["raw_reparse"]["candidate_records"], 227)
        self.assertEqual(
            receipt["identity"]["evidence_parser_sources"],
            analysis.EVIDENCE_PARSER_IDENTITIES,
        )
        self.assertEqual(
            receipt["identity"]["current_parser_sources"],
            analysis.CURRENT_PARSER_IDENTITIES,
        )
        self.assertTrue(
            receipt["scope"]["historical_to_current_parser_compatibility_pinned"]
        )
        self.assertTrue(
            receipt["scope"][
                "historical_manager_rebound_to_evidence_local_snapshot"
            ]
        )
        self.assertFalse(receipt["scope"]["live_manager_path_consulted"])
        manager = receipt["identity"]["shared_runtime"]["historical_manager"]
        self.assertEqual(
            manager["evidence_local_snapshot"]["sha256"],
            analysis.manager_witness.HISTORICAL_MANAGER_SHA256,
        )
        self.assertTrue(
            all(receipt["comparability"].values())
        )

    def test_exact_all227_and_loop226_cumulative_deltas(self) -> None:
        metric = self.receipt["metric"]
        all_records = metric["all_records_including_startup_0"]
        loop = metric["loop_records_1_through_226"]
        self.assertEqual(all_records["baseline_cycles"], 577_773_621)
        self.assertEqual(all_records["candidate_cycles"], 277_614_315)
        self.assertEqual(all_records["delta_cycles"], -300_159_306)
        self.assertEqual(
            all_records["candidate_vs_baseline_percent_rounded_4dp"],
            "-51.9510%",
        )
        self.assertEqual(loop["baseline_cycles"], 575_316_551)
        self.assertEqual(loop["candidate_cycles"], 276_165_167)
        self.assertEqual(loop["delta_cycles"], -299_151_384)
        self.assertEqual(
            loop["candidate_vs_baseline_percent_rounded_4dp"],
            "-51.9977%",
        )

    def test_receipt_is_deterministic_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            self.assertEqual(analysis.main(("--output", str(first))), 0)
            self.assertEqual(analysis.main(("--output", str(second))), 0)
            first_bytes = (first / analysis.RECEIPT_NAME).read_bytes()
            second_bytes = (second / analysis.RECEIPT_NAME).read_bytes()
            self.assertEqual(first_bytes, second_bytes)
            parsed = json.loads(first_bytes)
            self.assertEqual(parsed, self.receipt)
            with self.assertRaisesRegex(
                analysis.CumulativeAnalysisError, "refusing to replace"
            ):
                analysis.main(("--output", str(first)))

    def test_mutated_report_and_semantic_join_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mutated = Path(directory) / "baseline.json"
            mutated.write_bytes(
                analysis.DEFAULT_BASELINE_REPORT.read_bytes() + b" "
            )
            with self.assertRaisesRegex(
                analysis.CumulativeAnalysisError, "baseline report.*identity changed"
            ):
                analysis.analyze(mutated, analysis.DEFAULT_CANDIDATE_REPORT)

        baseline_report = analysis.load_json(analysis.DEFAULT_BASELINE_REPORT)
        candidate_report = analysis.load_json(analysis.DEFAULT_CANDIDATE_REPORT)
        baseline = analysis.reparse_normative(
            baseline_report,
            "accepted-temt-control",
            analysis.combined.resolve_normative_layout,
            analysis.combined.layout_evidence,
        )
        candidate = analysis.reparse_normative(
            candidate_report,
            "crc-nibble-thre-candidate",
            analysis.nibble.resolve_normative_layout,
            analysis.nibble.layout_evidence,
        )
        changed = copy.deepcopy(candidate)
        changed["record_identities"][0]["file_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            analysis.CumulativeAnalysisError, "record_identities differs"
        ):
            analysis.assert_comparable(
                baseline_report, candidate_report, baseline, changed
            )

    def test_output_must_not_overlap_either_input_evidence_tree(self) -> None:
        for root_name, input_root in (
            ("candidate", analysis.DEFAULT_CANDIDATE_REPORT.parent),
            ("manager-witness", analysis.DEFAULT_MANAGER_WITNESS),
        ):
            for relation, output in (
                ("equal", input_root),
                ("descendant", input_root / "analysis"),
                ("ancestor", input_root.parent),
            ):
                with self.subTest(root=root_name, relation=relation), self.assertRaisesRegex(
                    analysis.CumulativeAnalysisError,
                    "must not equal, contain, or descend",
                ):
                    analysis.main(("--output", str(output)))

    def test_promoted_live_manager_is_not_consulted(self) -> None:
        value = json.loads(
            analysis.mos_profile.builder.MANAGER_MANIFEST.read_text(encoding="utf-8")
        )
        value["binary"]["bytes"] = 142_988
        value["binary"]["sha256"] = (
            "ae0a45869dde58e44bcdad82e0294c937c1ff81df1ce4aba142d2e60983812c8"
        )
        value["manager"]["loader_crc32"] = {
            "compile_time_value": 4,
            "algorithm": "CRC-32/ISO-HDLC reflected",
            "polynomial": "EDB88320",
            "init": "FFFFFFFF",
            "xorout": "FFFFFFFF",
            "implementation": "16-entry 256-aligned RRD nibble table",
            "table_entries": 16,
            "rrd_operations_per_data_byte": 8,
        }
        with tempfile.TemporaryDirectory() as directory:
            promoted = Path(directory) / "MANAGER.json"
            promoted.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(promoted.stat().st_size, 146_504)
            self.assertEqual(
                hashlib.sha256(promoted.read_bytes()).hexdigest(),
                "e0edbed10fac20ac3f27c63fd7abd9a0e6a0c86311e72f8018255c6a5bb539fc",
            )
            with mock.patch.object(
                analysis.mos_profile.builder,
                "MANAGER_MANIFEST",
                promoted,
            ):
                receipt = analysis.analyze(
                    analysis.DEFAULT_BASELINE_REPORT,
                    analysis.DEFAULT_CANDIDATE_REPORT,
                )
        self.assertFalse(receipt["scope"]["live_manager_path_consulted"])
        self.assertEqual(
            receipt["identity"]["shared_runtime"]["historical_manager"]
            ["historical_report_identity"],
            analysis.manager_witness.HISTORICAL_REPORT_IDENTITY,
        )

    def test_mutated_historical_manager_witness_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "manager-witness"
            shutil.copytree(analysis.DEFAULT_MANAGER_WITNESS, copied)
            snapshot = copied / analysis.manager_witness.SNAPSHOT_NAME
            snapshot.write_bytes(snapshot.read_bytes() + b" ")
            with self.assertRaisesRegex(
                analysis.manager_witness.HistoricalManagerWitnessError,
                "historical MANAGER identity changed",
            ):
                analysis.analyze(
                    analysis.DEFAULT_BASELINE_REPORT,
                    analysis.DEFAULT_CANDIDATE_REPORT,
                    copied,
                )

    def test_current_parser_identity_drift_fails_closed(self) -> None:
        changed = copy.deepcopy(analysis.CURRENT_PARSER_IDENTITIES)
        changed["baseline_profile"]["sha256"] = "0" * 64
        with mock.patch.object(analysis, "CURRENT_PARSER_IDENTITIES", changed):
            with self.assertRaisesRegex(
                analysis.CumulativeAnalysisError,
                "current raw-log parser source identity changed",
            ):
                analysis.analyze(
                    analysis.DEFAULT_BASELINE_REPORT,
                    analysis.DEFAULT_CANDIDATE_REPORT,
                )


if __name__ == "__main__":
    unittest.main()
