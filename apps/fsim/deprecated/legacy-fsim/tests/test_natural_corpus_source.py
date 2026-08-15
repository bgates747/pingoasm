from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from pingo_terrain.hex_terrain import HEX_CELL_COUNT
from pingo_terrain.natural_corpus_source import (
    COMPONENT_RECORD,
    FACE_RECORD,
    NaturalCorpusSource,
    SOURCE_SCHEMA,
    VERTEX_RECORD,
    canonical_bytes,
    semantic_payload,
    sha256_bytes,
)


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_natural_runtime_review_blender as review  # noqa: E402
import build_natural_terrain_corpus as builder  # noqa: E402
import export_natural_runtime_corpus_blender as exporter  # noqa: E402


class NaturalCorpusSourceTests(unittest.TestCase):
    def test_fixed_record_budget_matches_complete_master(self) -> None:
        self.assertEqual(VERTEX_RECORD.size, 16)
        self.assertEqual(COMPONENT_RECORD.size, 8)
        self.assertEqual(FACE_RECORD.size, 17)
        self.assertEqual(exporter.EXPECTED_VERTICES * VERTEX_RECORD.size, 7_964_272)
        self.assertEqual(HEX_CELL_COUNT * COMPONENT_RECORD.size, 401_464)
        self.assertEqual(exporter.EXPECTED_FACES * FACE_RECORD.size, 16_872_109)
        self.assertEqual(
            7_964_272 + 401_464 + 16_872_109,
            25_237_845,
        )

    def test_complete_generated_source_streams_exactly_when_present(self) -> None:
        path = exporter.DEFAULT_OUTPUT / "SOURCE.json"
        if not path.is_file():
            self.skipTest("generated complete natural source is absent")
        source = NaturalCorpusSource(path)
        counts = [0, 0, 0]
        for component in source.components():
            counts[0] += 1
            counts[1] += len(component.vertices)
            counts[2] += len(component.faces)
        self.assertEqual(counts, [50_183, 842_903, 992_477])
        self.assertEqual(
            source.document["semantic_sha256"],
            builder.EXPECTED_SOURCE_SEMANTIC_SHA256,
        )

    def test_semantic_hash_excludes_generator_metadata(self) -> None:
        document = {
            "schema": SOURCE_SCHEMA,
            "source": {"blend_sha256": "a" * 64},
            "coordinate_contract": {"counts_per_metre": 16},
            "format_contract": {"byte_order": "little-endian"},
            "selection": {"component_count": HEX_CELL_COUNT},
            "statistics": {"master_faces": 1},
            "seam_evidence": {"shared": 0},
            "sections": {"faces": {"sha256": "b" * 64}},
            "generator": {"blender_version": "first"},
        }
        first = sha256_bytes(canonical_bytes(semantic_payload(document)))
        document["generator"] = {"blender_version": "second"}
        second = sha256_bytes(canonical_bytes(semantic_payload(document)))
        self.assertEqual(first, second)

    def test_runtime_review_maps_fifteen_semantics_to_exact_three_classes(self) -> None:
        self.assertEqual([review.runtime_class(index) for index in range(15)], [0] + [1] * 4 + [2] * 10)
        self.assertEqual(review.PALETTE_INDEX_BY_MATERIAL, (20, 7, 7, 7, 7) + (21,) * 10)
        with self.assertRaises(ValueError):
            review.runtime_class(15)

    def test_generated_world_and_review_receipts_match_when_present(self) -> None:
        world_path = builder.DEFAULT_OUTPUT / "WORLD.json"
        review_path = review.DEFAULT_OUTPUT.with_suffix(".json")
        if not world_path.is_file() or not review_path.is_file():
            self.skipTest("generated complete runtime review is absent")
        world = json.loads(world_path.read_text(encoding="utf-8"))
        receipt = json.loads(review_path.read_text(encoding="utf-8"))
        self.assertEqual(world["statistics"], builder.EXPECTED_AGGREGATE)
        self.assertEqual(receipt["geometry"]["vertices"], 497_767)
        self.assertEqual(receipt["geometry"]["faces"], 992_477)
        self.assertEqual(receipt["presentation"]["material_classes"], 3)


if __name__ == "__main__":
    unittest.main()

