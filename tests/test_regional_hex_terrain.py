from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regional_hex_terrain as builder  # noqa: E402

from pingo_terrain.hex_terrain import HEX_CELL_COUNT, HexCell  # noqa: E402
from pingo_terrain.p3dm import make_container, parse_container  # noqa: E402
from pingo_terrain.regional_raster import RasterMosaic  # noqa: E402


class RegionalHexBuilderTests(unittest.TestCase):
    def test_full_and_campanile_selections_are_exact(self) -> None:
        full = builder.selected_cells("full")
        proof = builder.selected_cells("campanile-r5")
        self.assertEqual(len(full), HEX_CELL_COUNT)
        self.assertEqual([cell.cell_id for cell in full], list(range(HEX_CELL_COUNT)))
        self.assertEqual(len(proof), 91)
        self.assertEqual(proof[0], HexCell(*builder.CAMPANILE_CELL))
        self.assertEqual(len(set(proof)), len(proof))

    def test_path_and_budget_match_runtime_contract(self) -> None:
        first = HexCell(0, 0)
        last = builder.selected_cells("full")[-1]
        self.assertEqual(builder.record_path(first).as_posix(), "TRH/L0/00/00.AGN")
        self.assertEqual(
            builder.record_path(last).as_posix(),
            f"TRH/L0/{last.cell_id >> 8:02X}/{last.cell_id & 255:02X}.AGN",
        )
        budget = builder.corpus_budget(HEX_CELL_COUNT)
        self.assertEqual(budget["container_bytes_per_cell"], 3412)
        self.assertEqual(budget["triangles_per_cell"], 210)
        self.assertEqual(budget["container_bytes"], 171_224_396)

    def test_world_contract_records_straight_hex_boundaries(self) -> None:
        source = Path(builder.__file__).read_text(encoding="utf-8")
        self.assertIn(
            '"boundary_policy": "six straight sides; each runtime side is '
            'five collinear lattice edges"',
            source,
        )

    def test_campanile_start_reconstructs_accepted_projected_witness(self) -> None:
        start = builder.canonical_start()
        self.assertEqual((start["q"], start["r"]), (90, 121))
        self.assertEqual(start["cell_id"], HexCell(90, 121).cell_id)
        self.assertEqual(
            (start["pingo_x_count"], start["pingo_y_count"], start["pingo_z_count"]),
            (3711, 3496, -1482),
        )

    def test_budget_only_cli_does_not_read_or_write_the_corpus(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/build_regional_hex_terrain.py"),
                "--selection",
                "full",
                "--budget-only",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["budget"]["cells"], HEX_CELL_COUNT)

    def test_one_real_source_cell_round_trips(self) -> None:
        source_manifest = json.loads(builder.rectangular.SOURCE_MANIFEST.read_text())
        datasets = {item["id"]: item for item in source_manifest["datasets"]}
        first_dem = ROOT / datasets[builder.rectangular.DEM_DATASET_ID]["tiles"][0]["local_path"]
        first_nlcd = ROOT / datasets[builder.rectangular.NLCD_DATASET_ID]["tiles"][0]["local_path"]
        if not first_dem.is_file() or not first_nlcd.is_file():
            self.skipTest("pinned Bay Area source rasters are not present")
        dem = RasterMosaic(ROOT, datasets[builder.rectangular.DEM_DATASET_ID])
        nlcd = RasterMosaic(ROOT, datasets[builder.rectangular.NLCD_DATASET_ID])
        cell = HexCell(*builder.CAMPANILE_CELL)
        with builder.rectangular.CoordinateTransformer() as transformer:
            built, *_ = builder.build_one(cell, dem, nlcd, transformer)
        container = make_container(built.tile)
        self.assertEqual(parse_container(container), built.tile)
        self.assertEqual(len(container), 3412)


if __name__ == "__main__":
    unittest.main()
