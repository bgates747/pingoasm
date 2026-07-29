#!/usr/bin/env python3
"""Regression tests for profile-driven render benchmark generation."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_render_benchmark as benchmark


class MotionTranslationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "translation_motion": {
                "center": [0, 0, 0],
                "amplitude": [2400, 1800, 1600],
                "cycles": [1, 2, 1],
                "phase_degrees": [0, 0, 90],
            }
        }

    def test_cardinal_motion_poses(self) -> None:
        self.assertEqual(
            benchmark.motion_translation(self.profile, 0),
            (0, 0, 1600),
        )
        self.assertEqual(
            benchmark.motion_translation(self.profile, 90),
            (2400, 0, 0),
        )
        self.assertEqual(
            benchmark.motion_translation(self.profile, 180),
            (0, 0, -1600),
        )
        self.assertEqual(
            benchmark.motion_translation(self.profile, 270),
            (-2400, 0, 0),
        )

    def test_stationary_profile_has_no_translation(self) -> None:
        self.assertIsNone(benchmark.motion_translation({}, 90))

    def test_generated_pose_uses_absolute_translation_then_rotation(self) -> None:
        source = benchmark.render_pose(
            "y",
            90,
            "measured",
            9,
            benchmark.motion_translation(self.profile, 90),
        )
        translation_call = source.index("call sodabs")
        rotation_call = source.index("call sorabs")
        self.assertLess(translation_call, rotation_call)
        self.assertIn("translation (2400, 0, 0)", source)
        self.assertIn("ld de,8192", source)


class MotionProfileValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "name": "test",
            "model_source": "apps/turbovega/src/cube.inc",
            "texture_source": "src/blender/blenderaxes.rgba2",
            "texture_format": "rgba2222",
            "target_format": "rgba2222",
            "texture_width": 34,
            "texture_height": 34,
            "control_id": 1,
            "texture_bitmap_id": 2,
            "target_bitmap_id": 3,
            "warmup_target_bitmap_id": 4,
            "object_scale": 1280,
            "camera_pose": [0, 0, 3200],
            "warmup_frames": 1,
            "measured_frames": 36,
            "rotation_axis": "y",
            "rotation_step_degrees": 10,
            "resolution": [320, 240],
            "translation_motion": {
                "center": [0, 0, 0],
                "amplitude": [2400, 1800, 1600],
                "cycles": [1, 2, 1],
                "phase_degrees": [0, 0, 90],
            },
        }

    def load(self, profile: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            return benchmark.load_profile(path)

    def test_motion_must_be_an_object(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile["translation_motion"] = []
        with self.assertRaisesRegex(ValueError, "must be an object"):
            self.load(profile)

    def test_motion_rejects_missing_and_unknown_fields(self) -> None:
        missing = copy.deepcopy(self.profile)
        del missing["translation_motion"]["cycles"]
        with self.assertRaisesRegex(ValueError, "is missing: cycles"):
            self.load(missing)

        unknown = copy.deepcopy(self.profile)
        unknown["translation_motion"]["unexpected"] = [0, 0, 0]
        with self.assertRaisesRegex(ValueError, "unknown fields: unexpected"):
            self.load(unknown)

    def test_motion_rejects_wrong_shape_and_non_numeric_values(self) -> None:
        wrong_shape = copy.deepcopy(self.profile)
        wrong_shape["translation_motion"]["center"] = [0, 0]
        with self.assertRaisesRegex(ValueError, "needs three numeric values"):
            self.load(wrong_shape)

        non_numeric = copy.deepcopy(self.profile)
        non_numeric["translation_motion"]["cycles"] = [1, True, 1]
        with self.assertRaisesRegex(ValueError, "needs three numeric values"):
            self.load(non_numeric)

    def test_motion_rejects_nonfinite_and_out_of_range_values(self) -> None:
        nonfinite = copy.deepcopy(self.profile)
        nonfinite["translation_motion"]["phase_degrees"] = [
            0,
            float("inf"),
            0,
        ]
        with self.assertRaisesRegex(ValueError, "needs three finite values"):
            self.load(nonfinite)

        out_of_range = copy.deepcopy(self.profile)
        out_of_range["translation_motion"]["center"] = [-32767, 0, 0]
        out_of_range["translation_motion"]["amplitude"] = [1, 0, 0]
        with self.assertRaisesRegex(ValueError, "-32767\\.\\.32767"):
            self.load(out_of_range)

    def test_motion_accepts_both_documented_endpoints(self) -> None:
        endpoints = copy.deepcopy(self.profile)
        endpoints["translation_motion"]["center"] = [-32767, 32767, 0]
        endpoints["translation_motion"]["amplitude"] = [0, 0, 0]
        self.assertEqual(
            self.load(endpoints)["translation_motion"]["center"],
            [-32767, 32767, 0],
        )


class StationaryGenerationRegressionTests(unittest.TestCase):
    def test_cube_stationary_assembly_remains_byte_identical(self) -> None:
        profile_path = (
            benchmark.BENCHMARK_ROOT / "profiles" / "cube-rgba2222.json"
        )
        profile = benchmark.load_profile(profile_path)
        texture_source = benchmark.project_path(profile["texture_source"])
        texture_name = profile.get("texture_filename", texture_source.name)
        profile["_texture_size"] = texture_source.stat().st_size
        expected = (
            benchmark.FIXTURES_ROOT
            / profile["name"]
            / "src"
            / "benchmark.asm"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            benchmark.assembly(profile, profile_path, texture_name),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
