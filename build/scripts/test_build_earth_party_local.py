#!/usr/bin/env python3
"""Regression tests for the interactive eZ80-local Earth Party."""

from __future__ import annotations

import math
import re
import unittest
from pathlib import Path

import build_earth_party_local as party


SOURCE = party.SOURCE_DIR / party.ASSEMBLY_FILENAME
Q15_ONE = 32767


def round_q15(value: int) -> int:
    magnitude = (abs(value) + 16383) // Q15_ONE
    return -magnitude if value < 0 else magnitude


class EarthPartySourceTests(unittest.TestCase):
    def test_profile_has_six_unique_portable_models(self) -> None:
        profile = party.load_profile()
        models = profile["models"]
        self.assertEqual(
            [model["name"] for model in models],
            ["jet", "earthuv", "crash", "lara", "heavytank", "airliner"],
        )
        self.assertEqual(
            len({model["texture_filename"] for model in models}),
            len(models),
        )

    def test_scene_uses_persistent_local_orbits(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertRegex(source, r"(?im)^orbit_radius:\s*equ\s+2500\s*$")
        self.assertRegex(source, r"(?im)^orbit_forward_step:\s*equ\s+-123\s*$")
        self.assertRegex(source, r"(?im)^orbit_yaw_step:\s*equ\s+256\s*$")
        self.assertRegex(
            source,
            (
                r"(?ims)^simulate_party_step:\s*.*?"
                r"ld\s+ix\s*,\s*crash_state\s*"
                r"call\s+p3d_object_step16\s*"
                r"ld\s+ix\s*,\s*lara_state\s*"
                r"call\s+p3d_object_step16\s*"
                r"ld\s+ix\s*,\s*heavytank_state\s*"
                r"call\s+p3d_object_step16\s*"
                r"ld\s+ix\s*,\s*airliner_state\s*"
                r"jp\s+p3d_object_step16"
            ),
        )

    def test_all_orbits_close_without_radial_runaway(self) -> None:
        # Physical Y yaws corresponding to the four canonical Euler seeds in
        # earth-party.asm. Rotation precedes translation exactly as in p3d.
        seeds = (
            ((0, 2500), -8320),
            ((2500, 0), -128),
            ((0, -2500), 8064),
            ((-2500, 0), 16256),
        )
        sine = tuple(
            round(math.sin(index * 2.0 * math.pi / 256.0) * Q15_ONE)
            for index in range(256)
        )
        cosine = tuple(
            round(math.cos(index * 2.0 * math.pi / 256.0) * Q15_ONE)
            for index in range(256)
        )

        for initial_position, initial_yaw in seeds:
            with self.subTest(position=initial_position):
                x, z = initial_position
                yaw = initial_yaw
                squared_radii: list[int] = []
                for _ in range(128):
                    yaw = (yaw + 256) & 0x7FFF
                    phase = (yaw >> 7) & 0xFF
                    x += round_q15(sine[phase] * -123)
                    z += round_q15(cosine[phase] * -123)
                    squared_radii.append(x * x + z * z)

                self.assertEqual((x, z), initial_position)
                self.assertEqual(yaw, initial_yaw & 0x7FFF)
                self.assertEqual(min(squared_radii), 6_250_000)
                self.assertEqual(max(squared_radii), 6_330_545)

    def test_earth_basis_has_realistic_leftward_obliquity(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        match = re.search(
            (
                r"(?ims)^earth_base_orientation:\s*"
                r"dw\s+([^\n]+)\s*"
                r"dw\s+([^\n]+)\s*"
                r"dw\s+([^\n]+)"
            ),
            source,
        )
        self.assertIsNotNone(match)
        matrix = tuple(
            int(value.strip())
            for row in match.groups()
            for value in row.split(",")
        )
        north = (matrix[1], matrix[4], matrix[7])
        self.assertLess(north[0], 0)
        self.assertGreater(north[2], 0)
        magnitude = math.sqrt(sum(value * value for value in north))
        tilt = math.degrees(math.acos(north[1] / magnitude))
        self.assertAlmostEqual(tilt, 23.44, delta=0.3)

    def test_ids_and_bitmap_ids_are_unique(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        for suffix in ("mid", "oid", "bmid"):
            category = [
                int(value)
                for value in re.findall(
                    rf"(?im)^(?:jet|earthuv|crash|lara|heavytank|airliner)_{suffix}:\s*equ\s+(\d+)\s*$",
                    source,
                )
            ]
            self.assertEqual(len(category), 6)
            self.assertEqual(len(set(category)), 6)
            if suffix == "bmid":
                target = int(
                    re.search(
                        r"(?im)^tgtbmid:\s*equ\s+(\d+)\s*$",
                        source,
                    ).group(1)
                )
                self.assertNotIn(target, category)


if __name__ == "__main__":
    unittest.main()
