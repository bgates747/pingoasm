#!/usr/bin/env python3
"""Build the complete reusable regular N=1 terrain hierarchy.

The accepted N=5 ``TRH/L0`` corpus is the sole geometry/semantic source.
Every cell is first reduced through :func:`regular_lod.decimate_l0_tile`, then
the canonical N=1 surfaces are packed into the aligned hierarchy declared by
``regular_lod.HIERARCHY_LEVELS``:

``8x4 -> 4x2 -> 2x1 -> 1x1`` in ``(q, offset_row)`` coordinates.

All node faces come from that lattice; no runtime origin, seam, or named GIS
feature is authored here.  L2 and L1 use the exact 1,024 metre count algebra.
L4 and L8 use their guarded legal extents and report their independent P3DM
quantization honestly.  Downward node skirts are fail-soft coverage only.

The build publishes through a new directory rename and never modifies its L0
source or previous experimental corpora::

    .venv/bin/python scripts/build_regular_lod_corpus.py
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HEX_BASIS_Q_EAST_M,
    HEX_BASIS_R_NORTH_M,
    HEX_CELL_COUNT,
    HEX_EVEN_COLUMN_ROWS,
    HEX_ODD_COLUMN_ROWS,
    HEX_ORIGIN_EAST_M,
    HEX_ORIGIN_NORTH_M,
    HEX_Q_MAX,
    HEX_TERRAIN_Y_COUNT,
    HexCell,
    hex_center_m,
    hex_corners_counts,
    iter_cells,
)
from pingo_terrain.materials import (  # noqa: E402
    AGON_SOLID_TERRAIN_MATERIALS,
    BERKELEY_TERRAIN_MATERIALS,
)
from pingo_terrain.p3dm import (  # noqa: E402
    P3DMMeta,
    P3DMTile,
    make_container,
    make_data,
    parse_container,
)
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    SKIRT_DEPTH_M,
)
from pingo_terrain.regular_lod import (  # noqa: E402
    COARSE_SLOT_COUNT,
    FAR_RING,
    HIERARCHY_LEVELS,
    MANAGER_SLOT_COUNT,
    NEAR_RING_MAX,
    P3DM_FILE_LIMIT,
    HierarchyNode,
    bounded_node_cells,
    decimate_l0_tile,
    iter_hierarchy_nodes,
    node_center_m,
    node_planar_half_extents_m,
    offset_row,
    select_hierarchy_nodes,
    terrain_class,
    validate_hierarchy_plan,
)


DEFAULT_SOURCE = ROOT / "build/p3dm/bay-area-hex-full-l0"
DEFAULT_OUTPUT = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
RUNTIME_RESOURCES = ROOT / "build/p3dm/bay-area-hex-three-class-comparison"
SOURCE_WORLD_SHA256 = (
    "43a41bced05f35eaf104e48c906b59e28f4b0ac254ec60fa2b35166b0e707a26"
)
SOURCE_SCHEMA = "pingo-terrain-regional-hex-corpus-v1"
OUTPUT_SCHEMA = "pingo-terrain-regular-n1-hierarchy-v1"
RESOURCE_NAMES = ("MATID.RG2", "PATTERN.RG2", "PATLUT.BIN")
N5_SURFACE_VERTICES = 91
N5_SURFACE_TRIANGLES = 150
N5_SKIRT_TRIANGLES = 60
N1_SURFACE_VERTICES = 7
N1_SURFACE_TRIANGLES = 6
P3DM_COORDINATE_FACTOR = 32_768
SKIRT_DEPTH_COUNTS = round(SKIRT_DEPTH_M * COUNTS_PER_METRE)
AGON_PALETTE_BY_CLASS = (20, 7, 21)

EXPECTED_LEVELS = {
    "L8": {
        "records": 1_593,
        "vertices": 261_108,
        "surface_triangles": 301_098,
        "skirt_triangles": 145_288,
        "triangles": 446_386,
        "data_bytes": 7_025_232,
        "container_bytes": 7_184_584,
        "maximum_record_bytes": 4_568,
    },
    "L4": {
        "records": 6_372,
        "vertices": 365_027,
        "surface_triangles": 301_098,
        "skirt_triangles": 277_404,
        "triangles": 578_502,
        "data_bytes": 9_539_994,
        "container_bytes": 10_177_196,
        "maximum_record_bytes": 1_616,
    },
    "L2": {
        "records": 25_145,
        "vertices": 552_227,
        "surface_triangles": 301_098,
        "skirt_triangles": 502_044,
        "triangles": 803_142,
        "data_bytes": 14_560_346,
        "container_bytes": 17_075_060,
        "maximum_record_bytes": 680,
    },
    "L1": {
        "records": 50_183,
        "vertices": 652_379,
        "surface_triangles": 301_098,
        "skirt_triangles": 602_196,
        "triangles": 903_294,
        "data_bytes": 17_965_514,
        "container_bytes": 23_084_180,
        "maximum_record_bytes": 460,
    },
}
EXPECTED_RECORDS = 83_293
EXPECTED_CONTAINER_BYTES = 57_521_020
LEVEL_CENTER_OFFSETS_M = {
    "L8": (1_680, 962),
    "L4": (720, 412),
    "L2": (240, 138),
    "L1": (0, 0),
}


@dataclass(frozen=True, slots=True)
class SourcePoint:
    east_count: int
    north_count: int
    elevation_delta_count: int


@dataclass(frozen=True, slots=True)
class SourceCell:
    cell: HexCell
    points: tuple[SourcePoint, ...]
    selectors: tuple[int, ...]
    stage_buffer_id: int
    uvs: tuple[tuple[int, int], ...]
    minimum_elevation_dm: int
    maximum_elevation_dm: int
    source_path: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class BuiltNode:
    node: HierarchyNode
    cells: tuple[HexCell, ...]
    tile: P3DMTile
    center_east_m: int
    center_north_m: int
    surface_triangles: int
    skirt_triangles: int


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _atomic_json(path: Path, document: dict) -> None:
    _atomic_bytes(
        path,
        (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    return (
        resolved.relative_to(ROOT).as_posix()
        if resolved.is_relative_to(ROOT)
        else str(resolved)
    )


def _source_record_path(cell_id: int) -> Path:
    return (
        Path("TRH")
        / "L0"
        / f"{cell_id >> 8:02X}"
        / f"{cell_id & 255:02X}.AGN"
    )


def _material_mapping() -> list[dict[str, object]]:
    expected = ((0, 85, 255),) + ((170, 170, 170),) * 4 + (
        (0, 170, 85),
    ) * 10
    actual = tuple(material.rgb for material in AGON_SOLID_TERRAIN_MATERIALS)
    if actual != expected:
        raise SystemExit(f"three-color runtime palette changed: {actual!r}")
    return [
        {
            "source_material_id": source.material_id,
            "nlcd_category": source.nlcd_category,
            "semantic_name": source.name,
            "runtime_class": terrain_class(source.material_id),
            "canonical_selector": (0, 1, 5)[terrain_class(source.material_id)],
            "agon_palette_index": AGON_PALETTE_BY_CLASS[
                terrain_class(source.material_id)
            ],
            "rgb8": list(runtime.rgb),
        }
        for source, runtime in zip(
            BERKELEY_TERRAIN_MATERIALS,
            AGON_SOLID_TERRAIN_MATERIALS,
            strict=True,
        )
    ]


def _load_source_world(source: Path) -> tuple[dict, bytes]:
    path = source / "WORLD.json"
    payload = path.read_bytes()
    if sha256_bytes(payload) != SOURCE_WORLD_SHA256:
        raise SystemExit("accepted N=5 WORLD index hash changed")
    try:
        world = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SystemExit("accepted N=5 WORLD index is unreadable") from error
    witness = (
        world.get("schema"),
        len(world.get("records", ())),
        world.get("topology", {}).get("side_steps"),
        world.get("normalization", {}).get("model_half_extent_m"),
    )
    if witness != (SOURCE_SCHEMA, HEX_CELL_COUNT, 5, 1_024):
        raise SystemExit(f"accepted N=5 WORLD contract changed: {witness!r}")
    return world, payload


def _source_cell(cell: HexCell, source_tile: P3DMTile, source_record: dict) -> SourceCell:
    decimated = decimate_l0_tile(cell, source_tile)
    center_east_m, center_north_m = cell.center_m
    keys = (
        (center_east_m * COUNTS_PER_METRE, center_north_m * COUNTS_PER_METRE),
    ) + hex_corners_counts(cell.q, cell.r)
    points = []
    for index, ((east_count, north_count), encoded) in enumerate(
        zip(keys, decimated.tile.positions[:N1_SURFACE_VERTICES], strict=True)
    ):
        expected_x = 2 * (north_count - center_north_m * COUNTS_PER_METRE)
        expected_z = -2 * (east_count - center_east_m * COUNTS_PER_METRE)
        if encoded[0] != expected_x or encoded[2] != expected_z or encoded[1] & 1:
            raise SystemExit(
                f"N=1 source position {index} lost exact count form at "
                f"{cell.q},{cell.r}"
            )
        points.append(SourcePoint(east_count, north_count, encoded[1] // 2))
    return SourceCell(
        cell=cell,
        points=tuple(points),
        selectors=decimated.sector_material_ids,
        stage_buffer_id=decimated.tile.stage_buffer_id,
        uvs=decimated.tile.uvs,
        minimum_elevation_dm=decimated.tile.meta.minimum_elevation_dm,
        maximum_elevation_dm=decimated.tile.meta.maximum_elevation_dm,
        source_path=source_record["path"],
        source_sha256=source_record["sha256"],
    )


def load_source_cells(source: Path, world: dict) -> dict[tuple[int, int], SourceCell]:
    records = sorted(world["records"], key=lambda item: item["cell_id"])
    cells = tuple(iter_cells())
    if len(records) != len(cells):
        raise SystemExit("N=5 WORLD and bounded lattice disagree")
    result = {}
    for ordinal, (record, cell) in enumerate(zip(records, cells, strict=True), 1):
        relative = _source_record_path(cell.cell_id)
        witness = (
            record.get("cell_id"),
            record.get("q"),
            record.get("r"),
            record.get("path"),
            record.get("surface_vertices"),
            record.get("surface_triangles"),
            record.get("skirt_triangles"),
        )
        expected = (
            cell.cell_id,
            cell.q,
            cell.r,
            relative.as_posix(),
            N5_SURFACE_VERTICES,
            N5_SURFACE_TRIANGLES,
            N5_SKIRT_TRIANGLES,
        )
        if witness != expected:
            raise SystemExit(f"N=5 record identity changed: {witness!r}")
        payload = (source / relative).read_bytes()
        if len(payload) != record["bytes"] or sha256_bytes(payload) != record["sha256"]:
            raise SystemExit(f"N=5 record hash changed: {source / relative}")
        tile = parse_container(payload)
        result[(cell.q, cell.r)] = _source_cell(cell, tile, record)
        if ordinal % 500 == 0 or ordinal == HEX_CELL_COUNT:
            print(
                f"REGULAR_HIERARCHY_SOURCE records={ordinal}/{HEX_CELL_COUNT}",
                flush=True,
            )
    return result


def _boundary_edges(
    faces: Sequence[tuple[int, int, int]],
) -> tuple[tuple[int, int, int], ...]:
    counts: Counter[tuple[int, int]] = Counter()
    owners: dict[tuple[int, int], tuple[int, int, int]] = {}
    for face_index, face in enumerate(faces):
        for start, end in zip(face, face[1:] + face[:1], strict=True):
            edge = min(start, end), max(start, end)
            counts[edge] += 1
            owners[edge] = start, end, face_index
    if any(count > 2 for count in counts.values()):
        raise SystemExit("hierarchy node contains a non-manifold surface edge")
    return tuple(owners[edge] for edge in sorted(counts) if counts[edge] == 1)


def _encode_count(delta_count: int, half_extent_m: int) -> int:
    encoded = round(
        Fraction(delta_count * P3DM_COORDINATE_FACTOR, COUNTS_PER_METRE * half_extent_m)
    )
    if not -32_767 <= encoded <= 32_767:
        raise SystemExit(
            f"hierarchy coordinate exceeds guarded extent {half_extent_m}: {encoded}"
        )
    return encoded


def build_node(
    node: HierarchyNode,
    source_cells: dict[tuple[int, int], SourceCell],
) -> BuiltNode:
    cells = bounded_node_cells(node)
    if not cells:
        raise SystemExit(f"attempted to build empty hierarchy node {node.identity}")
    vertex_sources: dict[tuple[int, int], int] = {}
    source_faces: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = []
    surface_materials: list[int] = []
    node_sources = []
    for cell in cells:
        source = source_cells[(cell.q, cell.r)]
        node_sources.append(source)
        keys = tuple((point.east_count, point.north_count) for point in source.points)
        for point, key in zip(source.points, keys, strict=True):
            previous = vertex_sources.setdefault(key, point.elevation_delta_count)
            if previous != point.elevation_delta_count:
                raise SystemExit(f"source N=1 elevation seam differs at {key}")
        for sector, material in enumerate(source.selectors):
            current = 1 + sector
            following = 1 + (sector + 1) % 6
            source_faces.append((keys[0], keys[following], keys[current]))
            surface_materials.append(material)
    ordered_keys = tuple(vertex_sources)
    local_index = {key: index for index, key in enumerate(ordered_keys)}
    surface_faces = [
        tuple(local_index[key] for key in face) for face in source_faces
    ]
    east_counts = [key[0] for key in ordered_keys]
    north_counts = [key[1] for key in ordered_keys]
    center_east_m = round(
        (min(east_counts) + max(east_counts)) / (2 * COUNTS_PER_METRE)
    )
    center_north_m = round(
        (min(north_counts) + max(north_counts)) / (2 * COUNTS_PER_METRE)
    )
    expected_center = node_center_m(node)
    if len(cells) == node.level.width_q * node.level.height_rows and (
        center_east_m,
        center_north_m,
    ) != expected_center:
        raise SystemExit(
            f"complete node center changed: {(center_east_m, center_north_m)} "
            f"!= {expected_center}"
        )
    center_east_count = center_east_m * COUNTS_PER_METRE
    center_north_count = center_north_m * COUNTS_PER_METRE
    positions = [
        (
            _encode_count(north - center_north_count, node.level.model_half_extent_m),
            _encode_count(
                vertex_sources[(east, north)], node.level.model_half_extent_m
            ),
            _encode_count(-(east - center_east_count), node.level.model_half_extent_m),
        )
        for east, north in ordered_keys
    ]
    faces = list(surface_faces)
    materials = list(surface_materials)
    boundary = _boundary_edges(surface_faces)
    bottom_indices: dict[int, int] = {}
    for start, end, owner_face in boundary:
        for top in (start, end):
            if top in bottom_indices:
                continue
            east, north = ordered_keys[top]
            bottom_indices[top] = len(positions)
            positions.append(
                (
                    _encode_count(
                        north - center_north_count,
                        node.level.model_half_extent_m,
                    ),
                    _encode_count(
                        vertex_sources[(east, north)] - SKIRT_DEPTH_COUNTS,
                        node.level.model_half_extent_m,
                    ),
                    _encode_count(
                        -(east - center_east_count),
                        node.level.model_half_extent_m,
                    ),
                )
            )
        bottom_start = bottom_indices[start]
        bottom_end = bottom_indices[end]
        faces.extend(((start, bottom_start, bottom_end), (start, bottom_end, end)))
        materials.extend((surface_materials[owner_face],) * 2)
    template = node_sources[0]
    tile = P3DMTile(
        stage_buffer_id=template.stage_buffer_id,
        meta=P3DMMeta(
            layer_kind=0,
            lod=node.level.lod,
            shading_mode=2,
            illumination=0,
            material_set=0,
            tile_x=node.anchor_q,
            tile_y=node.anchor_offset_row,
            center_east_m=center_east_m - REGIONAL_ORIGIN_EAST_M,
            center_north_m=center_north_m - REGIONAL_ORIGIN_NORTH_M,
            minimum_elevation_dm=min(
                source.minimum_elevation_dm for source in node_sources
            ),
            maximum_elevation_dm=max(
                source.maximum_elevation_dm for source in node_sources
            ),
            model_half_extent_m=node.level.model_half_extent_m,
        ),
        positions=tuple(positions),
        position_indices=tuple(index for face in faces for index in face),
        uvs=template.uvs,
        uv_indices=tuple(material for material in materials for _ in range(3)),
    )
    return BuiltNode(
        node=node,
        cells=cells,
        tile=tile,
        center_east_m=center_east_m,
        center_north_m=center_north_m,
        surface_triangles=len(surface_faces),
        skirt_triangles=2 * len(boundary),
    )


def _copy_resources(destination: Path) -> dict[str, dict[str, object]]:
    result = {}
    for name in RESOURCE_NAMES:
        source = RUNTIME_RESOURCES / name
        payload = source.read_bytes()
        _atomic_bytes(destination / name, payload)
        result[name] = {"bytes": len(payload), "sha256": sha256_bytes(payload)}
    return result


def _assembly_include() -> str:
    """Return corpus geometry metadata; runtime planning has a separate ABI."""

    lines = [
        "; AUTO-GENERATED by scripts/build_regular_lod_corpus.py",
        f"regular_corpus_level_count: equ {len(HIERARCHY_LEVELS)}",
        f"regular_corpus_region_q_max: equ {HEX_Q_MAX}",
        f"regular_corpus_region_even_rows: equ {HEX_EVEN_COLUMN_ROWS}",
        f"regular_corpus_region_odd_rows: equ {HEX_ODD_COLUMN_ROWS}",
        f"regular_corpus_hex_origin_east_m: equ {HEX_ORIGIN_EAST_M}",
        f"regular_corpus_hex_origin_north_m: equ {HEX_ORIGIN_NORTH_M}",
        f"regular_corpus_hex_basis_q_east_m: equ {HEX_BASIS_Q_EAST_M}",
        f"regular_corpus_hex_basis_offset_row_north_m: equ {HEX_BASIS_R_NORTH_M}",
        "regular_corpus_hex_odd_q_north_offset_m: equ 275",
        "regular_corpus_level_record_bytes: equ 16",
        "regular_corpus_level_record_lod: equ 0",
        "regular_corpus_level_record_width_q: equ 1",
        "regular_corpus_level_record_height_rows: equ 2",
        "regular_corpus_level_record_path_code: equ 3",
        "regular_corpus_level_record_model_half_extent_m: equ 4",
        "regular_corpus_level_record_object_scale_q8_8: equ 6",
        "regular_corpus_level_record_q_block_count: equ 8",
        "regular_corpus_level_record_row_block_count: equ 10",
        "regular_corpus_level_record_center_east_offset_m: equ 12",
        "regular_corpus_level_record_center_north_offset_m: equ 14",
    ]
    for path_code, level in enumerate(HIERARCHY_LEVELS):
        prefix = f"regular_corpus_{level.name.lower()}"
        q_blocks = (HEX_Q_MAX + level.width_q) // level.width_q
        row_blocks = (
            HEX_EVEN_COLUMN_ROWS + level.height_rows - 1
        ) // level.height_rows
        east_offset, north_offset = LEVEL_CENTER_OFFSETS_M[level.name]
        lines.extend(
            (
                f"{prefix}_lod: equ {level.lod}",
                f"{prefix}_width_q: equ {level.width_q}",
                f"{prefix}_height_rows: equ {level.height_rows}",
                f"{prefix}_path_code: equ {path_code}",
                f"{prefix}_model_half_extent_m: equ {level.model_half_extent_m}",
                f"{prefix}_object_scale_q8_8: equ {level.object_scale_q8_8}",
                f"{prefix}_q_block_count: equ {q_blocks}",
                f"{prefix}_row_block_count: equ {row_blocks}",
                f"{prefix}_center_east_offset_m: equ {east_offset}",
                f"{prefix}_center_north_offset_m: equ {north_offset}",
            )
        )
    lines.append("regular_corpus_level_records:")
    for path_code, level in enumerate(HIERARCHY_LEVELS):
        q_blocks = (HEX_Q_MAX + level.width_q) // level.width_q
        row_blocks = (
            HEX_EVEN_COLUMN_ROWS + level.height_rows - 1
        ) // level.height_rows
        east_offset, north_offset = LEVEL_CENTER_OFFSETS_M[level.name]
        lines.extend(
            (
                f"    db {level.lod},{level.width_q},{level.height_rows},{path_code}",
                f"    dw {level.model_half_extent_m},{level.object_scale_q8_8}",
                f"    dw {q_blocks},{row_blocks}",
                f"    dw {east_offset},{north_offset}",
            )
        )
    lines.extend(
        (
            "regular_corpus_level_records_end:",
            'regular_corpus_path_l8: db "L8",0',
            'regular_corpus_path_l4: db "L4",0',
            'regular_corpus_path_l2: db "L2",0',
            'regular_corpus_path_l1: db "L1",0',
        )
    )
    return "\n".join(lines) + "\n"


def _build_signature(source_world: bytes) -> str:
    digest = hashlib.sha256(source_world)
    for path in (
        Path(__file__).resolve(),
        ROOT / "src/pingo_terrain/regular_lod.py",
        ROOT / "src/pingo_terrain/hex_terrain.py",
        ROOT / "src/pingo_terrain/p3dm.py",
        ROOT / "src/pingo_terrain/materials.py",
    ):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _phase_evidence() -> list[dict[str, object]]:
    evidence = []
    for phase_q in range(8):
        for phase_row in range(4):
            q = 80 + phase_q
            row = 120 + phase_row
            r = row - q // 2
            validate_hierarchy_plan(q, r, NEAR_RING_MAX)
            plan = select_hierarchy_nodes(q, r, NEAR_RING_MAX)
            counts = Counter(node.level.name for node in plan)
            evidence.append(
                {
                    "phase_q": phase_q,
                    "phase_offset_row": phase_row,
                    "origin": [q, r],
                    "coarse_nodes": len(plan),
                    "total_objects_with_91_fine": len(plan) + 91,
                    "level_counts": {
                        level.name: counts[level.name] for level in HIERARCHY_LEVELS
                    },
                }
            )
    return evidence


def build(args: argparse.Namespace) -> dict:
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to replace existing hierarchy: {output}")
    world, source_world_payload = _load_source_world(source)
    material_mapping = _material_mapping()
    source_cells = load_source_cells(source, world)
    nodes = tuple(iter_hierarchy_nodes())
    if len(nodes) != EXPECTED_RECORDS:
        raise SystemExit(f"hierarchy record count changed: {len(nodes)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent)
    )
    records: list[dict[str, object]] = []
    level_statistics: dict[str, Counter[str]] = {
        level.name: Counter() for level in HIERARCHY_LEVELS
    }
    try:
        for ordinal, node in enumerate(nodes, 1):
            built = build_node(node, source_cells)
            container = make_container(built.tile)
            if len(container) > P3DM_FILE_LIMIT:
                raise SystemExit(
                    f"hierarchy record exceeds {P3DM_FILE_LIMIT}: "
                    f"{node.relative_path} ({len(container)})"
                )
            if parse_container(container) != built.tile:
                raise SystemExit(f"P3DM round trip changed {node.relative_path}")
            relative = Path(node.relative_path)
            _atomic_bytes(staging / relative, container)
            data = make_data(built.tile)
            stats = level_statistics[node.level.name]
            stats["records"] += 1
            stats["cells"] += len(built.cells)
            stats["vertices"] += len(built.tile.positions)
            stats["surface_triangles"] += built.surface_triangles
            stats["skirt_triangles"] += built.skirt_triangles
            stats["triangles"] += built.surface_triangles + built.skirt_triangles
            stats["data_bytes"] += len(data)
            stats["container_bytes"] += len(container)
            stats["maximum_record_bytes"] = max(
                stats["maximum_record_bytes"], len(container)
            )
            records.append(
                {
                    "ordinal": ordinal - 1,
                    "level": node.level.name,
                    "lod": node.level.lod,
                    "anchor_q": node.anchor_q,
                    "anchor_offset_row": node.anchor_offset_row,
                    "path": node.relative_path.as_posix(),
                    "bytes": len(container),
                    "sha256": sha256_bytes(container),
                    "data_bytes": len(data),
                    "data_sha256": sha256_bytes(data),
                    "cells": [[cell.q, cell.r] for cell in built.cells],
                    "cell_count": len(built.cells),
                    "center_utm_m": [built.center_east_m, built.center_north_m],
                    "vertices": len(built.tile.positions),
                    "surface_triangles": built.surface_triangles,
                    "skirt_triangles": built.skirt_triangles,
                    "model_half_extent_m": node.level.model_half_extent_m,
                    "object_scale_q8_8": node.level.object_scale_q8_8,
                    "minimum_elevation_dm": built.tile.meta.minimum_elevation_dm,
                    "maximum_elevation_dm": built.tile.meta.maximum_elevation_dm,
                }
            )
            if ordinal % 500 == 0 or ordinal == len(nodes):
                print(
                    f"REGULAR_HIERARCHY_PROGRESS records={ordinal}/{len(nodes)}",
                    flush=True,
                )
        observed_levels = {
            name: dict(statistics) for name, statistics in level_statistics.items()
        }
        for level_name, expected in EXPECTED_LEVELS.items():
            observed = observed_levels[level_name]
            for key, value in expected.items():
                if key == "surface_triangles" and isinstance(value, str):
                    continue
                if observed.get(key) != value:
                    raise SystemExit(
                        f"{level_name} hierarchy statistic {key} changed: "
                        f"{observed.get(key)} != {value}"
                    )
        total_container_bytes = sum(
            statistics["container_bytes"] for statistics in observed_levels.values()
        )
        if total_container_bytes != EXPECTED_CONTAINER_BYTES:
            raise SystemExit(
                f"hierarchy byte total changed: {total_container_bytes} != "
                f"{EXPECTED_CONTAINER_BYTES}"
            )
        resources = _copy_resources(staging)
        include_payload = _assembly_include().encode("ascii")
        _atomic_bytes(staging / "REGCORP.INC", include_payload)
        phases = _phase_evidence()
        output_world = {
            "schema": OUTPUT_SCHEMA,
            "build_signature": _build_signature(source_world_payload),
            "artifact_role": (
                "complete reusable algorithmic regular N=1 hierarchy derived "
                "from the accepted N=5 corpus"
            ),
            "source": {
                "world_path": _relative_or_absolute(source / "WORLD.json"),
                "world_sha256": SOURCE_WORLD_SHA256,
                "schema": world["schema"],
                "build_signature": world["build_signature"],
                "records": len(source_cells),
            },
            "hierarchy": {
                "coordinate_space": "q and non-negative offset_row",
                "levels": [
                    {
                        "name": level.name,
                        "lod": level.lod,
                        "width_q": level.width_q,
                        "height_rows": level.height_rows,
                        "model_half_extent_m": level.model_half_extent_m,
                        "object_scale_q8_8": level.object_scale_q8_8,
                        "planar_half_extents_m": list(
                            node_planar_half_extents_m(
                                HierarchyNode(level, 0, 0)
                            )
                        ),
                    }
                    for level in HIERARCHY_LEVELS
                ],
                "path_equation": (
                    "RGL/{level}/{anchor_q:02X}/{anchor_offset_row:02X}.AGN"
                ),
                "record_count": len(records),
                "selection": (
                    "retain a node wholly outside the fine disk when it touches "
                    "the ring-6..30 annulus; recursively refine nodes touching "
                    "the fine disk"
                ),
                "outer_overfetch": (
                    "permitted beyond ring 30 only; no overlap with rings 0..5"
                ),
            },
            "geometry": {
                "source_n": 5,
                "target_n": 1,
                "source_vertex_subset": True,
                "material_reduction": (
                    "majority runtime class across each sector's 25 equal-area "
                    "N=5 triangles, lower class wins ties"
                ),
                "node_skirts": "64 m fail-soft outer-boundary skirts",
                "coordinate_encoding": "round(delta_m / H * 32768)",
                "same_lod_warning": (
                    "L8/L4 guarded normalization can introduce independent "
                    "cross-node rounding; decoded seam audit remains required"
                ),
                "mixed_lod_warning": (
                    "N=1 endpoints are an exact N=5 subset, but an explicit "
                    "transition is still required for the four intermediate "
                    "N=5 boundary heights"
                ),
            },
            "runtime_profile": {
                "position_driven": True,
                "fine_l0_rings": [0, NEAR_RING_MAX],
                "coarse_hierarchy_rings": [NEAR_RING_MAX + 1, FAR_RING],
                "fine_objects": 91,
                "coarse_slot_capacity": COARSE_SLOT_COUNT,
                "manager_slot_capacity": MANAGER_SLOT_COUNT,
                "phase_count": len(phases),
                "coarse_nodes_min": min(item["coarse_nodes"] for item in phases),
                "coarse_nodes_max": max(item["coarse_nodes"] for item in phases),
                "total_objects_min": min(
                    item["total_objects_with_91_fine"] for item in phases
                ),
                "total_objects_max": max(
                    item["total_objects_with_91_fine"] for item in phases
                ),
                "phase_evidence": phases,
            },
            "presentation": {
                "exact_three_color_runtime": True,
                "mapping": material_mapping,
                "resources": resources,
            },
            "provider_include": {
                "path": "REGCORP.INC",
                "bytes": len(include_payload),
                "sha256": sha256_bytes(include_payload),
                "level_record_bytes": 16,
            },
            "statistics": {
                "records": len(records),
                "container_bytes": total_container_bytes,
                "levels": observed_levels,
            },
            "records": records,
        }
        _atomic_json(staging / "WORLD.json", output_world)
        staging.replace(output)
    except BaseException:
        print(f"REGULAR_HIERARCHY_INCOMPLETE staging={staging}", file=sys.stderr)
        raise
    return output_world


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    world = build(args)
    statistics = world["statistics"]
    print(
        "REGULAR_N1_HIERARCHY",
        f"records={statistics['records']}",
        f"container_bytes={statistics['container_bytes']}",
        f"active_max={world['runtime_profile']['total_objects_max']}",
        f"output={args.output.expanduser().resolve()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
