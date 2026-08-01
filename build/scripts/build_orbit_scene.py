#!/usr/bin/env python3
"""Generate and assemble a deterministic multi-object Pingo orbit fixture."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = PROJECT_ROOT / "benchmarks" / "orbit-scene"
FIXTURES_ROOT = BENCHMARK_ROOT / "fixtures"
VDU_HELPERS = PROJECT_ROOT / "benchmarks" / "_common" / "vdu_pingo.inc"
SCRIPTS_DIR = PROJECT_ROOT / "build" / "scripts"
GENERATOR = "build/scripts/build_orbit_scene.py"
EZ80_APPLICATION_WINDOW = 0x80000


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    return path


def integer_word(value: float) -> int:
    return round(value)


def angle_word(degrees: float) -> int:
    return round((degrees % 360.0) * 32767.0 / 360.0)


def is_integer(value: float) -> bool:
    return math.isclose(value, round(value), abs_tol=1e-9)


def validate_staging_window(executable: Path, textures: list[Path]) -> None:
    largest_texture = max(texture.stat().st_size for texture in textures)
    required = executable.stat().st_size + largest_texture
    if required >= EZ80_APPLICATION_WINDOW:
        raise ValueError(
            f"executable plus largest staged texture requires {required} bytes; "
            f"eZ80 application window is {EZ80_APPLICATION_WINDOW} bytes"
        )


def validate_model(model: dict[str, Any], *, orbiter: bool) -> None:
    required = {
        "name",
        "model_obj_source",
        "texture_png_source",
        "texture_filename",
        "texture_size",
        "mesh_id",
        "object_id",
        "bitmap_id",
        "scale",
        "spin_turns_per_orbit",
    }
    if orbiter:
        required.add("phase_degrees")
    missing = sorted(required - model.keys())
    if missing:
        raise ValueError(
            f"{model.get('name', 'model')} is missing: {', '.join(missing)}"
        )
    if len(model["texture_size"]) != 2:
        raise ValueError(f"{model['name']}.texture_size needs two values")
    if len(model["spin_turns_per_orbit"]) != 3:
        raise ValueError(f"{model['name']}.spin_turns_per_orbit needs three values")
    for source_key in ("model_obj_source", "texture_png_source"):
        if not project_path(model[source_key]).is_file():
            raise ValueError(f"missing {model['name']} source: {model[source_key]}")


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "name",
        "resolution",
        "control_id",
        "target_bitmap_id",
        "warmup_target_bitmap_id",
        "target_format",
        "camera_pose",
        "series_runs",
        "warmup_frames",
        "frames_per_orbit",
        "orbit_revolutions",
        "include_closing_pose",
        "orbit_center",
        "orbit_radius",
        "central",
        "orbiters",
    }
    missing = sorted(required - profile.keys())
    if missing:
        raise ValueError("profile is missing: " + ", ".join(missing))
    if profile["target_format"] != "rgba2222":
        raise ValueError("orbit fixture currently requires an RGBA2222 target")
    if len(profile["resolution"]) != 2 or len(profile["camera_pose"]) != 3:
        raise ValueError("resolution needs two and camera_pose needs three values")
    if len(profile["orbit_center"]) != 3:
        raise ValueError("orbit_center needs three values")
    if not 1 <= int(profile["series_runs"]) <= 255:
        raise ValueError("series_runs must be between 1 and 255")
    if int(profile["warmup_frames"]) < 0:
        raise ValueError("warmup_frames must not be negative")
    if int(profile["frames_per_orbit"]) < 3:
        raise ValueError("frames_per_orbit must be at least three")
    if int(profile["orbit_revolutions"]) < 1:
        raise ValueError("orbit_revolutions must be positive")
    if not profile["orbiters"]:
        raise ValueError("at least one orbiter is required")
    camera_dolly = profile.get("camera_dolly")
    camera_ellipse = profile.get("camera_ellipse")
    if camera_dolly is not None and camera_ellipse is not None:
        raise ValueError("select camera_dolly or camera_ellipse, not both")
    if camera_dolly is not None:
        if set(camera_dolly) != {"near_z", "far_z", "objects_orbit"}:
            raise ValueError(
                "camera_dolly requires exactly near_z, far_z, and objects_orbit"
            )
        if not isinstance(camera_dolly["objects_orbit"], bool):
            raise ValueError("camera_dolly objects_orbit must be boolean")
        if float(camera_dolly["near_z"]) >= float(camera_dolly["far_z"]):
            raise ValueError("camera_dolly near_z must be less than far_z")
        if int(profile["orbit_revolutions"]) != 2:
            raise ValueError("camera_dolly requires two legs")
    if camera_ellipse is not None:
        required_ellipse = {
            "apoapsis_distance",
            "periapsis_distance",
            "camera_revolutions",
            "plane",
            "objects_orbit",
        }
        if set(camera_ellipse) != required_ellipse:
            raise ValueError(
                "camera_ellipse requires exactly apoapsis_distance, "
                "periapsis_distance, camera_revolutions, plane, and "
                "objects_orbit"
            )
        if not isinstance(camera_ellipse["objects_orbit"], bool):
            raise ValueError("camera_ellipse objects_orbit must be boolean")
        apoapsis = float(camera_ellipse["apoapsis_distance"])
        periapsis = float(camera_ellipse["periapsis_distance"])
        if periapsis <= 0 or apoapsis <= periapsis:
            raise ValueError(
                "camera_ellipse requires apoapsis_distance > "
                "periapsis_distance > 0"
            )
        if int(camera_ellipse["camera_revolutions"]) != 1:
            raise ValueError("camera_ellipse currently requires one revolution")
        if camera_ellipse["plane"] != "yz_polar":
            raise ValueError("camera_ellipse currently requires plane yz_polar")

    validate_model(profile["central"], orbiter=False)
    for model in profile["orbiters"]:
        validate_model(model, orbiter=True)

    models = [profile["central"], *profile["orbiters"]]
    for key in ("mesh_id", "object_id", "bitmap_id"):
        values = [int(model[key]) for model in models]
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {key}")
    bitmap_ids = [
        int(profile["target_bitmap_id"]),
        int(profile["warmup_target_bitmap_id"]),
        *(int(model["bitmap_id"]) for model in models),
    ]
    if len(bitmap_ids) != len(set(bitmap_ids)):
        raise ValueError("target and texture bitmap IDs must be distinct")

    revolutions = int(profile["orbit_revolutions"])
    for model in models:
        rates = model["spin_turns_per_orbit"]
        if not all(is_integer(float(rate) * revolutions) for rate in rates):
            raise ValueError(
                f"{model['name']} does not return to its starting orientation "
                f"after {revolutions} orbit(s)"
            )
    for model in profile["orbiters"]:
        if all(is_integer(float(rate)) for rate in model["spin_turns_per_orbit"]):
            raise ValueError(
                f"{model['name']} already returns front-facing after one orbit"
            )
    return profile


def banner(source: str) -> str:
    return (
        "; =============================================================================\n"
        "; AUTO-GENERATED FILE - DO NOT EDIT\n"
        f"; Generated by: {GENERATOR}\n"
        f"; Generated from: {source}\n"
        "; Edit the generator or its authoritative inputs instead.\n"
        "; =============================================================================\n\n"
    )


def render_pose(profile: dict[str, Any], frame: int, role: str) -> str:
    frames_per_orbit = int(profile["frames_per_orbit"])
    orbit_degrees = frame * 360.0 / frames_per_orbit
    cx, cy, cz = profile["orbit_center"]
    camera_dolly = profile.get("camera_dolly")
    camera_ellipse = profile.get("camera_ellipse")
    object_degrees = orbit_degrees
    if camera_dolly is not None and not camera_dolly["objects_orbit"]:
        object_degrees = 0.0
    if camera_ellipse is not None and not camera_ellipse["objects_orbit"]:
        object_degrees = 0.0
    lines = [
        f"    ; {role} frame {frame:03d}, orbit {orbit_degrees:.1f} degrees",
    ]

    central = profile["central"]
    central_angles = [
        angle_word(float(rate) * object_degrees)
        for rate in central["spin_turns_per_orbit"]
    ]
    lines.extend(
        (
            f"    ld hl,{central['name']}_oid",
            f"    ld bc,{integer_word(cx)}",
            f"    ld de,{integer_word(cy)}",
            f"    ld iy,{integer_word(cz)}",
            "    call sodabs",
            f"    ld hl,{central['name']}_oid",
            f"    ld bc,{central_angles[0]}",
            f"    ld de,{central_angles[1]}",
            f"    ld iy,{central_angles[2]}",
            "    call sorabs",
        )
    )

    radius = float(profile["orbit_radius"])
    for model in profile["orbiters"]:
        theta = math.radians(object_degrees + float(model["phase_degrees"]))
        x = integer_word(float(cx) + radius * math.sin(theta))
        y = integer_word(float(cy))
        z = integer_word(float(cz) + radius * math.cos(theta))
        angles = [
            angle_word(float(rate) * object_degrees)
            for rate in model["spin_turns_per_orbit"]
        ]
        lines.extend(
            (
                f"    ld hl,{model['name']}_oid",
                f"    ld bc,{x}",
                f"    ld de,{y}",
                f"    ld iy,{z}",
                "    call sodabs",
                f"    ld hl,{model['name']}_oid",
                f"    ld bc,{angles[0]}",
                f"    ld de,{angles[1]}",
                f"    ld iy,{angles[2]}",
                "    call sorabs",
            )
        )
    if camera_dolly is not None:
        leg = frame // frames_per_orbit
        leg_frame = frame % frames_per_orbit
        fraction = leg_frame / frames_per_orbit
        near_z = float(camera_dolly["near_z"])
        far_z = float(camera_dolly["far_z"])
        if leg == 0:
            camera_z = far_z + (near_z - far_z) * fraction
        else:
            camera_z = near_z + (far_z - near_z) * fraction
        if frame == frames_per_orbit * 2:
            camera_z = far_z
        camera_x, camera_y, _ = profile["camera_pose"]
        lines.extend(
            (
                f"    ld bc,{integer_word(float(camera_x))}",
                f"    ld de,{integer_word(float(camera_y))}",
                f"    ld iy,{integer_word(camera_z)}",
                "    call scdabs",
            )
        )
    elif camera_ellipse is not None:
        total_object_degrees = (
            360.0
            * int(profile["orbit_revolutions"])
        )
        camera_degrees = (
            orbit_degrees
            * 360.0
            * int(camera_ellipse["camera_revolutions"])
            / total_object_degrees
        )
        theta = math.radians(camera_degrees)
        apoapsis = float(camera_ellipse["apoapsis_distance"])
        periapsis = float(camera_ellipse["periapsis_distance"])
        semi_major = (apoapsis + periapsis) / 2.0
        eccentricity = (apoapsis - periapsis) / (apoapsis + periapsis)
        semi_latus = semi_major * (1.0 - eccentricity * eccentricity)
        radius = semi_latus / (1.0 - eccentricity * math.cos(theta))
        camera_x = integer_word(float(cx))
        camera_y = integer_word(float(cy) + radius * math.sin(theta))
        camera_z = integer_word(float(cz) + radius * math.cos(theta))
        camera_pitch = angle_word(-camera_degrees)
        lines.extend(
            (
                f"    ld bc,{camera_x}",
                f"    ld de,{camera_y}",
                f"    ld iy,{camera_z}",
                "    call scdabs",
                f"    ld bc,{camera_pitch}",
                "    ld de,0",
                "    ld iy,0",
                "    call scrabs",
            )
        )
    routine = "render_warmup_frame" if role == "warmup" else "render_frame"
    lines.append(f"    call {routine}")
    return "\n".join(lines) + "\n\n"


def assembly(
    profile: dict[str, Any],
    profile_path: Path,
    generation_overrides: list[str] | None = None,
) -> str:
    profile_rel = profile_path.resolve().relative_to(PROJECT_ROOT).as_posix()
    width, height = profile["resolution"]
    camera_x, camera_y, camera_z = profile["camera_pose"]
    models = [profile["central"], *profile["orbiters"]]

    includes = "\n".join(f'    include "{model["name"]}.inc"' for model in models)
    constants = []
    loads = []
    objects = []
    for model in models:
        name = model["name"]
        constants.extend(
            (
                f"{name}_mid: equ {model['mesh_id']}",
                f"{name}_oid: equ {model['object_id']}",
                f"{name}_bmid: equ {model['bitmap_id']}",
                f"{name}_scale: equ {model['scale']}",
                f'{name}_texture_name: db "{model["texture_filename"]}",0',
            )
        )
        loads.extend(
            (
                f"    ld bc,{name}_texture_width",
                f"    ld de,{name}_texture_height",
                f"    ld hl,{name}_bmid",
                f"    ld ix,{name}_texture_size",
                f"    ld iy,{name}_texture_name",
                "    ld a,1",
                "    call vdu_load_img",
                "",
            )
        )
        objects.extend(
            (
                f"    SV sid,{name}_mid,{name}_vertices,{name}_vertices_n",
                f"    SMVI sid,{name}_mid,{name}_vertex_indices,{name}_indices_n",
                f"    STC sid,{name}_mid,{name}_uvs,{name}_uvs_n",
                f"    STCI sid,{name}_mid,{name}_uv_indices,{name}_indices_n",
                f"    CO sid,{name}_oid,{name}_mid,{name}_bmid",
                f"    SO sid,{name}_oid,{name}_scale,{name}_scale,{name}_scale",
                "",
            )
        )

    warmups = "".join(
        render_pose(profile, frame, "warmup")
        for frame in range(int(profile["warmup_frames"]))
    )
    endpoint = 1 if profile["include_closing_pose"] else 0
    measured_count = (
        int(profile["frames_per_orbit"]) * int(profile["orbit_revolutions"])
        + endpoint
    )
    measured = "".join(
        render_pose(profile, frame, "measured") for frame in range(measured_count)
    )

    generation_note = ""
    if generation_overrides:
        generation_note = (
            "; Generation overrides: "
            + ", ".join(generation_overrides)
            + "\n\n"
        )
    return banner(profile_rel) + generation_note + f"""\
mos_load: equ 01h
mos_sysvars: equ 08h
mos_getkbmap: equ 1Eh
sysvar_time: equ 00h
sysvar_keyascii: equ 05h

    MACRO MOSCALL function
        ld a,function
        rst.lil 08h
    ENDMACRO

    .assume adl=1
    .org 0x040000
    jp start

    .align 64
    .db "MOS",0,1

start:
    push af
    push bc
    push de
    push ix
    push iy
    call main
    pop iy
    pop ix
    pop de
    pop bc
    pop af
    ld hl,0
    ret

    include "vdu_pingo.inc"
{includes}

sid: equ {profile["control_id"]}
tgtbmid: equ {profile["target_bitmap_id"]}
warmupbmid: equ {profile["warmup_target_bitmap_id"]}
benchmark_series_runs: equ {profile["series_runs"]}
benchmark_measured_frames: equ {measured_count}

{chr(10).join(constants)}

main:
{chr(10).join(loads)}
    CTB2 tgtbmid,{width},{height}
    CTB2 warmupbmid,{width},{height}
    CCS sid,{width},{height}
{chr(10).join(objects)}
    ld a,8+128
    call vdu_set_screen_mode
    xor a
    call vdu_set_scaling
    call cursor_off
    call vdu_clg
    call vdu_flip
    call vdu_clg

    ld bc,{camera_x}
    ld de,{camera_y}
    ld iy,{camera_z}
    call scdabs

    ld a,benchmark_series_runs
benchmark_series_loop:
    push af
{warmups}{measured}\
    pop af
    dec a
    jp nz,benchmark_series_loop

    xor a
    call vdu_set_screen_mode
    ld a,1
    call vdu_set_scaling
    call cursor_on
    ret

render_frame:
    RENDBMP sid,tgtbmid
    call vdu_clg
    DISPBMP tgtbmid,0,0
    call vdu_flip
    ret

render_warmup_frame:
    RENDBMP sid,warmupbmid
    call vdu_clg
    DISPBMP warmupbmid,0,0
    call vdu_flip
    ret

filedata:
"""


def generate(
    profile_path: Path,
    *,
    assemble: bool,
    fixture_suffix: str = "",
    frames_per_orbit: int | None = None,
    series_runs: int | None = None,
    warmup_frames: int | None = None,
) -> Path:
    profile = load_profile(profile_path)
    overrides = []
    if fixture_suffix:
        if "/" in fixture_suffix or fixture_suffix in {".", ".."}:
            raise ValueError("fixture suffix must not contain a path separator")
        profile["name"] += fixture_suffix
        overrides.append(f"fixture_suffix={fixture_suffix}")
    if frames_per_orbit is not None:
        if frames_per_orbit < 3:
            raise ValueError("frames_per_orbit must be at least three")
        profile["frames_per_orbit"] = frames_per_orbit
        overrides.append(f"frames_per_orbit={frames_per_orbit}")
    if series_runs is not None:
        if not 1 <= series_runs <= 255:
            raise ValueError("series_runs must be between 1 and 255")
        profile["series_runs"] = series_runs
        overrides.append(f"series_runs={series_runs}")
    if warmup_frames is not None:
        if warmup_frames < 0:
            raise ValueError("warmup_frames must not be negative")
        profile["warmup_frames"] = warmup_frames
        overrides.append(f"warmup_frames={warmup_frames}")
    fixture_root = FIXTURES_ROOT / profile["name"]
    source_dir = fixture_root / "src"
    target_dir = fixture_root / "tgt"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(SCRIPTS_DIR))
    from PIL import Image
    from agonImages import img_to_rgba2
    from blender_obj_to_asm import parse_obj_file, write_data

    for model in [profile["central"], *profile["orbiters"]]:
        texture_source = project_path(model["texture_png_source"])
        texture_target = target_dir / model["texture_filename"]
        image = Image.open(texture_source)
        expected_size = tuple(model["texture_size"])
        if image.size != expected_size:
            raise ValueError(
                f"{texture_source.relative_to(PROJECT_ROOT)} is {image.size}, "
                f"profile declares {expected_size}"
            )
        img_to_rgba2(image, texture_target)

        model_source = project_path(model["model_obj_source"])
        model_data = parse_obj_file(model_source)
        write_data(
            model_source.stem,
            *model_data,
            source_dir / f"{model['name']}.inc",
            texture_target,
            expected_size,
            symbol_prefix=model["name"],
            authoritative_input=model_source.relative_to(PROJECT_ROOT).as_posix(),
        )

    shutil.copy2(VDU_HELPERS, source_dir / "vdu_pingo.inc")
    (source_dir / "benchmark.asm").write_text(
        assembly(profile, profile_path, overrides),
        encoding="utf-8",
    )
    effective = dict(profile)
    effective["_generated_by"] = GENERATOR
    effective["_generation_overrides"] = overrides
    effective["measured_frames"] = (
        int(profile["frames_per_orbit"]) * int(profile["orbit_revolutions"])
        + (1 if profile["include_closing_pose"] else 0)
    )
    (fixture_root / "effective-profile.json").write_text(
        json.dumps(effective, indent=2) + "\n",
        encoding="utf-8",
    )

    output = target_dir / "benchmark.bin"
    if assemble:
        output.unlink(missing_ok=True)
        subprocess.run(
            ["ez80asm", "benchmark.asm", "../tgt/benchmark.bin"],
            cwd=source_dir,
            check=True,
        )
        validate_staging_window(output, list(target_dir.glob("*.rgba2")))
    return fixture_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--no-assemble", action="store_true")
    parser.add_argument("--fixture-suffix", default="")
    parser.add_argument("--frames-per-orbit", type=int)
    parser.add_argument("--series-runs", type=int)
    parser.add_argument("--warmup-frames", type=int)
    args = parser.parse_args()
    root = generate(
        args.profile.resolve(),
        assemble=not args.no_assemble,
        fixture_suffix=args.fixture_suffix,
        frames_per_orbit=args.frames_per_orbit,
        series_runs=args.series_runs,
        warmup_frames=args.warmup_frames,
    )
    print(f"Generated {root.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
