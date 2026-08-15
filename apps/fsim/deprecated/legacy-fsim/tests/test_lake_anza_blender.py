from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_lake_anza_blender as lake_builder  # noqa: E402

from pingo_terrain.hex_terrain import HexCell, locate_hex_cell  # noqa: E402
from pingo_terrain.regional_raster import RasterMosaic  # noqa: E402


class LakeAnzaBlenderBuilderTests(unittest.TestCase):
    def test_plan_selects_source_centroid_cell_and_exact_radius_one_disk(self) -> None:
        cells = lake_builder.selected_cells()
        self.assertEqual(cells[0], HexCell(92, 125))
        self.assertEqual(
            [(cell.q, cell.r) for cell in cells],
            [
                (92, 125),
                (91, 126),
                (92, 126),
                (93, 125),
                (93, 124),
                (92, 124),
                (91, 125),
            ],
        )
        plan = lake_builder.plan_summary()
        self.assertEqual(plan["target_cell_count"], 7)
        self.assertEqual(plan["overbuild_context_cell_count"], 19)
        self.assertEqual(plan["lake_anza_reference_cell"], [91, 126])

    def test_plan_only_runs_without_blender_python(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_lake_anza_blender.py"), "--plan-only"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        prefix, payload = completed.stdout.split(" ", 1)
        self.assertEqual(prefix, "LAKE_ANZA_PLAN")
        self.assertEqual(json.loads(payload)["target_cell_count"], 7)

    def test_real_pinned_component_is_the_expected_cross_cell_witness(self) -> None:
        manifest = json.loads(lake_builder.SOURCE_MANIFEST.read_text())
        datasets = {item["id"]: item for item in manifest["datasets"]}
        first = ROOT / datasets[lake_builder.rectangular.NLCD_DATASET_ID]["tiles"][0]["local_path"]
        if not first.is_file():
            self.skipTest("pinned regional NLCD source is not installed")
        nlcd = RasterMosaic(
            ROOT, datasets[lake_builder.rectangular.NLCD_DATASET_ID]
        )
        component = lake_builder._find_lake_component(
            nlcd, lake_builder.selected_cells()
        )
        self.assertEqual(len(component.cells), 39)
        self.assertEqual(len(component.boundary), 34)
        boundary_utm = lake_builder.project_points(
            component.boundary, "EPSG:5070", "EPSG:32610"
        )
        centroid = lake_builder.polygon_centroid(boundary_utm)
        self.assertEqual(locate_hex_cell(*centroid), HexCell(92, 125))

    def test_installed_control_is_exactly_the_accepted_runtime_surface(self) -> None:
        center_path = lake_builder.CONTROL_CORPUS / lake_builder.hex_builder.record_path(
            HexCell(92, 125)
        )
        if not center_path.is_file():
            self.skipTest("accepted full-L0 control corpus is not installed")
        control = lake_builder.build_control(lake_builder.CONTROL_CORPUS)
        self.assertEqual(len(control.vertices), 637)
        self.assertEqual(len(control.faces), 1_050)
        self.assertEqual(control.material_ids.count(0), 21)


if __name__ == "__main__":
    unittest.main()
