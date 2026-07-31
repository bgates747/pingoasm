#!/usr/bin/env python3
"""Regression tests for the flat-shaded Earth Party sibling fixture."""

from __future__ import annotations

import math
import re
import unittest
from pathlib import Path

import build_earth_party_flat_local as party


SOURCE = party.SOURCE_DIR / party.ASSEMBLY_FILENAME
Q15_ONE = 32767


def round_q15(value: int) -> int:
    magnitude = (abs(value) + 16383) // Q15_ONE
    return -magnitude if value < 0 else magnitude


class EarthPartyFlatSourceTests(unittest.TestCase):
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
        starfield = profile["starfield"]
        self.assertEqual(
            starfield["catalog_source"],
            "apps/earth-party-local/assets/stars.tsv",
        )
        self.assertEqual(starfield["texture_filename"], "stars.rgba2")
        self.assertEqual(starfield["viewport_height"], 240)
        self.assertEqual(starfield["object_scale"], 60000)
        self.assertEqual(starfield["shading"], "flat_palette")
        self.assertEqual(starfield["illumination"], "self")

        shading = {
            model["name"]: model.get("shading", "textured") for model in models
        }
        self.assertEqual(
            {name for name, mode in shading.items() if mode == "flat_palette"},
            {"jet", "airliner"},
        )

    def test_flat_and_illumination_policies_are_exact(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"(?ims)ld\s+bc\s*,\s*-16384\s*\n"
            r"\s*ld\s+de\s*,\s*0\s*\n"
            r"\s*ld\s+iy\s*,\s*28377\s*\n"
            r"\s*call\s+pingo_set_light_direction",
        )
        self.assertRegex(
            source,
            r"(?im)^\s*ld\s+a\s*,\s*32\s*\n\s*call\s+pingo_set_ambient_light",
        )
        for mesh in ("jet", "airliner"):
            self.assertRegex(
                source,
                rf"(?ims)ld\s+hl\s*,\s*{mesh}_mid\s*.*?"
                r"ld\s+a\s*,\s*pingo_shading_flat_palette\s*.*?"
                r"call\s+pingo_set_mesh_shading_mode",
            )
        for sector in ("px", "nx", "py", "ny", "pz", "nz"):
            self.assertRegex(
                source,
                rf"(?im)^\s*ld\s+hl\s*,\s*starfield_{sector}_mid\s*\n"
                r"\s*call\s+configure_emissive_flat_mesh",
            )

        helper = (party.SOURCE_DIR / "vdu_pingo.inc").read_text(encoding="utf-8")
        self.assertRegex(
            helper,
            r"(?ims)^pingo_set_mesh_illumination_mode:.*?db\s+\$49\s*,\s*48",
        )
        self.assertRegex(
            helper,
            r"(?ims)^pingo_set_light_direction:.*?db\s+\$49\s*,\s*43",
        )
        self.assertNotRegex(source, r"(?i)call\s+pingo_set_illumination_enabled")

    def test_scene_uses_persistent_local_orbits(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertRegex(source, r"(?im)^orbit_radius:\s*equ\s+2500\s*$")
        self.assertRegex(source, r"(?im)^orbit_forward_step:\s*equ\s+-46\s*$")
        self.assertRegex(source, r"(?im)^orbit_yaw_step:\s*equ\s+96\s*$")
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

    def test_earth_uses_generated_absolute_pose_cycle(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        simulation = re.search(
            r"(?ims)^simulate_party_step:.*?^simulate_earth_spin:",
            source,
        ).group(0)
        self.assertRegex(
            simulation,
            r"(?i)call\s+simulate_earth_spin",
        )
        self.assertNotRegex(
            simulation,
            r"(?ims)ld\s+ix\s*,\s*earth_state\s*"
            r"call\s+p3d_object_step16",
        )
        routine = re.search(
            r"(?ims)^simulate_earth_spin:.*?^scene_pose_dirty:",
            source,
        ).group(0)
        self.assertRegex(
            routine,
            r"(?ims)res\s+7\s*,\s*h.*?"
            r"ld\s+iy\s*,\s*earth_spin_pose_samples\s*"
            r"jp\s+p3d_object_apply_pose_sample8",
        )
        self.assertNotRegex(routine, r"(?i)p3d_mat3_to_euler16")

        for filename in (party.POSE_HELPER_INCLUDE, party.EARTH_POSE_INCLUDE):
            generated = (party.SOURCE_DIR / filename).read_text(encoding="utf-8")
            self.assertIn("AUTO-GENERATED FILE - DO NOT EDIT", generated)
            self.assertIn(f"Generated by: {party.GENERATOR}", generated)

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
                angular_residual = 0
                squared_radii: list[int] = []
                for _ in range(1024):
                    total = 96 + angular_residual
                    angular_residual = ((total + 64) % 128) - 64
                    yaw_delta = total - angular_residual
                    yaw = (yaw + yaw_delta) & 0x7FFF
                    phase = (yaw >> 7) & 0xFF
                    x += round_q15(sine[phase] * -46)
                    z += round_q15(cosine[phase] * -46)
                    squared_radii.append(x * x + z * z)

                self.assertEqual((x, z), initial_position)
                self.assertEqual(yaw, initial_yaw & 0x7FFF)
                self.assertEqual(angular_residual, 0)
                self.assertEqual(min(squared_radii), 6_104_981)
                self.assertEqual(max(squared_radii), 6_428_200)

    def test_earth_basis_has_realistic_leftward_obliquity(self) -> None:
        source = (party.SOURCE_DIR / party.EARTH_POSE_INCLUDE).read_text(
            encoding="utf-8"
        )
        match = re.search(
            (
                r"(?ims)^earth_spin_pose_base_orientation:\s*"
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
        self.assertIn("earth_spin_pose_sample_count: equ 256", source)
        self.assertIn("earth_spin_pose_sample_size: equ 24", source)

    def test_ids_and_bitmap_ids_are_unique(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        ordinary = "jet|earthuv|crash|lara|heavytank|airliner"
        sectors = (
            "starfield_px|starfield_nx|starfield_py|"
            "starfield_ny|starfield_pz|starfield_nz"
        )
        for suffix in ("mid", "oid"):
            category = [
                int(value)
                for value in re.findall(
                    rf"(?im)^(?:{ordinary}|{sectors})_{suffix}:\s*equ\s+(\d+)\s*$",
                    source,
                )
            ]
            self.assertEqual(len(category), 12)
            self.assertEqual(len(set(category)), 12)

        bitmap_ids = [
            int(value)
            for value in re.findall(
                rf"(?im)^(?:{ordinary}|starfield)_bmid:\s*equ\s+(\d+)\s*$",
                source,
            )
        ]
        self.assertEqual(len(bitmap_ids), 7)
        self.assertEqual(len(set(bitmap_ids)), 7)
        target = int(
            re.search(
                r"(?im)^tgtbmid:\s*equ\s+(\d+)\s*$",
                source,
            ).group(1)
        )
        self.assertNotIn(target, bitmap_ids)

    def test_starfield_sectors_are_initialized_once_and_remain_static(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        for sector in ("px", "nx", "py", "ny", "pz", "nz"):
            self.assertIn(f"starfield_{sector}_state", source)
            self.assertIn(f"starfield_{sector}_config", source)
            self.assertRegex(
                source,
                (
                    rf"(?ims)ld\s+ix\s*,\s*starfield_{sector}_state\s*"
                    rf"ld\s+iy\s*,\s*starfield_{sector}_config\s*"
                    r"call\s+init_party_object"
                ),
            )

        simulation = re.search(
            r"(?ims)^simulate_party_step:.*?^simulate_earth_spin:",
            source,
        ).group(0)
        dirty_scan = re.search(
            r"(?ims)^scene_pose_dirty:.*?^sync_scene_objects:",
            source,
        ).group(0)
        synchronization = re.search(
            r"(?ims)^sync_scene_objects:.*?^app_special_init:",
            source,
        ).group(0)
        self.assertNotIn("starfield_", simulation)
        self.assertNotIn("starfield_", dirty_scan)
        self.assertNotIn("starfield_", synchronization)


if __name__ == "__main__":
    unittest.main()
