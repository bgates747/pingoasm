import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import parse_qs, urlparse

from pingo_terrain.usgs_acquisition import (
    COVERAGE_REFERENCES_WGS84,
    DEM_GRID,
    NLCD_GRID,
    REQUESTED_WGS84_BOUNDS,
    acquisition_plan,
    read_source_query_summary,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = PROJECT_ROOT / "data/manifests/bay-area-2026-08-02.json"


class UsgsAcquisitionTests(unittest.TestCase):
    def test_requested_bounds_cover_landmarks_and_priority_airports(self) -> None:
        for name, (longitude, latitude) in COVERAGE_REFERENCES_WGS84.items():
            with self.subTest(name=name):
                self.assertTrue(REQUESTED_WGS84_BOUNDS.contains(longitude, latitude))

    def test_pinned_grid_dimensions_and_tile_plan(self) -> None:
        self.assertEqual((DEM_GRID.width, DEM_GRID.height), (10261, 12850))
        self.assertEqual((NLCD_GRID.width, NLCD_GRID.height), (4394, 5046))
        plan = acquisition_plan()
        dem = [tile for tile in plan if tile.grid is DEM_GRID]
        nlcd = [tile for tile in plan if tile.grid is NLCD_GRID]
        self.assertEqual(len(dem), 42)
        self.assertEqual(len(nlcd), 9)
        for grid, tiles in ((DEM_GRID, dem), (NLCD_GRID, nlcd)):
            self.assertEqual(sum(tile.width * tile.height for tile in tiles), grid.width * grid.height)
            self.assertEqual(min(tile.bounds.west for tile in tiles), grid.bounds.west)
            self.assertEqual(max(tile.bounds.east for tile in tiles), grid.bounds.east)
            self.assertEqual(min(tile.bounds.south for tile in tiles), grid.bounds.south)
            self.assertEqual(max(tile.bounds.north for tile in tiles), grid.bounds.north)
            for tile in tiles:
                self.assertLessEqual(tile.width, 2048)
                self.assertLessEqual(tile.height, 2048)
                self.assertAlmostEqual(tile.bounds.east - tile.bounds.west, tile.width * grid.pixel_size)
                self.assertAlmostEqual(tile.bounds.north - tile.bounds.south, tile.height * grid.pixel_size)

    def test_requests_pin_dimensions_crs_format_and_time(self) -> None:
        plan = acquisition_plan()
        dem_query = parse_qs(urlparse(plan[0].request_url).query)
        self.assertEqual(dem_query["bboxSR"], ["32610"])
        self.assertEqual(dem_query["imageSR"], ["32610"])
        self.assertEqual(dem_query["size"], [f"{plan[0].width},{plan[0].height}"])
        self.assertEqual(dem_query["pixelType"], ["F32"])
        self.assertEqual(dem_query["noData"], ["-9999"])
        nlcd = next(tile for tile in plan if tile.grid is NLCD_GRID)
        nlcd_query = parse_qs(urlparse(nlcd.request_url).query)
        self.assertEqual(nlcd_query["crs"], ["EPSG:5070"])
        self.assertEqual(nlcd_query["response_crs"], ["EPSG:5070"])
        self.assertEqual(nlcd_query["format"], ["GeoTIFF"])
        self.assertEqual(nlcd_query["time"], ["2025-01-01T00:00:00.000Z"])

    def test_source_query_requires_complete_navd88_records(self) -> None:
        payload = {
            "features": [
                {"attributes": {"ProductName": "USGS_3DEP", "VerticalDatum": "North American Vertical Datum of 1988 (NAVD 88)"}},
                {"attributes": {"ProductName": None, "VerticalDatum": None}},
            ],
            "exceededTransferLimit": False,
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            summary = read_source_query_summary(path)
        self.assertEqual(summary["intersecting_records"], 2)
        self.assertEqual(summary["data_records"], 1)
        self.assertEqual(summary["overview_records"], 1)
        self.assertEqual(summary["vertical_datums"], ["North American Vertical Datum of 1988 (NAVD 88)"])
        self.assertFalse(summary["exceeded_transfer_limit"])

    def test_checksum_manifest_matches_the_pinned_plan(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["region_id"], "bay-area")
        records = {
            (dataset["id"], tile["id"]): tile
            for dataset in manifest["datasets"]
            for tile in dataset["tiles"]
        }
        plan = acquisition_plan()
        self.assertEqual(len(records), len(plan))
        for tile in plan:
            record = records[(tile.grid.dataset_id, tile.id)]
            self.assertEqual(record["request_url"], tile.request_url)
            self.assertEqual(record["bbox"], list(tile.bounds.tuple))
            self.assertEqual((record["width"], record["height"]), (tile.width, tile.height))
            self.assertRegex(record["sha256"], re.compile(r"^[0-9a-f]{64}$"))
        outcome = manifest["acquisition_outcome"]
        self.assertEqual(outcome["accepted_tile_count"], 51)
        self.assertEqual(
            outcome["total_byte_size"],
            sum(record["byte_size"] for record in records.values()),
        )
        self.assertEqual(
            manifest["future_airport_layer_source"]["authoritative_manifest"],
            "data/manifests/faa-nasr-airports-2026-07-09.json",
        )


if __name__ == "__main__":
    unittest.main()
