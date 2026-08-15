#!/usr/bin/env python3
"""Build the experimental full-owner handoff profile without touching tgt.

The regular-LOD fixture has one accepted compile-time policy.  This helper
derives a temporary sibling source with ``terrain_manager_group_staging``
explicitly forced to either value, so the opposite policy remains a byte-exact
rollback after promotion.  It
audits its complete include closure, and writes the executable, listing,
symbols, and a small hash receipt beneath an explicitly disposable directory.
The assembly happens in a short-lived mirror under ``/tmp``.  Besides keeping
the accepted source tree untouched, that matters in read-only source checkouts:
ez80asm writes its listing and symbol sidecars beside the input source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = ROOT / "fixtures/terrain-manager-survey/src"
SOURCE = SOURCE_DIRECTORY / "terrain-manager-regular-lod-survey.asm"
TRANSITIONS = (
    ROOT
    / "fixtures/terrain-manager-regular-lod-survey/tgt"
    / "regular-lod-transitions.inc"
)
DEFAULT_OUTPUT = Path("/tmp/pingo-terrain-regular-lod-legacy-scratch")
DISABLED_POLICY = "terrain_manager_group_staging: equ 0"
ENABLED_POLICY = "terrain_manager_group_staging: equ 1"
OUTPUT_STEMS = {
    0: "terrain-manager-regular-lod-legacy-scratch",
    1: "terrain-manager-regular-lod-group-scratch",
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"disposable output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--group-staging",
        type=int,
        choices=(0, 1),
        default=0,
        help="compile-time terrain_manager_group_staging override (default: 0)",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_source(group_staging: int) -> str:
    text = SOURCE.read_text(encoding="ascii")
    disabled = text.count(DISABLED_POLICY)
    enabled = text.count(ENABLED_POLICY)
    if disabled + enabled != 1:
        raise SystemExit(
            "regular fixture no longer has exactly one group-staging policy"
        )
    requested = ENABLED_POLICY if group_staging else DISABLED_POLICY
    current = ENABLED_POLICY if enabled else DISABLED_POLICY
    return text.replace(current, requested)


def stage_source_mirror(directory: Path, group_staging: int) -> Path:
    """Create the minimum fsim-shaped tree ez80asm's relative includes need.

    ez80asm resolves includes from the entry source's working directory.  A
    single source symlink would consequently jump back into the real checkout
    and make its ``../../`` include paths wrong.  Keep the generated entry file
    real, mirror its parent layout, and symlink the immutable dependencies.
    """

    mirror_root = directory / "fsim"
    fixture_mirror = mirror_root / "fixtures"
    source_mirror = fixture_mirror / "terrain-manager-survey" / "src"
    source_mirror.mkdir(parents=True)

    for name in ("build", "runtime"):
        (mirror_root / name).symlink_to(ROOT / name, target_is_directory=True)

    for fixture in (ROOT / "fixtures").iterdir():
        if fixture.name == "terrain-manager-survey":
            continue
        (fixture_mirror / fixture.name).symlink_to(
            fixture, target_is_directory=fixture.is_dir()
        )

    for dependency in SOURCE_DIRECTORY.iterdir():
        if dependency == SOURCE:
            continue
        (source_mirror / dependency.name).symlink_to(
            dependency, target_is_directory=dependency.is_dir()
        )

    generated_source = source_mirror / "RLG.ASM"
    generated_source.write_text(profile_source(group_staging), encoding="ascii")
    return generated_source


def main() -> None:
    args = arguments()
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise SystemExit("ez80asm is not available on PATH")
    if not TRANSITIONS.is_file():
        raise SystemExit(f"transition include is missing: {TRANSITIONS}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    output_stem = OUTPUT_STEMS[args.group_staging]
    program = output / f"{output_stem}.bin"
    listing = output / f"{output_stem}.lst"
    symbols = output / f"{output_stem}.symbols"
    receipt = output / "BUILD.json"

    with tempfile.TemporaryDirectory(dir="/tmp", prefix="rlg-build-") as directory:
        temporary_source = stage_source_mirror(Path(directory), args.group_staging)
        generated_listing = temporary_source.with_suffix(".lst")
        generated_symbols = temporary_source.with_suffix(".symbols")
        generated_program = temporary_source.with_suffix(".BIN")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/audit_adl_width.py"),
                "--follow-includes",
                "--show-review",
                "--fail-review",
                str(temporary_source),
            ],
            cwd=temporary_source.parent,
            check=True,
        )
        subprocess.run(
            [
                assembler,
                "-l",
                "-s",
                temporary_source.name,
                generated_program.name,
                "-c",
            ],
            cwd=temporary_source.parent,
            check=True,
        )
        if not all(
            path.is_file()
            for path in (generated_program, generated_listing, generated_symbols)
        ):
            raise SystemExit("ez80asm omitted a requested scratch artifact")
        for generated, destination in (
            (generated_program, program),
            (generated_listing, listing),
            (generated_symbols, symbols),
        ):
            shutil.copy2(generated, destination)

    document = {
        "schema": "pingo-terrain-regular-lod-profile-scratch-v2",
        "source": str(SOURCE),
        "source_sha256": sha256(SOURCE),
        "transition_include": str(TRANSITIONS),
        "transition_include_sha256": sha256(TRANSITIONS),
        "policy": {"terrain_manager_group_staging": args.group_staging},
        "artifacts": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (program, listing, symbols)
        },
    }
    receipt.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(f"wrote group-staging={args.group_staging} scratch profile to {output}")


if __name__ == "__main__":
    main()
