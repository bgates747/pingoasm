#!/usr/bin/env python3
"""Tests for the orbit-scene hardware-SD deployer."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_orbit_scene as deployer


class AutoexecTests(unittest.TestCase):
    def test_fixture_uses_short_hardware_path(self) -> None:
        self.assertEqual(
            deployer.autoexec_lines(
                "earth-party-camera-ellipse-rgba2222"
            ),
            (
                "SET KEYBOARD 1",
                "cd /pingo/earth-party-camera-ellipse-rgba2222",
                "load benchmark.bin",
                "run",
            ),
        )


class DeploymentTests(unittest.TestCase):
    def test_direct_layout_preserves_unrelated_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = root / "orbit-fixtures"
            other_fixtures = root / "render-fixtures"
            source = fixtures / "ellipse" / "tgt"
            source.mkdir(parents=True)
            other_fixtures.mkdir()
            (source / "benchmark.bin").write_bytes(b"program")
            (source / "earth.rgba2").write_bytes(b"texture")

            sdcard = root / "sdcard"
            unrelated = sdcard / "pingo" / "cube"
            unrelated.mkdir(parents=True)
            (unrelated / "keep.bin").write_bytes(b"keep")

            with (
                patch.object(deployer, "FIXTURES_ROOT", fixtures),
                patch.object(
                    deployer, "OTHER_FIXTURES_ROOT", other_fixtures
                ),
                patch.object(deployer.os.path, "ismount", return_value=True),
            ):
                destination = deployer.deploy(sdcard, "ellipse")

            self.assertEqual(destination, sdcard / "pingo" / "ellipse")
            self.assertTrue((destination / "benchmark.bin").is_file())
            self.assertTrue((destination / "earth.rgba2").is_file())
            self.assertFalse((destination / "tgt").exists())
            self.assertTrue((unrelated / "keep.bin").is_file())
            self.assertIn(
                b"cd /pingo/ellipse\r\n",
                (sdcard / "autoexec.txt").read_bytes(),
            )

    def test_symlink_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = root / "orbit-fixtures"
            other_fixtures = root / "render-fixtures"
            source = fixtures / "ellipse" / "tgt"
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
                deployer.deploy(sdcard, "ellipse")

    def test_cross_suite_name_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = root / "orbit-fixtures"
            other_fixtures = root / "render-fixtures"
            source = fixtures / "shared-name" / "tgt"
            source.mkdir(parents=True)
            (other_fixtures / "shared-name").mkdir(parents=True)
            (source / "benchmark.bin").write_bytes(b"program")
            sdcard = root / "sdcard"
            sdcard.mkdir()

            with (
                patch.object(deployer, "FIXTURES_ROOT", fixtures),
                patch.object(
                    deployer, "OTHER_FIXTURES_ROOT", other_fixtures
                ),
                patch.object(deployer.os.path, "ismount", return_value=True),
                self.assertRaisesRegex(ValueError, "collides"),
            ):
                deployer.deploy(sdcard, "shared-name")


if __name__ == "__main__":
    unittest.main()
