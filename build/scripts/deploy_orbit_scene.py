#!/usr/bin/env python3
"""Deploy one generated orbit-scene fixture to a mounted Agon SD card."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = PROJECT_ROOT / "benchmarks" / "orbit-scene" / "fixtures"
OTHER_FIXTURES_ROOT = (
    PROJECT_ROOT / "benchmarks" / "render-spin" / "fixtures"
)
SD_FIXTURES_PATH = Path("pingo")
DEFAULT_SD_ROOT = Path("/media/smith/AGON")
DEFAULT_FIXTURE = "earth-party-rgba2222"
EXECUTABLE = "benchmark.bin"


def fixture_name(value: str) -> str:
    if Path(value).name != value or value in {"", ".", ".."}:
        raise argparse.ArgumentTypeError("fixture must be one direct directory name")
    return value


def autoexec_lines(name: str) -> tuple[str, ...]:
    mos_path = f"/{SD_FIXTURES_PATH.as_posix()}/{name}"
    return (
        "SET KEYBOARD 1",
        f"cd {mos_path}",
        f"load {EXECUTABLE}",
        "run",
    )


def deploy(sd_root: Path, name: str) -> Path:
    if not sd_root.is_dir() or not os.path.ismount(sd_root):
        raise ValueError(f"Agon SD card is not mounted at {sd_root}")

    source = FIXTURES_ROOT / name / "tgt"
    if not (source / EXECUTABLE).is_file():
        raise ValueError(f"fixture has not been built: {source / EXECUTABLE}")
    if (OTHER_FIXTURES_ROOT / name).is_dir():
        raise ValueError(
            f"fixture name collides in the shared /pingo namespace: {name}"
        )

    target_root = sd_root / SD_FIXTURES_PATH
    if target_root.exists() and (
        target_root.is_symlink() or not target_root.is_dir()
    ):
        raise ValueError(f"refusing unexpected deployment target: {target_root}")
    target_root.mkdir(parents=True, exist_ok=True)

    destination = target_root / name
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError(
                f"refusing unexpected fixture target: {destination}"
            )
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    autoexec = sd_root / "autoexec.txt"
    lines = autoexec_lines(name)
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
