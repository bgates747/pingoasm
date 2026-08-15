#!/usr/bin/env python3
"""Generate the scene-lit flat-pattern triangular Berkeley fixture."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
PINGOASM = Path("/home/smith/Agon/mystuff/pingoasm")
PINGO_SCRIPTS = PINGOASM / "build/scripts"
APP = ROOT / "fixtures/berkeley-flight-triangular-dither"
SOURCE = APP / "src"
TARGET = APP / "tgt"
PROFILE = ROOT / "profiles/berkeley-flight-triangular-dither.json"
DEM_PATH = ROOT / "data/downloads/berkeley-ca/usgs-3dep-10m-utm10n.tif"
NLCD_PATH = ROOT / "data/downloads/berkeley-ca/usgs-annual-nlcd-2025-epsg5070.tif"
PATTERN_BUILD = ROOT / "build/patterns"
PATTERN_SOURCE = PATTERN_BUILD / "berkeley-terrain-patterns.rgba2"
LOOKUP_SOURCE = PATTERN_BUILD / "berkeley-terrain-patterns.lookup.bin"
METADATA_SOURCE = PATTERN_BUILD / "berkeley-terrain-patterns.json"
PATTERN_NAME = "terrain-patterns.rgba2"
LOOKUP_NAME = "terrain-pattern-lookup.bin"
METADATA_NAME = "terrain-patterns.json"
SELECTOR_NAME = "terrain-material-ids.rgba2"
SELECTOR_WIDTH = 4
SELECTOR_HEIGHT = 4
EXPECTED_PATTERN_COUNT = 126
EXPECTED_MATERIAL_COUNT = 15
EXPECTED_BAND_COUNT = 16

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(PINGO_SCRIPTS))

from pingo_terrain.tiff_category import read_category_raster  # noqa: E402
from pingo_terrain.tiff_dem import read_float32_dem  # noqa: E402
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS  # noqa: E402
from blender_obj_to_asm import encode_uv_word, write_data  # noqa: E402


NLCD_TO_MATERIAL = {
    material.nlcd_category: material.material_id
    for material in BERKELEY_TERRAIN_MATERIALS
}


def selector_uv_words(material_id: int) -> tuple[int, int]:
    """Return UV words whose Pingo texel index is exactly ``material_id``."""

    if material_id not in range(SELECTOR_WIDTH * SELECTOR_HEIGHT):
        raise ValueError(f"material selector is outside 0..15: {material_id}")

    def center(cell: int, dimension: int) -> int:
        scale = dimension - 1
        lower = (cell * 65535 + scale - 1) // scale
        upper = (
            65535
            if cell == scale
            else ((cell + 1) * 65535 + scale - 1) // scale - 1
        )
        return (lower + upper) // 2

    column = material_id % SELECTOR_WIDTH
    row = material_id // SELECTOR_WIDTH
    return center(column, SELECTOR_WIDTH), 65535 - center(row, SELECTOR_HEIGHT)


def resolve_selector_uv_words(u_word: int, v_word: int) -> int:
    """Resolve one encoded UV using Pingo's endpoint/truncation rule."""

    column = (u_word * (SELECTOR_WIDTH - 1)) // 65535
    row = ((65535 - v_word) * (SELECTOR_HEIGHT - 1)) // 65535
    return row * SELECTOR_WIDTH + column


def parse_asm_words(path: Path, label: str) -> list[int]:
    """Read one generated ``dw`` table without the Pillow-bearing tooling."""

    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if line.strip() == f"{label}:"
        )
    except StopIteration as exc:
        raise ValueError(f"missing assembly table {label}: {path}") from exc
    words: list[int] = []
    for line in lines[start:]:
        source = line.split(";", 1)[0].strip()
        if not source:
            continue
        if source.endswith(":") or ": equ " in source.lower():
            break
        if not source.lower().startswith("dw "):
            if words:
                break
            continue
        words.extend(int(token.strip(), 0) for token in source[3:].split(","))
    return words


def validate_selector_asm(path: Path, symbol: str) -> list[int]:
    """Return and validate one compact row-major material ID per triangle."""

    raw_uvs = parse_asm_words(path, f"{symbol}_uvs")
    if len(raw_uvs) != SELECTOR_WIDTH * SELECTOR_HEIGHT * 2:
        raise ValueError(f"{symbol} does not contain the complete 4x4 selector")
    uv_words = list(zip(raw_uvs[0::2], raw_uvs[1::2], strict=True))
    encoded_ids = [
        resolve_selector_uv_words(u_word, v_word)
        for u_word, v_word in uv_words
    ]
    if encoded_ids != list(range(SELECTOR_WIDTH * SELECTOR_HEIGHT)):
        raise ValueError(f"{symbol} selector UVs do not encode row-major IDs")
    indices = parse_asm_words(path, f"{symbol}_uv_indices")
    if len(indices) % 3:
        raise ValueError(f"{symbol} UV index table is not triangular")
    resolved: list[int] = []
    for offset in range(0, len(indices), 3):
        triangle = indices[offset : offset + 3]
        if any(index not in range(len(uv_words)) for index in triangle):
            raise ValueError(f"{symbol} contains an invalid selector UV index")
        material_ids = [encoded_ids[index] for index in triangle]
        if material_ids[0] != material_ids[1] or material_ids[0] != material_ids[2]:
            raise ValueError(f"{symbol} triangle spans several material IDs")
        resolved.append(material_ids[0])
    return resolved


def stage_pattern_resources() -> dict:
    """Validate and vendor the immutable offline-compiled VDP resources."""

    metadata = json.loads(METADATA_SOURCE.read_text(encoding="utf-8"))
    if metadata["unique_pattern_count"] != EXPECTED_PATTERN_COUNT:
        raise ValueError("unexpected deduplicated terrain pattern count")
    if metadata["material_count"] != EXPECTED_MATERIAL_COUNT:
        raise ValueError("unexpected terrain material count")
    if metadata["illumination_band_count"] != EXPECTED_BAND_COUNT:
        raise ValueError("unexpected terrain illumination band count")
    if PATTERN_SOURCE.stat().st_size != EXPECTED_PATTERN_COUNT * 16:
        raise ValueError("terrain pattern library must contain 126 4x4 patterns")
    if LOOKUP_SOURCE.stat().st_size != (
        EXPECTED_MATERIAL_COUNT * EXPECTED_BAND_COUNT
    ):
        raise ValueError("terrain lookup must contain 15x16 one-byte IDs")
    lookup = LOOKUP_SOURCE.read_bytes()
    if any(pattern_id >= EXPECTED_PATTERN_COUNT for pattern_id in lookup):
        raise ValueError("terrain lookup contains an out-of-range pattern ID")

    shutil.copy2(PATTERN_SOURCE, TARGET / PATTERN_NAME)
    shutil.copy2(LOOKUP_SOURCE, TARGET / LOOKUP_NAME)
    shutil.copy2(METADATA_SOURCE, TARGET / METADATA_NAME)
    # Material identity comes from the selected texel's row-major position;
    # these opaque placeholder values are deliberately never color sampled.
    (TARGET / SELECTOR_NAME).write_bytes(
        bytes([0xC0] * (SELECTOR_WIDTH * SELECTOR_HEIGHT))
    )
    return metadata


def bilinear(dem, easting: float, northing: float) -> float:
    x = (easting - dem.origin_x) / dem.pixel_size_x - 0.5
    y = (dem.origin_y - northing) / dem.pixel_size_y - 0.5
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0
    if not (0 <= x0 < dem.width - 1 and 0 <= y0 < dem.height - 1):
        raise ValueError("terrain sample is outside the DEM")
    nw, ne = dem.value(x0, y0), dem.value(x0 + 1, y0)
    sw, se = dem.value(x0, y0 + 1), dem.value(x0 + 1, y0 + 1)
    return (nw * (1 - fx) + ne * fx) * (1 - fy) + (sw * (1 - fx) + se * fx) * fy


def project(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = subprocess.run(
        ["cs2cs", "EPSG:32610", "EPSG:5070"],
        input="".join(f"{x:.3f} {y:.3f}\n" for x, y in points),
        text=True, capture_output=True, check=True,
    )
    return [tuple(map(float, line.split()[:2])) for line in result.stdout.splitlines()]


def inside(point, triangle) -> bool:
    px, py = point
    (ax, ay), (bx, by), (cx, cy) = triangle
    denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denominator) < 1e-9:
        return False
    a = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
    b = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
    return min(a, b, 1.0 - a - b) >= -1e-9


def predominant(raster, triangle) -> int:
    columns = [(x - raster.origin_x) / raster.pixel_size_x for x, _ in triangle]
    rows = [(raster.origin_y - y) / raster.pixel_size_y for _, y in triangle]
    classes = []
    for row in range(max(0, math.floor(min(rows))), min(raster.height, math.ceil(max(rows)) + 1)):
        y = raster.origin_y - (row + 0.5) * raster.pixel_size_y
        for column in range(max(0, math.floor(min(columns))), min(raster.width, math.ceil(max(columns)) + 1)):
            x = raster.origin_x + (column + 0.5) * raster.pixel_size_x
            if inside((x, y), triangle):
                classes.append(raster.values[row * raster.width + column])
    if not classes:
        x = sum(value[0] for value in triangle) / 3
        y = sum(value[1] for value in triangle) / 3
        return raster.value_at_projected(x, y) or 0
    counts = Counter(classes)
    largest = max(counts.values())
    return min(value for value, count in counts.items() if count == largest)


def generate() -> dict:
    profile = json.loads(PROFILE.read_text())
    terrain = profile["terrain"]
    start = profile["start"]
    dem = read_float32_dem(DEM_PATH)
    nlcd = read_category_raster(NLCD_PATH)
    width = int(terrain["chunk_width_m"])
    columns = int(terrain["active_columns"])
    rows = int(terrain["active_rows"])
    spacing = float(terrain["triangular_lattice_spacing_m"])
    row_spacing = spacing * math.sqrt(3.0) / 2.0
    # Centroid partitioning deliberately lets whole triangles cross chunk
    # boundaries. Give every chunk the same padded model-space extent so the
    # mature exporter never performs its implicit per-mesh normalization.
    # Compensating object scale preserves the original metre-to-Pingo mapping.
    mesh_half_extent = width / 2.0 + spacing
    horizontal_object_scale = round(8192 * mesh_half_extent / (width / 2.0))
    center_e = start["utm10_easting_m"] + terrain["local_origin_offset_east_of_start_m"]
    center_n = start["utm10_northing_m"]
    west = center_e - columns * width / 2
    south = center_n - rows * width / 2
    vertical_origin = float(terrain["regional_vertical_origin_navd88_m"])
    selector_coordinates = [
        [u / 65535, v / 65535]
        for u, v in (
            selector_uv_words(material_id)
            for material_id in range(SELECTOR_WIDTH * SELECTOR_HEIGHT)
        )
    ]
    encoded_selector_ids = [
        resolve_selector_uv_words(
            encode_uv_word(coordinates[0]),
            encode_uv_word(coordinates[1]),
        )
        for coordinates in selector_coordinates
    ]
    if encoded_selector_ids != list(range(SELECTOR_WIDTH * SELECTOR_HEIGHT)):
        raise ValueError("normalized selector coordinates do not retain material IDs")
    generated = SOURCE / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    for stale in generated.glob("terrain_*.inc"):
        stale.unlink()
    pattern_metadata = stage_pattern_resources()
    setup = [
        "; AUTO-GENERATED by scripts/build_berkeley_flight_triangular_dither.py",
        "terrain_load_meshes:",
    ]
    create = ["terrain_create_objects:"]
    includes = []
    total_vertices = total_triangles = 0

    # One lattice spans the whole active region. Assigning complete triangles
    # to chunks by centroid retains a continuous phase across all 32 objects.
    east_limit = west + columns * width
    north_limit = south + rows * width
    gx_min = gy_min = -2
    gx_max = math.ceil(columns * width / spacing) + 2
    gy_max = math.ceil(rows * width / row_spacing) + 2
    points: dict[tuple[int, int], tuple[float, float]] = {}
    for gy in range(gy_min, gy_max + 1):
        offset = spacing / 2.0 if gy & 1 else 0.0
        north = south + gy * row_spacing
        for gx in range(gx_min, gx_max + 1):
            points[(gy, gx)] = (west + gx * spacing + offset, north)

    chunk_faces: list[list[list[tuple[float, float]]]] = [
        [] for _ in range(columns * rows)
    ]
    for gy in range(gy_min, gy_max):
        for gx in range(gx_min, gx_max):
            lower_w = points[(gy, gx)]
            lower_e = points[(gy, gx + 1)]
            upper_w = points[(gy + 1, gx)]
            upper_e = points[(gy + 1, gx + 1)]
            candidates = (
                ([lower_w, upper_w, upper_e], [lower_w, upper_e, lower_e])
                if gy & 1
                else ([lower_w, upper_w, lower_e], [lower_e, upper_w, upper_e])
            )
            for source_face in candidates:
                centroid_e = sum(point[0] for point in source_face) / 3.0
                centroid_n = sum(point[1] for point in source_face) / 3.0
                if not (
                    west <= centroid_e < east_limit
                    and south <= centroid_n < north_limit
                ):
                    continue
                column = min(columns - 1, int((centroid_e - west) // width))
                row = min(rows - 1, int((centroid_n - south) // width))
                chunk_faces[row * columns + column].append(source_face)

    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            symbol = f"terrain_{index:02d}"
            chunk_w = west + column * width
            chunk_s = south + row * width
            chunk_center_e = chunk_w + width / 2
            chunk_center_n = chunk_s + width / 2
            sources: list[tuple[float, float]] = []
            source_indices: dict[tuple[float, float], int] = {}
            faces: list[list[int]] = []
            for source_face in chunk_faces[index]:
                face = []
                for point in source_face:
                    if point not in source_indices:
                        source_indices[point] = len(sources)
                        sources.append(point)
                    face.append(source_indices[point])
                faces.append(face)
            elevations = [bilinear(dem, east, north) for east, north in sources]
            vertices = [
                [
                    (north - chunk_center_n) / mesh_half_extent,
                    (elevation - vertical_origin) / 320.0,
                    -(east - chunk_center_e) / mesh_half_extent,
                ]
                for (east, north), elevation in zip(sources, elevations, strict=True)
            ]
            maximum_coordinate = max(
                abs(coordinate)
                for vertex in vertices
                for coordinate in vertex
            )
            if maximum_coordinate > 1.0:
                raise ValueError(
                    f"{symbol} exceeds padded model extent: {maximum_coordinate}"
                )
            for face in faces:
                a, b, c = (vertices[vertex] for vertex in face)
                ab_x, ab_z = b[0] - a[0], b[2] - a[2]
                ac_x, ac_z = c[0] - a[0], c[2] - a[2]
                if ab_z * ac_x - ab_x * ac_z <= 0.0:
                    face[1], face[2] = face[2], face[1]
            projected = project(sources)
            selections = [
                NLCD_TO_MATERIAL.get(
                    predominant(nlcd, [projected[i] for i in face]),
                    NLCD_TO_MATERIAL[24],
                )
                for face in faces
            ]
            uv_indices = [[selection] * 3 for selection in selections]
            include_path = generated / f"{symbol}.inc"
            write_data(
                symbol, vertices, faces, selector_coordinates, uv_indices, [], [],
                include_path, TARGET / SELECTOR_NAME,
                (SELECTOR_WIDTH, SELECTOR_HEIGHT),
                symbol_prefix=symbol,
                authoritative_input="USGS 3DEP + Annual NLCD manifest berkeley-ca-2026-08-02",
                generator="scripts/build_berkeley_flight_triangular_dither.py",
            )
            if validate_selector_asm(include_path, symbol) != selections:
                raise ValueError(f"{symbol} UV selectors do not preserve material IDs")
            setup.extend([
                f"    SV sid,{index + 1},{symbol}_vertices,{symbol}_vertices_n",
                f"    SMVI sid,{index + 1},{symbol}_vertex_indices,{symbol}_indices_n",
                f"    STC sid,{index + 1},{symbol}_uvs,{symbol}_uvs_n",
                f"    STCI sid,{index + 1},{symbol}_uv_indices,{symbol}_indices_n",
                f"    ld hl,{index + 1}",
                "    ld a,pingo_shading_flat_pattern",
                "    call pingo_set_mesh_shading_mode",
                f"    ld hl,{index + 1}",
                "    ld a,pingo_mesh_illumination_scene",
                "    call pingo_set_mesh_illumination_mode",
            ])
            x = round((chunk_center_n - center_n) / 8 * 128)
            z = round(-(chunk_center_e - center_e) / 8 * 128)
            create.extend([
                f"    CO sid,{index + 1},{index + 1},terrain_bmid",
                f"    SO sid,{index + 1},{horizontal_object_scale},10240,{horizontal_object_scale}",
                f"    OT sid,{index + 1},{x},0,{z}",
            ])
            includes.append(f'    include "generated/{symbol}.inc"')
            total_vertices += len(vertices)
            total_triangles += len(faces)
    setup.append("    ret")
    create.append("    ret")
    (SOURCE / "terrain-scene.inc").write_text("\n".join(setup + [""] + create + [""] + includes) + "\n")
    return {
        "chunks": columns * rows,
        "vertices": total_vertices,
        "triangles": total_triangles,
        "spacing_m": spacing,
        "mesh_half_extent_m": mesh_half_extent,
        "horizontal_object_scale": horizontal_object_scale,
        "center_e": center_e,
        "center_n": center_n,
        "materials": len(BERKELEY_TERRAIN_MATERIALS),
        "patterns": pattern_metadata["unique_pattern_count"],
        "bands": pattern_metadata["illumination_band_count"],
    }


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    summary = generate()
    output = TARGET / "berkeley-flight-triangular-dither.bin"
    output_argument = Path("../tgt/berkeley-flight-triangular-dither.bin")
    subprocess.run(
        ["ez80asm", "berkeley-flight-triangular-dither.asm", str(output_argument)],
        cwd=SOURCE,
        check=True,
    )
    print(
        "BERKELEY_FLIGHT_TRIANGULAR_DITHER",
        *(f"{key}={value}" for key, value in summary.items()),
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
