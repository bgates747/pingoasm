#!/usr/bin/env python3
"""Deploy a sequential render-benchmark suite to a mounted Agon SD card."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = PROJECT_ROOT / "benchmarks" / "render-spin" / "fixtures"
SD_FIXTURES_PATH = Path("mystuff/pingoasm/benchmarks/render-spin/fixtures")
EXECUTABLE = "benchmark.bin"
DEFAULT_SUITE = (
    "cube-rgba2222",
    "earthico-rgba2222",
    "earthuv-rgba2222",
    "heavytank-rgba2222",
    "lara-rgba2222",
    "crash-rgba2222",
    "jet-rgba2222",
    "airliner-rgba2222",
)


def require_mount(path: Path) -> None:
    if not path.is_dir() or not os.path.ismount(path):
        raise ValueError(f"Agon SD card is not mounted at {path}")


def fixture_target(name: str) -> Path:
    return FIXTURES_ROOT / name / "tgt"


def validate_suite(names: tuple[str, ...]) -> None:
    if not names:
        raise ValueError("suite must contain at least one fixture")
    if len(set(names)) != len(names):
        raise ValueError("suite contains a duplicate fixture")
    for name in names:
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"invalid fixture name: {name!r}")
        source = fixture_target(name)
        if not (source / EXECUTABLE).is_file():
            raise ValueError(f"fixture has not been built: {source / EXECUTABLE}")


def autoexec_lines(names: tuple[str, ...]) -> list[str]:
    lines = ["SET KEYBOARD 1"]
    for name in names:
        mos_path = f"/{SD_FIXTURES_PATH.as_posix()}/{name}/tgt"
        lines.extend((f"cd {mos_path}", f"load {EXECUTABLE}", "run"))
    return lines


def deploy(sd_root: Path, names: tuple[str, ...]) -> None:
    require_mount(sd_root)
    validate_suite(names)

    target_root = sd_root / SD_FIXTURES_PATH
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True)

    for name in names:
        shutil.copytree(fixture_target(name), target_root / name / "tgt")

    autoexec = sd_root / "autoexec.txt"
    payload = "\r\n".join(autoexec_lines(names)) + "\r\n"
    autoexec.write_bytes(payload.encode("ascii"))

    print(f"Deployed {len(names)} fixtures to {target_root}")
    print("Autorun order: " + " -> ".join(names))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sd-root",
        type=Path,
        default=Path("/media/smith/AGON"),
        help="mounted Agon SD-card root",
    )
    parser.add_argument(
        "fixtures",
        nargs="*",
        help="fixture names in autorun order (default: qualified full suite)",
    )
    args = parser.parse_args()
    names = tuple(args.fixtures) if args.fixtures else DEFAULT_SUITE
    deploy(args.sd_root.resolve(), names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
