#!/usr/bin/env python3
"""Assemble and install the Marina ring-30 mixed-distance control fixture.

The coarse records and their generated assembly table must first be exported
from the pinned regular-hex Blender review with
``export_distance_lod_control_blender.py``.  This builder deliberately leaves
the qualified natural corpus untouched and exposes its ``NAT`` directory to
the sibling runtime root through one checked relative symlink.
"""

from __future__ import annotations

import argparse
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
FIXTURE = ROOT / "fixtures/terrain-manager-distance-survey"
TARGET = FIXTURE / "tgt"
ASSEMBLY_SOURCE = SOURCE_DIRECTORY / "terrain-manager-distance-survey.asm"
PROGRAM = TARGET / "terrain-manager-distance-survey.bin"
LISTING = TARGET / "terrain-manager-distance-survey.lst"
SYMBOLS = TARGET / "terrain-manager-distance-survey.symbols"
PLAN = TARGET / "distance-lod-plan.inc"
DEFAULT_OUTPUT = ROOT / "build/p3dm/bay-area-distance-lod-control"
NATURAL_OUTPUT = ROOT / "build/p3dm/bay-area-natural-full-l0"
RUNTIME_PROGRAM_NAME = "P3DDST.BIN"
RUNTIME_MANIFEST_NAME = "MANAGER.json"
PLAN_SCHEMA = "pingo-terrain-distance-lod-control-v1"
MANAGER_SCHEMA = "pingo-terrain-distance-lod-manager-v1"
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"
FIXTURE_LOAD_CAPACITY = 0x070000
EXPECTED_CHUNKS = 92
EXPECTED_NEAR_SLOTS = 91
EXPECTED_SLOT_COUNT = EXPECTED_NEAR_SLOTS + EXPECTED_CHUNKS
EXPECTED_SURFACE_TRIANGLES = 16_200
EXPECTED_SKIRT_TRIANGLES = 7_624
EXPECTED_CONTAINER_BYTES = 384_488
EXPECTED_MAXIMUM_RECORD_BYTES = 5_600
EXPECTED_MODEL_HALF_EXTENT_M = 1_792
EXPECTED_OBJECT_SCALE_Q8_8 = 57_344

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.p3dm import parse_container  # noqa: E402


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-assemble", action="store_true")
    return parser.parse_args(argv)


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


def require_distance_plan(output: Path) -> dict:
    manifest = output / "DISTANCE.json"
    include = output / "DISTLOD.INC"
    if not manifest.is_file() or not include.is_file():
        raise SystemExit(
            "export the distance control through Blender before assembling it"
        )
    try:
        report = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"distance plan is unreadable: {manifest}") from error
    geometry = report.get("geometry", {})
    witness = (
        report.get("schema"),
        len(report.get("records", ())),
        geometry.get("chunks"),
        geometry.get("surface_triangles"),
        geometry.get("skirt_triangles"),
        geometry.get("container_bytes"),
        geometry.get("maximum_record_bytes"),
        geometry.get("model_half_extent_m"),
        geometry.get("object_scale_q8_8"),
    )
    expected = (
        PLAN_SCHEMA,
        EXPECTED_CHUNKS,
        EXPECTED_CHUNKS,
        EXPECTED_SURFACE_TRIANGLES,
        EXPECTED_SKIRT_TRIANGLES,
        EXPECTED_CONTAINER_BYTES,
        EXPECTED_MAXIMUM_RECORD_BYTES,
        EXPECTED_MODEL_HALF_EXTENT_M,
        EXPECTED_OBJECT_SCALE_Q8_8,
    )
    if witness != expected:
        raise SystemExit(f"distance plan changed: {witness} != {expected}")

    total = 0
    expected_paths: set[str] = set()
    for ordinal, record in enumerate(report["records"]):
        expected_path = f"DST/{ordinal >> 8:02X}/{ordinal & 0xFF:02X}.AGN"
        record_witness = (
            record.get("ordinal"),
            record.get("path"),
            record.get("lod"),
            record.get("tier"),
        )
        if record_witness != (
            ordinal,
            expected_path,
            record.get("tier"),
            record.get("tier"),
        ):
            raise SystemExit(f"distance record identity changed: {record_witness}")
        path = output / expected_path
        if not path.is_file():
            raise SystemExit(f"distance record is missing: {path}")
        payload = path.read_bytes()
        if len(payload) != record.get("bytes") or sha256_file(path) != record.get(
            "sha256"
        ):
            raise SystemExit(f"distance record witness changed: {path}")
        tile = parse_container(payload)
        if (
            tile.meta.lod,
            tile.meta.tile_x,
            tile.meta.tile_y,
            tile.meta.model_half_extent_m,
        ) != (
            record["tier"],
            record["bucket_q"],
            record["bucket_r"],
            EXPECTED_MODEL_HALF_EXTENT_M,
        ):
            raise SystemExit(f"distance P3DM metadata changed: {path}")
        total += len(payload)
        expected_paths.add(expected_path)
    actual_paths = {
        path.relative_to(output).as_posix() for path in (output / "DST").rglob("*.AGN")
    }
    if actual_paths != expected_paths or total != EXPECTED_CONTAINER_BYTES:
        raise SystemExit("distance record set contains missing or unexpected files")

    include_text = include.read_text(encoding="ascii")
    required_literals = (
        f"distance_lod_chunk_count: equ {EXPECTED_CHUNKS}",
        f"distance_lod_near_slot_count: equ {EXPECTED_NEAR_SLOTS}",
        f"distance_lod_object_scale_q8_8: equ {EXPECTED_OBJECT_SCALE_Q8_8}",
        "distance_lod_record_bytes: equ 14",
    )
    if any(literal not in include_text for literal in required_literals):
        raise SystemExit("generated distance assembly plan has the wrong ABI")
    if "distance_lod_record_bytes: equ 14" not in include_text:
        raise SystemExit("distance provider record-pointer stride changed")
    return report


def expose_natural_corpus(output: Path) -> None:
    source = NATURAL_OUTPUT / "NAT"
    if not source.is_dir():
        raise SystemExit(f"complete natural corpus is missing: {source}")
    link = output / "NAT"
    expected = Path(os.path.relpath(source, output))
    if link.is_symlink():
        if Path(os.readlink(link)) != expected:
            raise SystemExit(f"refusing to replace unexpected NAT link: {link}")
        return
    if link.exists():
        raise SystemExit(f"refusing to replace non-symlink NAT path: {link}")
    link.symlink_to(expected, target_is_directory=True)


def assemble(output: Path) -> None:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise SystemExit("ez80asm is not available on PATH")
    TARGET.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / "DISTLOD.INC", PLAN)
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
        raise SystemExit("distance fixture exceeds the fixture load window")
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise SystemExit("distance fixture lost the common fixture entry")


def install(output: Path, plan: dict) -> dict:
    expose_natural_corpus(output)
    runtime_program = output / RUNTIME_PROGRAM_NAME
    shutil.copy2(PROGRAM, runtime_program)
    resources = {}
    for name in ("MATID.RG2", "PATTERN.RG2", "PATLUT.BIN"):
        path = output / name
        if not path.is_file():
            raise SystemExit(f"distance fixture resource is missing: {path}")
        resources[name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    report = {
        "schema": MANAGER_SCHEMA,
        "binary": {
            "path": str(runtime_program),
            "bytes": runtime_program.stat().st_size,
            "sha256": sha256_file(runtime_program),
        },
        "camera": {
            "axial_cell": [80, 125],
            "local_position_counts": [4275, 8000, 466],
            "rotation": [-1820, 8192, 0],
        },
        "manager": {
            "implementation": "runtime/ez80/terrain-manager.inc",
            "provider": "terrain-manager-distance-provider.inc",
            "near_ring_range": [0, 5],
            "middle_ring_range": [6, 15],
            "far_ring_range": [16, 30],
            "near_slots": EXPECTED_NEAR_SLOTS,
            "coarse_slots": EXPECTED_CHUNKS,
            "stable_slots": EXPECTED_SLOT_COUNT,
            "radius_desired_counts": [93, 99, 111, 129, 153, 183],
            "mesh_id_range": [1, EXPECTED_SLOT_COUNT],
            "object_id_range": [1, EXPECTED_SLOT_COUNT],
            "publication_budget_per_idle_pass": 1,
            "projection_far_command": 53,
            "projection_far_units": 65_535,
            "coarse_origin_policy": "fixed plan translated against current manager origin",
        },
        "geometry": plan["geometry"],
        "distance_plan": {
            "path": str(output / "DISTANCE.json"),
            "sha256": sha256_file(output / "DISTANCE.json"),
            "include_sha256": sha256_file(output / "DISTLOD.INC"),
        },
        "natural_corpus": {
            "target": str(NATURAL_OUTPUT / "NAT"),
            "runtime_link": "NAT",
        },
        "resources": resources,
        "experimental_limits": [
            "regular L1 and L2 currently share the same six-triangle cell topology",
            "natural-to-regular ring boundary is nonconforming",
            "chunk skirts are a fail-soft crack mask, not a seam solution",
            "coarse annulus is static around the Marina for this visual control",
        ],
    }
    _atomic_json(output / RUNTIME_MANIFEST_NAME, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    output = args.output.expanduser().resolve()
    plan = require_distance_plan(output)
    if args.skip_assemble:
        print(
            "DISTANCE_LOD_VALID",
            f"chunks={EXPECTED_CHUNKS}",
            f"triangles={EXPECTED_SURFACE_TRIANGLES + EXPECTED_SKIRT_TRIANGLES}",
            f"output={output}",
        )
        return 0
    assemble(output)
    report = install(output, plan)
    print(
        "DISTANCE_LOD_MANAGER",
        f"objects={EXPECTED_SLOT_COUNT}",
        f"triangles={EXPECTED_SURFACE_TRIANGLES + EXPECTED_SKIRT_TRIANGLES}",
        f"binary_bytes={report['binary']['bytes']}",
        f"binary_sha256={report['binary']['sha256']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
