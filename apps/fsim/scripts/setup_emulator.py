#!/usr/bin/env python3
"""Provision pingo_terrain's project-local, fail-closed PingoWolf profile."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE = PROJECT_ROOT / "emulator"
SDCARD = PROFILE / "sdcard"
AGON_ROOT = Path.home() / "Agon"
FAB_ROOT = AGON_ROOT / "mystuff/fab-agon-emulator"
DEFAULT_VDP_MODULE = (
    AGON_ROOT / "mystuff/agon-vdp/video/build/userspace/vdp_combined.so"
)
FSIM_PROGRAM = PROJECT_ROOT / "moslets/fsim/tgt/fsim.bin"
FSIM_CONFIG = b"/mystuff/pingo_terrain\r\n"
DEFAULT_AUTOEXEC = b"SET KEYBOARD 1\r\n"
LEGACY_GENERATED_AUTOEXECS = (
    (
        b"SET KEYBOARD 1\r\n"
        b"cd /mystuff/pingo_terrain/fixtures\r\n"
    ),
    (
        b"SET KEYBOARD 1\r\n"
        b"cd /mystuff/pingo_terrain/build/p3dm/bay-area-koak-proof\r\n"
        b"load P3DFSIM.BIN\r\n"
        b"run\r\n"
    ),
    (
        b"SET KEYBOARD 1\r\n"
        b"cd /mystuff/pingo_terrain/build/p3dm/"
        b"bay-area-koak-family-proof\r\n"
        b"load P3DLOD.BIN\r\n"
        b"run\r\n"
    ),
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=DEFAULT_VDP_MODULE,
        help=(
            "native PingoWolf VDP module to link into the profile "
            f"(default: {DEFAULT_VDP_MODULE})"
        ),
    )
    return parser.parse_args()


def replace_symlink(link: Path, target: Path) -> None:
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise SystemExit(f"Refusing to replace non-symlink path: {link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(target, link.parent))


def replace_directory_link(link: Path, target: Path) -> None:
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise SystemExit(f"Refusing to replace existing SD path: {link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)


def populate_shared_moslets(shared: Path, local: Path) -> None:
    """Expose the stock MOSlets without making the shared SD tree writable."""

    local.mkdir(parents=True, exist_ok=True)
    for source in sorted(shared.iterdir()):
        if not source.is_file() or source.name in {"fsim.bin", "fsim.cfg"}:
            continue
        destination = local / source.name
        if destination.is_symlink():
            replace_symlink(destination, source)
        elif not destination.exists():
            destination.symlink_to(os.path.relpath(source, destination.parent))


def create_profile_file(path: Path, data: bytes) -> None:
    """Create a profile-owned file once while preserving later user edits."""

    if path.is_symlink():
        raise SystemExit(f"Refusing to replace profile-file symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise SystemExit(f"Expected a regular profile file: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def provision_autoexec(path: Path) -> None:
    """Create the keyboard setup or retire an exact old generated autorun."""

    if path.is_symlink():
        raise SystemExit(f"Refusing to replace autoexec symlink: {path}")
    if not path.exists():
        path.write_bytes(DEFAULT_AUTOEXEC)
        return
    if not path.is_file():
        raise SystemExit(f"Expected a regular autoexec file: {path}")
    if path.read_bytes() in LEGACY_GENERATED_AUTOEXECS:
        path.write_bytes(DEFAULT_AUTOEXEC)


def emulator_executable() -> Path:
    for candidate in (
        FAB_ROOT / "fab-agon-emulator",
        FAB_ROOT / "target/release/fab-agon-emulator",
    ):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"Fab emulator executable is missing under {FAB_ROOT}")


def main() -> None:
    arguments = parse_arguments()
    vdp_module = arguments.vdp_module.expanduser().resolve()
    firmware = FAB_ROOT / "firmware"
    mos = firmware / "mos_console8.bin"
    mos_map = firmware / "mos_console8.map"
    shared_moslets = FAB_ROOT / "sdcard/mos"
    fixtures = PROJECT_ROOT / "fixtures"
    build = PROJECT_ROOT / "build"
    required = (
        emulator_executable(),
        firmware,
        mos,
        mos_map,
        vdp_module,
        shared_moslets,
        FSIM_PROGRAM,
        fixtures,
        build,
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "Required emulator paths are missing:\n"
            + "\n".join(f"  {path}" for path in missing)
        )

    PROFILE.mkdir(parents=True, exist_ok=True)
    SDCARD.mkdir(parents=True, exist_ok=True)
    replace_symlink(PROFILE / "fab-agon-emulator", required[0])
    replace_symlink(PROFILE / "firmware", firmware)
    replace_symlink(PROFILE / "mos_console8.bin", mos)
    replace_symlink(PROFILE / "mos_console8.map", mos_map)
    replace_symlink(PROFILE / "vdp_combined.so", vdp_module)
    (PROFILE / ".bespoke-vdp-profile").write_text(
        "vdp_combined.so\n", encoding="utf-8"
    )
    replace_directory_link(
        SDCARD / "mystuff/pingo_terrain/fixtures", fixtures
    )
    replace_directory_link(SDCARD / "mystuff/pingo_terrain/build", build)

    local_moslets = SDCARD / "mos"
    populate_shared_moslets(shared_moslets, local_moslets)
    replace_symlink(local_moslets / "fsim.bin", FSIM_PROGRAM)
    create_profile_file(local_moslets / "fsim.cfg", FSIM_CONFIG)

    autoexec = SDCARD / "autoexec.txt"
    provision_autoexec(autoexec)

    print(f"Emulator profile: {PROFILE}")
    print(f"VDP module:       {vdp_module}")
    print(f"FSIM launcher:    {local_moslets / 'fsim.bin'}")
    print(f"FSIM config:      {local_moslets / 'fsim.cfg'}")
    print(f"Autoexec:         {autoexec}")


if __name__ == "__main__":
    main()
