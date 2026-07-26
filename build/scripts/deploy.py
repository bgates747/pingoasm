#!/usr/bin/env python3
"""Deploy one self-contained Pingo assembly sample to emulator or hardware."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src/asm"
EMULATOR_SD = PROJECT_ROOT / "emulator/sdcard"
DEFAULT_SD_MOUNT = Path("/media/smith/AGON")
DEPLOY_RELATIVE_ROOT = Path("mystuff/pingoasm/src/asm")


def sample_name(value: str) -> str:
    candidate = Path(value)
    if candidate.name != value or value in ("", ".", ".."):
        raise argparse.ArgumentTypeError(
            "sample must be one direct directory name beneath src/asm"
        )
    return value


def replace_deployment(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"Sample source directory is missing: {source}")
    if not any(source.glob("*.bin")):
        raise SystemExit(f"Sample has no assembled .bin file: {source}")
    if destination.is_symlink():
        raise SystemExit(f"Refusing symlinked deployment target: {destination}")
    if destination.exists():
        if not destination.is_dir():
            raise SystemExit(
                f"Refusing non-directory deployment target: {destination}"
            )
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    print(f"Deployed {source} to {destination}")


def deploy_to_emulator(sample: str) -> None:
    if not EMULATOR_SD.is_dir():
        raise SystemExit(
            "Pingo emulator profile is missing. Create it with:\n"
            "  cd ~/Agon/mystuff/agon-dev-env\n"
            "  python3 scripts/setup_emulator.py pingoasm"
        )
    source = SOURCE_ROOT / sample
    destination = EMULATOR_SD / DEPLOY_RELATIVE_ROOT / sample
    replace_deployment(source, destination)


def deploy_to_hardware(sample: str, sd_mount: Path) -> None:
    sd_mount = sd_mount.expanduser()
    if not sd_mount.is_mount():
        raise SystemExit(f"Agon SD card is not mounted at {sd_mount}")

    source = SOURCE_ROOT / sample
    expected_root = sd_mount / DEPLOY_RELATIVE_ROOT
    destination = expected_root / sample
    if destination.parent != expected_root:
        raise SystemExit(f"Refusing unexpected deployment path: {destination}")
    if expected_root.is_symlink():
        raise SystemExit(f"Refusing symlinked deployment root: {expected_root}")
    replace_deployment(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Replace one Pingo sample directory on an emulator SD, "
            "a mounted hardware SD card, or both."
        )
    )
    parser.add_argument(
        "target",
        choices=("emulator", "hardware", "both"),
        help="Deployment destination",
    )
    parser.add_argument(
        "sample",
        nargs="?",
        type=sample_name,
        default="moveobj",
        help="Direct child of src/asm to deploy (default: moveobj)",
    )
    parser.add_argument(
        "--sd-mount",
        type=Path,
        default=DEFAULT_SD_MOUNT,
        help="Hardware SD mount point (default: /media/smith/AGON)",
    )
    args = parser.parse_args()

    if args.target in ("emulator", "both"):
        deploy_to_emulator(args.sample)
    if args.target in ("hardware", "both"):
        deploy_to_hardware(args.sample, args.sd_mount)


if __name__ == "__main__":
    main()
