#!/usr/bin/env python3
"""Convert and validate Pingo meshes that use one palette color per triangle."""

from __future__ import annotations

import argparse
import math
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image

from agonImages import colors64
from blender_obj_to_asm import encode_uv_word, parse_obj_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PALETTE = PROJECT_ROOT / "src" / "blender" / "colors64.png"
GENERATOR = "build/scripts/flat_palette.py"
PALETTE_WIDTH = 8
PALETTE_HEIGHT = 8
UV_WORD_MAX = 65535


class FlatPaletteError(ValueError):
    """Raised when a mesh cannot satisfy the flat-palette contract."""


def verify_palette_image(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    if image.size != (PALETTE_WIDTH, PALETTE_HEIGHT):
        raise FlatPaletteError(
            f"palette must be 8x8 pixels, not {image.width}x{image.height}: {path}"
        )
    pixels = [
        image.getpixel((x, y))
        for y in range(PALETTE_HEIGHT)
        for x in range(PALETTE_WIDTH)
    ]
    if pixels != colors64:
        raise FlatPaletteError(
            f"palette pixels are not canonical Agon indices 0..63: {path}"
        )
    return image


def _cell_center_word(cell: int, dimension: int) -> int:
    if dimension < 2 or not 0 <= cell < dimension:
        raise FlatPaletteError(
            f"cell {cell} is outside a {dimension}-texel dimension"
        )
    scale = dimension - 1
    lower = (cell * UV_WORD_MAX + scale - 1) // scale
    if cell == scale:
        upper = UV_WORD_MAX
    else:
        upper = (((cell + 1) * UV_WORD_MAX + scale - 1) // scale) - 1
    return (lower + upper) // 2


def palette_uv_words(index: int) -> tuple[int, int]:
    """Return a safe interior UV word pair for a row-major palette index."""
    if not 0 <= index < len(colors64):
        raise FlatPaletteError(f"palette index is outside 0..63: {index}")
    column = index % PALETTE_WIDTH
    row = index // PALETTE_WIDTH
    u_word = _cell_center_word(column, PALETTE_WIDTH)
    row_word = _cell_center_word(row, PALETTE_HEIGHT)
    v_word = UV_WORD_MAX - row_word
    return u_word, v_word


def resolve_uv_words(
    u_word: int,
    v_word: int,
    width: int,
    height: int,
) -> tuple[int, int]:
    """Resolve encoded UVs with Pingo's exact endpoint-and-truncation rule."""
    if width <= 0 or height <= 0:
        raise FlatPaletteError("texture dimensions must be positive")
    if not 0 <= u_word <= UV_WORD_MAX or not 0 <= v_word <= UV_WORD_MAX:
        raise FlatPaletteError(
            f"UV words must be unsigned 16-bit values: ({u_word}, {v_word})"
        )
    x = (u_word * (width - 1)) // UV_WORD_MAX
    y = ((UV_WORD_MAX - v_word) * (height - 1)) // UV_WORD_MAX
    return x, y


def _triangles(indices: Sequence[Sequence[int]] | Sequence[int]) -> list[list[int]]:
    if not indices:
        return []
    first = indices[0]
    if isinstance(first, int):
        flat = [int(value) for value in indices]
        if len(flat) % 3:
            raise FlatPaletteError(
                f"UV index count {len(flat)} is not a triangle triplet"
            )
        return [flat[offset : offset + 3] for offset in range(0, len(flat), 3)]
    triangles = [[int(value) for value in face] for face in indices]
    for triangle_index, triangle in enumerate(triangles):
        if len(triangle) != 3:
            raise FlatPaletteError(
                f"triangle {triangle_index} has {len(triangle)} UV corners, not 3"
            )
    return triangles


def validate_flat_palette_words(
    uv_words: Sequence[tuple[int, int]],
    uv_indices: Sequence[Sequence[int]] | Sequence[int],
    width: int = PALETTE_WIDTH,
    height: int = PALETTE_HEIGHT,
) -> list[tuple[int, int]]:
    """Reject any source triangle whose final UV words select several texels."""
    resolved: list[tuple[int, int]] = []
    for triangle_index, triangle in enumerate(_triangles(uv_indices)):
        cells: list[tuple[int, int]] = []
        for uv_index in triangle:
            if not 0 <= uv_index < len(uv_words):
                raise FlatPaletteError(
                    f"triangle {triangle_index} uses UV index {uv_index}, "
                    f"but only {len(uv_words)} UVs exist"
                )
            cells.append(resolve_uv_words(*uv_words[uv_index], width, height))
        if cells[0] != cells[1] or cells[0] != cells[2]:
            raise FlatPaletteError(
                f"triangle {triangle_index} is multi-color after encoding: "
                f"{cells[0]}, {cells[1]}, {cells[2]}"
            )
        resolved.append(cells[0])
    return resolved


def validate_flat_palette_data(
    texture_coordinates: Sequence[Sequence[float]],
    uv_indices: Sequence[Sequence[int]] | Sequence[int],
    width: int = PALETTE_WIDTH,
    height: int = PALETTE_HEIGHT,
) -> list[tuple[int, int]]:
    words = [
        (encode_uv_word(coordinate[0]), encode_uv_word(coordinate[1]))
        for coordinate in texture_coordinates
    ]
    return validate_flat_palette_words(words, uv_indices, width, height)


def _nearest_palette_index(rgb: tuple[int, int, int]) -> int:
    return min(
        range(len(colors64)),
        key=lambda index: (
            sum((rgb[channel] - colors64[index][channel]) ** 2 for channel in range(3)),
            index,
        ),
    )


def _inside_triangle(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    px, py = point
    ax, ay = a
    bx, by = b
    cx, cy = c
    denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denominator) < 1e-12:
        return False
    w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
    w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
    w2 = 1.0 - w0 - w1
    epsilon = 1e-9
    return w0 >= -epsilon and w1 >= -epsilon and w2 >= -epsilon


def _source_texels(
    image: Image.Image,
    coordinates: Sequence[Sequence[float]],
) -> list[tuple[int, int, int, int]]:
    points = [
        (
            min(1.0, max(0.0, uv[0])) * (image.width - 1),
            (1.0 - min(1.0, max(0.0, uv[1]))) * (image.height - 1),
        )
        for uv in coordinates
    ]
    min_x = max(0, math.ceil(min(point[0] for point in points)))
    max_x = min(image.width - 1, math.floor(max(point[0] for point in points)))
    min_y = max(0, math.ceil(min(point[1] for point in points)))
    max_y = min(image.height - 1, math.floor(max(point[1] for point in points)))
    pixels = []
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if _inside_triangle((x, y), points[0], points[1], points[2]):
                pixels.append(image.getpixel((x, y)))
    if pixels:
        return pixels

    # Very small UV triangles may contain no texel center. Use the texel that
    # Pingo would select at their centroid as a deterministic fallback.
    centroid_u = sum(uv[0] for uv in coordinates) / 3.0
    centroid_v = sum(uv[1] for uv in coordinates) / 3.0
    x = int(min(1.0, max(0.0, centroid_u)) * (image.width - 1))
    y = int((1.0 - min(1.0, max(0.0, centroid_v))) * (image.height - 1))
    return [image.getpixel((x, y))]


def predominant_palette_index(
    image: Image.Image,
    coordinates: Sequence[Sequence[float]],
) -> int:
    counts: Counter[int] = Counter()
    for red, green, blue, alpha in _source_texels(image, coordinates):
        if alpha == 0:
            continue
        counts[_nearest_palette_index((red, green, blue))] += 1
    if not counts:
        return 0
    largest = max(counts.values())
    return min(index for index, count in counts.items() if count == largest)


def convert_obj_model_data(
    obj_path: Path,
    source_texture_path: Path,
) -> tuple[tuple, list[int]]:
    """Return blender_obj_to_asm data with modal palette UVs per triangle."""
    model_data = parse_obj_file(obj_path)
    vertices, faces, texture_coordinates, uv_indices, normals, normal_indices = model_data
    if len(faces) != len(uv_indices):
        raise FlatPaletteError(
            f"every face needs texture coordinates: {obj_path}"
        )
    image = Image.open(source_texture_path).convert("RGBA")
    selections: list[int] = []
    flat_indices: list[list[int]] = []
    palette_coordinates = [
        [u_word / UV_WORD_MAX, v_word / UV_WORD_MAX]
        for u_word, v_word in (palette_uv_words(index) for index in range(64))
    ]
    for triangle_index, (face, triangle) in enumerate(zip(faces, uv_indices, strict=True)):
        if len(face) != 3 or len(triangle) != 3:
            raise FlatPaletteError(
                f"face {triangle_index} is not a textured triangle"
            )
        try:
            coordinates = [texture_coordinates[index] for index in triangle]
        except IndexError as exc:
            raise FlatPaletteError(
                f"face {triangle_index} has an out-of-range UV index"
            ) from exc
        palette_index = predominant_palette_index(image, coordinates)
        selections.append(palette_index)
        flat_indices.append([palette_index, palette_index, palette_index])

    validate_flat_palette_data(palette_coordinates, flat_indices)
    return (
        (
            vertices,
            faces,
            palette_coordinates,
            flat_indices,
            normals,
            normal_indices,
        ),
        selections,
    )


def _parse_asm_words(path: Path, label: str) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"{label}:":
            start = index + 1
            break
    if start is None:
        raise FlatPaletteError(f"missing assembly table {label}: {path}")

    values: list[int] = []
    for line in lines[start:]:
        source = line.split(";", 1)[0].strip()
        if not source:
            continue
        if source.endswith(":") or ": equ " in source.lower():
            break
        if not source.lower().startswith("dw "):
            if values:
                break
            continue
        for token in source[3:].split(","):
            values.append(int(token.strip(), 0))
    return values


def validate_flat_palette_asm(
    path: Path,
    symbol_prefix: str,
    width: int = PALETTE_WIDTH,
    height: int = PALETTE_HEIGHT,
) -> list[tuple[int, int]]:
    raw_uvs = _parse_asm_words(path, f"{symbol_prefix}_uvs")
    if len(raw_uvs) % 2:
        raise FlatPaletteError(
            f"{symbol_prefix}_uvs contains an odd word count: {len(raw_uvs)}"
        )
    uv_words = list(zip(raw_uvs[0::2], raw_uvs[1::2], strict=True))
    indices = _parse_asm_words(path, f"{symbol_prefix}_uv_indices")
    return validate_flat_palette_words(uv_words, indices, width, height)


def write_flat_obj(
    source_obj: Path,
    destination: Path,
    palette_indices: Sequence[int],
) -> None:
    source_lines = source_obj.read_text(encoding="utf-8").splitlines()
    output = [
        "# =============================================================================",
        "# AUTO-GENERATED FILE - DO NOT EDIT",
        f"# Generated by: {GENERATOR}",
        f"# Generated from: {source_obj}",
        "# One canonical Agon palette UV is assigned to each source triangle.",
        "# =============================================================================",
    ]
    palette_block = [
        f"vt {u_word / UV_WORD_MAX:.9f} {v_word / UV_WORD_MAX:.9f}"
        for u_word, v_word in (palette_uv_words(index) for index in range(64))
    ]
    inserted_palette = False
    face_index = 0
    for line in source_lines:
        stripped = line.strip()
        if stripped.startswith("vt "):
            continue
        if stripped.startswith("f "):
            if not inserted_palette:
                output.extend(palette_block)
                inserted_palette = True
            if face_index >= len(palette_indices):
                raise FlatPaletteError("OBJ contains more faces than converted selections")
            corners = stripped.split()[1:]
            if len(corners) != 3:
                raise FlatPaletteError(f"face {face_index} is not a triangle")
            uv_index = palette_indices[face_index] + 1
            rewritten = []
            for corner in corners:
                parts = corner.split("/")
                vertex = parts[0]
                normal = parts[2] if len(parts) > 2 else ""
                rewritten.append(
                    f"{vertex}/{uv_index}/{normal}" if normal else f"{vertex}/{uv_index}"
                )
            output.append("f " + " ".join(rewritten))
            face_index += 1
        else:
            output.append(line)
    if face_index != len(palette_indices):
        raise FlatPaletteError(
            f"OBJ contains {face_index} faces but {len(palette_indices)} were converted"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_obj", type=Path)
    parser.add_argument("source_texture", type=Path)
    parser.add_argument("output_obj", type=Path)
    parser.add_argument("--palette", type=Path, default=DEFAULT_PALETTE)
    args = parser.parse_args()

    verify_palette_image(args.palette)
    _, selections = convert_obj_model_data(args.source_obj, args.source_texture)
    write_flat_obj(args.source_obj, args.output_obj, selections)

    converted = parse_obj_file(args.output_obj)
    validate_flat_palette_data(converted[2], converted[3])
    counts = Counter(selections)
    summary = ", ".join(f"{index}:{counts[index]}" for index in sorted(counts))
    print(f"Wrote {args.output_obj} ({len(selections)} triangles; {summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
