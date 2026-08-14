from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from pingo_terrain.regular_lod_runtime import (
    ProtectedSlotAllocator,
    build_runtime_plan,
    emit_phase_include,
)


ROOT = Path(__file__).resolve().parent.parent
BUILDER_PATH = ROOT / "scripts/build_regular_lod_manager_survey.py"
ASSEMBLY = (
    ROOT
    / "fixtures/terrain-manager-survey/src/terrain-manager-regular-lod-survey.asm"
)


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_regular_lod_manager_survey", BUILDER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_builder()


class RegularLodManagerContractTests(unittest.TestCase):
    def test_marina_phase_counts_and_cold_slots_are_exact(self) -> None:
        near = []
        coarse = []
        totals = []
        for radius in range(6):
            runtime = build_runtime_plan(
                ProtectedSlotAllocator(), *builder.START_CELL, radius
            )
            near.append(len(runtime.near_entries))
            coarse.append(len(runtime.coarse.entries))
            totals.append(runtime.active_count)
        self.assertEqual(tuple(near), builder.NEAR_COUNTS)
        self.assertEqual(tuple(coarse), builder.MARINA_COARSE_COUNTS)
        self.assertEqual(tuple(totals), builder.MARINA_DESIRED_COUNTS)

        cold = build_runtime_plan(
            ProtectedSlotAllocator(),
            *builder.START_CELL,
            builder.DEFAULT_RADIUS,
        )
        self.assertEqual(
            tuple(entry.slot for entry in cold.coarse.entries),
            tuple(range(91, 227)),
        )
        self.assertEqual(cold.active_count, 227)
        centre = cold.near_entries[0]
        self.assertEqual((centre.q, centre.r, centre.slot), (80, 125, 46))

    def test_fixture_source_uses_the_full_manager_profile(self) -> None:
        source = ASSEMBLY.read_text(encoding="utf-8")
        for literal in (
            "terrain_manager_slot_count: equ 255",
            "terrain_manager_initial_ring: equ 5",
            "manager_survey_projection_far_units: equ 65535",
            'include "../../../build/p3dm/bay-area-regular-n1-hierarchy/REGCORP.INC"',
            'include "../../terrain-manager-regular-lod-survey/tgt/regular-lod-runtime.inc"',
            'include "terrain-manager-regular-lod-provider.inc"',
            'include "../../../runtime/ez80/terrain-manager.inc"',
            "call terrain_provider_prepare_plan",
        ):
            self.assertIn(literal, source)
        self.assertLess(
            source.index("CCS sid"), source.index("pingo_set_projection_far_units")
        )

    def test_generated_phase_include_is_exact(self) -> None:
        expected = emit_phase_include().encode("ascii")
        actual = builder.RUNTIME_INCLUDE.read_bytes()
        self.assertEqual(actual, expected)
        self.assertEqual(
            hashlib.sha256(actual).hexdigest(),
            "22607a410cb2c3ef3506d30d542a7eb7a14160bec8c73bd68a6abb33f204aff4",
        )

    def test_checked_trh_link_is_idempotent_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            output = root / "hierarchy"
            fine = root / "fine"
            output.mkdir()
            (fine / "TRH/L0").mkdir(parents=True)
            builder.expose_fine_corpus(output, fine)
            link = output / "TRH"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (fine / "TRH").resolve())
            builder.expose_fine_corpus(output, fine)

            link.unlink()
            link.mkdir()
            with self.assertRaises(SystemExit):
                builder.expose_fine_corpus(output, fine)


@unittest.skipUnless(
    builder.DEFAULT_OUTPUT.joinpath("WORLD.json").is_file(),
    "regular hierarchy has not been built",
)
class RegularLodManagerArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hierarchy, cls.selected = builder.require_hierarchy(
            builder.DEFAULT_OUTPUT
        )

    def test_hierarchy_and_fine_receipts_are_pinned(self) -> None:
        self.assertEqual(self.hierarchy["schema"], builder.HIERARCHY_SCHEMA)
        fine = builder.require_fine_corpus(builder.DEFAULT_FINE_CORPUS)
        self.assertEqual(fine["world_sha256"], builder.FINE_WORLD_SHA256)

    def test_exact_marina_record_set_round_trips(self) -> None:
        records, aggregates = builder.initial_runtime_records(
            builder.DEFAULT_OUTPUT,
            builder.DEFAULT_FINE_CORPUS,
            self.selected,
        )
        self.assertEqual(len(records), 227)
        self.assertEqual([record["order"] for record in records], list(range(227)))
        self.assertEqual([record["slot"] for record in records[91:]], list(range(91, 227)))
        self.assertEqual(
            aggregates,
            {
                "records": 227,
                "container_bytes": 787_192,
                "data_bytes": 764_288,
                "vertices": 28_232,
                "triangles": 48_364,
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
        self.assertEqual(records[0]["object_id"], 47)
        self.assertEqual(records[0]["path"], "TRH/L0/49/ED.AGN")
        self.assertEqual(records[0]["translation_counts"], [0, 9728, 0])
        self.assertTrue(
            all(len(record["translation_counts"]) == 3 for record in records)
        )


if __name__ == "__main__":
    unittest.main()
