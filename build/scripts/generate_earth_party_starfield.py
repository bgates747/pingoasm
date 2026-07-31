#!/usr/bin/env python3
"""Generate Earth Party's six-sector, real-star Pingo mesh and color atlas."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "apps" / "earth-party-local"
DEFAULT_CATALOG = APP_ROOT / "assets" / "stars.tsv"
DEFAULT_INCLUDE = APP_ROOT / "src" / "starfield.inc"
DEFAULT_TEXTURE = APP_ROOT / "tgt" / "stars.rgba2"
DEFAULT_PROFILE = APP_ROOT / "profile.json"

Q15_ONE = 32767
ANGLE_UNITS_PER_TURN = 32768
CANONICAL_INNER_RATIO = 0.3819660112501051
ATLAS_CELL_WIDTH = 4
ATLAS_HEIGHT = 2
EXPECTED_STAR_COUNT = 128
SECTOR_NAMES = ("px", "nx", "py", "ny", "pz", "nz")
REQUIRED_ANCHORS = {
    "Sirius",
    "Betelgeuse",
    "Rigel",
    "Polaris",
    "Vega",
    "Antares",
    "Acrux",
}


@dataclass(frozen=True)
class PaletteEntry:
    name: str
    max_bv: float
    rgba2222: int
    display_rgb: str


# Colors are deliberately more saturated than human naked-eye perception.
# RGBA2222 is packed AABBGGRR.
PALETTE = (
    PaletteEntry("hot_blue", 0.10, 0xF8, "#00AAFF"),
    PaletteEntry("blue_white", 0.45, 0xFE, "#AAFFFF"),
    PaletteEntry("white", 0.85, 0xFF, "#FFFFFF"),
    PaletteEntry("yellow", 1.20, 0xDF, "#FFFF55"),
    PaletteEntry("orange", 1.60, 0xCB, "#FFAA00"),
    PaletteEntry("red", math.inf, 0xC3, "#FF0000"),
)


@dataclass(frozen=True)
class CatalogStar:
    display_name: str
    hr: str
    bayer: str
    constellation: str
    ra_degrees: float
    dec_degrees: float
    vmag: float
    bv: float
    spectral_type: str
    selection: str


@dataclass(frozen=True)
class GeneratedStar:
    source: CatalogStar
    sector: str
    palette_index: int
    radius_pixels: float
    inward: tuple[float, float, float]
    vertices: tuple[tuple[int, int, int], ...]
    triangles: tuple[tuple[int, int, int], ...]


@dataclass
class Sector:
    name: str
    stars: list[GeneratedStar] = field(default_factory=list)


@dataclass(frozen=True)
class GenerationSummary:
    star_count: int
    triangle_count: int
    vertex_count: int
    sector_star_counts: dict[str, int]
    texture_size: int


def read_catalog(path: Path) -> list[CatalogStar]:
    with path.open("r", encoding="utf-8", newline="") as source:
        rows = csv.DictReader(
            (line for line in source if not line.startswith("#")),
            delimiter="\t",
        )
        required = {
            "display_name",
            "hr",
            "bayer",
            "constellation",
            "ra_degrees",
            "dec_degrees",
            "vmag",
            "bv",
            "spectral_type",
            "selection",
        }
        if rows.fieldnames is None or set(rows.fieldnames) != required:
            raise ValueError("unexpected Earth Party star catalog columns")
        stars = [
            CatalogStar(
                display_name=row["display_name"],
                hr=row["hr"],
                bayer=row["bayer"],
                constellation=row["constellation"],
                ra_degrees=float(row["ra_degrees"]),
                dec_degrees=float(row["dec_degrees"]),
                vmag=float(row["vmag"]),
                bv=float(row["bv"]),
                spectral_type=row["spectral_type"],
                selection=row["selection"],
            )
            for row in rows
        ]

    if len(stars) != EXPECTED_STAR_COUNT:
        raise ValueError(
            f"expected {EXPECTED_STAR_COUNT} selected stars, found {len(stars)}"
        )
    names = {star.display_name for star in stars}
    missing = sorted(REQUIRED_ANCHORS - names)
    if missing:
        raise ValueError(f"missing required star anchors: {', '.join(missing)}")
    if len({star.hr for star in stars}) != len(stars):
        raise ValueError("duplicate HR identity in selected star catalog")
    for star in stars:
        if not (0.0 <= star.ra_degrees < 360.0):
            raise ValueError(f"{star.display_name}: RA outside [0,360)")
        if not (-90.0 <= star.dec_degrees <= 90.0):
            raise ValueError(f"{star.display_name}: declination outside [-90,90]")
        if not all(
            math.isfinite(value)
            for value in (star.ra_degrees, star.dec_degrees, star.vmag, star.bv)
        ):
            raise ValueError(f"{star.display_name}: non-finite catalog value")
    return stars


def matrix_multiply_vector(
    matrix: tuple[tuple[float, float, float], ...],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(
        sum(row[column] * vector[column] for column in range(3))
        for row in matrix
    )


def earth_tilt_matrix(
    tilt_x_units: int,
    tilt_z_units: int,
) -> tuple[tuple[float, float, float], ...]:
    x_angle = tilt_x_units * 2.0 * math.pi / ANGLE_UNITS_PER_TURN
    z_angle = tilt_z_units * 2.0 * math.pi / ANGLE_UNITS_PER_TURN
    cx, sx = math.cos(x_angle), math.sin(x_angle)
    cz, sz = math.cos(z_angle), math.sin(z_angle)
    # Rz(z) * Rx(x), matching earth_base_orientation in earth-party.asm.
    return (
        (cz, -sz * cx, sz * sx),
        (sz, cz * cx, -cz * sx),
        (0.0, sx, cx),
    )


def add(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(a + b for a, b in zip(left, right))


def scale(
    vector: tuple[float, float, float],
    factor: float,
) -> tuple[float, float, float]:
    return tuple(component * factor for component in vector)


def cross(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
) -> tuple[int, int, int]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def subtract_int(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
) -> tuple[int, int, int]:
    return tuple(a - b for a, b in zip(left, right))


def dot_int_float(
    left: tuple[int, int, int],
    right: tuple[float, float, float],
) -> float:
    return sum(a * b for a, b in zip(left, right))


def to_q15(vector: tuple[float, float, float]) -> tuple[int, int, int]:
    converted = tuple(int(round(component * Q15_ONE)) for component in vector)
    if any(component < -Q15_ONE or component > Q15_ONE for component in converted):
        raise ValueError(f"starfield coordinate outside signed Q15: {converted}")
    return converted


def magnitude_radius_pixels(
    magnitude: float,
    minimum: float,
    maximum: float,
) -> float:
    radius = maximum * 10.0 ** (-0.10 * (magnitude + 1.46))
    return max(minimum, min(maximum, radius))


def palette_index_for_bv(bv: float) -> int:
    for index, entry in enumerate(PALETTE):
        if bv <= entry.max_bv:
            return index
    raise AssertionError("infinite final palette bound was not selected")


def sector_for_direction(direction: tuple[float, float, float]) -> str:
    axis = max(range(3), key=lambda index: abs(direction[index]))
    prefix = "p" if direction[axis] >= 0.0 else "n"
    return prefix + "xyz"[axis]


def generate_star(
    source: CatalogStar,
    *,
    shell_radius: float,
    ra_center_hours: float,
    fov_radians: float,
    viewport_height: int,
    minimum_radius_pixels: float,
    maximum_radius_pixels: float,
    tilt: tuple[tuple[float, float, float], ...],
) -> GeneratedStar:
    angle = math.radians(
        source.ra_degrees - ra_center_hours * 15.0
    )
    declination = math.radians(source.dec_degrees)
    cos_dec = math.cos(declination)
    sin_dec = math.sin(declination)

    # Looking outward from inside the sphere: celestial east appears left when
    # north is up. u is screen-right/celestial-west, and u x v = -q.
    q = (-cos_dec * math.sin(angle), sin_dec, -cos_dec * math.cos(angle))
    u = (math.cos(angle), 0.0, -math.sin(angle))
    v = (
        sin_dec * math.sin(angle),
        cos_dec,
        sin_dec * math.cos(angle),
    )
    q = matrix_multiply_vector(tilt, q)
    u = matrix_multiply_vector(tilt, u)
    v = matrix_multiply_vector(tilt, v)
    inward = scale(q, -1.0)
    center = scale(q, shell_radius)

    radius_pixels = magnitude_radius_pixels(
        source.vmag,
        minimum_radius_pixels,
        maximum_radius_pixels,
    )
    outer_radius = (
        shell_radius
        * radius_pixels
        * math.tan(fov_radians / 2.0)
        / (viewport_height / 2.0)
    )
    inner_radius = outer_radius * CANONICAL_INNER_RATIO

    inner_vertices: list[tuple[float, float, float]] = []
    tip_vertices: list[tuple[float, float, float]] = []
    for index in range(5):
        tip_angle = math.pi / 2.0 + index * 2.0 * math.pi / 5.0
        inner_angle = tip_angle + math.pi / 5.0
        tip_vertices.append(
            add(
                center,
                add(
                    scale(u, outer_radius * math.cos(tip_angle)),
                    scale(v, outer_radius * math.sin(tip_angle)),
                ),
            )
        )
        inner_vertices.append(
            add(
                center,
                add(
                    scale(u, inner_radius * math.cos(inner_angle)),
                    scale(v, inner_radius * math.sin(inner_angle)),
                ),
            )
        )

    vertices = tuple(
        to_q15(vertex)
        for vertex in (center, *inner_vertices, *tip_vertices)
    )
    triangles = tuple(
        [(0, 1 + index, 1 + ((index + 1) % 5)) for index in range(5)]
        + [
            (1 + ((index - 1) % 5), 6 + index, 1 + index)
            for index in range(5)
        ]
    )
    for triangle in triangles:
        a, b, c = (vertices[index] for index in triangle)
        normal = cross(subtract_int(b, a), subtract_int(c, a))
        if normal == (0, 0, 0):
            raise ValueError(f"{source.display_name}: degenerate Q15 triangle")
        if dot_int_float(normal, inward) <= 0.0:
            raise ValueError(f"{source.display_name}: non-inward triangle winding")

    sector = sector_for_direction(q)
    sector_axis = "xyz".index(sector[1])
    sector_sign = 1 if sector[0] == "p" else -1
    if any(
        sector_sign * vertex[sector_axis] <= 0
        for vertex in vertices
    ):
        raise ValueError(
            f"{source.display_name}: glyph crosses its {sector} sector plane"
        )

    return GeneratedStar(
        source=source,
        sector=sector,
        palette_index=palette_index_for_bv(source.bv),
        radius_pixels=radius_pixels,
        inward=inward,
        vertices=vertices,
        triangles=triangles,
    )


def flatten_sector(
    sector: Sector,
) -> tuple[
    list[tuple[int, int, int]],
    list[tuple[int, int, int]],
    list[int],
]:
    vertices: list[tuple[int, int, int]] = []
    triangles: list[tuple[int, int, int]] = []
    uv_indices: list[int] = []
    for star in sector.stars:
        base = len(vertices)
        vertices.extend(star.vertices)
        for triangle in star.triangles:
            triangles.append(tuple(base + index for index in triangle))
            uv_indices.extend((star.palette_index,) * 3)
    return vertices, triangles, uv_indices


def atlas_bytes() -> bytes:
    row = b"".join(
        bytes((entry.rgba2222,)) * ATLAS_CELL_WIDTH
        for entry in PALETTE
    )
    return row * ATLAS_HEIGHT


def uv_words() -> list[tuple[int, int]]:
    width = len(PALETTE) * ATLAS_CELL_WIDTH
    result = []
    for index in range(len(PALETTE)):
        center_texel = index * ATLAS_CELL_WIDTH + 2
        u = round(center_texel * 65535 / (width - 1))
        result.append((u, 32768))
    return result


def write_words(
    output: list[str],
    label: str,
    values: Iterable[tuple[int, ...]],
) -> None:
    output.append(f"{label}:")
    for value in values:
        output.append("    dw " + ",".join(str(component) for component in value))
    output.append("")


def render_include(
    sectors: dict[str, Sector],
    *,
    catalog_path: Path,
    texture_filename: str,
    object_scale: int,
) -> str:
    all_stars = [star for sector in sectors.values() for star in sector.stars]
    lines = [
        "; =============================================================================",
        "; AUTO-GENERATED FILE - DO NOT EDIT",
        "; Generated by: build/scripts/generate_earth_party_starfield.py",
        f"; Generated from: {catalog_path.as_posix()}",
        "; Edit the generator or its authoritative inputs instead.",
        "; =============================================================================",
        "",
        f"starfield_star_count: equ {len(all_stars)}",
        f"starfield_triangle_count: equ {len(all_stars) * 10}",
        f"starfield_object_scale: equ {object_scale}",
        f"starfield_texture_width: equ {len(PALETTE) * ATLAS_CELL_WIDTH}",
        f"starfield_texture_height: equ {ATLAS_HEIGHT}",
        f"starfield_texture_size: equ {len(atlas_bytes())}",
        f"starfield_uvs_n: equ {len(PALETTE)}",
        "",
        "; One constant UV per exaggerated B-V color class.",
    ]
    for index, entry in enumerate(PALETTE):
        lines.append(
            f"; {index}: {entry.name} {entry.display_rgb} RGBA2222=0x{entry.rgba2222:02X}"
        )
    lines.append("")
    write_words(lines, "starfield_uvs", uv_words())

    for sector_name in SECTOR_NAMES:
        sector = sectors[sector_name]
        vertices, triangles, uv_indices = flatten_sector(sector)
        lines.extend(
            (
                "; -----------------------------------------------------------------------------",
                f"; {sector_name.upper()} sector: {len(sector.stars)} stars",
                "; -----------------------------------------------------------------------------",
                f"starfield_{sector_name}_stars_n: equ {len(sector.stars)}",
                f"starfield_{sector_name}_vertices_n: equ {len(vertices)}",
                f"starfield_{sector_name}_indices_n: equ {len(triangles) * 3}",
                "",
                f"starfield_{sector_name}_vertices:",
            )
        )
        vertex_offset = 0
        for star in sector.stars:
            lines.append(
                f"    ; {star.source.display_name} | HR {star.source.hr} | "
                f"{star.source.bayer} {star.source.constellation} | "
                f"V={star.source.vmag:.3f} B-V={star.source.bv:.3f} | "
                f"{PALETTE[star.palette_index].name} | "
                f"r={star.radius_pixels:.2f}px"
            )
            for vertex in star.vertices:
                lines.append(
                    "    dw " + ",".join(str(component) for component in vertex)
                )
            vertex_offset += len(star.vertices)
        lines.append("")
        write_words(
            lines,
            f"starfield_{sector_name}_vertex_indices",
            triangles,
        )
        lines.append(f"starfield_{sector_name}_uv_indices:")
        for offset in range(0, len(uv_indices), 15):
            lines.append(
                "    dw "
                + ",".join(str(value) for value in uv_indices[offset : offset + 15])
            )
        lines.append("")

    lines.append(f'starfield_texture: db "{texture_filename}",0')
    lines.append("")
    return "\n".join(lines)


def validate_configuration(configuration: dict[str, Any]) -> None:
    required = {
        "catalog_source",
        "texture_filename",
        "ra_center_hours",
        "shell_radius",
        "object_scale",
        "fov_radians",
        "viewport_height",
        "minimum_radius_pixels",
        "maximum_radius_pixels",
        "earth_tilt_x_units",
        "earth_tilt_z_units",
    }
    missing = sorted(required - configuration.keys())
    if missing:
        raise ValueError(f"starfield configuration missing: {', '.join(missing)}")
    if Path(str(configuration["texture_filename"])).name != configuration["texture_filename"]:
        raise ValueError("starfield texture filename must be a basename")
    if not (0.0 < float(configuration["shell_radius"]) < 0.98):
        raise ValueError("starfield shell radius must be between 0 and 0.98")
    if not (0 < int(configuration["object_scale"]) <= 65535):
        raise ValueError("starfield object scale must fit one unsigned word")
    if int(configuration["viewport_height"]) <= 0:
        raise ValueError("starfield viewport height must be positive")
    minimum = float(configuration["minimum_radius_pixels"])
    maximum = float(configuration["maximum_radius_pixels"])
    if not (0.0 < minimum <= maximum):
        raise ValueError("invalid starfield pixel-radius limits")


def generate(
    catalog_path: Path,
    include_path: Path,
    texture_path: Path,
    configuration: dict[str, Any],
    *,
    provenance_path: str | None = None,
) -> GenerationSummary:
    validate_configuration(configuration)
    catalog = read_catalog(catalog_path)
    tilt = earth_tilt_matrix(
        int(configuration["earth_tilt_x_units"]),
        int(configuration["earth_tilt_z_units"]),
    )
    sectors = {name: Sector(name) for name in SECTOR_NAMES}
    for source in catalog:
        star = generate_star(
            source,
            shell_radius=float(configuration["shell_radius"]),
            ra_center_hours=float(configuration["ra_center_hours"]),
            fov_radians=float(configuration["fov_radians"]),
            viewport_height=int(configuration["viewport_height"]),
            minimum_radius_pixels=float(configuration["minimum_radius_pixels"]),
            maximum_radius_pixels=float(configuration["maximum_radius_pixels"]),
            tilt=tilt,
        )
        sectors[star.sector].stars.append(star)

    for sector in sectors.values():
        sector.stars.sort(
            key=lambda star: (
                star.source.ra_degrees,
                star.source.dec_degrees,
                star.source.hr,
            )
        )
        if not sector.stars:
            raise ValueError(f"empty starfield sector: {sector.name}")

    provenance = provenance_path or catalog_path.as_posix()
    include = render_include(
        sectors,
        catalog_path=Path(provenance),
        texture_filename=str(configuration["texture_filename"]),
        object_scale=int(configuration["object_scale"]),
    )
    include_path.parent.mkdir(parents=True, exist_ok=True)
    texture_path.parent.mkdir(parents=True, exist_ok=True)
    include_path.write_text(include, encoding="utf-8")
    texture_path.write_bytes(atlas_bytes())

    stars = [star for sector in sectors.values() for star in sector.stars]
    return GenerationSummary(
        star_count=len(stars),
        triangle_count=len(stars) * 10,
        vertex_count=len(stars) * 11,
        sector_star_counts={
            name: len(sectors[name].stars) for name in SECTOR_NAMES
        },
        texture_size=len(atlas_bytes()),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--include", type=Path, default=DEFAULT_INCLUDE)
    parser.add_argument("--texture", type=Path, default=DEFAULT_TEXTURE)
    arguments = parser.parse_args()

    profile = json.loads(arguments.profile.read_text(encoding="utf-8"))
    configuration = profile["starfield"]
    catalog = arguments.catalog or (
        PROJECT_ROOT / str(configuration["catalog_source"])
    )
    summary = generate(
        catalog,
        arguments.include,
        arguments.texture,
        configuration,
        provenance_path=str(configuration["catalog_source"]),
    )
    print(
        f"Generated {summary.star_count} stars, "
        f"{summary.triangle_count} triangles, sectors "
        + ", ".join(
            f"{name}={summary.sector_star_counts[name]}"
            for name in SECTOR_NAMES
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
