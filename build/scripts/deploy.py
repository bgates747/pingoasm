#!/usr/bin/env python3
"""Deploy Pingo applications to the emulator or hardware SD card."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = PROJECT_ROOT / "apps"
EMULATOR_SD = PROJECT_ROOT / "emulator/sdcard"
DEFAULT_SD_MOUNT = Path("/media/smith/AGON")
DEPLOY_RELATIVE_ROOT = Path("mystuff/pingoasm/apps")
def sample_name(value: str) -> str:
    candidate = Path(value)
    if candidate.name != value or value in ("", ".", ".."):
        raise argparse.ArgumentTypeError(
            "app must be one direct directory name beneath apps"
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


def clear_directory(directory: Path, preserve: frozenset[str] = frozenset()) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise SystemExit(f"Refusing unsafe emulator SD path: {directory}")
    for child in directory.iterdir():
        if child.name in preserve:
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            raise SystemExit(f"Refusing unexpected SD entry: {child}")


def deploy_to_emulator() -> None:
    if not EMULATOR_SD.is_dir():
        raise SystemExit(
            "Pingo emulator profile is missing. Create it with:\n"
            "  cd ~/Agon/mystuff/agon-dev-env\n"
            "  python3 scripts/setup_emulator.py pingoasm"
        )
    required = APPS_ROOT / "moveobj/tgt/cube.bin"
    if not required.is_file():
        raise SystemExit(f"Required default application is missing: {required}")

    # autoexec.txt is user-controlled runtime configuration.
    clear_directory(EMULATOR_SD, preserve=frozenset({"autoexec.txt"}))
    destination = EMULATOR_SD / DEPLOY_RELATIVE_ROOT
    destination.parent.mkdir(parents=True)
    shutil.copytree(APPS_ROOT, destination)
    print(f"Deployed {APPS_ROOT} to {destination}")


def deploy_to_hardware(sample: str, sd_mount: Path) -> None:
    sd_mount = sd_mount.expanduser()
    if not sd_mount.is_mount():
        raise SystemExit(f"Agon SD card is not mounted at {sd_mount}")

    source = APPS_ROOT / sample / "tgt"
    expected_root = sd_mount / DEPLOY_RELATIVE_ROOT / sample
    destination = expected_root / "tgt"
    if destination.parent != expected_root:
        raise SystemExit(f"Refusing unexpected deployment path: {destination}")
    if expected_root.is_symlink():
        raise SystemExit(f"Refusing symlinked deployment root: {expected_root}")
    replace_deployment(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Replace the complete app tree on the emulator SD, deploy one "
            "app target to hardware, or do both."
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
        help=(
            "Direct child of apps for hardware deployment "
            "(default: moveobj; ignored for emulator-only deployment)"
        ),
    )
    parser.add_argument(
        "--sd-mount",
        type=Path,
        default=DEFAULT_SD_MOUNT,
        help="Hardware SD mount point (default: /media/smith/AGON)",
    )
    args = parser.parse_args()

    if args.target in ("emulator", "both"):
        deploy_to_emulator()
    if args.target in ("hardware", "both"):
        deploy_to_hardware(args.sample, args.sd_mount)


if __name__ == "__main__":
    main()
