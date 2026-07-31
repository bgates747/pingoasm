#!/usr/bin/env python3
"""Regression tests for the Pingo flat-palette conversion contract."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import flat_palette as flat
from blender_obj_to_asm import encode_uv_word, parse_obj_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PaletteAssetTests(unittest.TestCase):
    def test_canonical_png_and_packed_asset(self) -> None:
        image = flat.verify_palette_image(flat.DEFAULT_PALETTE)
        self.assertEqual(image.size, (8, 8))
        image.close()
        packed = PROJECT_ROOT / "src/blender/colors64.rgba2"
        self.assertEqual(len(packed.read_bytes()), 64)
        self.assertEqual(
            hashlib.sha256(packed.read_bytes()).hexdigest(),
            "858b708a30584790b8255450819ffdca148a60150a31ba35be3ff8f70f92f130",
        )

    def test_uv_encoder_reaches_both_endpoints(self) -> None:
        self.assertEqual(encode_uv_word(-1.0), 0)
        self.assertEqual(encode_uv_word(0.0), 0)
        self.assertEqual(encode_uv_word(1.0), 65535)
        self.assertEqual(encode_uv_word(2.0), 65535)

    def test_every_palette_index_round_trips(self) -> None:
        for index in range(64):
            with self.subTest(index=index):
                words = flat.palette_uv_words(index)
                self.assertEqual(
                    flat.resolve_uv_words(*words, 8, 8),
                    (index % 8, index // 8),
                )


class FlatTriangleValidationTests(unittest.TestCase):
    def test_accepts_one_cell_per_triangle(self) -> None:
        words = [flat.palette_uv_words(index) for index in (9, 12)]
        self.assertEqual(
            flat.validate_flat_palette_words(words, [[0, 0, 0], [1, 1, 1]]),
            [(1, 1), (4, 1)],
        )

    def test_rejects_multi_color_triangle(self) -> None:
        words = [flat.palette_uv_words(index) for index in (9, 12)]
        with self.assertRaisesRegex(
            flat.FlatPaletteError,
            r"triangle 0 is multi-color.*\(1, 1\).*\(4, 1\)",
        ):
            flat.validate_flat_palette_words(words, [[0, 1, 0]])

    def test_rejects_non_triangle_and_bad_index(self) -> None:
        words = [flat.palette_uv_words(9)]
        with self.assertRaisesRegex(flat.FlatPaletteError, "not 3"):
            flat.validate_flat_palette_words(words, [[0, 0, 0, 0]])
        with self.assertRaisesRegex(flat.FlatPaletteError, "UV index 1"):
            flat.validate_flat_palette_words(words, [[0, 1, 0]])


class PredominantColorMigrationTests(unittest.TestCase):
    @staticmethod
    def select_from_pixels(pixels: list[tuple[int, int, int, int]]) -> int:
        coordinates = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
        with Image.new("RGBA", (1, 1)) as image:
            with mock.patch.object(flat, "_source_texels", return_value=pixels):
                return flat.predominant_palette_index(image, coordinates)

    def test_transparent_texels_are_ignored(self) -> None:
        transparent = (*flat.colors64[63], 0)
        opaque = (*flat.colors64[17], 255)
        self.assertEqual(
            self.select_from_pixels([transparent, transparent, opaque]),
            17,
        )

    def test_modal_palette_index_wins(self) -> None:
        modal = (*flat.colors64[12], 255)
        minority = (*flat.colors64[9], 255)
        self.assertEqual(
            self.select_from_pixels([modal, minority, modal]),
            12,
        )

    def test_palette_tie_uses_lowest_index(self) -> None:
        higher = (*flat.colors64[12], 255)
        lower = (*flat.colors64[9], 255)
        self.assertEqual(self.select_from_pixels([higher, lower]), 9)

    def test_all_transparent_triangle_falls_back_to_index_zero(self) -> None:
        self.assertEqual(
            self.select_from_pixels(
                [(*flat.colors64[9], 0), (*flat.colors64[12], 0)]
            ),
            0,
        )

    def test_cube_selects_one_stable_color_per_face(self) -> None:
        model, selections = flat.convert_obj_model_data(
            PROJECT_ROOT / "src/blender/cube.obj",
            PROJECT_ROOT / "src/blender/blenderaxes.png",
        )
        self.assertEqual(selections, [25, 12, 9, 16, 17, 10] * 2)
        self.assertEqual(
            flat.validate_flat_palette_data(model[2], model[3]),
            [
                (1, 3),
                (4, 1),
                (1, 1),
                (0, 2),
                (1, 2),
                (2, 1),
            ]
            * 2,
        )

    def test_obj_rewrite_round_trips_through_the_normal_parser(self) -> None:
        source = PROJECT_ROOT / "src/blender/cube.obj"
        _, selections = flat.convert_obj_model_data(
            source,
            PROJECT_ROOT / "src/blender/blenderaxes.png",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cube-flat.obj"
            flat.write_flat_obj(source, output, selections)
            converted = parse_obj_file(output)
            resolved = flat.validate_flat_palette_data(converted[2], converted[3])
        self.assertEqual(len(resolved), 12)

    def test_generated_obj_banner_names_flat_palette_generator(self) -> None:
        source = PROJECT_ROOT / "src/blender/cube.obj"
        _, selections = flat.convert_obj_model_data(
            source,
            PROJECT_ROOT / "src/blender/blenderaxes.png",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cube-flat.obj"
            flat.write_flat_obj(source, output, selections)
            generated = output.read_text(encoding="utf-8")

        self.assertIn("# AUTO-GENERATED FILE - DO NOT EDIT", generated)
        self.assertIn(
            "# Generated by: build/scripts/flat_palette.py",
            generated,
        )


if __name__ == "__main__":
    unittest.main()
