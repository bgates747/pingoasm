from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

from pingo_terrain.p3dm import make_data, parse_container


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "build/p3dm/bay-area-distance-lod-control"
DISTANCE = OUTPUT / "DISTANCE.json"
ASSEMBLY = (
    ROOT
    / "fixtures/terrain-manager-survey/src/terrain-manager-distance-survey.asm"
)
PROVIDER = (
    ROOT
    / "fixtures/terrain-manager-survey/src/terrain-manager-distance-provider.inc"
)
BUILDER_PATH = ROOT / "scripts/build_distance_lod_control.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_distance_lod_control", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DISTANCE.is_file(), "distance-LOD corpus has not been exported")
class DistanceLodCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(DISTANCE.read_text(encoding="utf-8"))

    def test_exact_aggregate_and_cell_coverage(self) -> None:
        geometry = self.document["geometry"]
        self.assertEqual(
            geometry,
            {
                "chunks": 92,
                "container_bytes": 384_488,
                "maximum_record_bytes": 5_600,
                "model_half_extent_m": 1_792,
                "object_scale_q8_8": 57_344,
                "selected_cells": 2_700,
                "skirt_triangles": 7_624,
                "surface_triangles": 16_200,
            },
        )
        cells = [tuple(cell) for record in self.document["records"] for cell in record["cells"]]
        self.assertEqual(len(cells), 2_700)
        self.assertEqual(len(set(cells)), 2_700)
        self.assertEqual(
            {record["tier"] for record in self.document["records"]}, {1, 2}
        )
        self.assertEqual(
            sum(record["tier"] == 1 for record in self.document["records"]), 23
        )
        self.assertEqual(
            sum(record["tier"] == 2 for record in self.document["records"]), 69
        )

    def test_every_container_round_trips_and_fits(self) -> None:
        totals = {"vertices": 0, "triangles": 0, "data_bytes": 0, "bytes": 0}
        for ordinal, record in enumerate(self.document["records"]):
            self.assertEqual(record["ordinal"], ordinal)
            self.assertEqual(record["path"], f"DST/00/{ordinal:02X}.AGN")
            path = OUTPUT / record["path"]
            payload = path.read_bytes()
            self.assertEqual(len(payload), record["bytes"])
            self.assertLess(len(payload), 16_384)
            tile = parse_container(payload)
            self.assertEqual(tile.meta.lod, record["tier"])
            self.assertEqual(tile.meta.tile_x, record["bucket_q"])
            self.assertEqual(tile.meta.tile_y, record["bucket_r"])
            self.assertEqual(tile.meta.model_half_extent_m, 1_792)
            totals["vertices"] += len(tile.positions)
            totals["triangles"] += len(tile.position_indices) // 3
            totals["data_bytes"] += len(make_data(tile))
            totals["bytes"] += len(payload)
        self.assertEqual(
            totals,
            {
                "vertices": 13_910,
                "triangles": 23_824,
                "data_bytes": 375_236,
                "bytes": 384_488,
            },
        )

    def test_builder_accepts_exact_generated_plan(self) -> None:
        builder = load_builder()
        report = builder.require_distance_plan(OUTPUT)
        self.assertEqual(report["geometry"]["chunks"], 92)


class DistanceLodAssemblyContractTests(unittest.TestCase):
    def test_one_universal_manager_owns_all_183_slots(self) -> None:
        source = ASSEMBLY.read_text(encoding="utf-8")
        self.assertIn("terrain_manager_slot_count: equ 183", source)
        self.assertIn('include "terrain-manager-distance-provider.inc"', source)
        self.assertIn('include "../../../runtime/ez80/terrain-manager.inc"', source)
        self.assertNotIn('include "terrain-manager-hex-provider.inc"', source)
        self.assertLess(source.index("CCS sid"), source.index("pingo_set_projection_far_units"))
        self.assertIn("manager_survey_projection_far_units: equ 65535", source)

    def test_provider_keeps_near_and_coarse_contracts_distinct(self) -> None:
        source = PROVIDER.read_text(encoding="utf-8")
        for literal in (
            "add a,distance_lod_chunk_count",
            "add a,distance_lod_near_slot_count",
            "distance_provider_position_coarse_candidate:",
            "call distance_provider_refresh_origin_shift",
            "sbc hl,de",
            "every static coarse chunk is desired",
        ):
            self.assertIn(literal, source)
        self.assertEqual(source.count("terrain_provider_load_candidate:"), 1)
        self.assertEqual(source.count("terrain_provider_position_candidate:"), 1)

    def test_desired_counts_fit_the_u8_manager(self) -> None:
        near = (1, 7, 19, 37, 61, 91)
        self.assertEqual(tuple(count + 92 for count in near), (93, 99, 111, 129, 153, 183))
        self.assertLessEqual(183, 255)


if __name__ == "__main__":
    unittest.main()
