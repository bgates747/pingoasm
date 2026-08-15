#!/usr/bin/env python3
"""Build the distinct cockpit/flight-model Berkeley terrain fixture."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import agonutils


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "fixtures/berkeley-flight-fdm"
SOURCE = APP / "src"
TARGET = APP / "tgt"
PANEL_SOURCE = ROOT / "assets/cockpit/fsimpanel.png"
PANEL_TARGET = TARGET / "fsimpanel.rgba2"
AGON64 = Path(
    "/home/smith/Agon/mystuff/agon-utils/examples/palettes/Agon64.gpl"
)
EXPECTED_PANEL_PNG_SHA256 = (
    "4beb8066ea7baa53914d0c02e67e53b41519f7bdd1da89f30903349527bd7b36"
)
EXPECTED_PANEL_RGBA2_SHA256 = (
    "53ca5a440747a7c92854d6c263bb0f9d563aa12636e0f2f4cc538dad50d11fb1"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    if sha256(PANEL_SOURCE) != EXPECTED_PANEL_PNG_SHA256:
        raise SystemExit("cockpit source checksum does not match its provenance")
    agonutils.img_to_rgba2(
        str(PANEL_SOURCE), str(PANEL_TARGET), str(AGON64), "rgb", None
    )
    if PANEL_TARGET.stat().st_size != 320 * 92:
        raise SystemExit("cockpit RGBA2222 output is not exactly 320x92 bytes")
    if sha256(PANEL_TARGET) != EXPECTED_PANEL_RGBA2_SHA256:
        raise SystemExit("cockpit RGBA2222 conversion is not deterministic")

    required = {
        "terrain-material-ids.rgba2": 16,
        "terrain-pattern-lookup.bin": 15 * 16,
        "terrain-patterns.rgba2": 126 * 4 * 4,
    }
    for name, expected_bytes in required.items():
        path = TARGET / name
        if not path.is_file() or path.stat().st_size != expected_bytes:
            raise SystemExit(
                f"{path} must be retained from the accepted dither fixture "
                f"at exactly {expected_bytes} bytes"
            )

    output = TARGET / "berkeley-flight-fdm.bin"
    subprocess.run(
        ["ez80asm", "berkeley-flight-fdm.asm", "../tgt/berkeley-flight-fdm.bin"],
        cwd=SOURCE,
        check=True,
    )
    print(
        "BERKELEY_FLIGHT_FDM",
        "viewport=320x148",
        "simulation_hz=30",
        f"panel_sha256={sha256(PANEL_TARGET)}",
        f"binary_sha256={sha256(output)}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
