from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regular_lod_historical_manager_witness as witness  # noqa: E402


class RegularLodHistoricalManagerWitnessTests(unittest.TestCase):
    CAPTURED_SOURCE = witness.DEFAULT_OUTPUT / witness.SNAPSHOT_NAME

    def rebuild_witness(self, output: Path) -> None:
        self.assertEqual(
            witness.main(
                (
                    "--source",
                    str(self.CAPTURED_SOURCE),
                    "--output",
                    str(output),
                )
            ),
            0,
        )

    def test_snapshot_receipt_is_exact_deterministic_and_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            self.rebuild_witness(first)
            self.rebuild_witness(second)
            first_files = {
                name: (first / name).read_bytes()
                for name in (witness.SNAPSHOT_NAME, witness.REPORT_NAME)
            }
            second_files = {
                name: (second / name).read_bytes()
                for name in (witness.SNAPSHOT_NAME, witness.REPORT_NAME)
            }
            self.assertEqual(first_files, second_files)
            snapshot, _receipt_path, receipt = witness.validate_witness(first)
            self.assertEqual(snapshot.stat().st_size, witness.HISTORICAL_MANAGER_BYTES)
            self.assertEqual(witness.sha256(snapshot), witness.HISTORICAL_MANAGER_SHA256)
            self.assertEqual(
                receipt["manager_semantic_witness"]["coverage_digest_sha256"],
                witness.mos_builder.EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256,
            )

    def test_rebuild_and_validation_ignore_promoted_live_manager(self) -> None:
        original = json.loads(self.CAPTURED_SOURCE.read_text(encoding="utf-8"))
        promoted = dict(original)
        promoted["binary"]["bytes"] = 142_988
        promoted["binary"]["sha256"] = (
            "ae0a45869dde58e44bcdad82e0294c937c1ff81df1ce4aba142d2e60983812c8"
        )
        promoted["manager"]["loader_crc32"] = {
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
            root = Path(directory)
            live_manager = root / "MANAGER.promoted.json"
            live_manager.write_text(
                json.dumps(promoted, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(live_manager.stat().st_size, 146_504)
            self.assertEqual(
                witness.sha256(live_manager),
                "e0edbed10fac20ac3f27c63fd7abd9a0e6a0c86311e72f8018255c6a5bb539fc",
            )
            historical = witness.mos_builder.validate_runtime_corpus(
                manifest_path=self.CAPTURED_SOURCE,
                root=witness.mos_builder.RUNTIME_FIXTURE,
            )
            changed_context = witness.mos_builder.validate_runtime_corpus(
                manifest_path=live_manager,
                root=witness.mos_builder.RUNTIME_FIXTURE,
            )
            output = root / "rebuilt-witness"
            with (
                mock.patch.object(witness, "DEFAULT_SOURCE", live_manager),
                mock.patch.object(
                    witness.mos_builder,
                    "MANAGER_MANIFEST",
                    live_manager,
                ),
            ):
                self.rebuild_witness(output)
                snapshot, _receipt_path, receipt = witness.validate_witness(output)
            self.assertEqual(snapshot.read_bytes(), self.CAPTURED_SOURCE.read_bytes())
            self.assertEqual(
                receipt,
                json.loads(
                    (witness.DEFAULT_OUTPUT / witness.REPORT_NAME).read_text(
                        encoding="utf-8"
                    )
                ),
            )
        self.assertEqual(changed_context, historical)

    def test_mutated_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "witness"
            self.rebuild_witness(output)
            snapshot = output / witness.SNAPSHOT_NAME
            snapshot.write_bytes(snapshot.read_bytes() + b" ")
            with self.assertRaisesRegex(
                witness.HistoricalManagerWitnessError,
                "historical MANAGER identity changed",
            ):
                witness.validate_witness(output)

    def test_symlink_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "witness"
            self.rebuild_witness(output)
            snapshot = output / witness.SNAPSHOT_NAME
            target = root / "outside.json"
            target.write_bytes(snapshot.read_bytes())
            snapshot.unlink()
            snapshot.symlink_to(target)
            with self.assertRaisesRegex(
                witness.HistoricalManagerWitnessError,
                "absent or unsafe",
            ):
                witness.validate_witness(output)


if __name__ == "__main__":
    unittest.main()
