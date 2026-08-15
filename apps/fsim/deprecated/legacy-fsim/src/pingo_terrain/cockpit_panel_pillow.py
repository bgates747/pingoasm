"""Pillow review backend for :mod:`pingo_terrain.cockpit_panel`.

The canonical native render is hard-edged and uses only opaque Agon RGB222
colors.  Optional supersampling is useful for a large design review, but its
intermediate colors are not authoritative for a future VDP backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from PIL import Image, ImageDraw

from .cockpit_panel import (
    BitmapFontProvider,
    Box,
    DrawCommand,
    FillCircle,
    FillRect,
    FillTriangle,
    GlyphRun,
    Ink,
    LEGACY_GAUGE_Y_SCALE,
    PanelProgram,
    Point,
    SimpleBitmapFontProvider,
    StrokeCircle,
    StrokeLine,
    build_panel_program,
    validate_panel_dimensions,
)


Rgba = tuple[int, int, int, int]

# Every channel belongs to the Agon's 2-bit-per-channel cube.  Semantic color
# IDs, rather than these host tuples, remain in the panel scene.
DEFAULT_RGB222_PALETTE: Mapping[Ink, Rgba] = MappingProxyType(
    {
        Ink.PANEL: (170, 170, 170, 255),
        Ink.PANEL_LIGHT: (255, 255, 255, 255),
        Ink.PANEL_SHADOW: (85, 85, 85, 255),
        Ink.BEZEL: (85, 85, 85, 255),
        Ink.FACE: (0, 0, 0, 255),
        Ink.MARK: (255, 255, 255, 255),
        Ink.SUBDUED_MARK: (170, 170, 170, 255),
        Ink.GPS_SCREEN: (0, 0, 0, 255),
    }
)


@dataclass(frozen=True, slots=True)
class _CommandTransform:
    factor: float
    pivot: Point | None
    gauge_y_scale: float

    def point(self, point: Point) -> tuple[int, int]:
        y = point.y
        if self.pivot is not None:
            y = self.pivot.y + (point.y - self.pivot.y) * self.gauge_y_scale
        return round(point.x * self.factor), round(y * self.factor)

    def box(self, box: Box) -> tuple[int, int, int, int]:
        top_left = self.point(Point(box.x0, box.y0))
        bottom_right = self.point(Point(box.x1, box.y1))
        return top_left[0], top_left[1], bottom_right[0], bottom_right[1]

    @property
    def line_width(self) -> int:
        return max(1, round(self.factor))


def _validate_palette(palette: Mapping[Ink, Rgba]) -> None:
    missing = set(Ink).difference(palette)
    if missing:
        raise ValueError(f"panel palette is missing inks: {sorted(missing)}")
    for ink, color in palette.items():
        if len(color) != 4 or any(channel not in (0, 85, 170, 255) for channel in color):
            raise ValueError(f"{ink} is not an opaque RGB222 color: {color}")
        if color[3] != 255:
            raise ValueError(f"{ink} is not opaque: {color}")


def _glyph_run(
    draw: ImageDraw.ImageDraw,
    command: DrawCommand,
    primitive: GlyphRun,
    transform: _CommandTransform,
    palette: Mapping[Ink, Rgba],
    fonts: BitmapFontProvider,
) -> None:
    """Center a bitmap glyph run using its actual, caller-defined metrics."""

    typeface = fonts.get_typeface(primitive.font_role, primitive.target_height)
    natural_width, natural_height = typeface.measure(primitive.text)
    x0, y0, x1, y1 = transform.box(primitive.box)
    available_width = max(1, x1 - x0)
    available_height = max(1, y1 - y0)

    desired_scale = primitive.target_height * transform.factor / natural_height
    horizontal_scale = min(desired_scale, available_width / max(1, natural_width))
    vertical_scale = horizontal_scale
    if command.group is not None:
        vertical_scale *= transform.gauge_y_scale
    if natural_height * vertical_scale > available_height:
        correction = available_height / (natural_height * vertical_scale)
        horizontal_scale *= correction
        vertical_scale *= correction

    rendered_width = natural_width * horizontal_scale
    rendered_height = natural_height * vertical_scale
    cursor_x = x0 + (available_width - rendered_width) / 2
    top = y0 + (available_height - rendered_height) / 2
    color = palette[primitive.ink]

    for character in primitive.text:
        glyph = typeface.glyph(character)
        glyph_top = top + (typeface.line_height - glyph.height) * vertical_scale
        for row_index, row_bits in enumerate(glyph.rows):
            for column in range(glyph.width):
                bit = 1 << (glyph.width - column - 1)
                if not row_bits & bit:
                    continue
                left = round(cursor_x + column * horizontal_scale)
                upper = round(glyph_top + row_index * vertical_scale)
                right = max(left, round(cursor_x + (column + 1) * horizontal_scale) - 1)
                lower = max(upper, round(glyph_top + (row_index + 1) * vertical_scale) - 1)
                draw.rectangle((left, upper, right, lower), fill=color)
        cursor_x += (glyph.width + typeface.spacing) * horizontal_scale


def _draw_command(
    draw: ImageDraw.ImageDraw,
    command: DrawCommand,
    program: PanelProgram,
    factor: float,
    legacy_squash: bool,
    palette: Mapping[Ink, Rgba],
    fonts: BitmapFontProvider,
) -> None:
    pivot = program.pivots.get(command.group) if command.group is not None else None
    transform = _CommandTransform(
        factor=factor,
        pivot=pivot,
        gauge_y_scale=LEGACY_GAUGE_Y_SCALE if legacy_squash and pivot else 1.0,
    )
    primitive = command.primitive

    if isinstance(primitive, FillRect):
        draw.rectangle(transform.box(primitive.box), fill=palette[primitive.ink])
    elif isinstance(primitive, StrokeLine):
        draw.line(
            (transform.point(primitive.start), transform.point(primitive.end)),
            fill=palette[primitive.ink],
            width=transform.line_width,
        )
    elif isinstance(primitive, FillTriangle):
        draw.polygon(
            (
                transform.point(primitive.first),
                transform.point(primitive.second),
                transform.point(primitive.third),
            ),
            fill=palette[primitive.ink],
        )
    elif isinstance(primitive, FillCircle):
        center_x, center_y = transform.point(primitive.center)
        radius_x = round(primitive.radius * factor)
        radius_y = round(
            primitive.radius
            * factor
            * (transform.gauge_y_scale if command.group is not None else 1.0)
        )
        draw.ellipse(
            (
                center_x - radius_x,
                center_y - radius_y,
                center_x + radius_x,
                center_y + radius_y,
            ),
            fill=palette[primitive.ink],
        )
    elif isinstance(primitive, StrokeCircle):
        center_x, center_y = transform.point(primitive.center)
        radius_x = round(primitive.radius * factor)
        radius_y = round(
            primitive.radius
            * factor
            * (transform.gauge_y_scale if command.group is not None else 1.0)
        )
        draw.ellipse(
            (
                center_x - radius_x,
                center_y - radius_y,
                center_x + radius_x,
                center_y + radius_y,
            ),
            outline=palette[primitive.ink],
            width=transform.line_width,
        )
    elif isinstance(primitive, GlyphRun):
        _glyph_run(draw, command, primitive, transform, palette, fonts)
    else:  # pragma: no cover - guarded by the closed Primitive union.
        raise TypeError(f"unsupported panel primitive: {type(primitive).__name__}")


def render_panel_program(
    program: PanelProgram,
    width: int,
    height: int,
    *,
    legacy_squash: bool = False,
    supersample: int = 1,
    palette: Mapping[Ink, Rgba] = DEFAULT_RGB222_PALETTE,
    fonts: BitmapFontProvider | None = None,
) -> Image.Image:
    """Render one panel program at an exact isotropic output size.

    ``supersample=1`` is the hard-edged RGB222 authority.  Larger values render
    at a multiple and reduce with Lanczos for review only.  ``legacy_squash``
    applies the measured historical 0.86 vertical scale around each gauge's
    center; it never changes the canonical scene consumed by future backends.
    """

    validate_panel_dimensions(width, height)
    if supersample <= 0 or supersample > 8:
        raise ValueError("supersample must be in the range 1..8")
    _validate_palette(palette)
    font_provider = fonts if fonts is not None else SimpleBitmapFontProvider()

    working_width = width * supersample
    working_height = height * supersample
    factor = working_width / program.reference_width
    if working_height / program.reference_height != factor:
        raise ValueError("panel program and output dimensions are not isotropic")

    image = Image.new("RGBA", (working_width, working_height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    for command in program.commands:
        _draw_command(
            draw,
            command,
            program,
            factor,
            legacy_squash,
            palette,
            font_provider,
        )

    if supersample > 1:
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def render_panel(
    width: int,
    height: int,
    *,
    legacy_squash: bool = False,
    supersample: int = 1,
    palette: Mapping[Ink, Rgba] = DEFAULT_RGB222_PALETTE,
    fonts: BitmapFontProvider | None = None,
) -> Image.Image:
    """Build and render the canonical cockpit panel."""

    return render_panel_program(
        build_panel_program(),
        width,
        height,
        legacy_squash=legacy_squash,
        supersample=supersample,
        palette=palette,
        fonts=fonts,
    )


__all__ = [
    "DEFAULT_RGB222_PALETTE",
    "render_panel",
    "render_panel_program",
]
