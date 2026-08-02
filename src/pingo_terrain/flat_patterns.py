"""Deterministic offline compiler for 4x4 terrain dither patterns."""

from __future__ import annotations

from dataclasses import dataclass
import colorsys
import hashlib
import heapq
import json
from pathlib import Path
from typing import Iterable, Sequence

from .materials import RGB8, TerrainMaterial


PATTERN_WIDTH = 4
PATTERN_HEIGHT = 4
PATTERN_PIXELS = PATTERN_WIDTH * PATTERN_HEIGHT
ILLUMINATION_BANDS = 16

# Standard 4x4 Bayer ranks.  A mixture's brightest native color occupies its
# lowest ranks, followed by successively darker colors.
BAYER_4X4: tuple[tuple[int, ...], ...] = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)

SCORE_WEIGHTS = {
    "mean_rgb": 0.30,
    "hue": 0.30,
    "saturation": 0.20,
    "value": 0.50,
    "native_pixel_spread": 0.03,
    "native_hue": 0.04,
    "native_excess_saturation": 0.04,
}

# A third native color must reduce the complete score by both amounts.  The
# absolute floor prevents a numerically impressive percentage improvement on
# an already imperceptible error from increasing pattern complexity.
THREE_COLOR_RELATIVE_IMPROVEMENT = 0.40
THREE_COLOR_ABSOLUTE_IMPROVEMENT = 0.0005
THREE_COLOR_POOL_SIZE = 12


@dataclass(frozen=True, slots=True)
class NativeColor:
    packed: int
    rgb: RGB8
    hsv: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class TargetColor:
    rgb: tuple[float, float, float]
    hue: float
    saturation: float
    value: float


@dataclass(frozen=True, slots=True)
class Mix:
    """A color-count mixture totaling one 4x4 pattern."""

    colors: tuple[NativeColor, ...]
    counts: tuple[int, ...]
    mean_rgb: tuple[float, float, float]
    mean_hsv: tuple[float, float, float]
    spread: float

    @property
    def color_count(self) -> int:
        return len(self.colors)

    @property
    def tie_key(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        return (
            tuple(color.packed for color in self.colors),
            self.counts,
        )


@dataclass(frozen=True, slots=True)
class SelectedPattern:
    material_id: int
    illumination_band: int
    illumination: float
    target: TargetColor
    mix: Mix
    score: float
    best_one_or_two_color_score: float
    pattern: bytes
    used_three_colors: bool


@dataclass(frozen=True, slots=True)
class CompiledPatterns:
    patterns: bytes
    lookup: bytes
    metadata: dict[str, object]

    @property
    def pattern_count(self) -> int:
        return len(self.patterns) // PATTERN_PIXELS

    def metadata_bytes(self) -> bytes:
        return (
            json.dumps(self.metadata, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")


def pack_opaque_rgba2222(rgb_levels: tuple[int, int, int]) -> int:
    """Pack 2-bit RGB levels into Agon's opaque AABBGGRR byte order."""

    red, green, blue = rgb_levels
    if any(level not in range(4) for level in rgb_levels):
        raise ValueError("RGBA2222 channel levels must be in 0..3")
    return 0xC0 | (blue << 4) | (green << 2) | red


def unpack_opaque_rgba2222(packed: int) -> RGB8:
    """Decode one opaque AABBGGRR byte to its RGB8 display levels."""

    if packed not in range(256) or packed & 0xC0 != 0xC0:
        raise ValueError("pixel is not an opaque RGBA2222 byte")
    return (
        (packed & 0x03) * 85,
        ((packed >> 2) & 0x03) * 85,
        ((packed >> 4) & 0x03) * 85,
    )


OPAQUE_RGBA2222_PALETTE: tuple[NativeColor, ...] = tuple(
    NativeColor(
        packed,
        unpack_opaque_rgba2222(packed),
        colorsys.rgb_to_hsv(
            *(channel / 255.0 for channel in unpack_opaque_rgba2222(packed))
        ),
    )
    for packed in range(0xC0, 0x100)
)


def target_for_band(
    material: TerrainMaterial,
    band: int,
    band_count: int = ILLUMINATION_BANDS,
) -> TargetColor:
    """Return a constant-hue/saturation target at one illumination band."""

    if band_count < 2:
        raise ValueError("at least two illumination bands are required")
    if band not in range(band_count):
        raise ValueError("illumination band is out of range")
    source = tuple(channel / 255.0 for channel in material.rgb)
    hue, saturation, base_value = colorsys.rgb_to_hsv(*source)
    illumination = band / (band_count - 1)
    value = base_value * illumination
    return TargetColor(
        rgb=colorsys.hsv_to_rgb(hue, saturation, value),
        hue=hue,
        saturation=saturation,
        value=value,
    )


def _make_mix(
    color_counts: Iterable[tuple[NativeColor, int]],
) -> Mix:
    entries = tuple(
        sorted(
            ((color, count) for color, count in color_counts if count),
            key=lambda item: item[0].packed,
        )
    )
    if not entries or sum(count for _, count in entries) != PATTERN_PIXELS:
        raise ValueError("a mix must contain exactly sixteen pixels")
    if any(count < 1 for _, count in entries):
        raise ValueError("mix counts must be positive")
    colors = tuple(color for color, _ in entries)
    counts = tuple(count for _, count in entries)
    mean_rgb8 = tuple(
        sum(color.rgb[channel] * count for color, count in entries)
        / PATTERN_PIXELS
        for channel in range(3)
    )
    mean_rgb = tuple(value / 255.0 for value in mean_rgb8)
    spread = sum(
        count
        * sum(
            ((color.rgb[channel] / 255.0) - mean_rgb[channel]) ** 2
            for channel in range(3)
        )
        / 3.0
        for color, count in entries
    ) / PATTERN_PIXELS
    return Mix(
        colors=colors,
        counts=counts,
        mean_rgb=mean_rgb,
        mean_hsv=colorsys.rgb_to_hsv(*mean_rgb),
        spread=spread,
    )


def pattern_bytes(mix: Mix) -> bytes:
    """Lay a mixture out once using the fixed Bayer rank ordering."""

    entries = sorted(
        zip(mix.colors, mix.counts, strict=True),
        key=lambda item: (
            max(item[0].rgb),
            0.2126 * item[0].rgb[0]
            + 0.7152 * item[0].rgb[1]
            + 0.0722 * item[0].rgb[2],
            item[0].packed,
        ),
        reverse=True,
    )
    rank_pixels: list[int] = []
    for color, count in entries:
        rank_pixels.extend([color.packed] * count)
    return bytes(rank_pixels[rank] for row in BAYER_4X4 for rank in row)


def score_mix(target: TargetColor, mix: Mix) -> float:
    """Score the mean HSV/RGB result and native-pixel color dispersion."""

    rgb_error = sum(
        (actual - desired) ** 2
        for actual, desired in zip(mix.mean_rgb, target.rgb, strict=True)
    ) / 3.0
    hue_delta = abs(mix.mean_hsv[0] - target.hue)
    hue_delta = min(hue_delta, 1.0 - hue_delta) * 2.0
    # Hue and saturation cease to be visually meaningful at black.  Scaling
    # their error by target value preserves the intended HSV trajectory while
    # allowing the zero band to resolve exactly to opaque black.
    hue_error = (hue_delta * target.saturation * target.value) ** 2
    saturation_error = (
        (mix.mean_hsv[1] - target.saturation) * target.value
    ) ** 2
    value_error = (mix.mean_hsv[2] - target.value) ** 2
    native_hue_error = 0.0
    native_excess_saturation_error = 0.0
    for color, count in zip(mix.colors, mix.counts, strict=True):
        hue, saturation, value = color.hsv
        hue_delta = abs(hue - target.hue)
        hue_delta = min(hue_delta, 1.0 - hue_delta) * 2.0
        share = count / PATTERN_PIXELS
        native_hue_error += (
            share
            * hue_delta**2
            * saturation**2
            * value**2
            * target.saturation
            * target.value
        )
        native_excess_saturation_error += (
            share
            * max(0.0, saturation - target.saturation) ** 2
            * value**2
            * target.value
        )
    return (
        SCORE_WEIGHTS["mean_rgb"] * rgb_error
        + SCORE_WEIGHTS["hue"] * hue_error
        + SCORE_WEIGHTS["saturation"] * saturation_error
        + SCORE_WEIGHTS["value"] * value_error
        + SCORE_WEIGHTS["native_pixel_spread"] * mix.spread
        + SCORE_WEIGHTS["native_hue"] * native_hue_error
        + SCORE_WEIGHTS["native_excess_saturation"]
        * native_excess_saturation_error
    )


def _candidate_key(target: TargetColor, mix: Mix) -> tuple[object, ...]:
    return (score_mix(target, mix), mix.color_count, mix.tie_key)


def _one_and_two_color_mixes() -> tuple[Mix, ...]:
    mixes = [
        _make_mix(((color, PATTERN_PIXELS),))
        for color in OPAQUE_RGBA2222_PALETTE
    ]
    for first_index, first in enumerate(OPAQUE_RGBA2222_PALETTE):
        for second in OPAQUE_RGBA2222_PALETTE[first_index + 1 :]:
            for first_count in range(1, PATTERN_PIXELS):
                mixes.append(
                    _make_mix(
                        (
                            (first, first_count),
                            (second, PATTERN_PIXELS - first_count),
                        )
                    )
                )
    return tuple(mixes)


ONE_AND_TWO_COLOR_MIXES = _one_and_two_color_mixes()


def _three_color_candidates(target: TargetColor, ranked: Sequence[Mix]) -> Iterable[Mix]:
    # Colors participating in the strongest complete one/two-color solutions
    # are much better triple candidates than merely taking the closest solid
    # pixels: complementary endpoints can be individually distant from the
    # desired mean.  Rank first by the complete objective, then cap the pool.
    color_rank: dict[int, tuple[int, float]] = {}
    for rank, mix in enumerate(ranked[:32]):
        mix_score = score_mix(target, mix)
        for color in mix.colors:
            current = color_rank.get(color.packed)
            candidate = (rank, mix_score)
            if current is None or candidate < current:
                color_rank[color.packed] = candidate
    pool = sorted(
        (color for color in OPAQUE_RGBA2222_PALETTE if color.packed in color_rank),
        key=lambda color: (color_rank[color.packed], color.packed),
    )[:THREE_COLOR_POOL_SIZE]
    for first_index, first in enumerate(pool):
        for second_index in range(first_index + 1, len(pool)):
            second = pool[second_index]
            for third in pool[second_index + 1 :]:
                for first_count in range(1, PATTERN_PIXELS - 1):
                    for second_count in range(
                        1, PATTERN_PIXELS - first_count
                    ):
                        third_count = (
                            PATTERN_PIXELS - first_count - second_count
                        )
                        yield _make_mix(
                            (
                                (first, first_count),
                                (second, second_count),
                                (third, third_count),
                            )
                        )


def select_pattern(
    material: TerrainMaterial,
    band: int,
    band_count: int = ILLUMINATION_BANDS,
) -> SelectedPattern:
    """Select the deterministic best 1/2-color mix, conditionally testing 3."""

    target = target_for_band(material, band, band_count)
    ranked = heapq.nsmallest(
        32,
        ONE_AND_TWO_COLOR_MIXES,
        key=lambda mix: _candidate_key(target, mix),
    )
    best_two = ranked[0]
    best_two_score = score_mix(target, best_two)
    best_three = min(
        _three_color_candidates(target, ranked),
        key=lambda mix: _candidate_key(target, mix),
        default=None,
    )
    selected = best_two
    selected_score = best_two_score
    used_three = False
    if best_three is not None:
        three_score = score_mix(target, best_three)
        absolute_improvement = best_two_score - three_score
        relative_threshold = (
            best_two_score * THREE_COLOR_RELATIVE_IMPROVEMENT
        )
        if (
            absolute_improvement >= THREE_COLOR_ABSOLUTE_IMPROVEMENT
            and absolute_improvement >= relative_threshold
        ):
            selected = best_three
            selected_score = three_score
            used_three = True
    return SelectedPattern(
        material_id=material.material_id,
        illumination_band=band,
        illumination=band / (band_count - 1),
        target=target,
        mix=selected,
        score=selected_score,
        best_one_or_two_color_score=best_two_score,
        pattern=pattern_bytes(selected),
        used_three_colors=used_three,
    )


def _rounded(values: Iterable[float]) -> list[float]:
    return [round(value, 9) for value in values]


def compile_patterns(
    materials: Sequence[TerrainMaterial],
    band_count: int = ILLUMINATION_BANDS,
) -> CompiledPatterns:
    """Compile and deduplicate a material-major pattern resource."""

    if not materials:
        raise ValueError("at least one material is required")
    if len(materials) > 255 or band_count not in range(2, 256):
        raise ValueError("material and band counts must fit one byte")
    if tuple(material.material_id for material in materials) != tuple(
        range(len(materials))
    ):
        raise ValueError("material IDs must be contiguous and ordered from zero")

    selected = [
        select_pattern(material, band, band_count)
        for material in materials
        for band in range(band_count)
    ]
    unique: list[bytes] = []
    pattern_ids: dict[bytes, int] = {}
    lookup = bytearray()
    entries: list[dict[str, object]] = []
    for item in selected:
        pattern_id = pattern_ids.get(item.pattern)
        if pattern_id is None:
            pattern_id = len(unique)
            if pattern_id > 255:
                raise ValueError("deduplicated pattern IDs do not fit one byte")
            pattern_ids[item.pattern] = pattern_id
            unique.append(item.pattern)
        lookup.append(pattern_id)
        entries.append(
            {
                "illumination_band": item.illumination_band,
                "material_id": item.material_id,
                "mean_hsv": _rounded(item.mix.mean_hsv),
                "mean_rgb8": _rounded(
                    value * 255.0 for value in item.mix.mean_rgb
                ),
                "native_color_count": item.mix.color_count,
                "native_colors": [
                    {
                        "count": count,
                        "packed": color.packed,
                        "rgb": list(color.rgb),
                    }
                    for color, count in zip(
                        item.mix.colors, item.mix.counts, strict=True
                    )
                ],
                "pattern_id": pattern_id,
                "score": round(item.score, 12),
                "best_one_or_two_color_score": round(
                    item.best_one_or_two_color_score, 12
                ),
                "three_color_absolute_improvement": round(
                    item.best_one_or_two_color_score - item.score, 12
                ),
                "target_hsv": _rounded(
                    (
                        item.target.hue,
                        item.target.saturation,
                        item.target.value,
                    )
                ),
                "target_rgb8": _rounded(
                    value * 255.0 for value in item.target.rgb
                ),
                "used_three_colors": item.used_three_colors,
            }
        )

    pattern_data = b"".join(unique)
    lookup_data = bytes(lookup)
    metadata: dict[str, object] = {
        "schema": "pingo-terrain-flat-patterns-v1",
        "pixel_format": "opaque RGBA2222, AABBGGRR",
        "pattern_dimensions": [PATTERN_WIDTH, PATTERN_HEIGHT],
        "material_count": len(materials),
        "illumination_band_count": band_count,
        "illumination_bands": [
            {
                "band": band,
                "factor_denominator": band_count - 1,
                "factor_numerator": band,
            }
            for band in range(band_count)
        ],
        "lookup_order": "material-major, illumination-band-minor",
        "lookup_entry_bytes": 1,
        "pattern_id_bytes": 1,
        "unique_pattern_count": len(unique),
        "materials": [
            {
                "material_id": material.material_id,
                "name": material.name,
                "nlcd_category": material.nlcd_category,
                "rgb": list(material.rgb),
            }
            for material in materials
        ],
        "optimizer": {
            "averaging_space": "RGB8 display-code values",
            "bayer_ranks": [list(row) for row in BAYER_4X4],
            "score_weights": SCORE_WEIGHTS,
            "target_trajectory": "HSV: fixed authored hue/saturation, scaled value",
            "three_color_absolute_improvement": THREE_COLOR_ABSOLUTE_IMPROVEMENT,
            "three_color_pool_size": THREE_COLOR_POOL_SIZE,
            "three_color_relative_improvement": THREE_COLOR_RELATIVE_IMPROVEMENT,
        },
        "entries": entries,
        "resources": {
            "lookup": {
                "bytes": len(lookup_data),
                "sha256": hashlib.sha256(lookup_data).hexdigest(),
            },
            "patterns": {
                "bytes": len(pattern_data),
                "sha256": hashlib.sha256(pattern_data).hexdigest(),
            },
        },
    }
    return CompiledPatterns(pattern_data, lookup_data, metadata)


def write_compiled_patterns(
    compiled: CompiledPatterns,
    output_directory: Path,
    stem: str = "berkeley-terrain-patterns",
) -> tuple[Path, Path, Path]:
    """Write raw VDP resources and deterministic descriptive metadata."""

    output_directory.mkdir(parents=True, exist_ok=True)
    patterns_path = output_directory / f"{stem}.rgba2"
    lookup_path = output_directory / f"{stem}.lookup.bin"
    metadata_path = output_directory / f"{stem}.json"
    patterns_path.write_bytes(compiled.patterns)
    lookup_path.write_bytes(compiled.lookup)
    metadata_path.write_bytes(compiled.metadata_bytes())
    return patterns_path, lookup_path, metadata_path
