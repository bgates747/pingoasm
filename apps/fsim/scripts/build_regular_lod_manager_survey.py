#!/usr/bin/env python3
"""Assemble and install the position-driven regular-LOD manager survey.

The hierarchy corpus, phase table, and full-owner transition recipes are
independent build products.  This script binds them to the universal terrain
manager, validates the exact Marina cold view and generated table contracts,
assembles the fixture, and installs only the small executable and a receipt
beside the already-built hierarchy.  The accepted detailed ``TRH`` tree is
exposed through one checked relative symlink; it is never copied or modified
here.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = ROOT / "fixtures/terrain-manager-survey/src"
FIXTURE = ROOT / "fixtures/terrain-manager-regular-lod-survey"
TARGET = FIXTURE / "tgt"
ASSEMBLY_SOURCE = SOURCE_DIRECTORY / "terrain-manager-regular-lod-survey.asm"
PROVIDER_SOURCE = SOURCE_DIRECTORY / "terrain-manager-regular-lod-provider.inc"
PROGRAM = TARGET / "terrain-manager-regular-lod-survey.bin"
LISTING = TARGET / "terrain-manager-regular-lod-survey.lst"
SYMBOLS = TARGET / "terrain-manager-regular-lod-survey.symbols"
RUNTIME_INCLUDE = TARGET / "regular-lod-runtime.inc"
TRANSITION_INCLUDE = TARGET / "regular-lod-transitions.inc"
DEFAULT_OUTPUT = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
DEFAULT_FINE_CORPUS = ROOT / "build/p3dm/bay-area-hex-full-l0"
RUNTIME_PROGRAM_NAME = "P3DRGL.BIN"
RUNTIME_MANIFEST_NAME = "MANAGER.json"
HIERARCHY_SCHEMA = "pingo-terrain-regular-n1-hierarchy-v1"
MANAGER_SCHEMA = "pingo-terrain-regular-lod-manager-survey-v2"
FINE_WORLD_SHA256 = (
    "43a41bced05f35eaf104e48c906b59e28f4b0ac254ec60fa2b35166b0e707a26"
)
RESOURCE_NAMES = ("MATID.RG2", "PATLUT.BIN", "PATTERN.RG2")
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"
FIXTURE_LOAD_CAPACITY = 0x070000

START_CELL = (80, 125)
START_OFFSET_ROW = 165
START_PHASE = (0, 1)
START_ROTATION = (0, -8_192, 0)
DEFAULT_RADIUS = 5
NEAR_COUNTS = (1, 7, 19, 37, 61, 91)
MARINA_COARSE_COUNTS = (110, 117, 127, 125, 135, 136)
MARINA_DESIRED_COUNTS = (111, 124, 146, 162, 196, 227)
MANAGER_SLOT_COUNT = 255
NEAR_SLOT_COUNT = 91
COARSE_SLOT_COUNT = 164
INITIAL_ACTIVE_COUNT = 227
INITIAL_CONTAINER_BYTES = 787_192
INITIAL_DATA_BYTES = 764_288
INITIAL_VERTICES = 28_232
INITIAL_TRIANGLES = 48_364
INITIAL_MAXIMUM_RECORD_BYTES = 4_568
EXPECTED_HIERARCHY_RECORDS = 83_293
EXPECTED_HIERARCHY_CONTAINER_BYTES = 57_521_020

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import HexCell, hex_center_m  # noqa: E402
from pingo_terrain.p3dm import make_data, parse_container  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
)
from pingo_terrain.regular_lod_runtime import (  # noqa: E402
    ProtectedSlotAllocator,
    all_terrain_transition_recipes,
    build_runtime_plan,
    encode_transition_table,
    emit_phase_include,
    emit_transition_include,
)


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fine-corpus", type=Path, default=DEFAULT_FINE_CORPUS)
    parser.add_argument(
        "--skip-assemble",
        action="store_true",
        help="validate inputs and regenerate the phase include without assembling",
    )
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
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


def _runtime_include() -> dict[str, object]:
    payload = emit_phase_include().encode("ascii")
    _atomic_bytes(RUNTIME_INCLUDE, payload)
    return {
        "path": str(RUNTIME_INCLUDE.relative_to(ROOT)),
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _transition_include() -> dict[str, object]:
    payload = emit_transition_include().encode("ascii")
    recipes = all_terrain_transition_recipes()
    encoded = encode_transition_table(recipes)
    groups = tuple(
        step
        for recipe in recipes
        for step in recipe.schedule.steps
    )
    witness = (
        len(recipes),
        len(groups),
        len(encoded),
        max(step.group.retiring_count for step in groups),
        max(step.group.entering_count for step in groups),
        max(
            step.group.retiring_count + step.group.entering_count
            for step in groups
        ),
        min(recipe.schedule.minimum_staging_margin for recipe in recipes),
    )
    expected = (192, 4_176, 21_504, 14, 14, 15, 4)
    if witness != expected:
        raise SystemExit(f"transition recipe contract changed: {witness} != {expected}")
    _atomic_bytes(TRANSITION_INCLUDE, payload)
    return {
        "path": str(TRANSITION_INCLUDE.relative_to(ROOT)),
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "recipe_count": witness[0],
        "group_count": witness[1],
        "logical_table_bytes": witness[2],
        "logical_table_sha256": sha256_bytes(encoded),
        "maximum_retiring": witness[3],
        "maximum_entering": witness[4],
        "maximum_commit_activity": witness[5],
        "minimum_staging_margin": witness[6],
        "audited_directed_bounded_transitions": 299_306,
    }


def require_hierarchy(output: Path) -> tuple[dict, dict[str, dict]]:
    world_path = output / "WORLD.json"
    include_path = output / "REGCORP.INC"
    if not world_path.is_file() or not include_path.is_file():
        raise SystemExit(
            "build the complete hierarchy first with "
            "scripts/build_regular_lod_corpus.py"
        )
    try:
        document = json.loads(world_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"regular hierarchy manifest is unreadable: {world_path}") from error

    statistics = document.get("statistics", {})
    hierarchy = document.get("hierarchy", {})
    runtime = document.get("runtime_profile", {})
    provider = document.get("provider_include", {})
    witness = (
        document.get("schema"),
        len(document.get("records", ())),
        statistics.get("records"),
        statistics.get("container_bytes"),
        hierarchy.get("record_count"),
        runtime.get("fine_objects"),
        runtime.get("coarse_slot_capacity"),
        runtime.get("manager_slot_capacity"),
        runtime.get("coarse_nodes_min"),
        runtime.get("coarse_nodes_max"),
        runtime.get("total_objects_min"),
        runtime.get("total_objects_max"),
    )
    expected = (
        HIERARCHY_SCHEMA,
        EXPECTED_HIERARCHY_RECORDS,
        EXPECTED_HIERARCHY_RECORDS,
        EXPECTED_HIERARCHY_CONTAINER_BYTES,
        EXPECTED_HIERARCHY_RECORDS,
        NEAR_SLOT_COUNT,
        COARSE_SLOT_COUNT,
        MANAGER_SLOT_COUNT,
        126,
        159,
        217,
        250,
    )
    if witness != expected:
        raise SystemExit(f"regular hierarchy contract changed: {witness} != {expected}")
    include_payload = include_path.read_bytes()
    if (
        provider.get("path") != "REGCORP.INC"
        or provider.get("bytes") != len(include_payload)
        or provider.get("sha256") != sha256_bytes(include_payload)
        or provider.get("level_record_bytes") != 16
    ):
        raise SystemExit("REGCORP.INC no longer matches its hierarchy receipt")
    levels = hierarchy.get("levels", ())
    level_witness = tuple(
        (
            item.get("name"),
            item.get("lod"),
            item.get("width_q"),
            item.get("height_rows"),
            item.get("model_half_extent_m"),
            item.get("object_scale_q8_8"),
        )
        for item in levels
    )
    expected_levels = (
        ("L8", 4, 8, 4, 2_001, 64_032),
        ("L4", 3, 4, 2, 1_041, 33_312),
        ("L2", 2, 2, 1, 1_024, 32_768),
        ("L1", 1, 1, 1, 1_024, 32_768),
    )
    if level_witness != expected_levels:
        raise SystemExit(f"regular hierarchy levels changed: {level_witness}")

    selected_paths = {
        entry.identity.node.relative_path.as_posix()
        for entry in build_runtime_plan(
            ProtectedSlotAllocator(), *START_CELL, DEFAULT_RADIUS
        ).coarse.entries
    }
    selected_records = {
        record["path"]: record
        for record in document["records"]
        if record.get("path") in selected_paths
    }
    if set(selected_records) != selected_paths:
        missing = sorted(selected_paths - set(selected_records))
        raise SystemExit(f"hierarchy WORLD omits Marina records: {missing[:8]}")
    return document, selected_records


def require_fine_corpus(fine: Path) -> dict[str, object]:
    world = fine / "WORLD.json"
    tree = fine / "TRH/L0"
    if not world.is_file() or not tree.is_dir():
        raise SystemExit(f"accepted fine corpus is incomplete: {fine}")
    actual = sha256_file(world)
    if actual != FINE_WORLD_SHA256:
        raise SystemExit(f"accepted fine WORLD changed: {actual}")
    return {
        "world_path": str(world),
        "world_sha256": actual,
        "record_tree": str(tree),
    }


def _fine_relative(cell: HexCell) -> Path:
    return (
        Path("TRH/L0")
        / f"{cell.cell_id >> 8:02X}"
        / f"{cell.cell_id & 0xFF:02X}.AGN"
    )


def initial_runtime_records(
    output: Path,
    fine: Path,
    hierarchy_records: dict[str, dict],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    runtime = build_runtime_plan(
        ProtectedSlotAllocator(), *START_CELL, DEFAULT_RADIUS
    )
    if (
        len(runtime.near_entries),
        len(runtime.coarse.entries),
        runtime.active_count,
    ) != (91, 136, INITIAL_ACTIVE_COUNT):
        raise SystemExit("Marina runtime plan changed")
    if tuple(entry.slot for entry in runtime.coarse.entries) != tuple(range(91, 227)):
        raise SystemExit("cold coarse allocator no longer fills slots 91..226")

    origin_east, origin_north = hex_center_m(*START_CELL)
    records: list[dict[str, object]] = []
    for order, entry in enumerate(runtime.near_entries):
        cell = HexCell(entry.q, entry.r)
        relative = _fine_relative(cell)
        path = fine / relative
        payload = path.read_bytes()
        tile = parse_container(payload)
        if (
            tile.meta.lod,
            tile.meta.tile_x,
            tile.meta.tile_y,
            tile.meta.model_half_extent_m,
        ) != (0, cell.q, cell.r, 1_024):
            raise SystemExit(f"fine P3DM metadata changed: {path}")
        translation = (
            (cell.center_m[1] - origin_north) * 16,
            9_728,
            (cell.center_m[0] - origin_east) * 16,
        )
        records.append(
            _record_receipt(
                order,
                entry.slot,
                0,
                cell.q,
                cell.r,
                relative,
                payload,
                tile,
                translation,
                "fine",
            )
        )

    for coarse_order, entry in enumerate(runtime.coarse.entries):
        order = len(runtime.near_entries) + coarse_order
        relative = Path(entry.identity.node.relative_path)
        metadata = hierarchy_records[relative.as_posix()]
        path = output / relative
        payload = path.read_bytes()
        if (
            len(payload) != metadata.get("bytes")
            or sha256_bytes(payload) != metadata.get("sha256")
        ):
            raise SystemExit(f"hierarchy record witness changed: {path}")
        tile = parse_container(payload)
        level = entry.identity.node.level
        if (
            tile.meta.lod,
            tile.meta.tile_x,
            tile.meta.tile_y,
            tile.meta.model_half_extent_m,
        ) != (
            level.lod,
            entry.anchor_q,
            entry.anchor_offset_row,
            level.model_half_extent_m,
        ):
            raise SystemExit(f"hierarchy P3DM metadata changed: {path}")
        center_east = REGIONAL_ORIGIN_EAST_M + tile.meta.center_east_m
        center_north = REGIONAL_ORIGIN_NORTH_M + tile.meta.center_north_m
        translation = (
            (center_north - origin_north) * 16,
            9_728,
            (center_east - origin_east) * 16,
        )
        records.append(
            _record_receipt(
                order,
                entry.slot,
                level.lod,
                entry.anchor_q,
                entry.anchor_offset_row,
                relative,
                payload,
                tile,
                translation,
                level.name,
            )
        )

    aggregates = {
        "records": len(records),
        "container_bytes": sum(int(record["bytes"]) for record in records),
        "data_bytes": sum(int(record["data_bytes"]) for record in records),
        "vertices": sum(int(record["vertices"]) for record in records),
        "triangles": sum(int(record["triangles"]) for record in records),
        "maximum_record_bytes": max(int(record["bytes"]) for record in records),
        "level_counts": dict(Counter(str(record["level"]) for record in records)),
    }
    expected_aggregates = {
        "records": INITIAL_ACTIVE_COUNT,
        "container_bytes": INITIAL_CONTAINER_BYTES,
        "data_bytes": INITIAL_DATA_BYTES,
        "vertices": INITIAL_VERTICES,
        "triangles": INITIAL_TRIANGLES,
        "maximum_record_bytes": INITIAL_MAXIMUM_RECORD_BYTES,
        "level_counts": {"fine": 91, "L1": 11, "L2": 21, "L4": 6, "L8": 98},
    }
    if aggregates != expected_aggregates:
        raise SystemExit(
            f"Marina runtime aggregate changed: {aggregates} != {expected_aggregates}"
        )
    return records, aggregates


def _record_receipt(
    order: int,
    slot: int,
    lod: int,
    identity_q: int,
    identity_r: int,
    relative: Path,
    payload: bytes,
    tile,
    translation: tuple[int, int, int],
    level: str,
) -> dict[str, object]:
    triangles = len(tile.position_indices) // 3
    return {
        "order": order,
        "slot": slot,
        "mesh_id": slot + 1,
        "object_id": slot + 1,
        "lod": lod,
        "level": level,
        "identity_q": identity_q,
        "identity_r": identity_r,
        "path": relative.as_posix(),
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "data_bytes": len(make_data(tile)),
        "vertices": len(tile.positions),
        "position_indices": len(tile.position_indices),
        "texture_coordinates": len(tile.uvs),
        "texture_indices": len(tile.uv_indices),
        "triangles": triangles,
        "translation_counts": list(translation),
    }


def expose_fine_corpus(output: Path, fine: Path) -> None:
    source = fine / "TRH"
    if not source.is_dir():
        raise SystemExit(f"fine TRH tree is missing: {source}")
    link = output / "TRH"
    expected = Path(os.path.relpath(source, output))
    if link.is_symlink():
        if Path(os.readlink(link)) != expected:
            raise SystemExit(f"refusing to replace unexpected TRH link: {link}")
        return
    if link.exists():
        raise SystemExit(f"refusing to replace non-symlink TRH path: {link}")
    link.symlink_to(expected, target_is_directory=True)


def assemble() -> None:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise SystemExit("ez80asm is not available on PATH")
    if not ASSEMBLY_SOURCE.is_file() or not PROVIDER_SOURCE.is_file():
        raise SystemExit("regular-LOD fixture source/provider is incomplete")
    TARGET.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_adl_width.py"),
            "--follow-includes",
            "--show-review",
            "--fail-review",
            str(ASSEMBLY_SOURCE),
        ],
        cwd=ROOT,
        check=True,
    )
    generated_program = SOURCE_DIRECTORY / PROGRAM.name
    subprocess.run(
        [
            assembler,
            "-l",
            "-s",
            ASSEMBLY_SOURCE.name,
            generated_program.name,
            "-c",
        ],
        cwd=SOURCE_DIRECTORY,
        check=True,
    )
    generated_listing = SOURCE_DIRECTORY / LISTING.name
    generated_symbols = SOURCE_DIRECTORY / SYMBOLS.name
    for path in (generated_program, generated_listing, generated_symbols):
        if not path.is_file():
            raise SystemExit(f"ez80asm omitted expected output: {path}")
    shutil.move(generated_program, PROGRAM)
    shutil.move(generated_listing, LISTING)
    shutil.move(generated_symbols, SYMBOLS)
    payload = PROGRAM.read_bytes()
    if len(payload) > FIXTURE_LOAD_CAPACITY:
        raise SystemExit("regular-LOD fixture exceeds the fixture load window")
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise SystemExit("regular-LOD fixture lost the common fixture entry")


def install(
    output: Path,
    fine: Path,
    hierarchy: dict,
    selected_records: list[dict[str, object]],
    aggregates: dict[str, object],
    runtime_include: dict[str, object],
    transition_include: dict[str, object],
) -> dict:
    expose_fine_corpus(output, fine)
    runtime_program = output / RUNTIME_PROGRAM_NAME
    shutil.copy2(PROGRAM, runtime_program)
    resources = {}
    expected_resources = hierarchy.get("presentation", {}).get("resources", {})
    for name in RESOURCE_NAMES:
        path = output / name
        if not path.is_file():
            raise SystemExit(f"regular hierarchy resource is missing: {path}")
        actual = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        if actual != expected_resources.get(name):
            raise SystemExit(f"regular hierarchy resource changed: {name}")
        resources[name] = actual
    report = {
        "schema": MANAGER_SCHEMA,
        "binary": {
            "path": str(runtime_program),
            "bytes": runtime_program.stat().st_size,
            "sha256": sha256_file(runtime_program),
        },
        "camera": {
            "axial_cell": list(START_CELL),
            "offset_row": START_OFFSET_ROW,
            "local_position_counts": [4_275, 8_000, -466],
            "rotation": list(START_ROTATION),
        },
        "presentation": {
            "background": {
                "policy": "full-frame solid sky behind transparent target",
                "agon_palette_index": 47,
                "attitude_dependent": False,
                "false_ground_enabled": False,
            },
            "terrain": {
                "shading": "flat-pattern",
                "scene_illumination_enabled": False,
                "unity_patterns_are_solid": True,
                "illumination_bands_may_dither": False,
                "agon_palette_indices": [20, 7, 21],
            },
        },
        "manager": {
            "implementation": "runtime/ez80/terrain-manager.inc",
            "provider": PROVIDER_SOURCE.name,
            "default_radius": DEFAULT_RADIUS,
            "maximum_radius": 5,
            "fine_ring_range": [0, 5],
            "coarse_ring_range": [6, 30],
            "near_slots": NEAR_SLOT_COUNT,
            "coarse_slot_capacity": COARSE_SLOT_COUNT,
            "stable_slots": MANAGER_SLOT_COUNT,
            "marina_near_counts": list(NEAR_COUNTS),
            "marina_coarse_counts": list(MARINA_COARSE_COUNTS),
            "marina_desired_counts": list(MARINA_DESIRED_COUNTS),
            "mesh_id_range": [1, MANAGER_SLOT_COUNT],
            "object_id_range": [1, MANAGER_SLOT_COUNT],
            "publication_budget_per_idle_pass": 1,
            "defer_stale_rebase": True,
            "fallback_position_fringe_cells": 1,
            "group_staging_enabled": True,
            "owner_domain": "unified detailed and coarse owners",
            "cold_slot_policy": "91 hashed detailed slots, then coarse slots",
            "post_handoff_slot_policy": "arbitrary authoritative owner-to-slot map",
            "transition_policy": "coverage-component atomic commit",
            "transition_radius": 5,
            "transition_recipe_count": 192,
            "transition_group_count": 4_176,
            "maximum_group_retiring": 14,
            "maximum_group_entering": 14,
            "maximum_group_commit_activity": 15,
            "minimum_group_staging_margin": 4,
            "radius_change_policy": "render-idle cold restart at current origin",
            "runtime_axis_adapter": {
                "source": "X=north,Y=up,Z=-east (reflected)",
                "published": "X=north,Y=up,Z=+east (right-handed)",
                "vertex_z_negated": True,
                "triangle_winding_reversed": True,
            },
            "projection_far_command": 53,
            "projection_far_units": 65_535,
            "phase_q": START_PHASE[0],
            "phase_offset_row": START_PHASE[1],
            "protected_slot_policy": (
                "preserve shared owner identities in their actual slots; stage "
                "each entering coverage component only in inactive slots; "
                "atomically retire and activate its complete owner group"
            ),
        },
        "hierarchy": {
            "world_path": str(output / "WORLD.json"),
            "world_sha256": sha256_file(output / "WORLD.json"),
            "records": EXPECTED_HIERARCHY_RECORDS,
            "container_bytes": EXPECTED_HIERARCHY_CONTAINER_BYTES,
            "runtime_include": runtime_include,
            "transition_include": transition_include,
        },
        "fine_corpus": {
            "world_path": str(fine / "WORLD.json"),
            "world_sha256": FINE_WORLD_SHA256,
            "runtime_link": "TRH",
            "target": str(fine / "TRH"),
        },
        "initial_view": {
            "aggregates": aggregates,
            "records": selected_records,
        },
        "resources": resources,
        "experimental_limits": [
            (
                "adjacent regional handoff recipes are qualified only for an "
                "exact converged radius-five endpoint"
            ),
            (
                "radius zero through four are cold-fill review modes: they do "
                "not normalize regional movement, and translation eventually "
                "stops at the signed local-coordinate boundary"
            ),
            (
                "a radius-key cold restart deactivates the complete endpoint "
                "before its sky-only incremental refill"
            ),
            (
                "retained detailed placement proves only the normal one-cell "
                "origin transition fringe"
            ),
            "skirts are a fail-soft crack mask, not a conforming mixed-LOD seam",
            "L8/L4 records can retain independent same-level quantization",
        ],
    }
    _atomic_json(output / RUNTIME_MANIFEST_NAME, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    output = args.output.expanduser().resolve()
    fine = args.fine_corpus.expanduser().resolve()
    hierarchy, hierarchy_records = require_hierarchy(output)
    require_fine_corpus(fine)
    runtime_include = _runtime_include()
    transition_include = _transition_include()
    records, aggregates = initial_runtime_records(
        output, fine, hierarchy_records
    )
    if args.skip_assemble:
        print(
            "REGULAR_LOD_MANAGER_VALID",
            f"objects={aggregates['records']}",
            f"container_bytes={aggregates['container_bytes']}",
            f"runtime_include_sha256={runtime_include['sha256']}",
            f"transition_include_sha256={transition_include['sha256']}",
            f"output={output}",
        )
        return 0
    if output != DEFAULT_OUTPUT.resolve():
        raise SystemExit(
            "assembly source is pinned to the default hierarchy output; "
            "use --skip-assemble for an alternate validation root"
        )
    assemble()
    report = install(
        output,
        fine,
        hierarchy,
        records,
        aggregates,
        runtime_include,
        transition_include,
    )
    print(
        "REGULAR_LOD_MANAGER",
        f"objects={aggregates['records']}",
        f"binary_bytes={report['binary']['bytes']}",
        f"binary_sha256={report['binary']['sha256']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
