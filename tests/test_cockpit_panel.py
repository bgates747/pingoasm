from __future__ import annotations

import unittest

from pingo_terrain.cockpit_panel import (
    BitmapFontProvider,
    BitmapGlyph,
    BitmapTypeface,
    Box,
    FillCircle,
    FontRole,
    GAUGE_CENTERS,
    GlyphRun,
    Point,
    SimpleBitmapFontProvider,
    build_panel_program,
    validate_panel_dimensions,
)
from pingo_terrain.cockpit_panel_pillow import (
    DEFAULT_RGB222_PALETTE,
    render_panel,
    render_panel_program,
)


EXPECTED_WELLS = {
    "airspeed": Box(3, 2, 47, 46),
    "attitude": Box(54, 2, 98, 46),
    "altimeter": Box(106, 2, 150, 46),
    "turn": Box(3, 47, 47, 91),
    "heading": Box(54, 47, 98, 91),
    "vertical_speed": Box(106, 47, 150, 91),
    "nav1": Box(158, 2, 202, 46),
    "nav2": Box(158, 47, 202, 91),
}


class _RecordingFontProvider(BitmapFontProvider):
    def __init__(self) -> None:
        self.requests: list[tuple[FontRole, int]] = []
        # A deliberately non-3x5 font proves that renderer metrics come from
        # the provider rather than from Pillow or hard-coded glyph dimensions.
        glyph = BitmapGlyph(2, (0b11, 0b01, 0b10, 0b01, 0b10, 0b01, 0b11))
        self.typeface = BitmapTypeface({"?": glyph}, line_height=7, spacing=2)

    def get_typeface(self, role: FontRole, target_height: int) -> BitmapTypeface:
        self.requests.append((role, target_height))
        return self.typeface


class CockpitPanelSceneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.program = build_panel_program()

    def test_reference_scene_has_eight_exact_round_wells(self) -> None:
        self.assertEqual(set(GAUGE_CENTERS), set(EXPECTED_WELLS))
        for name, expected in EXPECTED_WELLS.items():
            bounds = self.program.regions[f"well.{name}"]
            self.assertEqual(bounds, expected)
            self.assertEqual(bounds.width, bounds.height)
            outer = [
                command.primitive
                for command in self.program.commands
                if command.name == f"{name}.outer"
            ]
            self.assertEqual(len(outer), 1)
            self.assertIsInstance(outer[0], FillCircle)
            self.assertEqual(outer[0].center, GAUGE_CENTERS[name])
            self.assertEqual(outer[0].radius, 22)

    def test_named_regions_fit_reference_canvas(self) -> None:
        for name, box in self.program.regions.items():
            with self.subTest(region=name):
                self.assertGreaterEqual(box.x0, 0)
                self.assertGreaterEqual(box.y0, 0)
                self.assertLessEqual(box.x1, self.program.reference_width)
                self.assertLessEqual(box.y1, self.program.reference_height)
        self.assertEqual(self.program.regions["gps.opening"], Box(212, 4, 315, 88))

    def test_scene_contains_no_live_values_or_source_annunciator(self) -> None:
        text = " ".join(
            command.primitive.text
            for command in self.program.commands
            if isinstance(command.primitive, GlyphRun)
        )
        for forbidden in ("OFF", "276", "096", "180", "270", "090"):
            self.assertNotIn(forbidden, text)
        self.assertFalse(any("needle" in command.name for command in self.program.commands))
        self.assertFalse(any("cdi" in command.name for command in self.program.commands))
        self.assertFalse(any("glideslope" in command.name for command in self.program.commands))

    def test_dynamic_repaint_bounds_exist_without_dynamic_commands(self) -> None:
        for name, center in GAUGE_CENTERS.items():
            self.assertEqual(
                self.program.regions[f"dynamic.{name}"],
                Box(center.x - 18, center.y - 18, center.x + 18, center.y + 18),
            )

    def test_dimensions_are_always_isotropic(self) -> None:
        for accepted in ((80, 23), (320, 92), (1280, 368), (1920, 552)):
            validate_panel_dimensions(*accepted)
        for rejected in ((0, 0), (320, 91), (321, 92), (-320, -92)):
            with self.subTest(size=rejected), self.assertRaises(ValueError):
                validate_panel_dimensions(*rejected)


class CockpitPanelPillowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.program = build_panel_program()

    def test_native_render_is_opaque_rgb222_and_deterministic(self) -> None:
        first = render_panel_program(self.program, 320, 92)
        second = render_panel_program(self.program, 320, 92)
        self.assertEqual(first.mode, "RGBA")
        self.assertEqual(first.size, (320, 92))
        self.assertEqual(first.tobytes(), second.tobytes())
        allowed = set(DEFAULT_RGB222_PALETTE.values())
        colors = set(first.get_flattened_data())
        self.assertLessEqual(colors, allowed)
        self.assertTrue(all(color[3] == 255 for color in colors))

    def test_large_preview_retains_exact_size(self) -> None:
        image = render_panel(1280, 368)
        self.assertEqual(image.size, (1280, 368))

    def test_gps_opening_is_one_uniform_blank_screen(self) -> None:
        image = render_panel_program(self.program, 320, 92)
        expected = DEFAULT_RGB222_PALETTE[next(
            ink for ink in DEFAULT_RGB222_PALETTE if ink.value == "gps_screen"
        )]
        samples = {
            image.getpixel((x, y))
            for x in range(214, 314, 7)
            for y in range(6, 87, 7)
        }
        self.assertEqual(samples, {expected})

    def test_legacy_squash_is_preview_only(self) -> None:
        canonical = render_panel_program(self.program, 320, 92)
        legacy = render_panel_program(self.program, 320, 92, legacy_squash=True)
        self.assertNotEqual(canonical.getpixel((25, 2)), legacy.getpixel((25, 2)))
        self.assertEqual(
            self.program.regions["well.airspeed"],
            Box(3, 2, 47, 46),
            "legacy rendering must not mutate canonical geometry",
        )

    def test_arbitrary_bitmap_font_metrics_are_honored(self) -> None:
        fonts = _RecordingFontProvider()
        image = render_panel_program(self.program, 640, 184, fonts=fonts)
        self.assertEqual(image.size, (640, 184))
        self.assertGreater(len(fonts.requests), 10)
        self.assertIn((FontRole.INSTRUMENT, 4), fonts.requests)

    def test_invalid_supersample_and_palette_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            render_panel_program(self.program, 320, 92, supersample=0)
        incomplete = dict(DEFAULT_RGB222_PALETTE)
        incomplete.pop(next(iter(incomplete)))
        with self.assertRaises(ValueError):
            render_panel_program(self.program, 320, 92, palette=incomplete)

    def test_placeholder_font_is_explicit_and_backend_neutral(self) -> None:
        provider = SimpleBitmapFontProvider()
        typeface = provider.get_typeface(FontRole.PANEL, 17)
        self.assertEqual(typeface.line_height, 5)
        self.assertEqual(typeface.measure("ABC"), (11, 5))
        self.assertIsInstance(typeface.glyph("A"), BitmapGlyph)
        self.assertIsInstance(typeface.glyph("@"), BitmapGlyph)


if __name__ == "__main__":
    unittest.main()
