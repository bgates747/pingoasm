#!/usr/bin/env python3
"""Build the full-corpus, no-dynamics Bay Area camera survey fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/regional-camera-survey"
SOURCE = FIXTURE / "src"
TARGET = FIXTURE / "tgt"
CORPUS = ROOT / "build/p3dm/bay-area-full-l0"
WORLD = CORPUS / "WORLD.json"
PROGRAM_NAME = "regional-camera-survey.bin"
PROGRAM = TARGET / PROGRAM_NAME
LISTING = TARGET / "regional-camera-survey.lst"
SYMBOLS = TARGET / "regional-camera-survey.symbols"
RUNTIME_PROGRAM = CORPUS / "P3DSURV.BIN"
ACCEPTED = ROOT / "fixtures/berkeley-flight-triangular-dither/tgt"
TRACKED_RECEIPT = ROOT / "data/manifests/bay-area-full-l0-2026-08-02.json"
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"
START_TILE = (85, 179)
START_CANONICAL = (-1857, 3496, 3638)
FRAME_Z_BIAS = 12288
WINDOW_X = tuple(range(-2, 6))
WINDOW_Y = tuple(range(-2, 2))
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

from pingo_terrain.p3dm import LayerKind, parse_container  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def terrain_path(tile_x: int, tile_y: int) -> Path:
    tile_id = tile_y * 201 + tile_x
    return CORPUS / "TRN/L0" / f"{tile_id >> 8:02X}" / f"{tile_id & 255:02X}.AGN"


def require_corpus() -> dict:
    if not WORLD.is_file() or not TRACKED_RECEIPT.is_file():
        raise SystemExit(
            "Build the full L0 corpus first with scripts/build_regional_terrain.py"
        )
    receipt = json.loads(TRACKED_RECEIPT.read_text(encoding="utf-8"))
    world_receipt = receipt["world_manifest"]
    if WORLD.stat().st_size != world_receipt["byte_size"]:
        raise SystemExit("full-corpus WORLD.json length differs from tracked receipt")
    if sha256(WORLD) != world_receipt["sha256"]:
        raise SystemExit("full-corpus WORLD.json hash differs from tracked receipt")
    world = json.loads(WORLD.read_text(encoding="utf-8"))
    grid = world["world_grid"]
    statistics = world["statistics"]
    witness = (
        world["selection"],
        grid["columns"],
        grid["rows"],
        grid["chunk_width_m"],
        statistics["records"],
        statistics["container_bytes"],
    )
    expected = ("full", 201, 252, 512, 50652, 269883360)
    if witness != expected:
        raise SystemExit(f"regional corpus contract changed: {witness} != {expected}")

    records = world.get("records")
    if not isinstance(records, list) or len(records) != statistics["records"]:
        raise SystemExit("full-corpus WORLD.json record index is incomplete")
    seen_paths: set[str] = set()
    verified_bytes = 0
    for record in records:
        tile_x = int(record["tile_x"])
        tile_y = int(record["tile_y"])
        tile_id = int(record["tile_id"])
        expected_id = tile_y * grid["columns"] + tile_x
        expected_path = f"TRN/L0/{tile_id >> 8:02X}/{tile_id & 255:02X}.AGN"
        relative_path = str(record["path"])
        if (
            tile_id != expected_id
            or int(record["lod"]) != 0
            or relative_path != expected_path
            or relative_path in seen_paths
        ):
            raise SystemExit(
                f"full-corpus record/path contract failed: {relative_path}"
            )
        seen_paths.add(relative_path)
        path = CORPUS / relative_path
        if not path.is_file():
            raise SystemExit(f"full corpus is missing component: {path}")
        expected_bytes = int(record["bytes"])
        if path.stat().st_size != expected_bytes:
            raise SystemExit(f"full-corpus component length changed: {path}")
        if sha256(path) != record["sha256"]:
            raise SystemExit(f"full-corpus component hash changed: {path}")
        verified_bytes += expected_bytes
    if verified_bytes != statistics["container_bytes"]:
        raise SystemExit(
            "full-corpus indexed byte total differs from WORLD statistics"
        )

    paths = [
        terrain_path(START_TILE[0] + dx, START_TILE[1] + dy)
        for dy in WINDOW_Y
        for dx in WINDOW_X
    ]
    if len(paths) != 32 or len(set(paths)) != 32:
        raise AssertionError("regional start window is not an exact 8x4 set")
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"full corpus is missing start-window component: {path}")
        tile = parse_container(path.read_bytes())
        if tile.meta.layer_kind is not LayerKind.TERRAIN or tile.meta.lod != 0:
            raise SystemExit(f"start-window record has wrong layer/LOD: {path}")
        tile_id = int(path.parent.name + path.stem, 16)
        if (tile.meta.tile_x, tile.meta.tile_y) != (tile_id % 201, tile_id // 201):
            raise SystemExit(f"start-window path/metadata mismatch: {path}")
    return world


def install_resources() -> dict[str, dict[str, object]]:
    installed: dict[str, dict[str, object]] = {}
    for source_name, (runtime_name, expected_size, expected_hash) in RESOURCE_SPECS.items():
        source = ACCEPTED / source_name
        if source.stat().st_size != expected_size or sha256(source) != expected_hash:
            raise SystemExit(f"accepted terrain resource changed: {source}")
        destination = CORPUS / runtime_name
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
            str(SOURCE / "regional-camera-survey.asm"),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            assembler,
            "-l",
            "-s",
            "regional-camera-survey.asm",
            f"../tgt/{PROGRAM_NAME}",
            "-c",
        ],
        cwd=SOURCE,
        check=True,
    )
    generated_listing = SOURCE / "regional-camera-survey.lst"
    generated_symbols = SOURCE / "regional-camera-survey.symbols"
    if not generated_listing.is_file() or not generated_symbols.is_file():
        raise SystemExit("ez80asm omitted regional survey listing/symbols")
    shutil.move(generated_listing, LISTING)
    shutil.move(generated_symbols, SYMBOLS)
    payload = PROGRAM.read_bytes()
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise SystemExit("regional survey does not preserve the common fixture entry")
    shutil.copy2(PROGRAM, RUNTIME_PROGRAM)


def main() -> int:
    world = require_corpus()
    resources = install_resources()
    assemble()
    report = {
        "schema": "pingo-terrain-regional-camera-survey-v1",
        "binary": {
            "fixture_path": str(PROGRAM.relative_to(ROOT)),
            "runtime_path": str(RUNTIME_PROGRAM.relative_to(ROOT)),
            "bytes": RUNTIME_PROGRAM.stat().st_size,
            "sha256": sha256(RUNTIME_PROGRAM),
        },
        "corpus": {
            "world_path": str(WORLD.relative_to(ROOT)),
            "world_sha256": sha256(WORLD),
            "records": world["statistics"]["records"],
            "container_bytes": world["statistics"]["container_bytes"],
            "verified_records": len(world["records"]),
            "verified_container_bytes": sum(
                int(record["bytes"]) for record in world["records"]
            ),
        },
        "camera": {
            "coarse_tile": list(START_TILE),
            "canonical_fine_counts": list(START_CANONICAL),
            "render_frame_z_bias": FRAME_Z_BIAS,
            "render_frame_position_counts": [
                START_CANONICAL[0],
                START_CANONICAL[1],
                START_CANONICAL[2] + FRAME_Z_BIAS,
            ],
            "rotation": [0, 0, 0],
        },
        "window": {
            "slots": 32,
            "x_offsets": [min(WINDOW_X), max(WINDOW_X)],
            "y_offsets": [min(WINDOW_Y), max(WINDOW_Y)],
            "slot_equation": "(tile_y & 3) * 8 + (tile_x & 7)",
        },
        "resources": resources,
    }
    manifest = CORPUS / "SURVEY.json"
    manifest.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "REGIONAL_CAMERA_SURVEY",
        f"bytes={RUNTIME_PROGRAM.stat().st_size}",
        f"sha256={sha256(RUNTIME_PROGRAM)}",
        f"output={RUNTIME_PROGRAM}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
