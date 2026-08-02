import colorsys
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pingo_terrain.flat_patterns import (
    BAYER_4X4,
    ILLUMINATION_BANDS,
    PATTERN_PIXELS,
    compile_patterns,
    pack_opaque_rgba2222,
    target_for_band,
    unpack_opaque_rgba2222,
    write_compiled_patterns,
)
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS, NLCD_MATERIALS


class FlatPatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compiled = compile_patterns(BERKELEY_TERRAIN_MATERIALS)

    def test_material_vocabulary_is_the_fifteen_authored_colors(self) -> None:
        self.assertEqual(len(BERKELEY_TERRAIN_MATERIALS), 15)
        self.assertEqual(
            [material.material_id for material in BERKELEY_TERRAIN_MATERIALS],
            list(range(15)),
        )
        self.assertEqual(
            [material.nlcd_category for material in BERKELEY_TERRAIN_MATERIALS],
            [11, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95],
        )
        self.assertEqual(
            [material.rgb for material in BERKELEY_TERRAIN_MATERIALS],
            [
                (43, 102, 128),
                (135, 144, 120),
                (143, 139, 123),
                (119, 118, 111),
                (96, 97, 95),
                (154, 139, 103),
                (75, 116, 68),
                (49, 88, 59),
                (62, 104, 64),
                (102, 115, 66),
                (126, 135, 80),
                (112, 130, 75),
                (154, 140, 74),
                (53, 95, 84),
                (82, 119, 106),
            ],
        )
        for material in BERKELEY_TERRAIN_MATERIALS:
            self.assertEqual(
                NLCD_MATERIALS[material.nlcd_category],
                (material.name, material.rgb),
            )

    def test_rgba2222_uses_opaque_aabbggrr_order(self) -> None:
        self.assertEqual(pack_opaque_rgba2222((0, 0, 0)), 0xC0)
        self.assertEqual(pack_opaque_rgba2222((3, 0, 0)), 0xC3)
        self.assertEqual(pack_opaque_rgba2222((0, 3, 0)), 0xCC)
        self.assertEqual(pack_opaque_rgba2222((0, 0, 3)), 0xF0)
        self.assertEqual(pack_opaque_rgba2222((3, 3, 3)), 0xFF)
        self.assertEqual(unpack_opaque_rgba2222(0xD9), (85, 170, 85))

    def test_bayer_matrix_contains_each_rank_once(self) -> None:
        self.assertEqual(
            sorted(rank for row in BAYER_4X4 for rank in row),
            list(range(PATTERN_PIXELS)),
        )

    def test_hsv_trajectory_holds_authored_hue_and_saturation(self) -> None:
        material = BERKELEY_TERRAIN_MATERIALS[0]
        base_h, base_s, base_v = colorsys.rgb_to_hsv(
            *(channel / 255 for channel in material.rgb)
        )
        for band in range(1, ILLUMINATION_BANDS):
            target = target_for_band(material, band)
            self.assertAlmostEqual(target.hue, base_h)
            self.assertAlmostEqual(target.saturation, base_s)
            self.assertAlmostEqual(
                target.value,
                base_v * band / (ILLUMINATION_BANDS - 1),
            )
            actual_h, actual_s, actual_v = colorsys.rgb_to_hsv(*target.rgb)
            self.assertAlmostEqual(actual_h, base_h)
            self.assertAlmostEqual(actual_s, base_s)
            self.assertAlmostEqual(actual_v, target.value)

    def test_resource_dimensions_ids_opacity_and_deduplication(self) -> None:
        compiled = self.compiled
        self.assertEqual(len(compiled.lookup), 15 * ILLUMINATION_BANDS)
        self.assertEqual(len(compiled.patterns), compiled.pattern_count * 16)
        self.assertLessEqual(compiled.pattern_count, len(compiled.lookup))
        patterns = [
            compiled.patterns[offset : offset + PATTERN_PIXELS]
            for offset in range(0, len(compiled.patterns), PATTERN_PIXELS)
        ]
        self.assertEqual(len(patterns), len(set(patterns)))
        self.assertTrue(
            all(identifier < len(patterns) for identifier in compiled.lookup)
        )
        self.assertTrue(all(pixel & 0xC0 == 0xC0 for pixel in compiled.patterns))
        self.assertTrue(all(len(set(pattern)) <= 3 for pattern in patterns))
        for index, entry in enumerate(compiled.metadata["entries"]):
            self.assertEqual(entry["material_id"], index // ILLUMINATION_BANDS)
            self.assertEqual(
                entry["illumination_band"], index % ILLUMINATION_BANDS
            )
            self.assertEqual(entry["pattern_id"], compiled.lookup[index])
        self.assertTrue(
            all(
                entry["native_color_count"] >= 2
                for entry in compiled.metadata["entries"][15::16]
            )
        )

    def test_zero_band_is_one_shared_solid_black_pattern(self) -> None:
        compiled = self.compiled
        zero_ids = compiled.lookup[0::ILLUMINATION_BANDS]
        self.assertEqual(len(set(zero_ids)), 1)
        pattern_id = zero_ids[0]
        start = pattern_id * PATTERN_PIXELS
        self.assertEqual(
            compiled.patterns[start : start + PATTERN_PIXELS],
            bytes([0xC0] * PATTERN_PIXELS),
        )

    def test_every_selected_third_color_clears_the_material_improvement_gate(self) -> None:
        entries = self.compiled.metadata["entries"]
        for entry in entries:
            if not entry["used_three_colors"]:
                continue
            improvement = entry["three_color_absolute_improvement"]
            self.assertGreaterEqual(improvement, 0.0005)
            self.assertGreaterEqual(
                improvement,
                entry["best_one_or_two_color_score"] * 0.40 - 1e-12,
            )

    def test_metadata_and_files_are_byte_deterministic(self) -> None:
        compiled = self.compiled
        metadata_bytes = compiled.metadata_bytes()
        parsed = json.loads(metadata_bytes)
        self.assertEqual(parsed["material_count"], 15)
        self.assertEqual(parsed["illumination_band_count"], 16)
        self.assertEqual(parsed["resources"]["lookup"]["bytes"], 240)
        self.assertEqual(
            parsed["resources"]["patterns"]["bytes"],
            len(compiled.patterns),
        )
        self.assertEqual(
            parsed["resources"]["lookup"]["sha256"],
            hashlib.sha256(compiled.lookup).hexdigest(),
        )
        self.assertEqual(compiled.pattern_count, 126)
        self.assertEqual(
            hashlib.sha256(compiled.patterns).hexdigest(),
            "cd1ebe2550335951ce09f80b5de150e4ff34c2da90518e30ad7ba7826f9d686a",
        )
        self.assertEqual(
            hashlib.sha256(compiled.lookup).hexdigest(),
            "9ed22fb30b1dc56a8f6e706ef9d39d683b9d15d89d69c088bea6b797272b3ee0",
        )
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            first_paths = write_compiled_patterns(compiled, Path(first))
            second_paths = write_compiled_patterns(compiled, Path(second))
            self.assertEqual(
                [path.read_bytes() for path in first_paths],
                [path.read_bytes() for path in second_paths],
            )


if __name__ == "__main__":
    unittest.main()
