from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pingo_terrain.landmark_ac3d import inspect_ac3d


SAMPLE = """AC3Db
MATERIAL "Stone" rgb 0.8 0.7 0.6 amb 0 0 0 emis 0 0 0 spec 0 0 0 shi 0 trans 0
MATERIAL "Light" rgb 1 1 1 amb 0 0 0 emis 1 1 1 spec 0 0 0 shi 0 trans 0
OBJECT world
kids 1
OBJECT poly
name "Tower"
texture "tower.rgb"
loc 1 2 3
numvert 4
-2 0 -3
2 0 -3
2 8 3
-2 8 3
numsurf 2
SURF 0x00
mat 0
refs 4
0 0 0
1 1 0
2 1 1
3 0 1
SURF 0x02
mat 1
refs 2
0 0 0
2 1 1
kids 0
"""


class AC3DInspectionTests(unittest.TestCase):
    def test_reports_geometry_materials_and_texture_without_importing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tower.ac"
            path.write_text(SAMPLE)
            report = inspect_ac3d(path)

        self.assertEqual(report.header, "AC3Db")
        self.assertEqual(report.object_count, 2)
        self.assertEqual(report.material_count, 2)
        self.assertEqual(report.materials[0].name, "Stone")
        self.assertEqual(report.vertex_count, 4)
        self.assertEqual(report.surface_count, 2)
        self.assertEqual(report.polygon_surface_count, 1)
        self.assertEqual(report.line_surface_count, 1)
        self.assertEqual(report.fan_triangle_count, 2)
        self.assertEqual(report.textures, ("tower.rgb",))
        self.assertEqual(report.material_surface_counts, ((0, 1), (1, 1)))
        self.assertEqual(report.minimum_xyz, (-2.0, 0.0, -3.0))
        self.assertEqual(report.maximum_xyz, (2.0, 8.0, 3.0))
        self.assertTrue(report.has_object_transforms)

    def test_rejects_non_ac3d_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-ac3d.ac"
            path.write_text("OBJ instead\n")
            with self.assertRaisesRegex(ValueError, "missing AC3D header"):
                inspect_ac3d(path)


if __name__ == "__main__":
    unittest.main()
