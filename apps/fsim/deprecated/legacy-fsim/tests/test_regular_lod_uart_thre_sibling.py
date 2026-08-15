from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regular_lod_uart_thre_sibling as sibling  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RegularLodUartThreSiblingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "uart-thre-sibling"
        sibling.main(("--output", str(cls.output)))
        cls.receipt = json.loads(
            (cls.output / "BUILD.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_hash_pinned_patch_is_one_exact_reversible_source_diff(self) -> None:
        loader = sibling.ACCEPTED_LOADER.read_text(encoding="utf-8")

        candidate, witness = sibling.patch_loader(loader)

        self.assertEqual(witness["replacement_count"], 1)
        self.assertEqual(
            witness["canonical_block_sha256"],
            sibling.CANONICAL_UPLOAD_BLOCK_SHA256,
        )
        self.assertEqual(
            witness["candidate_block_sha256"],
            sibling.CANDIDATE_UPLOAD_BLOCK_SHA256,
        )
        self.assertTrue(witness["reverse_substitution_exact"])
        canonical = sibling.extract_upload_block(loader)
        self.assertEqual(
            candidate.replace(sibling.CANDIDATE_UPLOAD_BLOCK, canonical, 1),
            loader,
        )
        damaged_block = canonical.replace(
            "P3DM_LD_U16_BC p3dm_data_size", "ld bc,1", 1
        )
        damaged = loader.replace(canonical, damaged_block, 1)
        with self.assertRaisesRegex(sibling.UartThreSiblingBuildError, "hash"):
            sibling.extract_upload_block(damaged)

    def test_pinned_console8_proves_rst18_temt_cts_and_thr_offsets(self) -> None:
        contract = sibling.validate_console8_contract()

        self.assertEqual(contract["rst18_target"], 0x001422)
        self.assertEqual(contract["rst18_counted_uart_call_offset"], 0x00142F)
        self.assertEqual(contract["uart0_putch_target"], 0x0010CA)
        self.assertEqual(contract["uart0_tx_target"], 0x001056)
        self.assertEqual(contract["uart0_tx_lsr_poll_offset"], 0x00105C)
        self.assertEqual(contract["uart0_tx_readiness_mask_offset"], 0x001060)
        self.assertEqual(contract["uart0_tx_readiness_mask"], 0x40)
        self.assertEqual(contract["uart0_tx_thr_write_offset"], 0x00106D)
        self.assertEqual(contract["uart0_cts_port"], 0xA2)
        self.assertEqual(contract["uart0_cts_mask"], 0x08)
        self.assertEqual(contract["uart0_lsr_port"], 0xC5)
        self.assertEqual(contract["uart0_thr_port"], 0xC0)
        self.assertEqual(
            contract["private_serial_flags_address"],
            sibling.MOS_SERIAL_FLAGS_ADDRESS,
        )

    def test_sender_model_honors_adversarial_readiness_and_exact_registers(self) -> None:
        payload = bytes(range(256)) * 3 + b"tail"

        result = sibling.model_uart_thre_sender(
            payload, entry_a=0xA7, schedule_seed=0x5D
        )

        self.assertEqual(result["output"], payload)
        self.assertEqual(result["writes"], len(payload))
        self.assertGreater(result["cts_polls"], len(payload))
        self.assertGreater(result["thre_polls"], len(payload))
        self.assertEqual(result["writes_before_both_ready"], 0)
        self.assertFalse(result["fallback"])
        self.assertEqual(
            result["final_registers"],
            {
                "AF": 0x0044,
                "BC": 0,
                "E": 0xA7,
                "HL_advance": len(payload),
                "MB_unchanged": True,
                "D_DEU_unchanged": True,
                "IX_IY_SP_unchanged": True,
                "alternate_registers_unchanged": True,
                "I_unchanged": True,
                "IFF1_IFF2_unchanged": True,
                "R_timing_dependent_not_compared": True,
            },
        )

    def test_zero_is_no_write_and_bad_configuration_uses_positive_fallback(self) -> None:
        zero = sibling.model_uart_thre_sender(b"", entry_a=0x5A, serial_flags=0)
        fallback = sibling.model_uart_thre_sender(
            b"\x00\x01\xff", entry_a=0xC3, serial_flags=1
        )
        dlab = sibling.model_uart_thre_sender(
            b"\x11\x22", entry_a=0xC4, dlab=True
        )
        mbase = sibling.model_uart_thre_sender(
            b"\xaa\x55", entry_a=0xC5, mbase=4
        )

        self.assertEqual(zero["output"], b"")
        self.assertEqual(zero["writes"], 0)
        self.assertTrue(zero["zero_no_write"])
        self.assertFalse(zero["fallback"])
        self.assertEqual(zero["final_registers"]["E"], 0x5A)
        self.assertEqual(fallback["output"], b"\x00\x01\xff")
        self.assertTrue(fallback["fallback"])
        self.assertEqual(dlab["output"], b"\x11\x22")
        self.assertTrue(dlab["fallback"])
        self.assertEqual(mbase["output"], b"\xaa\x55")
        self.assertTrue(mbase["fallback"])

    def test_all_227_mirrored_upload_transcripts_are_byte_exact(self) -> None:
        evidence = sibling.validate_upload_transcripts()

        self.assertTrue(evidence["qualified"])
        self.assertEqual(
            evidence["aggregates"],
            {
                "records": 227,
                "container_bytes": 787_192,
                "data_bytes": 764_288,
                "upload_transcript_bytes": 768_828,
                "maximum_record_bytes": 4_568,
                "minimum_data_bytes": 358,
                "maximum_data_bytes": 4_468,
                "level_counts": {
                    "fine": 91,
                    "L1": 11,
                    "L2": 21,
                    "L4": 6,
                    "L8": 98,
                },
            },
        )
        self.assertEqual(
            evidence["coverage_digest_sha256"],
            "d9854f9b0c9b7a399cb00f6a5202c5d452094fc5a9cdda8fab60f714ed4a7612",
        )
        self.assertEqual(
            evidence["concatenated_transcript_sha256"],
            "74bc444430713cbd07a2ca5247d9c906394fb92c5f498ee85938c272cfa731fd",
        )
        self.assertEqual(
            evidence["adversarial_readiness_schedule"][
                "writes_before_both_ready"
            ],
            0,
        )
        self.assertEqual(
            evidence["adversarial_readiness_schedule"]["writes"], 764_288
        )
        self.assertTrue(evidence["zero_count"]["explicit_no_write"])
        self.assertEqual(len(evidence["records"]), 227)

    def test_candidate_binary_is_deterministic_isolated_and_adl_clean(self) -> None:
        receipt = self.receipt

        self.assertEqual(receipt["schema"], sibling.SCHEMA)
        self.assertTrue(receipt["qualified"])
        self.assertTrue(receipt["source_patch"]["temporary_control_program_exact"])
        self.assertEqual(
            receipt["source_patch"]["temporary_control_program_sha256"],
            sibling.ACCEPTED_PROGRAM_SHA256,
        )
        self.assertEqual(receipt["source_patch"]["candidate_independent_builds"], 2)
        self.assertTrue(
            receipt["source_patch"][
                "candidate_program_listing_symbols_byte_exact"
            ]
        )
        self.assertEqual(receipt["artifacts"]["program"]["bytes"], 142_828)
        self.assertEqual(
            receipt["artifacts"]["program"]["sha256"],
            "65843171996faa8916f17f7d05eeaabe328b292eca625f17025876f64bdeb7eb",
        )
        self.assertIn("0 definite width hazards", receipt["adl_audit"]["output"])
        self.assertIn("0 indirect/unresolved", receipt["adl_audit"]["output"])
        self.assertEqual(
            receipt["candidate_opcode_contract"]["fast_readiness_mask"], 0x20
        )
        self.assertEqual(
            receipt["candidate_opcode_contract"]["opcode_windows"]["thre_poll"][
                "hex"
            ],
            "ed38c5e620",
        )
        self.assertEqual(
            receipt["candidate_opcode_contract"]["opcode_windows"]["cts_poll"][
                "hex"
            ],
            "ed38a2ed6408",
        )

    def test_build_never_touches_accepted_crc_or_launcher_artifacts(self) -> None:
        immutable = (
            sibling.ACCEPTED_SOURCE,
            sibling.ACCEPTED_LOADER,
            sibling.ACCEPTED_PROGRAM,
            sibling.ACCEPTED_LISTING,
            sibling.ACCEPTED_SYMBOLS,
            ROOT / "scripts/build_regular_lod_crc_register_sibling.py",
            ROOT / "scripts/profile_regular_lod_crc_register_sibling.py",
            ROOT / "moslets/fsim/tgt/fsim.bin",
            ROOT / "moslets/fsim/tgt/fsim.lst",
            ROOT / "moslets/fsim/tgt/fsim.symbols",
        )
        before = {path: sha256(path) for path in immutable}
        artifact_names = (
            "BUILD.json",
            f"{sibling.PROGRAM_STEM}.bin",
            f"{sibling.PROGRAM_STEM}.lst",
            f"{sibling.PROGRAM_STEM}.symbols",
        )
        first = {name: (self.output / name).read_bytes() for name in artifact_names}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "second-uart-thre-sibling"
            self.assertEqual(sibling.main(("--output", str(output))), 0)
            second = {name: (output / name).read_bytes() for name in artifact_names}
            self.assertEqual(second, first)
        self.assertEqual({path: sha256(path) for path in immutable}, before)


if __name__ == "__main__":
    unittest.main()
