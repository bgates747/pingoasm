from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure
from pingo_terrain.family_transition import (
    assembly_include,
    build_fixed_west_transition,
)
from pingo_terrain.regional_lod import parse_bundle


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/koak-flight-family-lod"
SOURCE = FIXTURE / "src"
TARGET = FIXTURE / "tgt"
PROOF = ROOT / "build/p3dm/bay-area-koak-family-proof"


class KOAKFamilyLodFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (SOURCE / "koak-flight-family-lod.asm").read_text()
        cls.streaming = (SOURCE / "family-streaming.inc").read_text()
        cls.scene = (SOURCE / "family-scene.inc").read_text()
        cls.plan = build_fixed_west_transition()

    def test_sibling_fixture_reuses_flight_but_not_loose_coordinator(self) -> None:
        self.assertIn("sid: equ 1732", self.main)
        self.assertIn('include "family-streaming.inc"', self.main)
        self.assertIn('include "family-scene.inc"', self.main)
        self.assertIn("nested-agnb-loader.inc", self.main)
        self.assertIn("pingo-wide-translation.inc", self.main)
        self.assertIn("pingo-projection.inc", self.main)
        self.assertNotIn('include "regional-streaming.inc"', self.main)
        self.assertRegex(
            self.main,
            r"ld hl,8000\s+call pingo_set_projection_far_units",
        )

    def test_scene_has_exact_37_resident_slots_but_24_steady_active(self) -> None:
        slots = [
            int(value)
            for value in re.findall(
                r"^\s*ESTABLISH_TERRAIN_SLOT\s+(\d+)\s*$",
                self.scene,
                flags=re.MULTILINE,
            )
        ]
        self.assertEqual(slots, list(range(1, 38)))
        self.assertEqual(self.plan.current_plan.terrain_count, 24)
        self.assertEqual(self.plan.next_plan.terrain_count, 24)

    def test_generated_plan_include_exactly_matches_host_oracle(self) -> None:
        self.assertEqual(
            (TARGET / "family-plan.inc").read_text(),
            assembly_include(self.plan),
        )
        record = json.loads((TARGET / "family-plan.json").read_text())
        self.assertEqual(record, self.plan.to_json_record())
        self.assertEqual(len(record["loads"]), 37)
        self.assertEqual(len(record["required_families"]), 20)

    def test_service_is_render_idle_one_load_and_swap_has_no_disk_io(self) -> None:
        loop = self.main.split("@loop:", 1)[1].split("@exit:", 1)[0]
        self.assertLess(
            loop.index("ld a,(render_in_flight)"),
            loop.index("call streaming_service_one"),
        )
        self.assertLess(
            loop.index("call streaming_service_one"),
            loop.index("call submit_current_render"),
        )
        service = self.streaming.split("streaming_service_one:", 1)[1].split(
            "family_load_current_entry:", 1
        )[0]
        self.assertEqual(service.count("call family_load_current_entry"), 1)
        loader = self.streaming.split("family_load_current_entry:", 1)[1].split(
            "streaming_record_load_error_hold:", 1
        )[0]
        self.assertEqual(loader.count("call agnb_load_selected_component"), 1)
        swap = self.streaming.split("family_maybe_swap:", 1)[1].split(
            "streaming_delta_to_count:", 1
        )[0]
        self.assertNotIn("agnb_load", swap)
        self.assertNotIn("p3dm_load", swap)
        self.assertLess(swap.index("@deactivate:"), swap.index("@activate:"))

    def test_loader_clobbers_ix_only_after_slot_and_activation_are_latched(self) -> None:
        loader = self.streaming.split("family_load_current_entry:", 1)[1].split(
            "streaming_record_load_error_hold:", 1
        )[0]
        self.assertLess(
            loader.index("call agnb_load_selected_component"),
            loader.index("ld (family_entry_activate_latched),a"),
        )
        self.assertLess(
            loader.index("call family_position_entry_ix"),
            loader.index("ld a,(family_position_slot)"),
        )
        activation = loader.split("call family_position_entry_ix", 1)[1]
        self.assertNotIn("(ix+family_entry_slot)", activation)
        self.assertNotIn("(ix+family_entry_activate)", activation)
        self.assertRegex(
            activation,
            re.compile(
                r"ld a,\(family_entry_activate_latched\).*"
                r"ld a,\(family_position_slot\).*"
                r"call pingo_set_object_active",
                re.DOTALL,
            ),
        )

    def test_plan_index_zero_extends_deu_before_mlt_and_long_add(self) -> None:
        pointer = self.streaming.split("family_plan_pointer_a:", 1)[1].split(
            "family_initialize_request_ix:", 1
        )[0]
        self.assertRegex(
            pointer,
            re.compile(
                r"ld de,0\s+.*ld e,a\s+.*"
                r"ld d,family_plan_entry_size\s+.*mlt de\s+.*"
                r"ld hl,family_plan_table\s+.*add hl,de",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            pointer,
            re.compile(r"family_plan_pointer_a:\s+ld e,a", re.DOTALL),
        )

    def test_failure_holds_cursor_and_rebase_positions_inactive_preloads(self) -> None:
        failure = self.streaming.split("streaming_record_load_error_hold:", 1)[1].split(
            "streaming_record_load_error:", 1
        )[0]
        self.assertIn("ld (family_error_hold),a", failure)
        self.assertNotIn("family_plan_cursor", failure)
        reposition = self.streaming.split("family_reposition_all:", 1)[1].split(
            "family_maybe_swap:", 1
        )[0]
        self.assertIn("family_plan_cursor", reposition)
        self.assertIn("call family_position_entry_ix", reposition)
        self.assertNotIn("pingo_set_object_active", reposition)

    def test_full_include_closure_has_no_definite_multibyte_overrun(self) -> None:
        closure = include_closure([SOURCE / "koak-flight-family-lod.asm"])
        result = audit_paths(closure)
        self.assertFalse(result.hazards)
        self.assertEqual(
            {(item.path.name, item.line) for item in result.review_items},
            {("3d.inc", 3828), ("timer.inc", 19)},
        )

    def test_generated_binary_and_twenty_family_corpus_are_self_consistent(self) -> None:
        manifest_path = PROOF / "FAMILY.json"
        if not manifest_path.is_file():
            self.skipTest("ignored family-LOD proof has not been built")
        report = json.loads(manifest_path.read_text())
        binary = PROOF / report["binary"]["path"]
        self.assertEqual(binary.stat().st_size, report["binary"]["bytes"])
        self.assertEqual(
            hashlib.sha256(binary.read_bytes()).hexdigest(),
            report["binary"]["sha256"],
        )
        corpus = report["family_corpus"]
        self.assertEqual(corpus["family_count"], 20)
        self.assertEqual(corpus["bytes"], 1_785_012)
        for family in corpus["families"]:
            path = PROOF / family["path"]
            payload = path.read_bytes()
            self.assertEqual(len(payload), family["bytes"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), family["sha256"])
            tiles, spans = parse_bundle(payload)
            self.assertEqual(len(tiles), 10)
            self.assertEqual(len(spans), 10)
            self.assertTrue(all(span.data_bytes <= 16_384 for span in spans))


if __name__ == "__main__":
    unittest.main()
