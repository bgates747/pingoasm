from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import capture_regular_lod_manager_survey as regular  # noqa: E402


class RegularLodCaptureContractTests(unittest.TestCase):
    def test_cold_capture_uses_exact_manager_bounds(self) -> None:
        self.assertEqual(regular.START_CELL, (80, 125))
        self.assertEqual(regular.DEFAULT_RADIUS, 5)
        self.assertEqual(regular.SLOT_COUNT, 255)
        self.assertEqual(regular.ACTIVE_COUNT, 227)
        self.assertEqual(regular.SEQUENCES, (0, 226))
        self.assertEqual(regular.PROGRAM_NAME, "P3DRGL.BIN")

    def test_shared_capture_binding_is_complete(self) -> None:
        survey = regular.survey
        names = (
            "FIXTURE",
            "DEFAULT_RADIUS",
            "SEQUENCES",
            "START_CELL",
            "SLOT_COUNT",
            "PROGRAM_NAME",
            "PROGRAM",
            "MANIFEST",
            "WORLD",
            "MANIFEST_SCHEMA",
            "CAPTURE_SCHEMA",
            "CAPTURE_REPORT_NAME",
            "CAPTURE_LABEL",
            "expected_cells",
            "terrain_record_paths",
            "expected_publication_shapes",
            "validate_fixture_contract",
        )
        previous = {name: getattr(survey, name) for name in names}
        try:
            regular.configure_shared_capture()
            self.assertEqual(survey.FIXTURE, regular.FIXTURE)
            self.assertEqual(survey.SLOT_COUNT, 255)
            self.assertEqual(survey.SEQUENCES, (0, 226))
            self.assertIs(survey.expected_cells, regular.expected_cells)
            self.assertIs(
                survey.terrain_record_paths, regular.terrain_record_paths
            )
            self.assertIs(
                survey.expected_publication_shapes,
                regular.expected_publication_shapes,
            )
        finally:
            for name, value in previous.items():
                setattr(survey, name, value)

    def test_final_render_parser_requires_all_227_objects(self) -> None:
        line = (
            "PINGO_RENDER seq=226 bmid=257 render_us=1 far=65535 "
            "ob=227 obt=227 ofr=100\n"
        )
        self.assertEqual(
            regular._final_render_counts(line),
            {"far": 65_535, "ob": 227, "obt": 227},
        )
        with self.assertRaises(SystemExit):
            regular._final_render_counts(
                "PINGO_RENDER seq=226 bmid=257 far=65535 ob=226 obt=226\n"
            )


@unittest.skipUnless(regular.MANIFEST.is_file(), "regular manager is not installed")
class InstalledRegularLodCaptureContractTests(unittest.TestCase):
    def test_receipt_drives_exact_paths_shapes_and_transforms(self) -> None:
        records = regular.initial_records()
        self.assertEqual(len(records), 227)
        self.assertEqual(len(regular.terrain_record_paths()), 227)
        self.assertEqual(len(regular.expected_cells()), 227)
        self.assertEqual(len(regular.expected_publication_shapes()), 227)
        self.assertEqual(records[0]["object_id"], 47)
        self.assertEqual(records[-1]["object_id"], 227)


if __name__ == "__main__":
    unittest.main()
