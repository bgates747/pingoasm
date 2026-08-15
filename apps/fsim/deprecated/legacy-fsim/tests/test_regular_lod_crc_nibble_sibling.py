from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regular_lod_crc_nibble_sibling as nibble  # noqa: E402
import build_regular_lod_crc_register_sibling as register  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RegularLodCrcNibbleSiblingTests(unittest.TestCase):
    def test_hash_pinned_integrated_nibble_policy_is_unique(self) -> None:
        loader = nibble.ACCEPTED_LOADER.read_text(encoding="utf-8")

        witness = register.integrated_policy_witness(
            loader,
            nibble.CANDIDATE_CRC_BLOCK,
            nibble.CANDIDATE_CRC_BLOCK_SHA256,
            4,
        )

        self.assertEqual(witness["replacement_count"], 0)
        self.assertEqual(
            witness["canonical_block_sha256"],
            nibble.CANONICAL_CRC_BLOCK_SHA256,
        )
        self.assertEqual(
            witness["candidate_block_sha256"],
            nibble.CANDIDATE_CRC_BLOCK_SHA256,
        )
        self.assertTrue(witness["loader_unmodified"])
        self.assertTrue(witness["integrated_blocks_unique"])
        self.assertEqual(witness["integrated_policy_selection"], 4)
        canonical = register.extract_crc_block(loader)
        self.assertEqual(loader.count(canonical), 1)
        self.assertEqual(loader.count(nibble.CANDIDATE_CRC_BLOCK), 1)
        damaged = loader.replace("xor 020h", "xor 021h", 1)
        with self.assertRaisesRegex(nibble.CrcNibbleSiblingBuildError, "hash"):
            register.extract_crc_block(damaged)

    def test_table_and_exact_rrd_memory_model_match_iso_hdlc_vectors(self) -> None:
        table = nibble.validate_table()
        evidence = nibble.validate_differential_vectors()

        self.assertEqual(table["entries"], 16)
        self.assertEqual(table["bytes"], 64)
        self.assertEqual(table["alignment"], 256)
        self.assertEqual(
            table["little_endian_sha256"],
            "9af680c2988bbb73e930ba9b2e9a51a28303c3add723b5685f2d5e9a9d1eb8a8",
        )
        self.assertEqual(nibble.nibble_crc32(b"123456789"), 0xCBF43926)
        self.assertEqual(evidence["count"], 30)
        self.assertTrue(evidence["same_payload_set_as_register_sibling"])
        self.assertEqual(
            evidence["digest_sha256"],
            register.EXPECTED_VECTOR_DIGEST_SHA256,
        )
        for payload in register.deterministic_vectors():
            self.assertEqual(
                nibble.nibble_crc32(payload), zlib.crc32(payload) & 0xFFFFFFFF
            )

    def test_exact_227_record_corpus_and_single_bit_negatives(self) -> None:
        evidence = nibble.validate_corpus_crc()

        self.assertTrue(evidence["qualified"])
        self.assertEqual(
            evidence["aggregates"],
            {
                "records": 227,
                "container_bytes": 787_192,
                "data_bytes": 764_288,
                "maximum_record_bytes": 4_568,
                "level_counts": {
                    "fine": 91,
                    "L1": 11,
                    "L2": 21,
                    "L4": 6,
                    "L8": 98,
                },
            },
        )
        self.assertEqual(len(evidence["records"]), 227)
        self.assertEqual(
            evidence["coverage_digest_sha256"],
            "ae068d40838e5e2f04fc48cbddd18a383d902618c69ddf9ab50f80c54d1bf089",
        )
        self.assertTrue(
            all(
                record["negative_single_bit"]["rejected"]
                for record in evidence["records"]
            )
        )

    def test_instruction_and_error_precedence_contracts_are_explicit(self) -> None:
        contract = nibble.validate_instruction_contract()
        precedence = nibble.validate_error_precedence()

        self.assertEqual(contract["nibble_passes_unrolled"], 2)
        self.assertEqual(contract["rrd_operations_per_byte"], 8)
        self.assertTrue(contract["interrupt_mask_unchanged"])
        self.assertTrue(contract["shadow_registers_unchanged"])
        self.assertIn("BC, DE, HL, and IX", contract["asynchronous_handler_caveat"])
        self.assertEqual(
            precedence["call_order"],
            [
                "padding",
                "position_indices",
                "uv_indices",
                "crc32",
                "retain_descriptor",
            ],
        )
        self.assertTrue(precedence["invalid_position_index_returns_before_crc"])
        self.assertTrue(precedence["invalid_uv_index_returns_before_crc"])
        self.assertTrue(precedence["descriptor_publication_after_crc"])

    def test_static_design_is_smaller_safer_choice_than_byte_table(self) -> None:
        corpus = nibble.validate_corpus_crc()
        design = nibble.validate_static_design(corpus)

        self.assertEqual(design["candidate_cycles_per_data_byte"], 130)
        self.assertEqual(
            design["candidate_hardware_instruction_baseline_cycles_per_data_byte"],
            138,
        )
        self.assertEqual(design["register_polynomial_applications"], 3_058_615)
        self.assertAlmostEqual(
            design["register_mean_k_per_data_byte"], 4.0019141998827665
        )
        self.assertEqual(design["candidate_estimated_cycles"], 99_396_484)
        self.assertEqual(design["register_estimated_cycles"], 159_018_264)
        self.assertEqual(design["live_register_cycles_over_static_model"], 75_703)
        self.assertEqual(
            design["candidate_calibrated_cycles_if_live_overhead_is_shared"],
            99_472_187,
        )
        self.assertAlmostEqual(
            design["candidate_estimated_reduction_from_live_register_crc_percent"],
            37.52341092858663,
        )
        self.assertAlmostEqual(
            design[
                "candidate_calibrated_reduction_from_live_register_crc_percent"
            ],
            37.475827100345036,
        )
        self.assertEqual(design["candidate_block_machine_bytes"], 377)
        self.assertEqual(design["candidate_block_growth_bytes"], 238)

    def test_scratch_build_reproduces_control_and_never_touches_accepted(self) -> None:
        immutable = (
            nibble.ACCEPTED_SOURCE,
            nibble.ACCEPTED_LOADER,
            nibble.ACCEPTED_PROGRAM,
            nibble.ACCEPTED_LISTING,
            nibble.ACCEPTED_SYMBOLS,
            ROOT / "moslets/fsim/tgt/fsim.bin",
            ROOT / "moslets/fsim/tgt/fsim.lst",
            ROOT / "moslets/fsim/tgt/fsim.symbols",
        )
        before = {path: sha256(path) for path in immutable}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crc-nibble-sibling"
            self.assertEqual(nibble.main(("--output", str(output))), 0)
            receipt = json.loads(
                (output / "BUILD.json").read_text(encoding="utf-8")
            )

        self.assertEqual({path: sha256(path) for path in immutable}, before)
        self.assertEqual(receipt["schema"], nibble.SCHEMA)
        self.assertTrue(receipt["qualified"])
        self.assertFalse(receipt["scope"]["emulator_run"])
        self.assertEqual(
            receipt["source_patch"]["temporary_control_program_sha256"],
            register.ACCEPTED_PROGRAM_SHA256,
        )
        self.assertTrue(
            receipt["source_patch"]["temporary_control_program_exact"]
        )
        self.assertEqual(
            receipt["artifacts"]["program"]["sha256"],
            "ae0a45869dde58e44bcdad82e0294c937c1ff81df1ce4aba142d2e60983812c8",
        )
        self.assertEqual(receipt["artifacts"]["program"]["bytes"], 142_988)
        self.assertEqual(
            receipt["artifacts"]["listing"]["sha256"],
            "d39bbe43ee4dc2bcda1d14945b8a6d1f55c119013e58a9ffbb6c621fc92efc14",
        )
        self.assertEqual(
            receipt["artifacts"]["symbols"]["sha256"],
            "fefc6a6e2e051faad70e90db57573f35f19e55e7a48a37c3363f98d0833e2756",
        )
        self.assertTrue(receipt["source_patch"]["loader_unmodified"])
        self.assertEqual(
            receipt["source_patch"]["integrated_policy_selection"], 4
        )
        self.assertEqual(
            receipt["memory"]["p3dm_crc32_nibble_table"],
            [0x043900, 0x043940],
        )
        self.assertIn("0 definite width hazards", receipt["adl_audit"]["output"])
        self.assertIn("0 indirect/unresolved", receipt["adl_audit"]["output"])


if __name__ == "__main__":
    unittest.main()
