#!/usr/bin/env python3
"""Generate assets and assemble the interactive eZ80-local Earth Party app."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "apps" / "earth-party-local"
PROFILE_PATH = APP_ROOT / "profile.json"
SOURCE_DIR = APP_ROOT / "src"
TARGET_DIR = APP_ROOT / "tgt"
SCRIPTS_DIR = PROJECT_ROOT / "build" / "scripts"
ASSEMBLY_FILENAME = "earth-party.asm"
OUTPUT_FILENAME = "earth-party.bin"
STARFIELD_INCLUDE = "starfield.inc"
POSE_HELPER_INCLUDE = "pose-cycle.inc"
EARTH_POSE_INCLUDE = "earth-spin-cycle.inc"
COMMON_POSE_HELPER = PROJECT_ROOT / "apps" / "_common" / POSE_HELPER_INCLUDE
GENERATOR = "build/scripts/build_earth_party_local.py"
EZ80_APPLICATION_WINDOW = 0x80000
EXPECTED_MODELS = (
    "jet",
    "earthuv",
    "crash",
    "lara",
    "heavytank",
    "airliner",
)


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    return path


def load_profile() -> dict[str, Any]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    models = profile.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("Earth Party profile needs at least one model")

    required = {
        "name",
        "model_obj_source",
        "texture_png_source",
        "texture_filename",
        "texture_size",
    }
    names: list[str] = []
    textures: list[str] = []
    for model in models:
        missing = sorted(required - model.keys())
        if missing:
            raise ValueError(
                f"{model.get('name', 'model')} is missing: {', '.join(missing)}"
            )
        name = str(model["name"])
        if not name.isidentifier() or not name.isascii():
            raise ValueError(f"assembly-unsafe model name: {name!r}")
        names.append(name)
        textures.append(str(model["texture_filename"]))
        if len(model["texture_size"]) != 2:
            raise ValueError(f"{name}.texture_size needs two values")
        for source_key in ("model_obj_source", "texture_png_source"):
            if not project_path(str(model[source_key])).is_file():
                raise ValueError(f"missing {name} source: {model[source_key]}")

    if tuple(names) != EXPECTED_MODELS:
        raise ValueError(
            "Earth Party models must be exactly: " + ", ".join(EXPECTED_MODELS)
        )

    starfield = profile.get("starfield")
    if not isinstance(starfield, dict):
        raise ValueError("Earth Party profile needs a starfield section")
    sys.path.insert(0, str(SCRIPTS_DIR))
    from generate_earth_party_starfield import validate_configuration

    validate_configuration(starfield)
    for key in ("earth_tilt_x_units", "earth_tilt_z_units"):
        value = starfield.get(key)
        if not isinstance(value, int) or not -32768 <= value <= 32767:
            raise ValueError(f"starfield.{key} must be a signed 16-bit integer")
    catalog_source = project_path(str(starfield["catalog_source"]))
    if not catalog_source.is_file():
        raise ValueError(f"missing starfield catalog: {starfield['catalog_source']}")
    textures.append(str(starfield["texture_filename"]))

    if len(textures) != len(set(textures)):
        raise ValueError("texture filenames must be unique")
    for texture in textures:
        texture_path = Path(texture)
        if (
            texture_path.name != texture
            or texture_path.suffix.lower() != ".rgba2"
            or texture == OUTPUT_FILENAME
        ):
            raise ValueError(f"unsafe texture filename: {texture!r}")
    return profile


def validate_staging_window(executable: Path, textures: list[Path]) -> None:
    largest_texture = max(texture.stat().st_size for texture in textures)
    required = executable.stat().st_size + largest_texture
    if required >= EZ80_APPLICATION_WINDOW:
        raise ValueError(
            f"executable plus largest staged texture requires {required} bytes; "
            f"eZ80 application window is {EZ80_APPLICATION_WINDOW} bytes"
        )


def build() -> Path:
    profile = load_profile()
    if not SOURCE_DIR.is_dir():
        raise RuntimeError(f"missing application source directory: {SOURCE_DIR}")

    sys.path.insert(0, str(SCRIPTS_DIR))
    from PIL import Image
    from agonImages import img_to_rgba2
    from blender_obj_to_asm import parse_obj_file, write_data
    from generate_earth_party_starfield import generate as generate_starfield
    from generate_pose_cycle import (
        PoseCycleSpec,
        write_generated_snapshot,
        write_pose_cycle_include,
    )

    temporary_root = Path(tempfile.mkdtemp(prefix=".earth-party-build-", dir=APP_ROOT))
    generated_source = temporary_root / "src"
    payload = temporary_root / "tgt"
    generated_source.mkdir()
    payload.mkdir()
    try:
        textures: list[Path] = []
        for model in profile["models"]:
            name = str(model["name"])
            expected_size = tuple(int(value) for value in model["texture_size"])
            texture_source = project_path(str(model["texture_png_source"]))
            texture_target = payload / str(model["texture_filename"])
            with Image.open(texture_source) as image:
                if image.size != expected_size:
                    raise ValueError(
                        f"{texture_source.relative_to(PROJECT_ROOT)} is "
                        f"{image.size}, profile declares {expected_size}"
                    )
                img_to_rgba2(image, texture_target)
            textures.append(texture_target)

            model_source = project_path(str(model["model_obj_source"]))
            write_data(
                model_source.stem,
                *parse_obj_file(model_source),
                generated_source / f"{name}.inc",
                texture_target,
                expected_size,
                symbol_prefix=name,
                authoritative_input=(
                    model_source.relative_to(PROJECT_ROOT).as_posix()
                ),
            )

        starfield = profile["starfield"]
        starfield_texture = payload / str(starfield["texture_filename"])
        generate_starfield(
            project_path(str(starfield["catalog_source"])),
            generated_source / STARFIELD_INCLUDE,
            starfield_texture,
            starfield,
            provenance_path=str(starfield["catalog_source"]),
        )
        textures.append(starfield_texture)

        write_generated_snapshot(
            COMMON_POSE_HELPER,
            generated_source / POSE_HELPER_INCLUDE,
            generator=GENERATOR,
            source_label="apps/_common/pose-cycle.inc",
        )
        write_pose_cycle_include(
            generated_source / EARTH_POSE_INCLUDE,
            PoseCycleSpec(
                symbol="earth_spin_pose",
                base_euler=(
                    int(starfield["earth_tilt_x_units"]),
                    0,
                    int(starfield["earth_tilt_z_units"]),
                ),
                local_axis="y",
                sample_count=256,
            ),
            generator=GENERATOR,
            authoritative_input="apps/earth-party-local/profile.json",
        )

        # Only the six generated model includes and procedural starfield are
        # replaceable. Hand-written controls and the app-local 3D snapshot
        # remain untouched.
        for name in EXPECTED_MODELS:
            (generated_source / f"{name}.inc").replace(
                SOURCE_DIR / f"{name}.inc"
            )
        (generated_source / STARFIELD_INCLUDE).replace(
            SOURCE_DIR / STARFIELD_INCLUDE
        )
        for filename in (POSE_HELPER_INCLUDE, EARTH_POSE_INCLUDE):
            (generated_source / filename).replace(SOURCE_DIR / filename)

        temporary_output = payload / OUTPUT_FILENAME
        output_argument = os.path.relpath(
            temporary_output.resolve(),
            SOURCE_DIR.resolve(),
        )
        subprocess.run(
            ["ez80asm", ASSEMBLY_FILENAME, output_argument],
            cwd=SOURCE_DIR,
            check=True,
        )
        validate_staging_window(temporary_output, textures)

        # Promote only a completely assembled and staging-safe payload. Keep
        # the old target recoverable until the new directory is in place.
        previous_target = temporary_root / "previous-tgt"
        if TARGET_DIR.exists():
            TARGET_DIR.rename(previous_target)
        try:
            payload.rename(TARGET_DIR)
        except BaseException:
            if previous_target.exists():
                previous_target.rename(TARGET_DIR)
            raise
        if previous_target.exists():
            shutil.rmtree(previous_target)
        return TARGET_DIR / OUTPUT_FILENAME
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


def main() -> int:
    output = build()
    print(f"Built {output.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
