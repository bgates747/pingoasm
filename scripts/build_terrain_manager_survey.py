#!/usr/bin/env python3
"""Build the hex-native universal terrain-manager camera survey."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/terrain-manager-survey"
SOURCE = FIXTURE / "src"
TARGET = FIXTURE / "tgt"
DEFAULT_CORPUS = ROOT / "build/p3dm/bay-area-hex-full-l0"
FULL_WORLD_BYTES = 46_764_348
FULL_WORLD_SHA256 = "43a41bced05f35eaf104e48c906b59e28f4b0ac254ec60fa2b35166b0e707a26"
FULL_BUILD_SIGNATURE = "c20f6939998b5ff2eac79b328641400681f99b82e2b8f1a6ce40a02b61815e10"
FULL_CORPUS_BYTES = 171_224_396
PROGRAM_NAME = "terrain-manager-survey.bin"
PROGRAM = TARGET / PROGRAM_NAME
LISTING = TARGET / "terrain-manager-survey.lst"
SYMBOLS = TARGET / "terrain-manager-survey.symbols"
RUNTIME_PROGRAM_NAME = "P3DHXMG.BIN"
RUNTIME_MANIFEST_NAME = "MANAGER.json"
START_CELL = (90, 121)
START_CANONICAL = (3711, 3496, -1482)
DEFAULT_RADIUS = 2
MAXIMUM_RADIUS = 5
RADIUS_COUNTS = tuple(1 + 3 * radius * (radius + 1) for radius in range(6))
SLOT_COUNT = RADIUS_COUNTS[-1]
MESH_BASE = 1
OBJECT_BASE = 1
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"
FIXTURE_LOAD_CAPACITY = 0x070000
ACCEPTED_RESOURCES = ROOT / "fixtures/berkeley-flight-triangular-dither/tgt"
RESOURCE_SPECS = {
    "terrain-material-ids.rgba2": (
        "MATID.RG2",
        16,
        "13a88af40ba2a90e641349d255ff7c752b11fa84f1f8b976149ec32614afd926",
    ),
    "terrain-patterns.rgba2": (
        "PATTERN.RG2",
        2016,
        "cd1ebe2550335951ce09f80b5de150e4ff34c2da90518e30ad7ba7826f9d686a",
    ),
    "terrain-pattern-lookup.bin": (
        "PATLUT.BIN",
        240,
        "9ed22fb30b1dc56a8f6e706ef9d39d683b9d15d89d69c088bea6b797272b3ee0",
    ),
}

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import (  # noqa: E402
    HEX_BASIS_Q_EAST_M,
    HEX_BASIS_Q_NORTH_M,
    HEX_BASIS_R_EAST_M,
    HEX_BASIS_R_NORTH_M,
    HEX_CELL_COUNT,
    HEX_MODEL_HALF_EXTENT_M,
    HEX_OBJECT_SCALE_Q8_8,
    HEX_TERRAIN_Y_COUNT,
    HexCell,
    cell_from_id,
    disk_offsets,
    hex_topology,
)
from pingo_terrain.p3dm import LayerKind, make_data, parse_container  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    STAGING_BUFFER_ID,
)


REFERENCE_TOPOLOGY = hex_topology(*START_CELL)
SURFACE_VERTICES = len(REFERENCE_TOPOLOGY.keys)
SURFACE_TRIANGLES = len(REFERENCE_TOPOLOGY.faces)
BOUNDARY_VERTICES = len(
    {index for edge in REFERENCE_TOPOLOGY.boundary_edges for index in edge[:2]}
)
SKIRT_TRIANGLES = len(REFERENCE_TOPOLOGY.boundary_edges) * 2
TOTAL_VERTICES = SURFACE_VERTICES + BOUNDARY_VERTICES
TOTAL_TRIANGLES = SURFACE_TRIANGLES + SKIRT_TRIANGLES


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help=f"hex corpus root (default: {DEFAULT_CORPUS})",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def report_path(path: Path) -> str:
    """Prefer stable repo-relative paths, but admit explicit external corpora."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def record_path(corpus: Path, cell: HexCell) -> Path:
    cell_id = cell.cell_id
    return corpus / "TRH/L0" / f"{cell_id >> 8:02X}" / f"{cell_id & 0xFF:02X}.AGN"


def _record_integer(record: dict, key: str, path: Path) -> int:
    value = record.get(key)
    if type(value) is not int:
        raise SystemExit(f"hex WORLD {key} is not an integer for {path}: {value!r}")
    return value


def _record_hash(record: dict, key: str, path: Path) -> str:
    value = record.get(key)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SystemExit(f"hex WORLD {key} is malformed for {path}: {value!r}")
    return value


def validate_corpus_records(
    corpus: Path,
    world: dict,
    indexed: dict[int, dict],
    cells: tuple[HexCell, ...] | range,
) -> None:
    """Fail closed unless every selected WORLD record and P3DM agree exactly."""

    statistics = world.get("statistics")
    if not isinstance(statistics, dict):
        raise SystemExit("hex WORLD statistics are absent or malformed")
    expected_stage_buffer = world.get("stage_buffer_id")
    if expected_stage_buffer != STAGING_BUFFER_ID:
        raise SystemExit(
            "hex WORLD staging-buffer contract changed: "
            f"{expected_stage_buffer!r} != {STAGING_BUFFER_ID}"
        )

    aggregates = {
        "records": 0,
        "container_bytes": 0,
        "data_bytes": 0,
        "vertices": 0,
        "triangles": 0,
    }
    maximum_elevations: list[int] = []

    for item in cells:
        cell = cell_from_id(item) if isinstance(item, int) else item
        path = record_path(corpus, cell)
        relative = path.relative_to(corpus).as_posix()
        record = indexed.get(cell.cell_id)
        if not isinstance(record, dict):
            raise SystemExit(f"hex WORLD omits cell {cell.cell_id}: {relative}")

        identity = (
            _record_integer(record, "cell_id", path),
            _record_integer(record, "q", path),
            _record_integer(record, "r", path),
            _record_integer(record, "offset_row", path),
            _record_integer(record, "lod", path),
            record.get("path"),
        )
        expected_identity = (
            cell.cell_id,
            cell.q,
            cell.r,
            cell.offset_row,
            0,
            relative,
        )
        if identity != expected_identity:
            raise SystemExit(
                f"hex WORLD identity changed for cell {cell.cell_id}: "
                f"{identity} != {expected_identity}"
            )

        expected_bytes = _record_integer(record, "bytes", path)
        expected_hash = _record_hash(record, "sha256", path)
        expected_data_bytes = _record_integer(record, "data_bytes", path)
        expected_data_hash = _record_hash(record, "data_sha256", path)
        if not path.is_file():
            raise SystemExit(f"hex corpus is missing indexed cell: {path}")
        try:
            container = path.read_bytes()
        except OSError as error:
            raise SystemExit(f"cannot read indexed hex cell {path}: {error}") from error
        if len(container) != expected_bytes:
            raise SystemExit(
                f"hex container length changed for {path}: "
                f"{len(container)} != {expected_bytes}"
            )
        actual_hash = sha256_bytes(container)
        if actual_hash != expected_hash:
            raise SystemExit(
                f"hex container SHA-256 changed for {path}: "
                f"{actual_hash} != {expected_hash}"
            )
        try:
            tile = parse_container(container)
        except ValueError as error:
            raise SystemExit(f"invalid indexed P3DM container {path}: {error}") from error
        data = make_data(tile)
        actual_data_hash = sha256_bytes(data)
        if len(data) != expected_data_bytes or actual_data_hash != expected_data_hash:
            raise SystemExit(
                f"hex P3DM DATA witness changed for {path}: "
                f"({len(data)}, {actual_data_hash}) != "
                f"({expected_data_bytes}, {expected_data_hash})"
            )

        center_east_m, center_north_m = cell.center_m
        p3dm_contract = (
            tile.stage_buffer_id,
            tile.meta.layer_kind,
            tile.meta.lod,
            tile.meta.tile_x,
            tile.meta.tile_y,
            tile.meta.center_east_m,
            tile.meta.center_north_m,
            tile.meta.model_half_extent_m,
            len(tile.positions),
            len(tile.position_indices) // 3,
            len(tile.uvs),
        )
        expected_p3dm_contract = (
            STAGING_BUFFER_ID,
            LayerKind.TERRAIN,
            0,
            cell.q,
            cell.r,
            center_east_m - REGIONAL_ORIGIN_EAST_M,
            center_north_m - REGIONAL_ORIGIN_NORTH_M,
            HEX_MODEL_HALF_EXTENT_M,
            TOTAL_VERTICES,
            TOTAL_TRIANGLES,
            16,
        )
        if p3dm_contract != expected_p3dm_contract:
            raise SystemExit(
                f"hex P3DM contract changed for {path}: "
                f"{p3dm_contract} != {expected_p3dm_contract}"
            )

        count_contract = (
            _record_integer(record, "vertices", path),
            _record_integer(record, "surface_vertices", path),
            _record_integer(record, "triangles", path),
            _record_integer(record, "surface_triangles", path),
            _record_integer(record, "skirt_triangles", path),
            _record_integer(record, "maximum_elevation_dm", path),
        )
        expected_count_contract = (
            TOTAL_VERTICES,
            SURFACE_VERTICES,
            TOTAL_TRIANGLES,
            SURFACE_TRIANGLES,
            SKIRT_TRIANGLES,
            tile.meta.maximum_elevation_dm,
        )
        if count_contract != expected_count_contract:
            raise SystemExit(
                f"hex WORLD geometry contract changed for {path}: "
                f"{count_contract} != {expected_count_contract}"
            )

        surface_selectors = tuple(
            tile.uv_indices[triangle * 3]
            for triangle in range(SURFACE_TRIANGLES)
        )
        material_histogram = {
            str(material): count
            for material, count in sorted(Counter(surface_selectors).items())
        }
        if material_histogram != record.get("material_histogram"):
            raise SystemExit(
                f"hex surface-material histogram changed for {path}: "
                f"{material_histogram} != {record.get('material_histogram')!r}"
            )

        aggregates["records"] += 1
        aggregates["container_bytes"] += len(container)
        aggregates["data_bytes"] += len(data)
        aggregates["vertices"] += len(tile.positions)
        aggregates["triangles"] += len(tile.position_indices) // 3
        maximum_elevations.append(tile.meta.maximum_elevation_dm)

    aggregate_witness = {
        **aggregates,
        "maximum_elevation_dm_min": min(maximum_elevations),
        "maximum_elevation_dm_max": max(maximum_elevations),
    }
    expected_aggregate = {
        key: statistics.get(key) for key in aggregate_witness
    }
    if aggregate_witness != expected_aggregate:
        raise SystemExit(
            f"hex corpus aggregate changed: {aggregate_witness} != {expected_aggregate}"
        )


def require_corpus(corpus: Path) -> dict:
    world_path = corpus / "WORLD.json"
    if not world_path.is_file():
        raise SystemExit(
            "Build the hex corpus first with scripts/build_regional_hex_terrain.py"
        )
    world = json.loads(world_path.read_text(encoding="utf-8"))
    selection = world.get("selection")
    expected_records = {
        "campanile-r5": SLOT_COUNT,
        "full": HEX_CELL_COUNT,
    }.get(selection)
    witness = (
        world.get("schema"),
        expected_records,
        world.get("statistics", {}).get("records"),
        world.get("path_equation"),
        world.get("topology", {}).get("basis_q_m"),
        world.get("topology", {}).get("basis_r_m"),
        world.get("normalization", {}).get("object_scale_q8_8"),
        world.get("normalization", {}).get("object_translation_y_count"),
    )
    expected = (
        "pingo-terrain-regional-hex-corpus-v1",
        expected_records,
        expected_records,
        "TRH/L0/{cell_id >> 8:02X}/{cell_id & 255:02X}.AGN",
        [HEX_BASIS_Q_EAST_M, HEX_BASIS_Q_NORTH_M],
        [HEX_BASIS_R_EAST_M, HEX_BASIS_R_NORTH_M],
        HEX_OBJECT_SCALE_Q8_8,
        HEX_TERRAIN_Y_COUNT,
    )
    if expected_records is None or witness != expected:
        raise SystemExit(f"hex corpus contract changed: {witness} != {expected}")
    signature = world.get("build_signature")
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(character not in "0123456789abcdef" for character in signature)
    ):
        raise SystemExit("hex corpus build signature is absent or malformed")
    if selection == "full" and (
        world_path.stat().st_size != FULL_WORLD_BYTES
        or sha256(world_path) != FULL_WORLD_SHA256
        or signature != FULL_BUILD_SIGNATURE
        or world["statistics"].get("container_bytes") != FULL_CORPUS_BYTES
    ):
        raise SystemExit("full hex corpus differs from the qualified WORLD witness")

    start = world.get("canonical_start", {})
    start_witness = (
        start.get("q"),
        start.get("r"),
        start.get("pingo_x_count"),
        start.get("pingo_y_count"),
        start.get("pingo_z_count"),
    )
    if start_witness != (*START_CELL, *START_CANONICAL):
        raise SystemExit(f"hex Campanile start changed: {start_witness}")

    records = world.get("records")
    if not isinstance(records, list) or len(records) != expected_records:
        raise SystemExit("hex WORLD record index is incomplete")
    indexed: dict[int, dict] = {}
    for ordinal, record in enumerate(records):
        if not isinstance(record, dict):
            raise SystemExit(f"hex WORLD record {ordinal} is not an object")
        cell_id = record.get("cell_id")
        if type(cell_id) is not int:
            raise SystemExit(f"hex WORLD record {ordinal} has no integer cell ID")
        if cell_id in indexed:
            raise SystemExit(f"hex WORLD record index repeats cell ID {cell_id}")
        indexed[cell_id] = record
    if len(indexed) != len(records):
        raise SystemExit("hex WORLD record index repeats a cell ID")

    desired = tuple(
        HexCell(START_CELL[0] + dq, START_CELL[1] + dr)
        for dq, dr in disk_offsets(MAXIMUM_RADIUS)
    )
    if len(desired) != SLOT_COUNT or len({cell.cell_id for cell in desired}) != SLOT_COUNT:
        raise AssertionError("radius-five start disk is not exactly 91 unique cells")
    if selection == "full":
        expected_ids = set(range(HEX_CELL_COUNT))
        validation_cells: tuple[HexCell, ...] | range = range(HEX_CELL_COUNT)
    else:
        expected_ids = {cell.cell_id for cell in desired}
        validation_cells = desired
    if set(indexed) != expected_ids:
        raise SystemExit(f"{selection} hex WORLD indexes the wrong cell set")

    validate_corpus_records(corpus, world, indexed, validation_cells)
    return world


def install_resources(corpus: Path) -> dict[str, dict[str, object]]:
    installed: dict[str, dict[str, object]] = {}
    for source_name, (runtime_name, expected_size, expected_hash) in RESOURCE_SPECS.items():
        source = ACCEPTED_RESOURCES / source_name
        if source.stat().st_size != expected_size or sha256(source) != expected_hash:
            raise SystemExit(f"accepted terrain resource changed: {source}")
        destination = corpus / runtime_name
        shutil.copy2(source, destination)
        installed[runtime_name] = {
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }
    return installed


def assemble() -> None:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise SystemExit("ez80asm is not available on PATH")
    TARGET.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_adl_width.py"),
            "--follow-includes",
            "--show-review",
            "--fail-review",
            str(SOURCE / "terrain-manager-survey.asm"),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            assembler,
            "-l",
            "-s",
            "terrain-manager-survey.asm",
            f"../tgt/{PROGRAM_NAME}",
            "-c",
        ],
        cwd=SOURCE,
        check=True,
    )
    generated_listing = SOURCE / "terrain-manager-survey.lst"
    generated_symbols = SOURCE / "terrain-manager-survey.symbols"
    if not generated_listing.is_file() or not generated_symbols.is_file():
        raise SystemExit("ez80asm omitted manager-survey listing/symbols")
    shutil.move(generated_listing, LISTING)
    shutil.move(generated_symbols, SYMBOLS)

    payload = PROGRAM.read_bytes()
    if len(payload) > FIXTURE_LOAD_CAPACITY:
        raise SystemExit("manager survey exceeds the resident-safe fixture window")
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise SystemExit("manager survey does not preserve the common fixture entry")


def main() -> int:
    args = arguments()
    corpus = args.corpus.expanduser().resolve()
    world = require_corpus(corpus)
    resources = install_resources(corpus)
    assemble()
    runtime_program = corpus / RUNTIME_PROGRAM_NAME
    shutil.copy2(PROGRAM, runtime_program)

    report = {
        "schema": "pingo-terrain-manager-survey-v1",
        "binary": {
            "fixture_path": report_path(PROGRAM),
            "runtime_path": report_path(runtime_program),
            "bytes": runtime_program.stat().st_size,
            "sha256": sha256(runtime_program),
        },
        "corpus": {
            "world_path": report_path(corpus / "WORLD.json"),
            "world_sha256": sha256(corpus / "WORLD.json"),
            "selection": world["selection"],
            "records": world["statistics"]["records"],
            "container_bytes": world["statistics"]["container_bytes"],
        },
        "camera": {
            "axial_cell": list(START_CELL),
            "local_position_counts": list(START_CANONICAL),
            "rotation": [0, 0, 0],
        },
        "manager": {
            "topology": "flat-top-axial-hex",
            "default_radius": DEFAULT_RADIUS,
            "maximum_radius": MAXIMUM_RADIUS,
            "radius_cell_counts": list(RADIUS_COUNTS),
            "stable_slots": SLOT_COUNT,
            "mesh_id_range": [MESH_BASE, MESH_BASE + SLOT_COUNT - 1],
            "object_id_range": [OBJECT_BASE, OBJECT_BASE + SLOT_COUNT - 1],
            "publication_budget_per_idle_pass": 1,
            "translation_command": 52,
        },
        "resources": resources,
    }
    runtime_manifest = corpus / RUNTIME_MANIFEST_NAME
    runtime_manifest.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "TERRAIN_MANAGER_SURVEY",
        f"slots={SLOT_COUNT}",
        f"bytes={runtime_program.stat().st_size}",
        f"sha256={sha256(runtime_program)}",
        f"output={runtime_program}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
