#!/usr/bin/env python3
"""Regression tests for deterministic multi-object orbit math."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_orbit_scene as orbit


PROFILE = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "orbit-scene"
    / "profiles"
    / "earth-party-rgba2222.json"
)
CAMERA_DOLLY_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "orbit-scene"
    / "profiles"
    / "earth-party-camera-dolly-rgba2222.json"
)
CAMERA_ELLIPSE_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "orbit-scene"
    / "profiles"
    / "earth-party-camera-ellipse-rgba2222.json"
)


class OrbitMathTests(unittest.TestCase):
    def test_profile_closes_every_orientation_after_two_orbits(self) -> None:
        profile = orbit.load_profile(PROFILE)
        revolutions = profile["orbit_revolutions"]
        for model in [profile["central"], *profile["orbiters"]]:
            for rate in model["spin_turns_per_orbit"]:
                self.assertTrue(orbit.is_integer(rate * revolutions))

    def test_orbiters_do_not_all_close_after_one_orbit(self) -> None:
        profile = orbit.load_profile(PROFILE)
        for model in profile["orbiters"]:
            self.assertFalse(
                all(orbit.is_integer(rate) for rate in model["spin_turns_per_orbit"])
            )

    def test_closing_pose_matches_initial_pose_commands(self) -> None:
        profile = orbit.load_profile(PROFILE)
        first = orbit.render_pose(profile, 0, "measured").splitlines()[1:-1]
        closing_frame = (
            profile["frames_per_orbit"] * profile["orbit_revolutions"]
        )
        last = orbit.render_pose(
            profile, closing_frame, "measured"
        ).splitlines()[1:-1]
        self.assertEqual(first, last)

    def test_nonclosing_rate_is_rejected(self) -> None:
        data = json.loads(PROFILE.read_text(encoding="utf-8"))
        data["orbiters"][0]["spin_turns_per_orbit"][0] = 0.4
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8"
        ) as stream:
            json.dump(data, stream)
            stream.flush()
            with self.assertRaisesRegex(ValueError, "does not return"):
                orbit.load_profile(Path(stream.name))

    def test_expected_measured_frame_count(self) -> None:
        profile = orbit.load_profile(PROFILE)
        self.assertEqual(
            profile["frames_per_orbit"] * profile["orbit_revolutions"] + 1,
            289,
        )

    def test_high_resolution_review_keeps_exact_closing_pose(self) -> None:
        profile = orbit.load_profile(PROFILE)
        profile["frames_per_orbit"] = 144
        closing = profile["frames_per_orbit"] * profile["orbit_revolutions"]
        first = orbit.render_pose(profile, 0, "measured").splitlines()[1:-1]
        last = orbit.render_pose(profile, closing, "measured").splitlines()[1:-1]
        self.assertEqual(first, last)
        self.assertEqual(closing + 1, 289)

    def test_staging_window_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "benchmark.bin"
            texture = root / "texture.rgba2"
            executable.write_bytes(b"x" * 100)
            texture.write_bytes(b"x" * 200)
            orbit.validate_staging_window(executable, [texture])
            executable.write_bytes(b"x" * (orbit.EZ80_APPLICATION_WINDOW - 199))
            with self.assertRaisesRegex(ValueError, "application window"):
                orbit.validate_staging_window(executable, [texture])

    def test_camera_dolly_starts_far_reaches_near_and_ends_far(self) -> None:
        profile = orbit.load_profile(CAMERA_DOLLY_PROFILE)
        frames = profile["frames_per_orbit"]
        first = orbit.render_pose(profile, 0, "measured")
        middle = orbit.render_pose(profile, frames, "measured")
        last = orbit.render_pose(profile, frames * 2, "measured")
        self.assertIn("    ld iy,10000\n    call scdabs", first)
        self.assertIn("    ld iy,2500\n    call scdabs", middle)
        self.assertIn("    ld iy,10000\n    call scdabs", last)

    def test_camera_dolly_reinstates_object_orbits(self) -> None:
        profile = orbit.load_profile(CAMERA_DOLLY_PROFILE)
        first = orbit.render_pose(profile, 0, "measured").splitlines()[1:-5]
        quarter = orbit.render_pose(
            profile, profile["frames_per_orbit"] // 4, "measured"
        ).splitlines()[1:-5]
        self.assertNotEqual(first, quarter)

    def test_camera_ellipse_endpoints_and_look_at_yaw(self) -> None:
        profile = orbit.load_profile(CAMERA_ELLIPSE_PROFILE)
        frames = profile["frames_per_orbit"]
        first = orbit.render_pose(profile, 0, "measured")
        periapsis = orbit.render_pose(profile, frames, "measured")
        last = orbit.render_pose(profile, frames * 2, "measured")
        self.assertIn("    ld bc,0\n    ld de,0\n    ld iy,10000\n", first)
        self.assertIn("    ld bc,0\n    ld de,0\n    ld iy,-3500\n", periapsis)
        self.assertIn("    ld bc,16384\n    ld de,0\n    ld iy,0\n", periapsis)
        self.assertIn("    ld bc,0\n    ld de,0\n    ld iy,10000\n", last)
        self.assertIn("    ld bc,0\n    ld de,0\n    ld iy,0\n", last)

    def test_camera_ellipse_crosses_north_pole_at_pitch_minus_90(self) -> None:
        profile = orbit.load_profile(CAMERA_ELLIPSE_PROFILE)
        quarter_camera_orbit = profile["frames_per_orbit"] // 2
        pose = orbit.render_pose(profile, quarter_camera_orbit, "measured")
        self.assertIn("    ld bc,0\n    ld de,4074\n    ld iy,-1000\n", pose)
        self.assertIn("    ld bc,24575\n    ld de,0\n    ld iy,0\n", pose)


if __name__ == "__main__":
    unittest.main()
