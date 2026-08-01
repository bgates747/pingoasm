#!/usr/bin/env python3
"""Deploy the current flat PingoWolf application payload to an Agon SD card."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MOUNT = Path("/media") / os.environ.get("USER", "smith") / "AGON"
WOLF_ROOT = Path.home() / "Agon" / "mystuff" / "Wolf3dOrig"

PINGO_SOURCE = PROJECT_ROOT / "apps" / "earth-party-flat" / "tgt"
WOLF_SOURCES = {
    "wolf3d.bin": WOLF_ROOT / "src/asm/wolf3d/tgt/wolf3d.bin",
    "tiles.agnb": WOLF_ROOT
    / "agonport/assets/generated/wolf3d/levels/level_00/tiles.agnb",
    "sprites.agnb": WOLF_ROOT
    / "agonport/assets/generated/wolf3d/levels/level_00/sprites.agnb",
    "hud.agnb": WOLF_ROOT / "agonport/assets/generated/wolf3d/hud/hud.agnb",
    "sfx.agnb": WOLF_ROOT / "agonport/assets/generated/wolf3d/audio/sfx.agnb",
}


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty runtime file: {path}")


def clear_directory(directory: Path) -> None:
    """Clear one validated leaf directory without deleting the directory."""
    if directory.is_symlink():
        raise RuntimeError(f"Refusing to clear symlinked destination: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount", type=Path, default=DEFAULT_MOUNT)
    args = parser.parse_args()

    mount = args.mount.resolve()
    if not mount.is_mount():
        raise RuntimeError(f"Agon SD card is not mounted at {mount}")

    pingo_sources = sorted(path for path in PINGO_SOURCE.iterdir() if path.is_file())
    if not pingo_sources:
        raise RuntimeError(f"No Pingo runtime files found in {PINGO_SOURCE}")
    for source in pingo_sources:
        require_file(source)
    for source in WOLF_SOURCES.values():
        require_file(source)

    package_root = mount / "PingoWolf"
    pingo_destination = package_root / "Pingo"
    wolf_destination = package_root / "Wolf"
    clear_directory(pingo_destination)
    clear_directory(wolf_destination)

    for source in pingo_sources:
        shutil.copy2(source, pingo_destination / source.name)
    for filename, source in WOLF_SOURCES.items():
        shutil.copy2(source, wolf_destination / filename)

    # MOS text files use CRLF. Leave application selection to the command line.
    (mount / "autoexec.txt").write_bytes(
        b"SET KEYBOARD 1\r\ncd /PingoWolf\r\n"
    )

    print(f"Pingo: {len(pingo_sources)} files -> {pingo_destination}")
    print(f"Wolf: {len(WOLF_SOURCES)} files -> {wolf_destination}")
    print(f"Autoexec: SET KEYBOARD 1; cd /PingoWolf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
