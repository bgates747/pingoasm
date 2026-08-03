#!/usr/bin/env python3
"""Assemble and validate the resident FSIM fixture-launcher MOSlet."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "moslets/fsim/src"
TARGET = ROOT / "moslets/fsim/tgt"
PROGRAM = TARGET / "fsim.bin"
LISTING = TARGET / "fsim.lst"
SYMBOLS = TARGET / "fsim.symbols"
MOSLET_LIMIT = 32 * 1024
FIXTURE_ENTRY = 0x040000
FIXTURE_LOAD_CAPACITY = 0x070000
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"


FIXTURES = (
    ("fixtures/berkeley-flight/tgt", "berkeley-flight.bin"),
    (
        "fixtures/berkeley-flight-triangular/tgt",
        "berkeley-flight-triangular.bin",
    ),
    (
        "fixtures/berkeley-flight-triangular-dither/tgt",
        "berkeley-flight-triangular-dither.bin",
    ),
    ("fixtures/berkeley-flight-fdm/tgt", "berkeley-flight-fdm.bin"),
    ("build/p3dm/bay-area-koak-proof", "P3DFSIM.BIN"),
    ("build/p3dm/bay-area-koak-family-proof", "P3DLOD.BIN"),
    ("fixtures/p3dm-loader-probe/tgt", "p3dm-loader-probe.bin"),
    (
        "fixtures/nested-agnb-loader-probe/tgt",
        "nested-agnb-loader-probe.bin",
    ),
    ("fixtures/campanile-p3dm-probe/tgt", "CAMPTEST.BIN"),
    ("build/p3dm/bay-area-hex-full-l0", "P3DHXMG.BIN"),
)


def require_fixture_entries() -> None:
    missing: list[Path] = []
    invalid: list[str] = []
    for directory, filename in FIXTURES:
        path = ROOT / directory / filename
        if not path.is_file():
            missing.append(path)
            continue
        data = path.read_bytes()
        if len(data) > FIXTURE_LOAD_CAPACITY:
            invalid.append(f"{path} (exceeds resident-safe load window)")
            continue
        if data[:4] != FIXTURE_STUB or data[0x40:0x45] != MOS_ADL_HEADER:
            invalid.append(str(path))
    if missing:
        raise SystemExit(
            "FSIM fixture binaries are missing:\n"
            + "\n".join(f"  {path}" for path in missing)
        )
    if invalid:
        raise SystemExit(
            f"FSIM requires the common 0x{FIXTURE_ENTRY:06X} entry/header:\n"
            + "\n".join(f"  {path}" for path in invalid)
        )


def main() -> int:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise SystemExit("ez80asm is not available on PATH")
    require_fixture_entries()
    TARGET.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_adl_width.py"),
            "--follow-includes",
            "--show-review",
            "--fail-review",
            str(SOURCE / "fsim.asm"),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [assembler, "-l", "-s", "fsim.asm", "../tgt/fsim.bin", "-c"],
        cwd=SOURCE,
        check=True,
    )
    source_listing = SOURCE / "fsim.lst"
    source_symbols = SOURCE / "fsim.symbols"
    if not source_listing.is_file() or not source_symbols.is_file():
        raise SystemExit("ez80asm did not produce the requested listing/symbols")
    shutil.move(source_listing, LISTING)
    shutil.move(source_symbols, SYMBOLS)

    data = PROGRAM.read_bytes()
    if len(data) >= MOSLET_LIMIT:
        raise SystemExit(
            f"FSIM is {len(data)} bytes; MOSlets must be smaller than "
            f"{MOSLET_LIMIT} bytes"
        )
    if data[:4] != bytes((0xC3, 0x45, 0x00, 0x0B)):
        raise SystemExit("FSIM does not begin with the expected 0x0B0000 stub")
    if data[0x40:0x45] != MOS_ADL_HEADER:
        raise SystemExit("FSIM does not contain the expected MOS ADL header")

    print(
        "FSIM_LAUNCHER",
        f"fixtures={len(FIXTURES)}",
        f"entry=0x{FIXTURE_ENTRY:06X}",
        f"bytes={len(data)}",
        f"sha256={hashlib.sha256(data).hexdigest()}",
        f"output={PROGRAM}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
