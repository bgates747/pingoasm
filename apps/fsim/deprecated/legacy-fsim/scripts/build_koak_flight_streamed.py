#!/usr/bin/env python3
"""Build the streamed KOAK 28L light-flight fixture into its proof corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import agonutils


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "fixtures/koak-flight-streamed/src"
PROOF = ROOT / "build/p3dm/bay-area-koak-proof"
AIRCRAFT_OUTPUT = ROOT / "build/aircraft/pingoasm-jet"
ACCEPTED = ROOT / "fixtures/berkeley-flight-triangular-dither/tgt"
PANEL_SOURCE = ROOT / "assets/cockpit/fsimpanel.png"
AGON64 = Path("/home/smith/Agon/mystuff/agon-utils/examples/palettes/Agon64.gpl")

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.aircraft_asset import build as build_aircraft  # noqa: E402
from pingo_terrain.p3dm import LayerKind, parse_container  # noqa: E402


EXPECTED = {
    "terrain-material-ids.rgba2": (
        16,
        "13a88af40ba2a90e641349d255ff7c752b11fa84f1f8b976149ec32614afd926",
    ),
    "terrain-patterns.rgba2": (
        2016,
        "cd1ebe2550335951ce09f80b5de150e4ff34c2da90518e30ad7ba7826f9d686a",
    ),
    "terrain-pattern-lookup.bin": (
        240,
        "9ed22fb30b1dc56a8f6e706ef9d39d683b9d15d89d69c088bea6b797272b3ee0",
    ),
}
PANEL_SOURCE_SHA256 = (
    "4beb8066ea7baa53914d0c02e67e53b41519f7bdd1da89f30903349527bd7b36"
)
PANEL_RGBA2_SHA256 = (
    "53ca5a440747a7c92854d6c263bb0f9d563aa12636e0f2f4cc538dad50d11fb1"
)
RESOURCE_NAMES = {
    "terrain-material-ids.rgba2": "MATID.RG2",
    "terrain-patterns.rgba2": "PATTERN.RG2",
    "terrain-pattern-lookup.bin": "PATLUT.BIN",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_proof_corpus() -> None:
    required = (
        PROOF / "WORLD.json",
        PROOF / "AIRPORTS.json",
        PROOF / "TRN/L0/73/00.AGN",
        PROOF / "APT/KOAK/P00.AGN",
        PROOF / "APT/KOAK/M00.AGN",
        PROOF / "APT/SOLID64.RG2",
    )
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise SystemExit(
            "Build the regional KOAK proof corpus first; missing:\n"
            + "\n".join(f"  {path}" for path in missing)
        )
    world = json.loads((PROOF / "WORLD.json").read_text(encoding="utf-8"))
    start = world["canonical_start"]
    witness = (
        start["coarse_tile_x"],
        start["coarse_tile_y"],
        start["pingo_x_count"],
        start["initial_pingo_y_count"],
        start["pingo_z_count"],
    )
    if witness != (94, 146, 3106, 64, 2226):
        raise SystemExit(f"KOAK canonical start witness changed: {witness}")
    terrain_paths = sorted((PROOF / "TRN/L0").glob("*/*.AGN"))
    if len(terrain_paths) != 81:
        raise SystemExit(f"KOAK proof must contain 81 L0 cells, found {len(terrain_paths)}")
    for path in terrain_paths:
        terrain = parse_container(path.read_bytes())
        tile_id = int(path.parent.name + path.stem, 16)
        expected_tile = (tile_id % 201, tile_id // 201)
        meta = terrain.meta
        if meta.layer_kind is not LayerKind.TERRAIN or meta.lod != 0:
            raise SystemExit(f"unexpected proof layer/LOD: {path}")
        if (meta.tile_x, meta.tile_y) != expected_tile:
            raise SystemExit(f"path/tile mismatch: {path} -> {expected_tile}")
        expected_center = (meta.tile_x * 512 + 256, meta.tile_y * 512 + 256)
        if (meta.center_east_m, meta.center_north_m) != expected_center:
            raise SystemExit(f"terrain centre mismatch: {path}")
        if meta.model_half_extent_m != 768 or terrain.stage_buffer_id != 0x7400:
            raise SystemExit(f"terrain runtime transform contract changed: {path}")

    pavement = parse_container((PROOF / "APT/KOAK/P00.AGN").read_bytes())
    marking = parse_container((PROOF / "APT/KOAK/M00.AGN").read_bytes())
    if pavement.meta.layer_kind is not LayerKind.AIRPORT_PAVEMENT:
        raise SystemExit("KOAK P00 is not an airport-pavement component")
    if marking.meta.layer_kind is not LayerKind.AIRPORT_MARKING:
        raise SystemExit("KOAK M00 is not an airport-marking component")
    airport_witnesses = (
        pavement.meta.tile_x,
        pavement.meta.tile_y,
        pavement.meta.center_east_m,
        pavement.meta.center_north_m,
        pavement.meta.model_half_extent_m,
    )
    if airport_witnesses != (91, 145, 46708, 74497, 1658):
        raise SystemExit(f"KOAK group-0 transform changed: {airport_witnesses}")
    if (
        marking.meta.tile_x,
        marking.meta.tile_y,
        marking.meta.center_east_m,
        marking.meta.center_north_m,
        marking.meta.model_half_extent_m,
    ) != airport_witnesses:
        raise SystemExit("KOAK P00/M00 no longer share one transform")


def install_resources() -> dict[str, dict[str, object]]:
    installed: dict[str, dict[str, object]] = {}
    for source_name, destination_name in RESOURCE_NAMES.items():
        source = ACCEPTED / source_name
        expected_size, expected_hash = EXPECTED[source_name]
        if source.stat().st_size != expected_size or sha256(source) != expected_hash:
            raise SystemExit(f"accepted resource identity changed: {source}")
        destination = PROOF / destination_name
        shutil.copy2(source, destination)
        installed[destination_name] = {
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }

    if sha256(PANEL_SOURCE) != PANEL_SOURCE_SHA256:
        raise SystemExit("cockpit source identity changed")
    panel = PROOF / "PANEL.RG2"
    agonutils.img_to_rgba2(str(PANEL_SOURCE), str(panel), str(AGON64), "rgb", None)
    if panel.stat().st_size != 320 * 92 or sha256(panel) != PANEL_RGBA2_SHA256:
        raise SystemExit("cockpit RGBA2222 conversion changed")
    installed[panel.name] = {"bytes": panel.stat().st_size, "sha256": sha256(panel)}

    aircraft_manifest = build_aircraft(AIRCRAFT_OUTPUT)
    jet = AIRCRAFT_OUTPUT / "JET64.RG2"
    shutil.copy2(jet, PROOF / jet.name)
    installed[jet.name] = {
        "bytes": jet.stat().st_size,
        "sha256": sha256(PROOF / jet.name),
    }
    installed["aircraft_manifest"] = aircraft_manifest
    return installed


def main() -> int:
    require_proof_corpus()
    resources = install_resources()
    output = PROOF / "P3DFSIM.BIN"
    subprocess.run(
        [
            "ez80asm",
            "koak-flight-streamed.asm",
            "../../../build/p3dm/bay-area-koak-proof/P3DFSIM.BIN",
        ],
        cwd=SOURCE,
        check=True,
    )
    report = {
        "schema": "pingo-terrain-koak-flight-v1",
        "binary": {
            "path": output.name,
            "bytes": output.stat().st_size,
            "sha256": sha256(output),
        },
        "canonical_camera": {
            "coarse_tile": [94, 146],
            "translation_counts": [3106, 64, 2226],
            "yaw": -14411,
        },
        "aircraft_reference_counts": [3088, 44, 2181],
        "active_object_limit": 28,
        "terrain_slots": 25,
        "resources": resources,
    }
    (PROOF / "FLIGHT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "KOAK_FLIGHT_STREAMED",
        f"binary_bytes={output.stat().st_size}",
        f"binary_sha256={sha256(output)}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
