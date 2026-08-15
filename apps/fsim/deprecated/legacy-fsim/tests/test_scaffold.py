import unittest

import agonutils

from pingo_terrain import __version__
from pingo_terrain.paths import MANIFEST_ROOT, PROJECT_ROOT


class ScaffoldTests(unittest.TestCase):
    def test_project_identity(self) -> None:
        self.assertEqual(__version__, "0.0.0")
        self.assertEqual(PROJECT_ROOT.name, "fsim")

    def test_manifest_directory_is_tracked(self) -> None:
        self.assertTrue(MANIFEST_ROOT.is_dir())

    def test_agonutils_comes_from_canonical_checkout(self) -> None:
        module_path = agonutils.__file__
        self.assertIsNotNone(module_path)
        self.assertIn("/home/smith/Agon/mystuff/agon-utils/", module_path)


if __name__ == "__main__":
    unittest.main()
