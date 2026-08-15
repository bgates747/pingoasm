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

import build_regular_lod_crc_register_sibling as sibling  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RegularLodCrcRegisterSiblingTests(unittest.TestCase):
    def test_hash_pinned_integrated_register_policy_is_unique(self) -> None:
        loader = sibling.ACCEPTED_LOADER.read_text(encoding="utf-8")

        witness = sibling.integrated_policy_witness(
            loader,
            sibling.CANDIDATE_CRC_BLOCK,
            sibling.CANDIDATE_CRC_BLOCK_SHA256,
            2,
        )

        self.assertEqual(witness["replacement_count"], 0)
        self.assertEqual(
            witness["canonical_block_sha256"],
            sibling.CANONICAL_CRC_BLOCK_SHA256,
        )
        self.assertEqual(
            witness["candidate_block_sha256"],
            sibling.CANDIDATE_CRC_BLOCK_SHA256,
        )
        self.assertTrue(witness["loader_unmodified"])
        self.assertTrue(witness["integrated_blocks_unique"])
        self.assertEqual(witness["integrated_policy_selection"], 2)
        canonical = sibling.extract_crc_block(loader)
        self.assertEqual(loader.count(canonical), 1)
        self.assertEqual(loader.count(sibling.CANDIDATE_CRC_BLOCK), 1)
        damaged = loader.replace("xor 020h", "xor 021h", 1)
        with self.assertRaisesRegex(sibling.CrcSiblingBuildError, "hash"):
            sibling.extract_crc_block(damaged)

    def test_register_model_matches_iso_hdlc_deterministic_vectors(self) -> None:
        evidence = sibling.validate_differential_vectors()

        self.assertEqual(sibling.register_crc32(b"123456789"), 0xCBF43926)
        self.assertEqual(evidence["count"], 30)
        self.assertEqual(
            evidence["digest_sha256"],
            "a438970c746b6c3d26c3bf636a22312744d9ec4c9152f7185ef3bf540561d12e",
        )
        for payload in sibling.deterministic_vectors():
            self.assertEqual(
                sibling.register_crc32(payload), zlib.crc32(payload) & 0xFFFFFFFF
            )

    def test_exact_227_record_corpus_and_single_bit_negatives(self) -> None:
        evidence = sibling.validate_corpus_crc()

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
        self.assertEqual(
            evidence["coverage_digest_sha256"],
            "07be70d9f4f44a79a96e8e740b57b8d8d572561e0595b2fa7622770e1d206671",
        )
        self.assertEqual(len(evidence["records"]), 227)
        self.assertTrue(
            all(record["negative_single_bit"]["rejected"] for record in evidence["records"])
        )

    def test_instruction_contract_preserves_register_bytes_and_error_order(self) -> None:
        contract = sibling.validate_instruction_contract()

        self.assertEqual(contract["crc_registers_low_to_high"], ["L", "H", "E", "D"])
        self.assertEqual(contract["final_crc_value_store_order"], [0, 1, 2, 3])
        self.assertEqual(contract["descriptor_compare_order"], [0, 1, 2, 3])
        self.assertEqual(contract["crc_failure_target"], "p3dm_bad_crc32")
        self.assertTrue(contract["counter_push_pop_exact"])
        self.assertTrue(contract["interrupt_mask_unchanged"])

    def test_scratch_build_reproduces_control_and_never_touches_accepted(self) -> None:
        immutable = (
            sibling.ACCEPTED_SOURCE,
            sibling.ACCEPTED_LOADER,
            sibling.ACCEPTED_PROGRAM,
            sibling.ACCEPTED_TARGET / "terrain-manager-regular-lod-survey.lst",
            sibling.ACCEPTED_TARGET / "terrain-manager-regular-lod-survey.symbols",
            ROOT / "moslets/fsim/tgt/fsim.bin",
            ROOT / "moslets/fsim/tgt/fsim.lst",
            ROOT / "moslets/fsim/tgt/fsim.symbols",
        )
        before = {path: sha256(path) for path in immutable}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crc-register-sibling"
            self.assertEqual(sibling.main(("--output", str(output))), 0)
            receipt = json.loads((output / "BUILD.json").read_text(encoding="utf-8"))
            legacy_paths = sibling.validate_legacy_control_artifacts(
                output, receipt
            )
            self.assertEqual(
                tuple(path.name for path in legacy_paths),
                (
                    "terrain-manager-regular-lod-crc-legacy-control.bin",
                    "terrain-manager-regular-lod-crc-legacy-control.lst",
                    "terrain-manager-regular-lod-crc-legacy-control.symbols",
                ),
            )

        self.assertEqual({path: sha256(path) for path in immutable}, before)
        self.assertEqual(receipt["schema"], sibling.SCHEMA)
        self.assertTrue(receipt["qualified"])
        self.assertEqual(
            receipt["source_patch"]["temporary_control_program_sha256"],
            sibling.ACCEPTED_PROGRAM_SHA256,
        )
        self.assertTrue(receipt["source_patch"]["temporary_control_program_exact"])
        self.assertTrue(receipt["source_patch"]["loader_unmodified"])
        self.assertEqual(
            receipt["source_patch"]["integrated_policy_selection"], 2
        )
        self.assertEqual(
            receipt["artifacts"]["program"]["sha256"],
            "a4a88621ee4ed3af42ad6006bebf5e48037d19ad4375568b3b9032594f139992",
        )
        self.assertEqual(receipt["artifacts"]["program"]["bytes"], 142_750)
        self.assertEqual(
            receipt["artifacts"]["legacy_control_program"],
            {
                "bytes": 142_763,
                "key": "artifacts/terrain-manager-regular-lod-crc-legacy-control.bin",
                "sha256": sibling.ACCEPTED_PROGRAM_SHA256,
            },
        )
        self.assertEqual(
            receipt["artifacts"]["legacy_control_listing"]["sha256"],
            "4951950b4f80c56a96c46246c56e1f314e5eae070600ddc9fce0111073439696",
        )
        self.assertEqual(
            receipt["artifacts"]["legacy_control_symbols"]["sha256"],
            "b1a9d5e35560df89c556f276b0910c6abf687416f0292d99882d891b46b07262",
        )
        self.assertIn("0 definite width hazards", receipt["adl_audit"]["output"])
        self.assertIn("0 indirect/unresolved", receipt["adl_audit"]["output"])
        self.assertEqual(
            receipt["memory"]["p3dm_crc_value"][1]
            - receipt["memory"]["p3dm_crc_value"][0],
            4,
        )


if __name__ == "__main__":
    unittest.main()
