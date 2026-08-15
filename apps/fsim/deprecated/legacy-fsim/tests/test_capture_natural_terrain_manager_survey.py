from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/capture_natural_terrain_manager_survey.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "capture_natural_terrain_manager_survey", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
natural = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(natural)


class NaturalManagerCaptureTests(unittest.TestCase):
    def test_variable_publication_shapes_come_from_world_records(self) -> None:
        records = []
        q0, r0 = natural.START_CELL
        for ordinal, (dq, dr) in enumerate(
            natural.survey.disk_offsets(natural.DEFAULT_RADIUS)
        ):
            cell = natural.survey.HexCell(q0 + dq, r0 + dr)
            records.append(
                {
                    "cell_id": cell.cell_id,
                    "data_bytes": 100 + ordinal,
                    "vertices": 3 + ordinal,
                    "triangles": 1 + ordinal,
                }
            )
        shapes = natural.publication_shapes({"records": records})
        self.assertEqual(len(shapes), 91)
        center_mesh = 1 + (5 * q0 + 11 * r0) % 91
        self.assertEqual(
            shapes[center_mesh],
            {
                "data_bytes": 100,
                "vertices": 3,
                "position_indices": 3,
                "texture_coordinates": 16,
                "texture_indices": 3,
            },
        )
        self.assertGreater(len(set(shape["vertices"] for shape in shapes.values())), 1)

    def test_generated_default_disk_shapes_match_runtime_world(self) -> None:
        if not natural.WORLD.is_file():
            self.skipTest("generated natural runtime corpus is absent")
        document = json.loads(natural.WORLD.read_text(encoding="utf-8"))
        shapes = natural.publication_shapes(document)
        self.assertEqual(
            set(shapes),
            set(
                natural.survey.expected_cells(
                    natural.DEFAULT_RADIUS, natural.START_CELL
                )
            ),
        )
        self.assertTrue(all(shape["texture_coordinates"] == 16 for shape in shapes.values()))
        self.assertTrue(all(shape["position_indices"] == shape["texture_indices"] for shape in shapes.values()))

    def test_shared_capture_binding_uses_nat_and_distinct_identity(self) -> None:
        natural.configure_shared_capture()
        self.assertEqual(natural.survey.PROGRAM_NAME, "P3DNAT.BIN")
        self.assertEqual(natural.survey.TERRAIN_RECORD_ROOT, "NAT")
        self.assertEqual(
            natural.survey.MANIFEST_SCHEMA,
            "pingo-terrain-natural-manager-survey-v2",
        )
        self.assertIn("natural", natural.survey.CAPTURE_REPORT_NAME)

    def test_generated_default_disk_records_match_world_checksums(self) -> None:
        if not natural.WORLD.is_file():
            self.skipTest("generated natural runtime corpus is absent")
        natural.configure_shared_capture()
        contract = natural.survey.validate_fixture_contract(
            natural.FIXTURE,
            natural.FIXTURE / natural.PROGRAM_NAME,
            natural.FIXTURE / "MANAGER.json",
            natural.WORLD,
        )
        records = contract["terrain_records"]
        self.assertEqual(len(records), 91)
        self.assertTrue(all(path.startswith("NAT/L0/") for path in records))


if __name__ == "__main__":
    unittest.main()
