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

import build_regular_lod_mos_uart_thre_sibling as builder  # noqa: E402
import build_regular_lod_crc_register_sibling as crc_builder  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RegularLodMosUartThreSiblingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.crc_build = Path(cls.temporary.name) / "crc-register"
        cls.output = Path(cls.temporary.name) / "mos-uart-thre"
        crc_builder.main(("--output", str(cls.crc_build)))
        builder.main(
            (
                "--crc-build",
                str(cls.crc_build),
                "--output",
                str(cls.output),
            )
        )
        cls.receipt = json.loads(
            (cls.output / builder.REPORT_NAME).read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_patch_is_one_exact_reversible_byte_with_pinned_hash(self) -> None:
        original, _contract = builder.validate_pinned_contract()
        candidate, witness = builder.patch_image(original)

        self.assertEqual(len(candidate), len(original))
        self.assertEqual(witness["changed_offsets"], [0x001060])
        self.assertEqual(witness["before"], 0x40)
        self.assertEqual(witness["after"], 0x20)
        self.assertTrue(witness["all_other_bytes_exact"])
        self.assertTrue(witness["reverse_patch_exact"])
        self.assertEqual(hashlib.sha256(candidate).hexdigest(), builder.PATCHED_MOS_SHA256)
        with self.assertRaisesRegex(builder.MosUartThreBuildError, "exact pinned"):
            wrong = bytearray(original)
            wrong[builder.UART0_TX_MASK_OFFSET] = 0x00
            builder.patch_image(bytes(wrong))
        with self.assertRaisesRegex(builder.MosUartThreBuildError, "exact pinned"):
            damaged = bytearray(original)
            damaged[0x1056] ^= 1
            builder.patch_image(bytes(damaged))

    def test_pinned_opcode_map_and_readiness_truth_table_are_exact(self) -> None:
        _image, contract = builder.validate_pinned_contract()
        rows = builder.readiness_truth_table()

        self.assertEqual(contract["rst18_target"], 0x001422)
        self.assertEqual(contract["uart0_tx_offset"], 0x001056)
        self.assertEqual(contract["uart0_tx_mask_offset"], 0x001060)
        self.assertEqual(contract["uart0_tx_thr_offset"], 0x00106D)
        self.assertFalse(rows[0]["temt_control_ready"])
        self.assertFalse(rows[0]["thre_candidate_ready"])
        self.assertFalse(rows[1]["temt_control_ready"])
        self.assertTrue(rows[1]["thre_candidate_ready"])
        self.assertTrue(rows[2]["temt_control_ready"])
        self.assertTrue(rows[2]["thre_candidate_ready"])

    def test_runtime_corpus_binds_all_227_exact_container_streams(self) -> None:
        evidence = builder.validate_runtime_corpus()

        self.assertTrue(evidence["qualified"])
        self.assertEqual(
            evidence["aggregates"],
            {
                "records": 227,
                "container_bytes": 787_192,
                "data_bytes": 764_288,
                "maximum_record_bytes": 4_568,
            },
        )
        self.assertEqual(
            evidence["coverage_digest_sha256"],
            "1cf09313ba0b2983a4a8c9f09fb01bfb0c3e9d854bb7520d988043ccaace141d",
        )
        self.assertEqual(len(evidence["records"]), 227)

    def test_control_candidate_and_receipt_are_deterministic(self) -> None:
        names = (
            builder.REPORT_NAME,
            builder.CONTROL_MOS_NAME,
            builder.CANDIDATE_MOS_NAME,
        )
        first = {name: (self.output / name).read_bytes() for name in names}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "second"
            builder.main(
                (
                    "--crc-build",
                    str(self.crc_build),
                    "--output",
                    str(output),
                )
            )
            second = {name: (output / name).read_bytes() for name in names}
        self.assertEqual(second, first)
        self.assertEqual(
            sha256(self.output / builder.CONTROL_MOS_NAME),
            builder.PINNED_MOS_SHA256,
        )
        self.assertEqual(
            sha256(self.output / builder.CANDIDATE_MOS_NAME),
            builder.PATCHED_MOS_SHA256,
        )

    def test_receipt_pins_private_crc1_app_and_forbids_blob_promotion(self) -> None:
        receipt = self.receipt

        self.assertTrue(receipt["qualified"])
        self.assertEqual(receipt["schema"], builder.SCHEMA)
        self.assertEqual(
            receipt["artifacts"]["legacy_control_program"]["sha256"],
            crc_builder.ACCEPTED_PROGRAM_SHA256,
        )
        self.assertFalse(
            receipt["historical_crc1_control"]["canonical_target_consulted"]
        )
        self.assertFalse(receipt["scope"]["accepted_application_modified"])
        self.assertFalse(receipt["scope"]["external_fab_checkout_modified"])
        self.assertTrue(
            receipt["limitations"]["must_not_install_or_distribute_patched_blob"]
        )
        self.assertTrue(
            receipt["limitations"]["patch_affects_every_uart0_serial_tx_caller"]
        )
        self.assertEqual(
            receipt["runtime_corpus"]["coverage_digest_sha256"],
            builder.EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256,
        )
        self.assertEqual(
            receipt["reference_source_context"][
                "observed_uart0_tx_readiness_symbol"
            ],
            "UART_LSR_ETH",
        )

    def test_build_does_not_touch_accepted_or_other_sibling_paths(self) -> None:
        immutable = tuple(
            path for path, _size, _digest in builder.ACCEPTED_INPUT_SPECS.values()
        ) + (
            builder.PINNED_MOS,
            builder.PINNED_MAP,
            builder.REFERENCE_SERIAL_SOURCE,
            ROOT / "scripts/build_regular_lod_uart_thre_sibling.py",
            ROOT / "scripts/build_regular_lod_crc_register_sibling.py",
            ROOT / "moslets/fsim/tgt/fsim.bin",
            ROOT / "moslets/fsim/tgt/fsim.lst",
            ROOT / "moslets/fsim/tgt/fsim.symbols",
        )
        before = {path: sha256(path) for path in immutable}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "immutability-build"
            builder.main(
                (
                    "--crc-build",
                    str(self.crc_build),
                    "--output",
                    str(output),
                )
            )
        self.assertEqual({path: sha256(path) for path in immutable}, before)

    def test_simulated_promoted_canonical_target_is_not_consulted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promoted_program = root / "canonical.bin"
            promoted_listing = root / "canonical.lst"
            promoted_symbols = root / "canonical.symbols"
            for path, payload in (
                (promoted_program, b"promoted-nibble-program"),
                (promoted_listing, b"promoted-nibble-listing"),
                (promoted_symbols, b"promoted-nibble-symbols"),
            ):
                path.write_bytes(payload)
            output = root / "mos-build"
            with (
                mock.patch.object(crc_builder, "ACCEPTED_PROGRAM", promoted_program),
                mock.patch.object(crc_builder, "ACCEPTED_LISTING", promoted_listing),
                mock.patch.object(crc_builder, "ACCEPTED_SYMBOLS", promoted_symbols),
            ):
                builder.main(
                    (
                        "--crc-build",
                        str(self.crc_build),
                        "--output",
                        str(output),
                    )
                )

            program = output / f"{crc_builder.CONTROL_PROGRAM_STEM}.bin"
            self.assertEqual(sha256(program), crc_builder.ACCEPTED_PROGRAM_SHA256)


if __name__ == "__main__":
    unittest.main()
