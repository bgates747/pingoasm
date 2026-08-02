#!/usr/bin/env python3
"""Package the accepted Berkeley triangular chunks as AGNB/P3DM records."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profiles/berkeley-flight-triangular-dither.json"
GENERATED = (
    ROOT / "fixtures/berkeley-flight-triangular-dither/src/generated"
)
DEFAULT_OUTPUT = ROOT / "build/p3dm/berkeley-triangular-dither"
STAGING_BUFFER_ID = 0x7400

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.p3dm import (  # noqa: E402
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    P3DMMeta,
    P3DMTile,
    ShadingMode,
    make_container,
    make_data,
    parse_container,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"output directory (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_dw_table(path: Path, label: str) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if line.strip() == f"{label}:"
        )
    except StopIteration as error:
        raise ValueError(f"missing assembly table {label}: {path}") from error
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


def grouped(values: list[int], width: int) -> tuple[tuple[int, ...], ...]:
    if len(values) % width:
        raise ValueError(f"table of {len(values)} words is not divisible by {width}")
    return tuple(
        tuple(values[offset : offset + width])
        for offset in range(0, len(values), width)
    )


def tile_from_include(
    path: Path,
    *,
    index: int,
    column: int,
    row: int,
    profile: dict,
) -> P3DMTile:
    symbol = f"terrain_{index:02d}"
    positions = grouped(parse_dw_table(path, f"{symbol}_vertices"), 3)
    position_indices = tuple(
        parse_dw_table(path, f"{symbol}_vertex_indices")
    )
    uvs = grouped(parse_dw_table(path, f"{symbol}_uvs"), 2)
    uv_indices = tuple(parse_dw_table(path, f"{symbol}_uv_indices"))

    terrain = profile["terrain"]
    start = profile["start"]
    width = int(terrain["chunk_width_m"])
    columns = int(terrain["active_columns"])
    rows = int(terrain["active_rows"])
    origin_east = round(
        start["utm10_easting_m"]
        + terrain["local_origin_offset_east_of_start_m"]
    )
    origin_north = round(start["utm10_northing_m"])
    west = origin_east - columns * width / 2
    south = origin_north - rows * width / 2
    center_east = round(west + (column + 0.5) * width)
    center_north = round(south + (row + 0.5) * width)
    vertical_origin = float(terrain["regional_vertical_origin_navd88_m"])
    elevations = [
        vertical_origin + position[1] / 32767.0 * 320.0
        for position in positions
    ]
    half_extent = math.ceil(
        width / 2 + float(terrain["triangular_lattice_spacing_m"])
    )
    return P3DMTile(
        stage_buffer_id=STAGING_BUFFER_ID,
        meta=P3DMMeta(
            layer_kind=LayerKind.TERRAIN,
            lod=0,
            shading_mode=ShadingMode.FLAT_PATTERN,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
            tile_x=column,
            tile_y=row,
            center_east_m=center_east - origin_east,
            center_north_m=center_north - origin_north,
            minimum_elevation_dm=math.floor(min(elevations) * 10),
            maximum_elevation_dm=math.ceil(max(elevations) * 10),
            model_half_extent_m=half_extent,
        ),
        positions=positions,
        position_indices=position_indices,
        uvs=uvs,
        uv_indices=uv_indices,
    )


def build(output: Path) -> dict:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    terrain = profile["terrain"]
    start = profile["start"]
    columns = int(terrain["active_columns"])
    rows = int(terrain["active_rows"])
    width = int(terrain["chunk_width_m"])
    origin_east = round(
        start["utm10_easting_m"]
        + terrain["local_origin_offset_east_of_start_m"]
    )
    origin_north = round(start["utm10_northing_m"])
    records = []
    output.mkdir(parents=True, exist_ok=True)
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            source = GENERATED / f"terrain_{index:02d}.inc"
            tile = tile_from_include(
                source,
                index=index,
                column=column,
                row=row,
                profile=profile,
            )
            container = make_container(tile)
            if parse_container(container) != tile:
                raise ValueError(f"P3DM round trip changed tile {index}")
            high = (index >> 8) & 0xFF
            low = index & 0xFF
            relative = Path("TRN") / "L0" / f"{high:02X}" / f"{low:02X}.AGN"
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(container)
            data = make_data(tile)
            records.append(
                {
                    "tile_id": index,
                    "path": relative.as_posix(),
                    "bytes": len(container),
                    "sha256": sha256_bytes(container),
                    "data_bytes": len(data),
                    "data_sha256": sha256_bytes(data),
                    "vertices": len(tile.positions),
                    "triangles": len(tile.position_indices) // 3,
                    "meta": {
                        **asdict(tile.meta),
                        "layer_kind": int(tile.meta.layer_kind),
                        "shading_mode": int(tile.meta.shading_mode),
                        "illumination": int(tile.meta.illumination),
                    },
                }
            )
    manifest = {
        "schema": "pingo-terrain-p3dm-corpus-v1",
        "agnb_version": "0.3",
        "p3dm_layout_version": 1,
        "source_profile": str(PROFILE_PATH.relative_to(ROOT)),
        "source_crs": profile["coordinate_system"]["source_crs"],
        "regional_origin_easting_m": origin_east,
        "regional_origin_northing_m": origin_north,
        "chunk_width_m": width,
        "columns": columns,
        "rows": rows,
        "stage_buffer_id": STAGING_BUFFER_ID,
        "records": records,
    }
    manifest_path = output / "WORLD.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    arguments = parse_arguments()
    output = arguments.output.expanduser().resolve()
    manifest = build(output)
    data_sizes = [record["data_bytes"] for record in manifest["records"]]
    print(
        "BERKELEY_P3DM",
        f"tiles={len(data_sizes)}",
        f"data_min={min(data_sizes)}",
        f"data_max={max(data_sizes)}",
        f"data_mean={sum(data_sizes) / len(data_sizes):.2f}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
