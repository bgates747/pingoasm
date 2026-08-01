#!/usr/bin/env python3
"""Link Pingo applications into emulators or copy them to hardware SD."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = PROJECT_ROOT / "apps"
TEST_APPS_ROOT = PROJECT_ROOT / "tests" / "apps"
EMULATOR_SD = PROJECT_ROOT / "emulator/sdcard"
DEFAULT_SD_MOUNT = Path("/media/smith/AGON")
DEPLOY_RELATIVE_ROOT = Path("mystuff/pingoasm/apps")
TEST_DEPLOY_RELATIVE_ROOT = Path("mystuff/pingoasm/tests/apps")
BENCHMARK_DEPLOY_RELATIVE_ROOT = Path("mystuff/pingoasm/benchmarks")


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


def replace_directory_link(source: Path, destination: Path) -> None:
    if destination.is_symlink():
        destination.unlink()
    elif destination.exists():
        if not destination.is_dir():
            raise SystemExit(
                f"Refusing non-directory emulator app path: {destination}"
            )
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source, target_is_directory=True)
    print(f"Linked {destination} to {source}")


def deploy_to_emulator(sdcard: Path, setup_profile: str) -> None:
    if not sdcard.is_dir():
        raise SystemExit(
            "Pingo emulator profile is missing. Create it with:\n"
            "  cd ~/Agon/mystuff/agon-dev-env\n"
            f"  python3 scripts/setup_emulator.py {setup_profile}"
        )
    required = APPS_ROOT / "earth-party-tex/tgt/earth-party.bin"
    if not required.is_file():
        raise SystemExit(f"Required default application is missing: {required}")

    destination = sdcard / DEPLOY_RELATIVE_ROOT
    replace_directory_link(APPS_ROOT, destination)
    replace_directory_link(TEST_APPS_ROOT, sdcard / TEST_DEPLOY_RELATIVE_ROOT)
    replace_directory_link(
        PROJECT_ROOT / "benchmarks",
        sdcard / BENCHMARK_DEPLOY_RELATIVE_ROOT,
    )


def deploy_to_hardware(sample: str, sd_mount: Path) -> None:
    sd_mount = sd_mount.expanduser()
    if not sd_mount.is_mount():
        raise SystemExit(f"Agon SD card is not mounted at {sd_mount}")

    app_source = APPS_ROOT / sample / "tgt"
    test_source = TEST_APPS_ROOT / sample / "tgt"
    if app_source.is_dir():
        source = app_source
        relative_root = DEPLOY_RELATIVE_ROOT
    elif test_source.is_dir():
        source = test_source
        relative_root = TEST_DEPLOY_RELATIVE_ROOT
    else:
        raise SystemExit(f"Unknown application or test fixture: {sample}")
    expected_root = sd_mount / relative_root / sample
    destination = expected_root / "tgt"
    if destination.parent != expected_root:
        raise SystemExit(f"Refusing unexpected deployment path: {destination}")
    if expected_root.is_symlink():
        raise SystemExit(f"Refusing symlinked deployment root: {expected_root}")
    replace_deployment(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Link the canonical app tree into an emulator SD, copy one app "
            "target to hardware, or do both."
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
        default="earth-party-tex",
        help=(
            "Direct child of apps or tests/apps for hardware deployment "
            "(default: earth-party-tex; ignored for emulator-only deployment)"
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
        deploy_to_emulator(EMULATOR_SD, "pingoasm")
    if args.target in ("hardware", "both"):
        deploy_to_hardware(args.sample, args.sd_mount)


if __name__ == "__main__":
    main()
