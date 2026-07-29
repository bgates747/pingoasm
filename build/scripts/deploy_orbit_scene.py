#!/usr/bin/env python3
"""Deploy one generated orbit-scene fixture to a mounted Agon SD card."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = PROJECT_ROOT / "benchmarks" / "orbit-scene" / "fixtures"
SD_FIXTURES_PATH = Path("mystuff/pingoasm/benchmarks/orbit-scene/fixtures")
DEFAULT_SD_ROOT = Path("/media/smith/AGON")
DEFAULT_FIXTURE = "earth-party-rgba2222"
EXECUTABLE = "benchmark.bin"


def fixture_name(value: str) -> str:
    if Path(value).name != value or value in {"", ".", ".."}:
        raise argparse.ArgumentTypeError("fixture must be one direct directory name")
    return value


def deploy(sd_root: Path, name: str) -> Path:
    if not sd_root.is_dir() or not os.path.ismount(sd_root):
        raise ValueError(f"Agon SD card is not mounted at {sd_root}")

    source = FIXTURES_ROOT / name / "tgt"
    if not (source / EXECUTABLE).is_file():
        raise ValueError(f"fixture has not been built: {source / EXECUTABLE}")

    target_root = sd_root / SD_FIXTURES_PATH
    if target_root.exists():
        if target_root.is_symlink() or not target_root.is_dir():
            raise ValueError(f"refusing unexpected deployment target: {target_root}")
        shutil.rmtree(target_root)
    destination = target_root / name / "tgt"
    shutil.copytree(source, destination)

    autoexec = sd_root / "autoexec.txt"
    mos_path = f"/{SD_FIXTURES_PATH.as_posix()}/{name}/tgt"
    lines = (
        "SET KEYBOARD 1",
        f"cd {mos_path}",
        f"load {EXECUTABLE}",
        "run",
    )
    autoexec.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
    print(f"Deployed {name} to {destination}")
    print(f"Selected only {name}/{EXECUTABLE} in {autoexec}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=fixture_name, default=DEFAULT_FIXTURE)
    parser.add_argument("--sd-root", type=Path, default=DEFAULT_SD_ROOT)
    args = parser.parse_args()
    deploy(args.sd_root.expanduser().resolve(), args.fixture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
