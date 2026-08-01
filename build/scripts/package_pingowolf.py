#!/usr/bin/env python3
"""Build and package the current PingoWolf Discord drop.

This is the PC-side equivalent of deploy_pingowolf_sd.py. It builds the
combined VDP firmware, gathers the same flat Pingo and Wolf payloads used on
hardware, writes provenance and checksums, and verifies the resulting ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from pathlib import Path


HOME = Path.home()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VDP_ROOT = HOME / "Agon/mystuff/agon-vdp"
DEFAULT_WOLF_ROOT = HOME / "Agon/mystuff/Wolf3dOrig"
DEFAULT_OUTPUT = HOME / "Desktop" / f"PingoWolf-{date.today().isoformat()}.zip"
PINGO_SOURCE = PROJECT_ROOT / "apps/earth-party-flat/tgt"
WOLF_RELATIVE_SOURCES = {
    "wolf3d.bin": Path("src/asm/wolf3d/tgt/wolf3d.bin"),
    "tiles.agnb": Path("agonport/assets/generated/wolf3d/levels/level_00/tiles.agnb"),
    "sprites.agnb": Path("agonport/assets/generated/wolf3d/levels/level_00/sprites.agnb"),
    "hud.agnb": Path("agonport/assets/generated/wolf3d/hud/hud.agnb"),
    "sfx.agnb": Path("agonport/assets/generated/wolf3d/audio/sfx.agnb"),
}
ZIP_TIME = (2026, 8, 1, 0, 0, 0)


def run(*command: str, cwd: Path) -> str:
    return subprocess.run(
        command, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE
    ).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing or empty package input: {path}")


def git_identity(repository: Path, expected_branch: str | None = None) -> tuple[str, str, str]:
    remote = run("git", "remote", "get-url", "origin", cwd=repository)
    branch = run("git", "branch", "--show-current", cwd=repository)
    commit = run("git", "rev-parse", "HEAD", cwd=repository)
    if expected_branch and branch != expected_branch:
        raise RuntimeError(
            f"{repository} is on branch {branch!r}; expected {expected_branch!r}"
        )
    if remote.endswith(".git"):
        remote = remote[:-4]
    if remote.startswith("git@github.com:"):
        remote = "https://github.com/" + remote.removeprefix("git@github.com:")
    return remote, branch, commit


def readme(identities: dict[str, tuple[str, str, str]], firmware_hash: str) -> str:
    vdp, pingo, wolf = (identities[name] for name in ("vdp", "pingo", "wolf"))
    return f"""# PingoWolf

This package contains the combined Pingo and Wolf3DOrig demonstration software
for the Agon platform and the custom PingoWolf VDP firmware required to run it.

## Contents

- `firmware.bin` — combined PingoWolf VDP firmware.
- `Pingo/` — Earth Party Pingo demonstration and runtime assets.
- `Wolf/` — Wolf3DOrig demonstration and runtime assets.
- `SHA256SUMS` — checksums for every runtime file.

The application directories are deliberately flat and match the layout tested
on physical Agon hardware.

## Install on an SD card

1. Create `/PingoWolf` in the root of an Agon SD card.
2. Copy everything beside this README into that directory.
3. At the MOS prompt, enter `cd /PingoWolf`, then
   `flash vdp firmware.bin`.
4. Allow flashing to finish, then completely power-cycle the Agon.

Firmware SHA-256: `{firmware_hash}`

## Run the demonstrations

Pingo Earth Party:

```text
cd /PingoWolf/Pingo
load earth-party-flat.bin
run
```

Wolf3DOrig:

```text
cd /PingoWolf/Wolf
load wolf3d.bin
run
```

Pingo Earth Party displays its controls while loading. Press any key when
prompted to begin.

## Source repositories

- Combined firmware: [{vdp[0]}, `{vdp[1]}` branch]({vdp[0]}/tree/{vdp[1]})  
  Packaged source commit: `{vdp[2]}`
- Pingo applications: [{pingo[0]}, `{pingo[1]}` branch]({pingo[0]}/tree/{pingo[1]})  
  Packaged source commit: `{pingo[2]}`
- Wolf3DOrig: [{wolf[0]}, `{wolf[1]}` branch]({wolf[0]}/tree/{wolf[1]})  
  Packaged source commit: `{wolf[2]}`

Original projects:

- [AgonPlatform/agon-vdp](https://github.com/AgonPlatform/agon-vdp)
- [fededevi/pingo](https://github.com/fededevi/pingo)
- [TurboVega/agon-vdp-otf, `pingo3D` branch](https://github.com/TurboVega/agon-vdp-otf/tree/pingo3D)

## Compatibility and provenance

The firmware and applications are a matched set. These applications are not
expected to work correctly on stock VDP firmware.

Crash Bandicoot and Lara Croft test-model data originated in publicly available
material of unknown provenance or license. They remain the property of their
respective rights holders and are included only for non-commercial experimental
and regression-testing use.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--vdp-root", type=Path, default=DEFAULT_VDP_ROOT)
    parser.add_argument("--wolf-root", type=Path, default=DEFAULT_WOLF_ROOT)
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="package the existing firmware.bin without rebuilding it",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    vdp_root = args.vdp_root.expanduser().resolve()
    wolf_root = args.wolf_root.expanduser().resolve()
    output = args.output.expanduser().resolve()

    identities = {
        "vdp": git_identity(vdp_root, "pingowolf"),
        "pingo": git_identity(PROJECT_ROOT),
        "wolf": git_identity(wolf_root),
    }

    if not args.no_build:
        pio = vdp_root / ".venv/bin/pio"
        require_file(pio)
        subprocess.run([pio, "run", "-e", "esp32dev"], cwd=vdp_root, check=True)

    firmware = vdp_root / ".pio/build/esp32dev/firmware.bin"
    require_file(firmware)
    pingo_sources = sorted(path for path in PINGO_SOURCE.iterdir() if path.is_file())
    if not pingo_sources:
        raise RuntimeError(f"no Pingo runtime files found in {PINGO_SOURCE}")
    for source in pingo_sources:
        require_file(source)
    wolf_sources = {name: wolf_root / relative for name, relative in WOLF_RELATIVE_SOURCES.items()}
    for source in wolf_sources.values():
        require_file(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pingowolf-package-") as temporary:
        root = Path(temporary) / "PingoWolf"
        pingo_dir = root / "Pingo"
        wolf_dir = root / "Wolf"
        pingo_dir.mkdir(parents=True)
        wolf_dir.mkdir()
        shutil.copy2(firmware, root / "firmware.bin")
        for source in pingo_sources:
            shutil.copy2(source, pingo_dir / source.name)
        for name, source in wolf_sources.items():
            shutil.copy2(source, wolf_dir / name)

        firmware_hash = sha256(root / "firmware.bin")
        (root / "README.md").write_text(
            readme(identities, firmware_hash), encoding="utf-8"
        )
        payloads = sorted(
            path for path in root.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        )
        sums = "".join(
            f"{sha256(path)}  {path.relative_to(root).as_posix()}\n"
            for path in payloads
        )
        (root / "SHA256SUMS").write_text(sums, encoding="utf-8")

        if output.exists():
            output.unlink()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                info = zipfile.ZipInfo(path.relative_to(root.parent).as_posix(), ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compresslevel=9)

    with zipfile.ZipFile(output) as archive:
        failed = archive.testzip()
        if failed:
            raise RuntimeError(f"ZIP CRC failure: {failed}")
        names = set(archive.namelist())
        required = {
            "PingoWolf/firmware.bin",
            "PingoWolf/README.md",
            "PingoWolf/SHA256SUMS",
            "PingoWolf/Pingo/earth-party-flat.bin",
            "PingoWolf/Wolf/wolf3d.bin",
        }
        if missing := required - names:
            raise RuntimeError(f"archive is missing required files: {sorted(missing)}")

    print(f"Package: {output}")
    print(f"Size: {output.stat().st_size} bytes")
    print(f"SHA-256: {sha256(output)}")
    print(f"Firmware SHA-256: {sha256(firmware)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
