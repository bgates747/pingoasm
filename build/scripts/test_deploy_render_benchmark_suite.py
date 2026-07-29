#!/usr/bin/env python3
"""Tests for the render-benchmark suite deployer."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_render_benchmark_suite as deployer


class AutoexecTests(unittest.TestCase):
    def test_default_suite_is_sequential_and_complete(self) -> None:
        lines = deployer.autoexec_lines(deployer.DEFAULT_SUITE)
        self.assertEqual(lines[0], "SET KEYBOARD 1")
        self.assertEqual(
            len(lines), 1 + 3 * len(deployer.DEFAULT_SUITE)
        )
        for index, name in enumerate(deployer.DEFAULT_SUITE):
            offset = 1 + 3 * index
            self.assertEqual(
                lines[offset],
                f"cd /pingo/{name}",
            )
            self.assertEqual(lines[offset + 1], "load benchmark.bin")
            self.assertEqual(lines[offset + 2], "run")


class DeploymentTests(unittest.TestCase):
    def test_direct_layout_preserves_unrelated_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = root / "render-fixtures"
            other_fixtures = root / "orbit-fixtures"
            source = fixtures / "cube" / "tgt"
            source.mkdir(parents=True)
            other_fixtures.mkdir()
            (source / "benchmark.bin").write_bytes(b"program")
            (source / "cube.rgba2").write_bytes(b"texture")

            sdcard = root / "sdcard"
            unrelated = sdcard / "pingo" / "ellipse"
            unrelated.mkdir(parents=True)
            (unrelated / "keep.bin").write_bytes(b"keep")

            with (
                patch.object(deployer, "FIXTURES_ROOT", fixtures),
                patch.object(
                    deployer, "OTHER_FIXTURES_ROOT", other_fixtures
                ),
                patch.object(deployer.os.path, "ismount", return_value=True),
            ):
                deployer.deploy(sdcard, ("cube",))

            destination = sdcard / "pingo" / "cube"
            self.assertTrue((destination / "benchmark.bin").is_file())
            self.assertTrue((destination / "cube.rgba2").is_file())
            self.assertFalse((destination / "tgt").exists())
            self.assertTrue((unrelated / "keep.bin").is_file())
            self.assertIn(
                b"cd /pingo/cube\r\n",
                (sdcard / "autoexec.txt").read_bytes(),
            )

    def test_symlink_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = root / "render-fixtures"
            other_fixtures = root / "orbit-fixtures"
            source = fixtures / "cube" / "tgt"
            source.mkdir(parents=True)
            other_fixtures.mkdir()
            (source / "benchmark.bin").write_bytes(b"program")

            sdcard = root / "sdcard"
            outside = root / "outside"
            sdcard.mkdir()
            outside.mkdir()
            (sdcard / "pingo").symlink_to(
                outside, target_is_directory=True
            )

            with (
                patch.object(deployer, "FIXTURES_ROOT", fixtures),
                patch.object(
                    deployer, "OTHER_FIXTURES_ROOT", other_fixtures
                ),
                patch.object(deployer.os.path, "ismount", return_value=True),
                self.assertRaisesRegex(ValueError, "unexpected deployment"),
            ):
                deployer.deploy(sdcard, ("cube",))

    def test_cross_suite_name_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = root / "render-fixtures"
            other_fixtures = root / "orbit-fixtures"
            source = fixtures / "shared-name" / "tgt"
            source.mkdir(parents=True)
            (other_fixtures / "shared-name").mkdir(parents=True)
            (source / "benchmark.bin").write_bytes(b"program")

            with (
                patch.object(deployer, "FIXTURES_ROOT", fixtures),
                patch.object(
                    deployer, "OTHER_FIXTURES_ROOT", other_fixtures
                ),
                self.assertRaisesRegex(ValueError, "collides"),
            ):
                deployer.validate_suite(("shared-name",))


if __name__ == "__main__":
    unittest.main()
