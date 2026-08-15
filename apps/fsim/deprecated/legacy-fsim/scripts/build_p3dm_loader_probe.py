#!/usr/bin/env python3
"""Build the one-file eZ80 AGNB/P3DM publication probe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SOURCE_FIXTURE = ROOT / "fixtures/berkeley-flight-triangular-dither"
PROBE = ROOT / "fixtures/p3dm-loader-probe"
SOURCE = PROBE / "src"
TARGET = PROBE / "tgt"
PROFILE = ROOT / "profiles/berkeley-flight-triangular-dither.json"
TILE_INDEX = 12
TILE_COLUMN = 4
TILE_ROW = 1
RUNTIME_PATH = Path("TRN/L0/00/0C.AGN")
LOADER_FILE_WINDOW = 16_384

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_berkeley_p3dm import tile_from_include  # noqa: E402
from pingo_terrain.p3dm import make_container, make_data, parse_container  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    generated = SOURCE_FIXTURE / "src/generated" / f"terrain_{TILE_INDEX:02d}.inc"
    tile = tile_from_include(
        generated,
        index=TILE_INDEX,
        column=TILE_COLUMN,
        row=TILE_ROW,
        profile=profile,
    )
    container = make_container(tile)
    if parse_container(container) != tile:
        raise SystemExit("P3DM probe container did not round-trip")
    if tile.stage_buffer_id != 0x7400:
        raise SystemExit("P3DM probe requires staging buffer 0x7400")
    if len(container) > LOADER_FILE_WINDOW:
        raise SystemExit(
            f"P3DM probe container exceeds its {LOADER_FILE_WINDOW}-byte reader window"
        )

    destination = TARGET / RUNTIME_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(container)
    for name in (
        "terrain-material-ids.rgba2",
        "terrain-pattern-lookup.bin",
        "terrain-patterns.rgba2",
    ):
        shutil.copy2(SOURCE_FIXTURE / "tgt" / name, TARGET / name)

    output = TARGET / "p3dm-loader-probe.bin"
    subprocess.run(
        ["ez80asm", "p3dm-loader-probe.asm", "../tgt/p3dm-loader-probe.bin"],
        cwd=SOURCE,
        check=True,
    )
    data = make_data(tile)
    report = {
        "schema": "pingo-terrain-p3dm-loader-probe-v1",
        "runtime_path": RUNTIME_PATH.as_posix(),
        "container_bytes": len(container),
        "container_sha256": sha256(destination),
        "data_bytes": len(data),
        "data_sha256": hashlib.sha256(data).hexdigest(),
        "binary_bytes": output.stat().st_size,
        "binary_sha256": sha256(output),
        "stage_buffer_id": tile.stage_buffer_id,
        "mesh_id": 1,
        "object_id": 1,
        "tile_x": tile.meta.tile_x,
        "tile_y": tile.meta.tile_y,
        "vertices": len(tile.positions),
        "triangles": len(tile.position_indices) // 3,
    }
    (TARGET / "probe.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "P3DM_LOADER_PROBE",
        f"container={len(container)}",
        f"data={len(data)}",
        f"vertices={len(tile.positions)}",
        f"triangles={len(tile.position_indices) // 3}",
        f"binary_sha256={report['binary_sha256']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
