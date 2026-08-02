#!/usr/bin/env python3
"""Provision pingo_terrain's project-local, fail-closed PingoWolf profile."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE = PROJECT_ROOT / "emulator"
SDCARD = PROFILE / "sdcard"
AGON_ROOT = Path.home() / "Agon"
FAB_ROOT = AGON_ROOT / "mystuff/fab-agon-emulator"
VDP_MODULE = (
    AGON_ROOT / "mystuff/agon-vdp/video/build/userspace/vdp_combined.so"
)


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


def emulator_executable() -> Path:
    for candidate in (
        FAB_ROOT / "fab-agon-emulator",
        FAB_ROOT / "target/release/fab-agon-emulator",
    ):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"Fab emulator executable is missing under {FAB_ROOT}")


def main() -> None:
    firmware = FAB_ROOT / "firmware"
    mos = firmware / "mos_console8.bin"
    mos_map = firmware / "mos_console8.map"
    fixtures = PROJECT_ROOT / "fixtures"
    required = (emulator_executable(), firmware, mos, mos_map, VDP_MODULE, fixtures)
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
    replace_symlink(PROFILE / "vdp_combined.so", VDP_MODULE)
    (PROFILE / ".bespoke-vdp-profile").write_text(
        "vdp_combined.so\n", encoding="utf-8"
    )
    replace_directory_link(
        SDCARD / "mystuff/pingo_terrain/fixtures", fixtures
    )

    autoexec = SDCARD / "autoexec.txt"
    if not autoexec.exists():
        autoexec.write_bytes(
            b"SET KEYBOARD 1\r\n"
            b"cd /mystuff/pingo_terrain/fixtures\r\n"
        )

    print(f"Emulator profile: {PROFILE}")
    print(f"Autoexec:         {autoexec}")


if __name__ == "__main__":
    main()
