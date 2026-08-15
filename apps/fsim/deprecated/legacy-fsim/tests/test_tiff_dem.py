import math
from pathlib import Path
import unittest

from pingo_terrain.tiff_dem import read_float32_dem


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEM = PROJECT_ROOT / "data/downloads/berkeley-ca/usgs-3dep-10m-utm10n.tif"


class TiffDemTests(unittest.TestCase):
    @unittest.skipUnless(DEM.is_file(), "ignored Berkeley DEM is not installed")
    def test_acquired_berkeley_dem(self) -> None:
        dem = read_float32_dem(DEM)
        self.assertEqual((dem.width, dem.height), (987, 619))
        self.assertAlmostEqual(dem.pixel_size_x, 10.0, places=5)
        self.assertAlmostEqual(dem.pixel_size_y, 10.0, places=5)
        valid = [
            value
            for value in dem.values
            if math.isfinite(value) and value != dem.nodata
        ]
        self.assertGreater(max(valid), 400.0)
        self.assertLess(max(valid), 1000.0)
        self.assertGreater(min(valid), -100.0)
        self.assertLess(min(valid), 10.0)


if __name__ == "__main__":
    unittest.main()
