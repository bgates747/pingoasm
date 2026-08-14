"""Validate and package the vendored PingoASM flat-palette Jet."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from .aircraft_view import (
    JET_MODEL_HALF_EXTENT_METRES,
    JET_OBJECT_SCALE_Q8_8,
    scale_half_extent_metres,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VENDOR_DIR = PROJECT_ROOT / "assets/aircraft/pingoasm-jet"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "build/aircraft/pingoasm-jet"
OUTPUT_INCLUDE = "jet-view.inc"
OUTPUT_TEXTURE = "JET64.RG2"
OUTPUT_MANIFEST = "AIRCRAFT.json"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest(vendor_dir: Path) -> dict:
    path = vendor_dir / "provenance.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "pingo-terrain-vendored-aircraft-v1":
        raise ValueError("unsupported vendored-aircraft provenance schema")
    for record in manifest.get("vendored_files", []):
        source = vendor_dir / record["path"]
        payload = source.read_bytes()
        if len(payload) != record["bytes"]:
            raise ValueError(f"vendored byte count changed: {source}")
        if sha256_bytes(payload) != record["sha256"]:
            raise ValueError(f"vendored SHA-256 changed: {source}")
    return manifest


def _equate(source: str, name: str) -> int:
    match = re.search(
        rf"(?im)^\s*{re.escape(name)}\s*:\s*equ\s+([^;\s]+)", source
    )
    if not match:
        raise ValueError(f"missing assembly equate {name}")
    return int(match.group(1), 0)


def _word_table(source: str, label: str) -> tuple[int, ...]:
    lines = source.splitlines()
    try:
        start = next(
            offset + 1
            for offset, line in enumerate(lines)
            if line.strip() == f"{label}:"
        )
    except StopIteration as error:
        raise ValueError(f"missing assembly table {label}") from error
    values: list[int] = []
    for line in lines[start:]:
        statement = line.split(";", 1)[0].strip()
        if not statement:
            continue
        if statement.endswith(":") or ": equ " in statement.lower():
            break
        if not statement.lower().startswith("dw "):
            if values:
                break
            continue
        values.extend(int(token.strip(), 0) for token in statement[3:].split(","))
    if not values:
        raise ValueError(f"empty assembly table {label}")
    return tuple(values)


def _grouped(values: tuple[int, ...], width: int) -> tuple[tuple[int, ...], ...]:
    if len(values) % width:
        raise ValueError(f"{len(values)} values are not divisible by {width}")
    return tuple(
        values[offset : offset + width]
        for offset in range(0, len(values), width)
    )


def load_vendor(vendor_dir: Path = DEFAULT_VENDOR_DIR) -> dict:
    """Return one completely validated flat Jet snapshot."""

    vendor_dir = vendor_dir.resolve()
    provenance = _manifest(vendor_dir)
    include_path = vendor_dir / "jet-flat.inc"
    texture_path = vendor_dir / "jet-flat.rgba2"
    source = include_path.read_text(encoding="utf-8")
    positions = _grouped(_word_table(source, "jet_vertices"), 3)
    position_indices = _word_table(source, "jet_vertex_indices")
    uvs = _grouped(_word_table(source, "jet_uvs"), 2)
    uv_indices = _word_table(source, "jet_uv_indices")

    expected = {
        "vertices": _equate(source, "jet_vertices_n"),
        "indices": _equate(source, "jet_indices_n"),
        "uvs": _equate(source, "jet_uvs_n"),
        "texture_width": _equate(source, "jet_texture_width"),
        "texture_height": _equate(source, "jet_texture_height"),
        "texture_size": _equate(source, "jet_texture_size"),
    }
    actual = {
        "vertices": len(positions),
        "indices": len(position_indices),
        "uvs": len(uvs),
        "texture_width": 8,
        "texture_height": 8,
        "texture_size": len(texture_path.read_bytes()),
    }
    if actual != expected:
        raise ValueError(f"Jet include counts changed: expected {expected}, got {actual}")
    if len(uv_indices) != len(position_indices):
        raise ValueError("Jet UV-index count does not equal position-index count")
    if len(position_indices) % 3:
        raise ValueError("Jet position-index count is not triangular")
    if not all(-32_768 <= value <= 32_767 for point in positions for value in point):
        raise ValueError("Jet position is outside signed 16-bit range")
    if not all(0 <= value < len(positions) for value in position_indices):
        raise ValueError("Jet position index is out of range")
    if not all(0 <= value <= 0xFFFF for uv in uvs for value in uv):
        raise ValueError("Jet UV coordinate is outside unsigned 16-bit range")
    if not all(0 <= value < len(uvs) for value in uv_indices):
        raise ValueError("Jet UV index is out of range")
    for offset in range(0, len(uv_indices), 3):
        triangle = uv_indices[offset : offset + 3]
        if len(set(triangle)) != 1:
            raise ValueError(f"Jet triangle {offset // 3} is not flat-palette shaded")

    return {
        "provenance": provenance,
        "positions": positions,
        "position_indices": position_indices,
        "uvs": uvs,
        "uv_indices": uv_indices,
        "texture": texture_path.read_bytes(),
    }


def _word_lines(values: Iterable[int], *, per_line: int) -> list[str]:
    values = list(values)
    return [
        "    dw " + ",".join(str(value) for value in values[offset : offset + per_line])
        for offset in range(0, len(values), per_line)
    ]


def _table_lines(
    label: str, rows: Iterable[Iterable[int]], *, rows_per_line: int = 1
) -> list[str]:
    rows = tuple(tuple(row) for row in rows)
    if not rows:
        raise ValueError(f"assembly table {label} cannot be empty")
    width = len(rows[0])
    if width == 0 or any(len(row) != width for row in rows):
        raise ValueError(f"assembly table {label} has inconsistent row widths")
    flattened = [value for row in rows for value in row]
    per_line = max(1, width * rows_per_line)
    return [f"{label}:", *_word_lines(flattened, per_line=per_line), ""]


def make_include(asset: dict) -> bytes:
    """Create the compact, normals-free assembly include used by flight."""

    positions = asset["positions"]
    indices = asset["position_indices"]
    uvs = asset["uvs"]
    uv_indices = asset["uv_indices"]
    source_hash = asset["provenance"]["vendored_files"][0]["sha256"]
    lines = [
        "; =============================================================================",
        "; AUTO-GENERATED FILE - DO NOT EDIT",
        "; Generated by: scripts/build_aircraft_asset.py",
        f"; Vendored flat Jet SHA-256: {source_hash}",
        "; Normals are omitted because current Pingo mesh upload does not consume them.",
        "; =============================================================================",
        "",
        f"aircraft_jet_indices_n: equ {len(indices)}",
        f"aircraft_jet_vertices_n: equ {len(positions)}",
        f"aircraft_jet_uvs_n: equ {len(uvs)}",
        "aircraft_jet_texture_width: equ 8",
        "aircraft_jet_texture_height: equ 8",
        "aircraft_jet_texture_size: equ 64",
        f"aircraft_jet_object_scale_q8_8: equ {JET_OBJECT_SCALE_Q8_8}",
        "",
    ]
    lines.extend(_table_lines("aircraft_jet_vertices", positions))
    lines.extend(
        ["aircraft_jet_vertex_indices:", *_word_lines(indices, per_line=12), ""]
    )
    lines.extend(_table_lines("aircraft_jet_uvs", uvs, rows_per_line=4))
    lines.extend(
        ["aircraft_jet_uv_indices:", *_word_lines(uv_indices, per_line=12), ""]
    )
    lines.append(f'aircraft_jet_texture: db "{OUTPUT_TEXTURE}",0')
    lines.append("")
    return ("\n".join(lines)).encode("utf-8")


def build(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    vendor_dir: Path = DEFAULT_VENDOR_DIR,
) -> dict:
    """Build the deterministic include, texture, and integration manifest."""

    asset = load_vendor(vendor_dir)
    include = make_include(asset)
    texture = asset["texture"]
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / OUTPUT_INCLUDE).write_bytes(include)
    (output_dir / OUTPUT_TEXTURE).write_bytes(texture)

    geometry = asset["provenance"]["source_geometry"]
    original_half_extent = float(geometry["normalization_half_extent_m"])
    scale_factor = JET_MODEL_HALF_EXTENT_METRES / original_half_extent
    minimum = geometry["minimum_xyz"]
    maximum = geometry["maximum_xyz"]
    manifest = {
        "schema": "pingo-terrain-aircraft-build-v1",
        "source_provenance": "assets/aircraft/pingoasm-jet/provenance.json",
        "source_rights_status": asset["provenance"]["rights"]["status"],
        "vertices": len(asset["positions"]),
        "triangles": len(asset["position_indices"]) // 3,
        "uv_selectors": len(asset["uvs"]),
        "forward_axis": "local -Z",
        "up_axis": "local +Y",
        "object_scale_q8_8": JET_OBJECT_SCALE_Q8_8,
        "rendered_model_half_extent_m": scale_half_extent_metres(
            JET_OBJECT_SCALE_Q8_8
        ),
        "source_to_render_scale": scale_factor,
        "rendered_dimensions_m": {
            "x": (maximum[0] - minimum[0]) * scale_factor,
            "y": (maximum[1] - minimum[1]) * scale_factor,
            "z": (maximum[2] - minimum[2]) * scale_factor,
        },
        "render_policy": {
            "shading": "solid flat / predominant palette selector",
            "illumination": "scene",
            "texture": OUTPUT_TEXTURE,
            "texture_size": [8, 8],
        },
        "outputs": [
            {
                "path": OUTPUT_INCLUDE,
                "bytes": len(include),
                "sha256": sha256_bytes(include),
            },
            {
                "path": OUTPUT_TEXTURE,
                "bytes": len(texture),
                "sha256": sha256_bytes(texture),
            },
        ],
    }
    encoded_manifest = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (output_dir / OUTPUT_MANIFEST).write_bytes(encoded_manifest)
    return manifest
