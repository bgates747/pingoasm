"""Backend-neutral description of the light-flight cockpit panel.

The panel is authored once on a 320 by 92 integer grid.  The primitives in
this module deliberately correspond to operations available from the Agon VDP:
filled rectangles, lines, triangles, and circles.  A Pillow renderer is the
first consumer, but the ordered scene is intended to become input to an eZ80
VDU-packet generator without changing the panel geometry.

This first scene contains the panel structure and fixed markings only.  Moving
needles, rotating cards, live digits, flags, and annunciators are explicitly
absent.  ``dynamic.*`` named regions reserve their future repaint bounds.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import cos, pi, sin
from types import MappingProxyType
from typing import Mapping, Protocol, TypeAlias


REFERENCE_WIDTH = 320
REFERENCE_HEIGHT = 92
ASPECT_WIDTH = 80
ASPECT_HEIGHT = 23
LEGACY_GAUGE_Y_SCALE = 43 / 50


class Ink(StrEnum):
    """Semantic, opaque RGB222 colors resolved by a rendering backend."""

    PANEL = "panel"
    PANEL_LIGHT = "panel_light"
    PANEL_SHADOW = "panel_shadow"
    BEZEL = "bezel"
    FACE = "face"
    MARK = "mark"
    SUBDUED_MARK = "subdued_mark"
    GPS_SCREEN = "gps_screen"


class FontRole(StrEnum):
    """Font selection hooks; roles are independent of glyph dimensions."""

    SCALE = "scale"
    INSTRUMENT = "instrument"
    PANEL = "panel"


class PanelLayer(StrEnum):
    """Stable ordering groups useful to a later assembly code generator."""

    SUBSTRATE = "substrate"
    RECESS = "recess"
    BEZEL = "bezel"
    STATIC_FACE = "static_face"
    FOREGROUND = "foreground"


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Box:
    """Geometric bounds in reference pixels; both extrema are retained."""

    x0: int
    y0: int
    x1: int
    y1: int

    def __post_init__(self) -> None:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError(f"invalid box: {self}")

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


@dataclass(frozen=True, slots=True)
class FillRect:
    box: Box
    ink: Ink


@dataclass(frozen=True, slots=True)
class StrokeLine:
    start: Point
    end: Point
    ink: Ink


@dataclass(frozen=True, slots=True)
class FillTriangle:
    first: Point
    second: Point
    third: Point
    ink: Ink


@dataclass(frozen=True, slots=True)
class FillCircle:
    center: Point
    radius: int
    ink: Ink

    def __post_init__(self) -> None:
        if self.radius < 0:
            raise ValueError("circle radius must be non-negative")


@dataclass(frozen=True, slots=True)
class StrokeCircle:
    center: Point
    radius: int
    ink: Ink

    def __post_init__(self) -> None:
        if self.radius < 0:
            raise ValueError("circle radius must be non-negative")


@dataclass(frozen=True, slots=True)
class GlyphRun:
    """Semantic text resolved through a caller-supplied bitmap font provider."""

    text: str
    box: Box
    ink: Ink
    font_role: FontRole
    target_height: int = 5

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("glyph run must not be empty")
        if self.target_height <= 0:
            raise ValueError("glyph target height must be positive")


Primitive: TypeAlias = (
    FillRect | StrokeLine | FillTriangle | FillCircle | StrokeCircle | GlyphRun
)


@dataclass(frozen=True, slots=True)
class DrawCommand:
    """One ordered operation with stable semantics and optional gauge group."""

    name: str
    layer: PanelLayer
    primitive: Primitive
    group: str | None = None


@dataclass(frozen=True, slots=True)
class BitmapGlyph:
    """One monochrome glyph represented by left-to-right bit rows."""

    width: int
    rows: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.width <= 0 or not self.rows:
            raise ValueError("bitmap glyph dimensions must be positive")
        if any(row < 0 or row >= 1 << self.width for row in self.rows):
            raise ValueError("bitmap glyph row exceeds declared width")

    @property
    def height(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class BitmapTypeface:
    """Backend-neutral bitmap font with arbitrary glyph width and height."""

    glyphs: Mapping[str, BitmapGlyph]
    line_height: int
    spacing: int = 1
    fallback: str = "?"

    def __post_init__(self) -> None:
        if self.line_height <= 0 or self.spacing < 0:
            raise ValueError("invalid bitmap typeface metrics")
        if self.fallback not in self.glyphs:
            raise ValueError("bitmap typeface is missing its fallback glyph")
        if any(glyph.height > self.line_height for glyph in self.glyphs.values()):
            raise ValueError("glyph is taller than the typeface line height")

    def glyph(self, character: str) -> BitmapGlyph:
        return self.glyphs.get(character, self.glyphs[self.fallback])

    def measure(self, text: str) -> tuple[int, int]:
        glyphs = tuple(self.glyph(character) for character in text)
        width = sum(glyph.width for glyph in glyphs)
        if glyphs:
            width += self.spacing * (len(glyphs) - 1)
        return width, self.line_height


class BitmapFontProvider(Protocol):
    """Hook for later supplied bitmap fonts of any native dimensions."""

    def get_typeface(
        self, role: FontRole, target_height: int
    ) -> BitmapTypeface:
        """Return the best available bitmap face for a semantic text role."""


@dataclass(frozen=True, slots=True)
class PanelProgram:
    """Complete immutable drawing program and named future repaint regions."""

    commands: tuple[DrawCommand, ...]
    regions: Mapping[str, Box]
    pivots: Mapping[str, Point]
    reference_width: int = REFERENCE_WIDTH
    reference_height: int = REFERENCE_HEIGHT


GAUGE_CENTERS: Mapping[str, Point] = MappingProxyType(
    {
        "airspeed": Point(25, 24),
        "attitude": Point(76, 24),
        "altimeter": Point(128, 24),
        "turn": Point(25, 69),
        "heading": Point(76, 69),
        "vertical_speed": Point(128, 69),
        "nav1": Point(180, 24),
        "nav2": Point(180, 69),
    }
)


def validate_panel_dimensions(width: int, height: int) -> None:
    """Reject non-positive or anisotropic output sizes."""

    if width <= 0 or height <= 0:
        raise ValueError("panel dimensions must be positive")
    if width * ASPECT_HEIGHT != height * ASPECT_WIDTH:
        raise ValueError(
            f"panel size must have the exact {ASPECT_WIDTH}:{ASPECT_HEIGHT} "
            f"aspect ratio, got {width}x{height}"
        )


def _glyph(pattern: str) -> BitmapGlyph:
    """Compile slash-separated 0/1 rows into a compact bitmap glyph."""

    rows = pattern.split("/")
    width = len(rows[0])
    if not rows or any(len(row) != width for row in rows):
        raise ValueError(f"malformed glyph pattern: {pattern!r}")
    return BitmapGlyph(width, tuple(int(row, 2) for row in rows))


_SIMPLE_3X5_PATTERNS = {
    " ": "000/000/000/000/000",
    "?": "110/001/010/000/010",
    "0": "111/101/101/101/111",
    "1": "010/110/010/010/111",
    "2": "110/001/111/100/111",
    "3": "110/001/011/001/110",
    "4": "101/101/111/001/001",
    "5": "111/100/110/001/110",
    "6": "011/100/111/101/111",
    "7": "111/001/010/010/010",
    "8": "111/101/111/101/111",
    "9": "111/101/111/001/110",
    "A": "010/101/111/101/101",
    "B": "110/101/110/101/110",
    "C": "011/100/100/100/011",
    "D": "110/101/101/101/110",
    "E": "111/100/110/100/111",
    "F": "111/100/110/100/100",
    "G": "011/100/101/101/011",
    "H": "101/101/111/101/101",
    "I": "111/010/010/010/111",
    "J": "001/001/001/101/010",
    "K": "101/101/110/101/101",
    "L": "100/100/100/100/111",
    "M": "101/111/111/101/101",
    "N": "101/111/111/111/101",
    "O": "010/101/101/101/010",
    "P": "110/101/110/100/100",
    "Q": "010/101/101/111/011",
    "R": "110/101/110/101/101",
    "S": "011/100/010/001/110",
    "T": "111/010/010/010/010",
    "U": "101/101/101/101/111",
    "V": "101/101/101/101/010",
    "W": "101/101/111/111/101",
    "X": "101/101/010/101/101",
    "Y": "101/101/010/010/010",
    "Z": "111/001/010/100/111",
    ".": "000/000/000/000/010",
    ",": "000/000/000/010/100",
    ":": "000/010/000/010/000",
    "-": "000/000/111/000/000",
    "+": "000/010/111/010/000",
    "/": "001/001/010/100/100",
}

SIMPLE_3X5_TYPEFACE = BitmapTypeface(
    glyphs=MappingProxyType(
        {character: _glyph(pattern) for character, pattern in _SIMPLE_3X5_PATTERNS.items()}
    ),
    line_height=5,
)


class SimpleBitmapFontProvider:
    """Deterministic placeholder until the Author supplies cockpit fonts."""

    def get_typeface(
        self, role: FontRole, target_height: int
    ) -> BitmapTypeface:
        del role, target_height
        return SIMPLE_3X5_TYPEFACE


class _SceneBuilder:
    def __init__(self) -> None:
        self.commands: list[DrawCommand] = []
        self.regions: dict[str, Box] = {}

    def add(
        self,
        name: str,
        layer: PanelLayer,
        primitive: Primitive,
        *,
        group: str | None = None,
    ) -> None:
        self.commands.append(DrawCommand(name, layer, primitive, group))

    def region(self, name: str, box: Box) -> None:
        if name in self.regions:
            raise ValueError(f"duplicate panel region: {name}")
        self.regions[name] = box


def _circle_box(center: Point, radius: int) -> Box:
    return Box(
        center.x - radius,
        center.y - radius,
        center.x + radius,
        center.y + radius,
    )


def _polar(center: Point, radius: int, angle_degrees: float) -> Point:
    """Return a dial point; zero degrees is up and angles increase clockwise."""

    angle = angle_degrees * pi / 180.0
    return Point(
        center.x + round(sin(angle) * radius),
        center.y - round(cos(angle) * radius),
    )


def _text_box(center: Point, width: int, height: int) -> Box:
    half = width // 2
    return Box(
        center.x - half,
        center.y - height // 2,
        center.x + width - half,
        center.y + (height + 1) // 2,
    )


def _add_text(
    builder: _SceneBuilder,
    name: str,
    text: str,
    box: Box,
    *,
    role: FontRole = FontRole.SCALE,
    ink: Ink = Ink.MARK,
    height: int = 5,
    group: str,
) -> None:
    builder.add(
        name,
        PanelLayer.STATIC_FACE,
        GlyphRun(text, box, ink, role, height),
        group=group,
    )


def _add_round_well(builder: _SceneBuilder, name: str) -> None:
    center = GAUGE_CENTERS[name]
    builder.region(f"well.{name}", _circle_box(center, 22))
    builder.region(f"dynamic.{name}", _circle_box(center, 18))
    # Nested filled circles give the VDP backend deterministic ring widths.
    for suffix, radius, ink in (
        ("outer", 22, Ink.PANEL_SHADOW),
        ("rim", 21, Ink.MARK),
        ("bezel", 20, Ink.BEZEL),
        ("face", 18, Ink.FACE),
    ):
        builder.add(
            f"{name}.{suffix}",
            PanelLayer.BEZEL,
            FillCircle(center, radius, ink),
            group=name,
        )


def _add_tick_ring(
    builder: _SceneBuilder,
    group: str,
    *,
    start_degrees: float,
    sweep_degrees: float,
    divisions: int,
    outer_radius: int = 17,
    major_every: int = 5,
    minor_length: int = 1,
    major_length: int = 3,
) -> None:
    center = GAUGE_CENTERS[group]
    for index in range(divisions + 1):
        angle = start_degrees + sweep_degrees * index / divisions
        length = major_length if index % major_every == 0 else minor_length
        builder.add(
            f"{group}.tick.{index:02d}",
            PanelLayer.STATIC_FACE,
            StrokeLine(
                _polar(center, outer_radius - length, angle),
                _polar(center, outer_radius, angle),
                Ink.MARK,
            ),
            group=group,
        )


def _add_airspeed(builder: _SceneBuilder) -> None:
    group = "airspeed"
    center = GAUGE_CENTERS[group]
    _add_tick_ring(
        builder,
        group,
        start_degrees=220,
        sweep_degrees=280,
        divisions=30,
        major_every=5,
    )
    for index, label in enumerate(("0", "40", "80", "120", "160", "200", "240")):
        point = _polar(center, 12, 220 + 280 * index / 6)
        _add_text(
            builder,
            f"{group}.label.{label}",
            label,
            _text_box(point, 11, 5),
            height=4,
            group=group,
        )
    _add_text(
        builder,
        f"{group}.title",
        "KNOTS",
        Box(center.x - 11, center.y + 8, center.x + 11, center.y + 14),
        role=FontRole.INSTRUMENT,
        height=4,
        group=group,
    )


def _add_attitude(builder: _SceneBuilder) -> None:
    group = "attitude"
    center = GAUGE_CENTERS[group]
    # Only fixed bank marks and the fixed aircraft reference belong to the base.
    # The sky/ground sphere and pitch ladder are moving card data and are absent.
    for index, angle in enumerate((-60, -30, 0, 30, 60)):
        builder.add(
            f"{group}.bank-mark.{index}",
            PanelLayer.STATIC_FACE,
            StrokeLine(_polar(center, 14, angle), _polar(center, 17, angle), Ink.MARK),
            group=group,
        )
    builder.add(
        f"{group}.left-wing",
        PanelLayer.STATIC_FACE,
        StrokeLine(Point(center.x - 12, center.y), Point(center.x - 3, center.y), Ink.MARK),
        group=group,
    )
    builder.add(
        f"{group}.right-wing",
        PanelLayer.STATIC_FACE,
        StrokeLine(Point(center.x + 3, center.y), Point(center.x + 12, center.y), Ink.MARK),
        group=group,
    )
    builder.add(
        f"{group}.reference",
        PanelLayer.STATIC_FACE,
        FillRect(Box(center.x - 2, center.y - 1, center.x + 2, center.y + 1), Ink.MARK),
        group=group,
    )
    _add_text(
        builder,
        f"{group}.title",
        "ATT",
        Box(center.x - 7, center.y + 9, center.x + 7, center.y + 15),
        role=FontRole.INSTRUMENT,
        height=4,
        group=group,
    )


def _add_altimeter(builder: _SceneBuilder) -> None:
    group = "altimeter"
    center = GAUGE_CENTERS[group]
    _add_tick_ring(
        builder,
        group,
        start_degrees=0,
        sweep_degrees=360,
        divisions=40,
        major_every=4,
    )
    for value in range(10):
        point = _polar(center, 12, value * 36)
        _add_text(
            builder,
            f"{group}.label.{value}",
            str(value),
            _text_box(point, 5, 5),
            height=4,
            group=group,
        )
    builder.add(
        f"{group}.pressure-window-frame",
        PanelLayer.STATIC_FACE,
        FillRect(Box(center.x - 7, center.y + 7, center.x + 7, center.y + 12), Ink.SUBDUED_MARK),
        group=group,
    )
    builder.add(
        f"{group}.pressure-window",
        PanelLayer.STATIC_FACE,
        FillRect(Box(center.x - 6, center.y + 8, center.x + 6, center.y + 11), Ink.FACE),
        group=group,
    )
    _add_text(
        builder,
        f"{group}.title",
        "ALT",
        Box(center.x - 7, center.y + 1, center.x + 7, center.y + 7),
        role=FontRole.INSTRUMENT,
        height=4,
        group=group,
    )


def _add_turn(builder: _SceneBuilder) -> None:
    group = "turn"
    center = GAUGE_CENTERS[group]
    for index, angle in enumerate((-60, -30, 0, 30, 60)):
        builder.add(
            f"{group}.reference.{index}",
            PanelLayer.STATIC_FACE,
            StrokeLine(_polar(center, 14, angle), _polar(center, 17, angle), Ink.MARK),
            group=group,
        )
    for side, x in (("left", center.x - 12), ("right", center.x + 12)):
        _add_text(
            builder,
            f"{group}.{side}",
            "L" if side == "left" else "R",
            Box(x - 3, center.y - 3, x + 3, center.y + 3),
            height=4,
            group=group,
        )
    # The curved slip track is fixed; its moving ball is intentionally absent.
    for radius in (12, 15):
        previous = _polar(center, radius, 125)
        for angle in range(135, 236, 10):
            current = _polar(center, radius, angle)
            builder.add(
                f"{group}.slip-track.{radius}.{angle}",
                PanelLayer.STATIC_FACE,
                StrokeLine(previous, current, Ink.SUBDUED_MARK),
                group=group,
            )
            previous = current
    _add_text(
        builder,
        f"{group}.title",
        "TURN",
        Box(center.x - 10, center.y + 5, center.x + 10, center.y + 11),
        role=FontRole.INSTRUMENT,
        height=4,
        group=group,
    )


def _add_heading(builder: _SceneBuilder) -> None:
    group = "heading"
    center = GAUGE_CENTERS[group]
    # Heading numerals live on the moving compass card and are not base art.
    for index, angle in enumerate((-45, -25, 0, 25, 45)):
        builder.add(
            f"{group}.lubber.{index}",
            PanelLayer.STATIC_FACE,
            StrokeLine(_polar(center, 14, angle), _polar(center, 17, angle), Ink.MARK),
            group=group,
        )
    builder.add(
        f"{group}.aircraft-horizontal",
        PanelLayer.STATIC_FACE,
        StrokeLine(Point(center.x - 8, center.y), Point(center.x + 8, center.y), Ink.MARK),
        group=group,
    )
    builder.add(
        f"{group}.aircraft-vertical",
        PanelLayer.STATIC_FACE,
        StrokeLine(Point(center.x, center.y - 5), Point(center.x, center.y + 5), Ink.MARK),
        group=group,
    )
    _add_text(
        builder,
        f"{group}.title",
        "HDG",
        Box(center.x - 7, center.y + 8, center.x + 7, center.y + 14),
        role=FontRole.INSTRUMENT,
        height=4,
        group=group,
    )


def _add_vertical_speed(builder: _SceneBuilder) -> None:
    group = "vertical_speed"
    center = GAUGE_CENTERS[group]
    _add_tick_ring(
        builder,
        group,
        start_degrees=-145,
        sweep_degrees=290,
        divisions=20,
        major_every=2,
    )
    for label, angle in (("20", -135), ("10", -68), ("0", 0), ("10", 68), ("20", 135)):
        point = _polar(center, 11, angle)
        _add_text(
            builder,
            f"{group}.label.{angle}",
            label,
            _text_box(point, 8, 5),
            height=4,
            group=group,
        )
    _add_text(
        builder,
        f"{group}.up",
        "UP",
        Box(center.x - 4, center.y - 7, center.x + 4, center.y - 1),
        height=4,
        group=group,
    )
    _add_text(
        builder,
        f"{group}.down",
        "DN",
        Box(center.x - 4, center.y + 2, center.x + 4, center.y + 8),
        height=4,
        group=group,
    )


def _add_obi(builder: _SceneBuilder, group: str, number: int) -> None:
    center = GAUGE_CENTERS[group]
    # The compass/course card, CDI, glideslope bar, flags, and digits are dynamic.
    builder.add(
        f"{group}.inner-ring",
        PanelLayer.STATIC_FACE,
        StrokeCircle(center, 13, Ink.SUBDUED_MARK),
        group=group,
    )
    for index, angle in enumerate((0, 45, 90, 135, 180, 225, 270, 315)):
        point = _polar(center, 13, angle)
        builder.add(
            f"{group}.dot.{index}",
            PanelLayer.STATIC_FACE,
            FillCircle(point, 1, Ink.MARK),
            group=group,
        )
    builder.add(
        f"{group}.aircraft-horizontal",
        PanelLayer.STATIC_FACE,
        StrokeLine(Point(center.x - 6, center.y), Point(center.x + 6, center.y), Ink.MARK),
        group=group,
    )
    builder.add(
        f"{group}.aircraft-vertical",
        PanelLayer.STATIC_FACE,
        StrokeLine(Point(center.x, center.y - 4), Point(center.x, center.y + 6), Ink.MARK),
        group=group,
    )
    builder.add(
        f"{group}.value-window-frame",
        PanelLayer.STATIC_FACE,
        FillRect(Box(center.x - 7, center.y - 12, center.x + 7, center.y - 7), Ink.SUBDUED_MARK),
        group=group,
    )
    builder.add(
        f"{group}.value-window",
        PanelLayer.STATIC_FACE,
        FillRect(Box(center.x - 6, center.y - 11, center.x + 6, center.y - 8), Ink.FACE),
        group=group,
    )
    _add_text(
        builder,
        f"{group}.title",
        f"NAV{number}",
        Box(center.x - 9, center.y + 9, center.x + 9, center.y + 15),
        role=FontRole.INSTRUMENT,
        height=4,
        group=group,
    )


def _add_screw(builder: _SceneBuilder, name: str, center: Point) -> None:
    builder.add(name + ".head", PanelLayer.FOREGROUND, FillCircle(center, 2, Ink.PANEL_SHADOW))
    builder.add(
        name + ".slot",
        PanelLayer.FOREGROUND,
        StrokeLine(Point(center.x - 1, center.y), Point(center.x + 1, center.y), Ink.MARK),
    )


def _add_recess(
    builder: _SceneBuilder,
    name: str,
    outer: Box,
    inner: Box,
    *,
    layer: PanelLayer = PanelLayer.FOREGROUND,
) -> None:
    builder.add(name + ".shadow", layer, FillRect(outer, Ink.PANEL_SHADOW))
    builder.add(name + ".opening", layer, FillRect(inner, Ink.FACE))


def build_panel_program() -> PanelProgram:
    """Build the canonical square-pixel, fixed-art cockpit scene."""

    builder = _SceneBuilder()
    builder.region("panel", Box(0, 0, REFERENCE_WIDTH, REFERENCE_HEIGHT))
    builder.region("instrument_field", Box(0, 0, 208, REFERENCE_HEIGHT))
    builder.region("gps.frame", Box(210, 2, 317, 90))
    builder.region("gps.opening", Box(212, 4, 315, 88))

    builder.add(
        "panel.substrate",
        PanelLayer.SUBSTRATE,
        FillRect(Box(0, 0, REFERENCE_WIDTH, REFERENCE_HEIGHT), Ink.PANEL),
    )
    builder.add(
        "panel.top-rail",
        PanelLayer.SUBSTRATE,
        FillRect(Box(0, 0, 208, 1), Ink.PANEL_LIGHT),
    )
    builder.add(
        "panel.avionics-divider",
        PanelLayer.SUBSTRATE,
        FillRect(Box(208, 0, 210, REFERENCE_HEIGHT), Ink.PANEL_LIGHT),
    )
    builder.add(
        "panel.right-edge",
        PanelLayer.SUBSTRATE,
        FillRect(Box(319, 0, 320, REFERENCE_HEIGHT), Ink.PANEL_SHADOW),
    )

    # One deliberately blank recess replaces the legacy radio stack.
    builder.add(
        "gps.shadow",
        PanelLayer.RECESS,
        FillRect(Box(210, 2, 317, 90), Ink.PANEL_SHADOW),
    )
    builder.add(
        "gps.highlight",
        PanelLayer.RECESS,
        FillRect(Box(211, 3, 316, 89), Ink.PANEL_LIGHT),
    )
    builder.add(
        "gps.opening",
        PanelLayer.RECESS,
        FillRect(Box(212, 4, 315, 88), Ink.GPS_SCREEN),
    )

    for gauge in GAUGE_CENTERS:
        _add_round_well(builder, gauge)
    _add_airspeed(builder)
    _add_attitude(builder)
    _add_altimeter(builder)
    _add_turn(builder)
    _add_heading(builder)
    _add_vertical_speed(builder)
    _add_obi(builder, "nav1", 1)
    _add_obi(builder, "nav2", 2)

    # Fixed adjustment knobs touch the corrected OBI well tangents by design.
    for name, center in (
        ("nav1-knob", Point(158, 40)),
        ("nav2-knob", Point(158, 85)),
        ("altimeter-knob", Point(105, 41)),
    ):
        builder.region(f"control.{name}", _circle_box(center, 4))
        builder.add(
            f"control.{name}.outer",
            PanelLayer.FOREGROUND,
            FillCircle(center, 4, Ink.PANEL_SHADOW),
        )
        builder.add(
            f"control.{name}.inner",
            PanelLayer.FOREGROUND,
            FillCircle(center, 2, Ink.BEZEL),
        )
        builder.add(
            f"control.{name}.slot",
            PanelLayer.FOREGROUND,
            StrokeLine(Point(center.x - 1, center.y), Point(center.x + 1, center.y), Ink.MARK),
        )

    # These three recesses preserve the source panel's control-position wells.
    _add_recess(builder, "control.upper", Box(85, 47, 119, 52), Box(86, 48, 118, 51))
    _add_recess(builder, "control.vertical", Box(100, 54, 105, 82), Box(101, 55, 104, 81))
    _add_recess(builder, "control.lower", Box(86, 82, 118, 89), Box(89, 85, 115, 88))
    builder.region("control.upper", Box(85, 47, 119, 52))
    builder.region("control.vertical", Box(100, 54, 105, 82))
    builder.region("control.lower", Box(86, 82, 118, 89))

    for name, center in (
        ("upper-left", Point(2, 2)),
        ("lower-left", Point(2, 89)),
        ("upper-divider", Point(205, 3)),
        ("lower-divider", Point(205, 88)),
        ("gps-upper-right", Point(317, 3)),
        ("gps-lower-right", Point(317, 88)),
    ):
        _add_screw(builder, f"screw.{name}", center)

    return PanelProgram(
        commands=tuple(builder.commands),
        regions=MappingProxyType(dict(builder.regions)),
        pivots=GAUGE_CENTERS,
    )


__all__ = [
    "ASPECT_HEIGHT",
    "ASPECT_WIDTH",
    "BitmapFontProvider",
    "BitmapGlyph",
    "BitmapTypeface",
    "Box",
    "DrawCommand",
    "FillCircle",
    "FillRect",
    "FillTriangle",
    "FontRole",
    "GAUGE_CENTERS",
    "GlyphRun",
    "Ink",
    "LEGACY_GAUGE_Y_SCALE",
    "PanelLayer",
    "PanelProgram",
    "Point",
    "REFERENCE_HEIGHT",
    "REFERENCE_WIDTH",
    "SIMPLE_3X5_TYPEFACE",
    "SimpleBitmapFontProvider",
    "StrokeCircle",
    "StrokeLine",
    "build_panel_program",
    "validate_panel_dimensions",
]
