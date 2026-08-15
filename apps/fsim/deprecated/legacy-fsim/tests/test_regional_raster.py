from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pingo_terrain.regional_raster import BlockRaster, RasterMosaic
from tests.test_geotiff import _tiny_category_tiff


class RegionalRasterTests(unittest.TestCase):
    def test_block_reader_and_projected_mosaic_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tiny.tif"
            _tiny_category_tiff(path)
            raster = BlockRaster(path, cache_blocks=1)
            self.assertEqual(
                [raster.value(x, y) for y in range(2) for x in range(2)],
                [11, 22, 250, 95],
            )

            dataset = {
                "id": "tiny",
                "bbox": [100.0, 140.0, 160.0, 200.0],
                "pixel_size_metres": [30.0, 30.0],
                "nodata": 250,
                "tiles": [
                    {
                        "id": "r00-c00",
                        "bbox": [100.0, 140.0, 160.0, 200.0],
                        "local_path": "tiny.tif",
                    }
                ],
            }
            mosaic = RasterMosaic(root, dataset, cache_blocks_per_tile=1)
            self.assertEqual(mosaic.sample_nearest(115.0, 185.0).value, 11)
            self.assertEqual(mosaic.sample_nearest(145.0, 185.0).value, 22)
            nodata = mosaic.sample_nearest(115.0, 155.0)
            self.assertTrue(nodata.nodata)
            self.assertIsNone(nodata.value)
            padded = mosaic.sample_nearest(80.0, 220.0)
            self.assertTrue(padded.edge_padded)
            self.assertEqual(padded.value, 11)

    def test_projected_bbox_iteration_excludes_outside_centers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _tiny_category_tiff(root / "tiny.tif")
            mosaic = RasterMosaic(
                root,
                {
                    "id": "tiny",
                    "bbox": [100.0, 140.0, 160.0, 200.0],
                    "pixel_size_metres": [30.0, 30.0],
                    "nodata": 250,
                    "tiles": [
                        {
                            "id": "r00-c00",
                            "bbox": [100.0, 140.0, 160.0, 200.0],
                            "local_path": "tiny.tif",
                        }
                    ],
                },
            )
            cells = list(mosaic.cells_in_bbox(110.0, 180.0, 150.0, 190.0))
            self.assertEqual(
                [(x, y, value) for x, y, value, _nodata in cells],
                [(115.0, 185.0, 11), (145.0, 185.0, 22)],
            )


if __name__ == "__main__":
    unittest.main()
