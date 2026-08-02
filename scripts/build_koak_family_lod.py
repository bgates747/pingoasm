#!/usr/bin/env python3
"""Build the fixed-west nested-family KOAK flight proof."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import agonutils


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "fixtures/koak-flight-family-lod/src"
TARGET = ROOT / "fixtures/koak-flight-family-lod/tgt"
OUTPUT = ROOT / "build/p3dm/bay-area-koak-family-proof"
LOOSE_PROOF = ROOT / "build/p3dm/bay-area-koak-proof"
AIRCRAFT_OUTPUT = ROOT / "build/aircraft/pingoasm-jet"
ACCEPTED = ROOT / "fixtures/berkeley-flight-triangular-dither/tgt"
PANEL_SOURCE = ROOT / "assets/cockpit/fsimpanel.png"
AGON64 = Path("/home/smith/Agon/mystuff/agon-utils/examples/palettes/Agon64.gpl")

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.aircraft_asset import build as build_aircraft  # noqa: E402
from pingo_terrain.family_transition import (  # noqa: E402
    assembly_include,
    build_fixed_west_transition,
)
from pingo_terrain.p3dm import LayerKind, parse_container  # noqa: E402
from pingo_terrain.regional_lod import build_pinned_family_set  # noqa: E402


EXPECTED_RESOURCES = {
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
PANEL_SOURCE_SHA256 = (
    "4beb8066ea7baa53914d0c02e67e53b41519f7bdd1da89f30903349527bd7b36"
)
PANEL_RGBA2_SHA256 = (
    "53ca5a440747a7c92854d6c263bb0f9d563aa12636e0f2f4cc538dad50d11fb1"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def install_shared_resources() -> dict[str, dict[str, object]]:
    installed: dict[str, dict[str, object]] = {}
    for source_name, (destination_name, expected_size, expected_hash) in (
        EXPECTED_RESOURCES.items()
    ):
        source = ACCEPTED / source_name
        if source.stat().st_size != expected_size or sha256(source) != expected_hash:
            raise SystemExit(f"accepted terrain resource changed: {source}")
        destination = OUTPUT / destination_name
        shutil.copy2(source, destination)
        installed[destination_name] = {
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }

    if sha256(PANEL_SOURCE) != PANEL_SOURCE_SHA256:
        raise SystemExit("cockpit source identity changed")
    panel = OUTPUT / "PANEL.RG2"
    agonutils.img_to_rgba2(str(PANEL_SOURCE), str(panel), str(AGON64), "rgb", None)
    if panel.stat().st_size != 320 * 92 or sha256(panel) != PANEL_RGBA2_SHA256:
        raise SystemExit("cockpit RGBA2222 conversion changed")
    installed[panel.name] = {
        "bytes": panel.stat().st_size,
        "sha256": sha256(panel),
    }

    aircraft_manifest = build_aircraft(AIRCRAFT_OUTPUT)
    jet = AIRCRAFT_OUTPUT / "JET64.RG2"
    shutil.copy2(jet, OUTPUT / jet.name)
    installed[jet.name] = {
        "bytes": jet.stat().st_size,
        "sha256": sha256(OUTPUT / jet.name),
    }
    installed["aircraft_manifest"] = aircraft_manifest

    for relative in (
        Path("APT/KOAK/P00.AGN"),
        Path("APT/KOAK/M00.AGN"),
        Path("APT/SOLID64.RG2"),
    ):
        source = LOOSE_PROOF / relative
        if not source.is_file():
            raise SystemExit(f"build the accepted KOAK proof first: missing {source}")
        destination = OUTPUT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        installed[relative.as_posix()] = {
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }
    pavement = parse_container((OUTPUT / "APT/KOAK/P00.AGN").read_bytes())
    marking = parse_container((OUTPUT / "APT/KOAK/M00.AGN").read_bytes())
    if pavement.meta.layer_kind is not LayerKind.AIRPORT_PAVEMENT:
        raise SystemExit("accepted KOAK P00 changed layer")
    if marking.meta.layer_kind is not LayerKind.AIRPORT_MARKING:
        raise SystemExit("accepted KOAK M00 changed layer")
    return installed


def main() -> int:
    plan = build_fixed_west_transition()
    TARGET.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan_include = assembly_include(plan)
    (TARGET / "family-plan.inc").write_text(plan_include, encoding="utf-8")
    plan_record = plan.to_json_record()
    plan_bytes = (
        json.dumps(plan_record, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (TARGET / "family-plan.json").write_bytes(plan_bytes)
    (OUTPUT / "FAMPLAN.JSN").write_bytes(plan_bytes)

    family_report = build_pinned_family_set(
        ROOT,
        OUTPUT,
        plan.required_families,
        verify_sources=True,
    )
    expected_paths = {
        entry.request.path.as_posix() for entry in plan.load_entries
    }
    actual_paths = {item["path"] for item in family_report["families"]}
    if actual_paths != expected_paths:
        raise SystemExit("built family paths disagree with generated runtime plan")
    if any(len(item["records"]) != 10 for item in family_report["families"]):
        raise SystemExit("fixed-west proof requires ten records in every family")

    resources = install_shared_resources()
    binary = OUTPUT / "P3DLOD.BIN"
    # ez80asm retains a short legacy filename buffer. Assemble through a
    # deliberately short temporary target, then install the completed binary.
    with tempfile.TemporaryDirectory(prefix="pfl", dir="/tmp") as temporary:
        assembled = Path(temporary) / "P3DLOD.BIN"
        subprocess.run(
            ["ez80asm", "koak-flight-family-lod.asm", str(assembled)],
            cwd=SOURCE,
            check=True,
        )
        shutil.copy2(assembled, binary)
    report = {
        "schema": "pingo-terrain-koak-family-lod-flight-v1",
        "binary": {
            "path": binary.name,
            "bytes": binary.stat().st_size,
            "sha256": sha256(binary),
        },
        "plan": {
            "sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "loads": len(plan.load_entries),
            "families": len(plan.required_families),
            "steady_active_terrain": 24,
            "resident_terrain_slots": 37,
        },
        "family_corpus": family_report,
        "resources": resources,
    }
    manifest = OUTPUT / "FAMILY.json"
    manifest.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "KOAK_FAMILY_LOD",
        f"binary_bytes={binary.stat().st_size}",
        f"binary_sha256={sha256(binary)}",
        f"family_bytes={family_report['bytes']}",
        f"output={OUTPUT}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
