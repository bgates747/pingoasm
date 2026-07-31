#!/usr/bin/env python3
"""Source and generated-output tests for the lighting/shading fixture."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

import build_lighting_shading as lighting
from flat_palette import FlatPaletteError, validate_flat_palette_asm


def executable_source(source: str) -> str:
    return "\n".join(line.split(";", 1)[0] for line in source.splitlines())


class LightingProfileTests(unittest.TestCase):
    def test_profile_uses_canonical_cube_and_palette(self) -> None:
        profile = lighting.load_profile()
        self.assertEqual(profile["model_obj_source"], "src/blender/cube.obj")
        self.assertEqual(profile["palette_png_source"], "src/blender/colors64.png")
        self.assertEqual(profile["palette_texture_size"], [8, 8])


class AssemblyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            lighting.SOURCE_DIR / lighting.ASSEMBLY_FILENAME
        ).read_text(encoding="utf-8")
        cls.code = executable_source(cls.source)

    def test_fixture_renders_and_displays_four_quadrants(self) -> None:
        self.assertEqual(len(re.findall(r"(?im)^\s*RENDBMP\s+sid,", self.code)), 4)
        self.assertRegex(self.code, r"DISPBMP\s+panel_default_bmid\s*,\s*0\s*,\s*0")
        self.assertRegex(self.code, r"DISPBMP\s+panel_side_bmid\s*,\s*160\s*,\s*0")
        self.assertRegex(self.code, r"DISPBMP\s+panel_overdrive_bmid\s*,\s*0\s*,\s*120")
        self.assertRegex(self.code, r"DISPBMP\s+panel_native_bmid\s*,\s*160\s*,\s*120")

    def test_fixture_exercises_all_new_controls(self) -> None:
        for routine in (
            "pingo_set_light_direction",
            "pingo_set_light_intensity",
            "pingo_set_ambient_light",
            "pingo_set_illumination_enabled",
            "pingo_set_mesh_shading_mode",
        ):
            with self.subTest(routine=routine):
                self.assertRegex(self.code, rf"(?i)\bcall\s+{routine}\b")
        self.assertIn("ld a,pingo_shading_textured", self.code)
        self.assertIn("ld a,pingo_shading_flat_palette", self.code)

    def test_fixture_does_not_invoke_retired_extensions(self) -> None:
        self.assertNotRegex(self.code, r"(?i)\bcall\s+(?:cto|vdu_set_dither)\b")

    def test_camera_uses_the_canonical_positive_z_pose(self) -> None:
        self.assertRegex(self.code, r"(?im)^cube_left_x:\s*equ\s+-480\s*$")
        self.assertRegex(self.code, r"(?im)^cube_right_x:\s*equ\s+480\s*$")
        self.assertRegex(self.code, r"(?im)^camera_z:\s*equ\s+3200\s*$")
        self.assertRegex(
            self.code,
            (
                r"(?ims)ld\s+bc\s*,\s*0\s*"
                r"ld\s+de\s*,\s*0\s*"
                r"ld\s+iy\s*,\s*camera_z\s*"
                r"jp\s+scdabs"
            ),
        )
        self.assertNotRegex(self.code, r"(?i)\b(?:call|jp)\s+scrabs\b")


class GeneratedSourceTests(unittest.TestCase):
    def test_generated_sources_are_portable_and_bannered(self) -> None:
        for filename in lighting.GENERATED_SOURCE_NAMES:
            with self.subTest(filename=filename):
                source = (lighting.SOURCE_DIR / filename).read_text(encoding="utf-8")
                self.assertIn("AUTO-GENERATED FILE - DO NOT EDIT", source)

    def test_flat_include_validates_after_final_word_encoding(self) -> None:
        cells = validate_flat_palette_asm(
            lighting.SOURCE_DIR / "flat-cube.inc",
            "flat_cube",
        )
        self.assertEqual(len(cells), 12)

    def test_common_snapshot_contains_exact_new_subcommands_and_padding(self) -> None:
        source = (lighting.SOURCE_DIR / "vdu_pingo.inc").read_text(encoding="utf-8")
        commands = {
            int(value)
            for value in re.findall(r"db\s+\$49\s*,\s*(4[3-7])", source, re.I)
        }
        self.assertEqual(commands, {43, 44, 45, 46, 47})
        direction = source.split("pingo_set_light_direction:", 1)[1].split(
            "pingo_set_light_intensity:", 1
        )[0]
        self.assertRegex(direction, r"(?im)^@end:\s+db\s+0\s*;\s*padding\s*$")

    def test_ordinary_build_rejects_a_manually_corrupted_flat_include(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory)
            for filename in (lighting.ASSEMBLY_FILENAME, *lighting.GENERATED_SOURCE_NAMES):
                shutil.copy2(lighting.SOURCE_DIR / filename, source_dir / filename)
            flat_path = source_dir / "flat-cube.inc"
            source = flat_path.read_text(encoding="utf-8")
            marker = "flat_cube_uv_indices:\n\tdw 25, 25, 25"
            self.assertIn(marker, source)
            flat_path.write_text(
                source.replace(marker, "flat_cube_uv_indices:\n\tdw 25, 12, 25", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FlatPaletteError, "triangle 0 is multi-color"):
                lighting.validate_existing_source(source_dir)
            self.assertIn("dw 25, 12, 25", flat_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
