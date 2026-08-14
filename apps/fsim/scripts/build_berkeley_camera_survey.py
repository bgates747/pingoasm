#!/usr/bin/env python3
"""Assemble the camera-only sibling of dithered Berkeley fixture 3."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/berkeley-flight-triangular-dither"
SOURCE = FIXTURE / "src"
TARGET = FIXTURE / "tgt"
PROGRAM_NAME = "berkeley-camera-survey.bin"
PROGRAM = TARGET / PROGRAM_NAME
LISTING = TARGET / "berkeley-camera-survey.lst"
SYMBOLS = TARGET / "berkeley-camera-survey.symbols"
BASE_BUILDER = ROOT / "scripts/build_berkeley_flight_triangular_dither.py"
RUNTIME_RESOURCES = (
    "terrain-material-ids.rgba2",
    "terrain-pattern-lookup.bin",
    "terrain-patterns.rgba2",
)
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regenerate-scene",
        action="store_true",
        help=(
            "first run the mature fixture-3 terrain generator; the ordinary "
            "build reuses its checked-in source and staged runtime resources"
        ),
    )
    return parser.parse_args()


def require_shared_scene() -> None:
    required = [SOURCE / "terrain-scene.inc"]
    required.extend(TARGET / filename for filename in RUNTIME_RESOURCES)
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise SystemExit(
            "Dithered Berkeley scene inputs are missing; rerun with "
            "--regenerate-scene:\n"
            + "\n".join(f"  {path}" for path in missing)
        )


def main() -> int:
    arguments = parse_arguments()
    if arguments.regenerate_scene:
        subprocess.run([sys.executable, str(BASE_BUILDER)], cwd=ROOT, check=True)
    require_shared_scene()

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
            str(SOURCE / "berkeley-camera-survey.asm"),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            assembler,
            "-l",
            "-s",
            "berkeley-camera-survey.asm",
            f"../tgt/{PROGRAM_NAME}",
            "-c",
        ],
        cwd=SOURCE,
        check=True,
    )
    source_listing = SOURCE / "berkeley-camera-survey.lst"
    source_symbols = SOURCE / "berkeley-camera-survey.symbols"
    if not source_listing.is_file() or not source_symbols.is_file():
        raise SystemExit("ez80asm did not produce the requested listing/symbols")
    shutil.move(source_listing, LISTING)
    shutil.move(source_symbols, SYMBOLS)

    payload = PROGRAM.read_bytes()
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise SystemExit("camera survey does not preserve the common fixture entry")
    print(
        "BERKELEY_CAMERA_SURVEY",
        "start=(0,-1144,16384)",
        "rotation=(0,0,0)",
        "speed=8..256",
        f"bytes={len(payload)}",
        f"sha256={hashlib.sha256(payload).hexdigest()}",
        f"output={PROGRAM}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
