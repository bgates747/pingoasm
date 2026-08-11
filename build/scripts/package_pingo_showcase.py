#!/usr/bin/env python3
"""Build a minimal Pingo-only Lara/Earth Party Discord package."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


HOME = Path.home()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VDP_ROOT = HOME / "Agon/mystuff/agon-vdp-pingo-v216-promotion"
DEFAULT_PIO = HOME / "Agon/mystuff/agon-vdp/.venv/bin/pio"
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / f"PingoShowcase-{date.today().isoformat()}.zip"
ARCHIVE_ROOT = "PingoShowcase"
FIRMWARE_ENVIRONMENT = "esp32dev"
RUNTIME_LAYOUT = {
    Path("apps/anim/tgt"): Path("Lara"),
    Path("apps/earth-party-tex/tgt"): Path("EarthParty"),
}
REQUIRED_ARCHIVE_FILES = (
    Path("firmware.bin"),
    Path("Lara/anim.bin"),
    Path("Lara/Lara.rgba2"),
    Path("EarthParty/earth-party.bin"),
    Path("EarthParty/stars.rgba2"),
)


def run(*command: os.PathLike[str] | str, cwd: Path) -> str:
    result = subprocess.run(
        [os.fspath(item) for item in command],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing or empty package input: {path}")


def git_identity(repository: Path) -> dict[str, object]:
    remote = run("git", "remote", "get-url", "origin", cwd=repository)
    if remote.endswith(".git"):
        remote = remote[:-4]
    if remote.startswith("git@github.com:"):
        remote = "https://github.com/" + remote.removeprefix("git@github.com:")
    return {
        "remote": remote,
        "branch": run("git", "branch", "--show-current", cwd=repository),
        "commit": run("git", "rev-parse", "HEAD", cwd=repository),
        "dirty": bool(run("git", "status", "--porcelain", cwd=repository)),
    }


def assert_pingo_only(vdp_root: Path, expected_branch: str) -> dict[str, object]:
    identity = git_identity(vdp_root)
    if identity["branch"] != expected_branch:
        raise RuntimeError(
            f"Pingo firmware worktree is on {identity['branch']!r}; "
            f"expected {expected_branch!r}"
        )
    if identity["dirty"]:
        raise RuntimeError("Pingo firmware worktree must be clean")
    tracked = run("git", "ls-files", cwd=vdp_root).splitlines()
    wolf_paths = [
        path for path in tracked
        if any(part.lower().startswith("wolf") for part in Path(path).parts)
    ]
    if wolf_paths:
        raise RuntimeError(
            "firmware worktree contains Wolf source paths: "
            + ", ".join(wolf_paths[:5])
        )
    video_source = vdp_root / "video"
    for source in video_source.rglob("*"):
        if source.is_file() and source.suffix.lower() in {".c", ".cpp", ".h", ".ino"}:
            if b"wolf3d" in source.read_bytes().lower():
                raise RuntimeError(f"firmware source references Wolf3D: {source}")
    return identity


def copy_file(source: Path, destination: Path) -> None:
    require_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_runtime(root: Path) -> None:
    for relative, archive_directory in RUNTIME_LAYOUT.items():
        source = PROJECT_ROOT / relative
        if not source.is_dir() or source.is_symlink():
            raise RuntimeError(f"missing runtime directory: {source}")
        files = [path for path in sorted(source.iterdir()) if path.is_file()]
        if not files:
            raise RuntimeError(f"empty runtime directory: {source}")
        for path in files:
            copy_file(path, root / archive_directory / path.name)
    for relative in REQUIRED_ARCHIVE_FILES[1:]:
        require_file(root / relative)


def readme(
    pingo_identity: dict[str, object],
    vdp_identity: dict[str, object],
    firmware_hash: str,
    release_tag: str,
) -> str:
    return f"""# Pingo interactive showcase

This non-commercial Agon package contains two interactive Pingo applications,
their runtime assets, and a matched **Pingo-only** VDP firmware. The
firmware contains no Wolf3DOrig implementation.

## Package layout

- `firmware.bin` — custom Pingo-only VDP firmware.
- `Lara/` — controllable running animation and its required texture.
- `EarthParty/` — controllable textured Earth Party and all required textures,
  including the real-star sky palette.
- `SHA256SUMS` — checksums for every other file in this package.

Keep each application directory flat and intact. The binaries load their
`.rgba2` assets by relative filename.

## Install the custom VDP firmware

1. Ensure the official Agon `flash` utility is installed as `/mos/flash.bin`
   on the SD card. It is distributed by
   <https://github.com/AgonPlatform/agon-flash/releases>.
2. Extract the complete `PingoShowcase` directory to the SD-card root.
3. Insert the card in the Agon and enter these MOS commands:

```text
cd /PingoShowcase
flash vdp firmware.bin
```

4. Do not interrupt the flash. When it finishes, completely power-cycle the
   Agon. The applications require this custom Pingo firmware and are not
   expected to run on stock VDP firmware.

Firmware SHA-256: `{firmware_hash}`

## Lara runner

Run from MOS:

```text
cd /PingoShowcase/Lara
load anim.bin
run
```

| Key | Action |
|---|---|
| W | Run forward at the captured stride speed |
| A / D | Strafe left / right |
| Left / Right | Turn left / right |
| Page Up / Page Down | Raise / lower the look-at camera |
| P | Pause or resume animation |
| R | Reset to frame 1 and pause |
| Escape | Exit cleanly to MOS |

The animation continues while Lara is stationary. Reverse running is
intentionally unbound.

## Earth Party with starfield

Run from MOS:

```text
cd /PingoShowcase/EarthParty
load earth-party.bin
run
```

Wait for `Ready. Press any key to begin.`, then press a key.

| Key | Action |
|---|---|
| W / S | Increase forward throttle / reduce it toward zero |
| Up / Down | Pitch |
| Left / Right | Roll |
| A / D | Yaw |
| Page Up / Page Down | Move camera up / down |
| Home / End | Move camera toward / away from Earth |
| Insert / Delete | Sweep camera around Earth |
| Escape | Exit cleanly to MOS |

The six-sector sky contains 128 real bright stars and included constellation
vertices. The camera always looks at the user-controlled jet.

## Exact source and provenance

- Application source: {pingo_identity['remote']}/tree/{release_tag}  
  Release tag `{release_tag}`; commit `{pingo_identity['commit']}`
- Pingo-only VDP: {vdp_identity['remote']}  
  Branch `{vdp_identity['branch']}`, commit `{vdp_identity['commit']}`

Source is deliberately omitted from this runtime package. Use the date-tagged
repository link above for the exact application, generator, Blender, metadata,
and documentation sources corresponding to these binaries.

## Asset rights

Bandai Namco Research Motiondataset 2 motion is © 2022 Bandai Namco Research
Inc. and licensed CC BY-NC 4.0. Changes, attribution, and the license are in the
date-tagged source repository. The Lara model's original source and redistribution
license remain unresolved. Other third-party model assets may likewise have
separate or unresolved terms. This package is provided only for non-commercial
education, experimentation, and community evaluation. All trademarks and
third-party assets remain the property of their respective owners. Consult
`THIRD_PARTY_ASSETS.md` at the source tag before redistributing any
asset-bearing portion.
"""


def parse_archive_date(value: str) -> tuple[int, int, int, int, int, int]:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    if not 1980 <= parsed.year <= 2107:
        raise argparse.ArgumentTypeError("ZIP date must be between 1980 and 2107")
    return (parsed.year, parsed.month, parsed.day, 0, 0, 0)


def write_zip(source_root: Path, output: Path, zip_time: tuple[int, ...]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(output.name + ".tmp")
    if temporary_output.exists():
        temporary_output.unlink()
    try:
        with zipfile.ZipFile(
            temporary_output, "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in sorted(source_root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(source_root.parent).as_posix()
                info = zipfile.ZipInfo(relative, zip_time)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compresslevel=9)
        temporary_output.replace(output)
    finally:
        if temporary_output.exists():
            temporary_output.unlink()


def checksums(root: Path) -> str:
    paths: Iterable[Path] = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    return "".join(
        f"{sha256(path)}  {path.relative_to(root).as_posix()}\n" for path in paths
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--vdp-root", type=Path, default=DEFAULT_VDP_ROOT)
    parser.add_argument("--pio", type=Path, default=DEFAULT_PIO)
    parser.add_argument("--vdp-branch", default="pingo-v2.16-promotion")
    parser.add_argument("--archive-date", default=date.today().isoformat())
    parser.add_argument(
        "--release-tag",
        help="source tag named in README (default: demo_<archive-date>)",
    )
    parser.add_argument(
        "--no-build-apps",
        action="store_true",
        help="package existing application targets without rebuilding them",
    )
    parser.add_argument(
        "--no-build-firmware",
        action="store_true",
        help="package the existing Pingo-only firmware without rebuilding it",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    output.relative_to(PROJECT_ROOT)
    if output.suffix.lower() != ".zip":
        raise RuntimeError("package output must use the .zip extension")
    vdp_root = args.vdp_root.expanduser().resolve()
    pio = args.pio.expanduser().resolve()
    zip_time = parse_archive_date(args.archive_date)
    release_tag = args.release_tag or f"demo_{args.archive_date}"

    vdp_identity = assert_pingo_only(vdp_root, args.vdp_branch)
    pingo_identity = git_identity(PROJECT_ROOT)

    if not args.no_build_apps:
        subprocess.run(
            [PROJECT_ROOT / ".venv/bin/python", "build/scripts/build_anim.py"],
            cwd=PROJECT_ROOT,
            check=True,
        )
        subprocess.run(
            [
                PROJECT_ROOT / ".venv/bin/python",
                "build/scripts/build_earth_party_tex.py",
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )

    if not args.no_build_firmware:
        require_file(pio)
        subprocess.run(
            [pio, "run", "-e", FIRMWARE_ENVIRONMENT],
            cwd=vdp_root,
            check=True,
        )
    firmware = vdp_root / f".pio/build/{FIRMWARE_ENVIRONMENT}/firmware.bin"
    require_file(firmware)

    with tempfile.TemporaryDirectory(prefix="pingo-showcase-package-") as temporary:
        root = Path(temporary) / ARCHIVE_ROOT
        root.mkdir()
        copy_runtime(root)
        copy_file(firmware, root / "firmware.bin")
        firmware_hash = sha256(root / "firmware.bin")
        (root / "README.md").write_text(
            readme(
                pingo_identity,
                vdp_identity,
                firmware_hash,
                release_tag,
            ),
            encoding="utf-8",
            newline="\n",
        )
        (root / "SHA256SUMS").write_text(
            checksums(root), encoding="utf-8", newline="\n"
        )
        write_zip(root, output, zip_time)

    with zipfile.ZipFile(output) as archive:
        failed = archive.testzip()
        if failed:
            raise RuntimeError(f"ZIP CRC failure: {failed}")
        names = set(archive.namelist())
        required = {
            f"{ARCHIVE_ROOT}/README.md",
            f"{ARCHIVE_ROOT}/SHA256SUMS",
            *(f"{ARCHIVE_ROOT}/{path.as_posix()}" for path in REQUIRED_ARCHIVE_FILES),
        }
        if missing := required - names:
            raise RuntimeError(f"archive is missing required files: {sorted(missing)}")
        if any("wolf3d" in name.lower() for name in names):
            raise RuntimeError("archive unexpectedly contains a Wolf3D path")

    print(f"Package: {output}")
    print(f"Size: {output.stat().st_size} bytes")
    print(f"SHA-256: {sha256(output)}")
    print(f"Firmware SHA-256: {sha256(firmware)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
