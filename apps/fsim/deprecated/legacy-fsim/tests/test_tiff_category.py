from pathlib import Path
import unittest

from pingo_terrain.tiff_category import read_category_raster


PROJECT_ROOT = Path(__file__).resolve().parent.parent
NLCD = PROJECT_ROOT / "data/downloads/berkeley-ca/usgs-annual-nlcd-2025-epsg5070.tif"


class CategoryTiffTests(unittest.TestCase):
    @unittest.skipUnless(NLCD.is_file(), "ignored Berkeley NLCD is not installed")
    def test_acquired_berkeley_landcover(self) -> None:
        raster = read_category_raster(NLCD)
        self.assertEqual((raster.width, raster.height), (369, 288))
        self.assertAlmostEqual(raster.pixel_size_x, 30.0, places=5)
        self.assertAlmostEqual(raster.pixel_size_y, 30.0, places=5)
        self.assertIn(11, raster.values)
        self.assertIn(24, raster.values)


if __name__ == "__main__":
    unittest.main()
