from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regular_lod_crc_nibble_sibling as nibble  # noqa: E402
import build_regular_lod_crc_register_sibling as register  # noqa: E402
import build_regular_lod_mos_uart_thre_sibling as mos  # noqa: E402
import build_regular_lod_uart_thre_sibling as uart  # noqa: E402
import profile_regular_lod_crc_mos_uart_thre_combined as combined  # noqa: E402
import profile_regular_lod_crc_nibble_thre_sibling as nibble_profile  # noqa: E402
import profile_regular_lod_crc_register_sibling as register_profile  # noqa: E402
import profile_regular_lod_mos_uart_thre_sibling as mos_profile  # noqa: E402
import profile_regular_lod_uart_thre_sibling as uart_profile  # noqa: E402


PROMOTED_MANAGER_BYTES = 146_504
PROMOTED_MANAGER_SHA256 = (
    "e0edbed10fac20ac3f27c63fd7abd9a0e6a0c86311e72f8018255c6a5bb539fc"
)


def write_promoted_manager(path: Path) -> Path:
    value = json.loads(register.MANAGER_MANIFEST.read_text(encoding="utf-8"))
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
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if (
        path.stat().st_size != PROMOTED_MANAGER_BYTES
        or hashlib.sha256(path.read_bytes()).hexdigest()
        != PROMOTED_MANAGER_SHA256
    ):
        raise AssertionError("simulated promoted MANAGER identity changed")
    return path


class RegularLodManagerContextDecouplingTests(unittest.TestCase):
    def test_all_selected_corpus_witnesses_ignore_exact_promoted_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            promoted = write_promoted_manager(Path(directory) / "MANAGER.json")
            self.assertEqual(
                register.validate_corpus_crc(),
                register.validate_corpus_crc(
                    manifest_path=promoted,
                    root=register.RUNTIME_FIXTURE,
                ),
            )
            self.assertEqual(
                nibble.validate_corpus_crc(),
                nibble.validate_corpus_crc(
                    manifest_path=promoted,
                    root=nibble.RUNTIME_FIXTURE,
                ),
            )
            self.assertEqual(
                uart.validate_upload_transcripts(),
                uart.validate_upload_transcripts(
                    manifest_path=promoted,
                    root=uart.RUNTIME_FIXTURE,
                ),
            )
            self.assertEqual(
                mos.validate_runtime_corpus(),
                mos.validate_runtime_corpus(
                    manifest_path=promoted,
                    root=mos.RUNTIME_FIXTURE,
                ),
            )

    def test_crc_build_receipts_are_byte_exact_across_promoted_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promoted = write_promoted_manager(root / "MANAGER.json")
            register_before = root / "register-before"
            register_after = root / "register-after"
            register.main(("--output", str(register_before)))
            with mock.patch.object(register, "MANAGER_MANIFEST", promoted):
                register.main(("--output", str(register_after)))
            self.assertEqual(
                (register_before / "BUILD.json").read_bytes(),
                (register_after / "BUILD.json").read_bytes(),
            )
            receipt = json.loads((register_after / "BUILD.json").read_text())
            self.assertNotIn("manager_manifest", receipt["accepted_inputs"])

            nibble_before = root / "nibble-before"
            nibble_after = root / "nibble-after"
            nibble.main(("--output", str(nibble_before)))
            with mock.patch.object(register, "MANAGER_MANIFEST", promoted):
                nibble.main(("--output", str(nibble_after)))
            self.assertEqual(
                (nibble_before / "BUILD.json").read_bytes(),
                (nibble_after / "BUILD.json").read_bytes(),
            )
            receipt = json.loads((nibble_after / "BUILD.json").read_text())
            self.assertNotIn("manager_manifest", receipt["accepted_inputs"])

    def test_uart_and_mos_receipts_are_byte_exact_across_promoted_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promoted = write_promoted_manager(root / "MANAGER.json")
            uart_before = root / "uart-before"
            uart_after = root / "uart-after"
            uart.main(("--output", str(uart_before)))
            with mock.patch.object(uart, "MANAGER_MANIFEST", promoted):
                uart.main(("--output", str(uart_after)))
            self.assertEqual(
                (uart_before / "BUILD.json").read_bytes(),
                (uart_after / "BUILD.json").read_bytes(),
            )
            receipt = json.loads((uart_after / "BUILD.json").read_text())
            self.assertNotIn("manager_manifest", receipt["accepted_inputs"])

            crc_build = root / "crc"
            register.main(("--output", str(crc_build)))
            mos_before = root / "mos-before"
            mos_after = root / "mos-after"
            mos.main(
                ("--crc-build", str(crc_build), "--output", str(mos_before))
            )
            with mock.patch.object(mos, "MANAGER_MANIFEST", promoted):
                mos.main(
                    ("--crc-build", str(crc_build), "--output", str(mos_after))
                )
            self.assertEqual(
                (mos_before / "BUILD.json").read_bytes(),
                (mos_after / "BUILD.json").read_bytes(),
            )
            receipt = json.loads((mos_after / "BUILD.json").read_text())
            self.assertNotIn("current_manager_manifest", receipt["inputs"])

    def test_all_historical_profile_input_gates_accept_promoted_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            promoted = write_promoted_manager(Path(directory) / "MANAGER.json")
            register_profile.validate_build(register.DEFAULT_OUTPUT)
            uart_profile.validate_build(uart.DEFAULT_OUTPUT)
            mos_profile.validate_build(mos.DEFAULT_OUTPUT)
            with mock.patch.object(mos, "MANAGER_MANIFEST", promoted):
                combined_inputs = combined.validate_inputs(
                    register.DEFAULT_OUTPUT,
                    mos.DEFAULT_OUTPUT,
                )
                nibble_inputs = nibble_profile.validate_inputs(
                    register.DEFAULT_OUTPUT,
                    nibble_profile.DEFAULT_NIBBLE_BUILD,
                    mos.DEFAULT_OUTPUT,
                )
            self.assertEqual(
                combined_inputs.identity["manager_manifest"]["sha256"],
                PROMOTED_MANAGER_SHA256,
            )
            self.assertEqual(
                nibble_inputs.identity["manager_manifest"]["sha256"],
                PROMOTED_MANAGER_SHA256,
            )


if __name__ == "__main__":
    unittest.main()
