#!/usr/bin/env python3
"""Generate and assemble a deterministic Pingo render benchmark fixture."""

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
BENCHMARK_ROOT = PROJECT_ROOT / "benchmarks" / "render-spin"
FIXTURES_ROOT = BENCHMARK_ROOT / "fixtures"
VDU_HELPERS = PROJECT_ROOT / "benchmarks" / "_common" / "vdu_pingo.inc"
GENERATOR = "build/scripts/build_render_benchmark.py"
SCRIPTS_DIR = PROJECT_ROOT / "build" / "scripts"

TEXTURE_FORMATS = {
    "rgba8888": 0,
    "rgba2222": 1,
}
TARGET_FORMATS = {
    "rgba8888": "CTB",
    "rgba2222": "CTB2",
}
AXIS_REGISTERS = {
    "x": ("{angle}", "0", "0"),
    "y": ("0", "{angle}", "0"),
    "z": ("0", "0", "{angle}"),
}


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {value}") from exc
    return path


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "name",
        "texture_format",
        "target_format",
        "texture_width",
        "texture_height",
        "control_id",
        "texture_bitmap_id",
        "target_bitmap_id",
        "warmup_target_bitmap_id",
        "object_scale",
        "camera_pose",
        "warmup_frames",
        "measured_frames",
        "rotation_axis",
        "rotation_step_degrees",
        "resolution",
    }
    missing = sorted(required - profile.keys())
    if missing:
        raise ValueError(f"profile is missing: {', '.join(missing)}")
    if ("model_source" in profile) == ("model_obj_source" in profile):
        raise ValueError("profile needs exactly one of model_source or model_obj_source")
    if ("texture_source" in profile) == ("texture_png_source" in profile):
        raise ValueError(
            "profile needs exactly one of texture_source or texture_png_source"
        )
    if profile["texture_format"] not in TEXTURE_FORMATS:
        raise ValueError(f"unsupported texture_format: {profile['texture_format']}")
    if profile["target_format"] not in TARGET_FORMATS:
        raise ValueError(f"unsupported target_format: {profile['target_format']}")
    if profile["rotation_axis"] not in AXIS_REGISTERS:
        raise ValueError(f"rotation_axis must be x, y, or z")
    ids = [
        profile["control_id"],
        profile["texture_bitmap_id"],
        profile["target_bitmap_id"],
        profile["warmup_target_bitmap_id"],
    ]
    if len(set(ids)) != len(ids):
        raise ValueError("control and bitmap IDs must be distinct")
    if len(profile["camera_pose"]) != 3 or len(profile["resolution"]) != 2:
        raise ValueError("camera_pose needs 3 values and resolution needs 2")
    closing_pose = profile.get("include_closing_pose", False)
    if not isinstance(closing_pose, bool):
        raise ValueError("include_closing_pose must be boolean")
    intervals = profile["measured_frames"] - (1 if closing_pose else 0)
    revolutions = int(profile.get("rotation_revolutions", 1))
    if revolutions < 1:
        raise ValueError("rotation_revolutions must be positive")
    if intervals * profile["rotation_step_degrees"] != 360 * revolutions:
        raise ValueError(
            "rotation intervals * rotation_step_degrees must equal "
            "360 * rotation_revolutions"
        )
    series_runs = int(profile.get("series_runs", 1))
    if not 1 <= series_runs <= 255:
        raise ValueError("series_runs must be between 1 and 255")
    motion = profile.get("translation_motion")
    if motion is not None:
        if not isinstance(motion, dict):
            raise ValueError("translation_motion must be an object")
        required_motion = {"center", "amplitude", "cycles", "phase_degrees"}
        missing_motion = sorted(required_motion - motion.keys())
        if missing_motion:
            raise ValueError(
                "translation_motion is missing: " + ", ".join(missing_motion)
            )
        unknown_motion = sorted(motion.keys() - required_motion)
        if unknown_motion:
            raise ValueError(
                "translation_motion has unknown fields: "
                + ", ".join(unknown_motion)
            )
        for field in sorted(required_motion):
            values = motion[field]
            if not isinstance(values, list) or len(values) != 3:
                raise ValueError(
                    f"translation_motion.{field} needs three numeric values"
                )
            numeric_values = all(
                not isinstance(value, bool) and isinstance(value, (int, float))
                for value in values
            )
            if not numeric_values:
                raise ValueError(
                    f"translation_motion.{field} needs three numeric values"
                )
            try:
                finite_values = all(math.isfinite(value) for value in values)
            except OverflowError:
                finite_values = False
            if not finite_values:
                raise ValueError(
                    f"translation_motion.{field} needs three finite values"
                )
        for center, amplitude in zip(
            motion["center"], motion["amplitude"], strict=True
        ):
            low = center - abs(amplitude)
            high = center + abs(amplitude)
            if low < -32767 or high > 32767:
                raise ValueError(
                    "translation_motion exceeds the -32767..32767 VDU range"
                )
    camera_motion = profile.get("camera_linear_motion")
    if camera_motion is not None:
        if not isinstance(camera_motion, dict):
            raise ValueError("camera_linear_motion must be an object")
        required_camera_motion = {"start", "turnaround"}
        if set(camera_motion) != required_camera_motion:
            raise ValueError(
                "camera_linear_motion requires exactly start and turnaround"
            )
        for field in sorted(required_camera_motion):
            values = camera_motion[field]
            if (
                not isinstance(values, list)
                or len(values) != 3
                or not all(
                    not isinstance(value, bool) and isinstance(value, (int, float))
                    for value in values
                )
                or not all(math.isfinite(value) for value in values)
            ):
                raise ValueError(
                    f"camera_linear_motion.{field} needs three finite numeric values"
                )
            if any(value < -32767 or value > 32767 for value in values):
                raise ValueError(
                    f"camera_linear_motion.{field} exceeds the "
                    "-32767..32767 VDU range"
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


def angle_word(degrees: int) -> int:
    return round((degrees % 360) * 32767 / 360)


def motion_translation(
    profile: dict[str, Any], degrees: int
) -> tuple[int, int, int] | None:
    motion = profile.get("translation_motion")
    if motion is None:
        return None
    values = []
    for center, amplitude, cycles, phase in zip(
        motion["center"],
        motion["amplitude"],
        motion["cycles"],
        motion["phase_degrees"],
        strict=True,
    ):
        radians = math.radians(cycles * degrees + phase)
        values.append(round(center + amplitude * math.sin(radians)))
    return values[0], values[1], values[2]


def camera_linear_translation(
    profile: dict[str, Any], index: int, frame_count: int
) -> tuple[int, int, int] | None:
    """Interpolate start -> turnaround -> start over one series."""
    motion = profile.get("camera_linear_motion")
    if motion is None:
        return None
    if frame_count < 2:
        return tuple(round(value) for value in motion["start"])
    phase = index / (frame_count - 1)
    fraction = phase * 2.0 if phase <= 0.5 else (1.0 - phase) * 2.0
    return tuple(
        round(start + (turnaround - start) * fraction)
        for start, turnaround in zip(
            motion["start"], motion["turnaround"], strict=True
        )
    )


def render_pose(
    axis: str,
    degrees: int,
    role: str,
    index: int,
    translation: tuple[int, int, int] | None = None,
    camera_translation: tuple[int, int, int] | None = None,
) -> str:
    registers = [
        value.format(angle=str(angle_word(degrees)))
        for value in AXIS_REGISTERS[axis]
    ]
    render_routine = "render_warmup_frame" if role == "warmup" else "render_frame"
    comment = f"    ; {role} frame {index:02d}, {degrees:03d} degrees"
    translation_code = ""
    if translation is not None:
        x, y, z = translation
        comment += f", translation ({x}, {y}, {z})"
        translation_code = (
            "    ld hl,oid\n"
            f"    ld bc,{x}\n"
            f"    ld de,{y}\n"
            f"    ld iy,{z}\n"
            "    call sodabs\n"
        )
    camera_code = ""
    if camera_translation is not None:
        camera_x, camera_y, camera_z = camera_translation
        comment += f", camera translation ({camera_x}, {camera_y}, {camera_z})"
        camera_code = (
            f"    ld bc,{camera_x}\n"
            f"    ld de,{camera_y}\n"
            f"    ld iy,{camera_z}\n"
            "    call scdabs\n"
        )
    return (
        comment + "\n"
        + translation_code
        + camera_code
        + "    ld hl,oid\n"
        f"    ld bc,{registers[0]}\n"
        f"    ld de,{registers[1]}\n"
        f"    ld iy,{registers[2]}\n"
        "    call sorabs\n"
        f"    call {render_routine}\n\n"
    )


def assembly(profile: dict[str, Any], profile_path: Path, texture_name: str) -> str:
    width, height = profile["resolution"]
    camera_x, camera_y, camera_z = profile["camera_pose"]
    warmups = profile["warmup_frames"]
    measured = profile["measured_frames"]
    step = profile["rotation_step_degrees"]
    axis = profile["rotation_axis"]
    poses = []
    for index in range(warmups):
        degrees = (index * step) % 360
        poses.append(
            render_pose(
                axis,
                degrees,
                "warmup",
                index,
                motion_translation(profile, degrees),
                camera_linear_translation(profile, index, warmups),
            )
        )
    for index in range(measured):
        degrees = index * step
        poses.append(
            render_pose(
                axis,
                degrees,
                "measured",
                index,
                motion_translation(profile, degrees),
                camera_linear_translation(profile, index, measured),
            )
        )
    pose_code = "".join(poses)
    profile_rel = profile_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    texture_size = profile["_texture_size"]
    texture_format = TEXTURE_FORMATS[profile["texture_format"]]
    target_macro = TARGET_FORMATS[profile["target_format"]]
    generation_note = ""
    if profile.get("_generation_overrides"):
        generation_note = (
            "; Generation overrides: "
            + ", ".join(profile["_generation_overrides"])
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
    include "model.inc"

sid: equ {profile["control_id"]}
mid: equ 1
oid: equ 1
objbmid: equ {profile["texture_bitmap_id"]}
tgtbmid: equ {profile["target_bitmap_id"]}
warmupbmid: equ {profile["warmup_target_bitmap_id"]}
obj_scale: equ {profile["object_scale"]}
benchmark_series_runs: equ {int(profile.get("series_runs", 1))}

benchmark_texture_width: equ {profile["texture_width"]}
benchmark_texture_height: equ {profile["texture_height"]}
benchmark_texture_size: equ {texture_size}
benchmark_texture_name: db "{texture_name}",0

main:
    ; Load the profile-selected texture and create its bitmap.
    ld bc,benchmark_texture_width
    ld de,benchmark_texture_height
    ld hl,objbmid
    ld ix,benchmark_texture_size
    ld iy,benchmark_texture_name
    ld a,{texture_format}
    call vdu_load_img

    {target_macro} tgtbmid,{width},{height}
    {target_macro} warmupbmid,{width},{height}
    CCS sid,{width},{height}
    SV sid,mid,model_vertices,model_vertices_n
    SMVI sid,mid,model_vertex_indices,model_indices_n
    STC sid,mid,model_uvs,model_uvs_n
    STCI sid,mid,model_uv_indices,model_indices_n
    CO sid,oid,mid,objbmid
    SO sid,oid,obj_scale,obj_scale,obj_scale

    ld a,8+128
    call vdu_set_screen_mode
    xor a
    call vdu_set_scaling
    call cursor_off
    call vdu_clg
    call vdu_flip
    call vdu_clg

    ld hl,oid
    ld bc,0
    ld de,0
    ld iy,0
    call sodabs

    ld bc,{camera_x}
    ld de,{camera_y}
    ld iy,{camera_z}
    call scdabs

    ld a,benchmark_series_runs
benchmark_series_loop:
    push af
{pose_code}\
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
    ; MOS loads the texture into free RAM beginning at this final label.
"""


def generated_copy(source: Path, destination: Path, profile_path: Path) -> None:
    source_rel = source.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    profile_rel = profile_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    destination.write_text(
        banner(f"{source_rel}; selected by {profile_rel}")
        + source.read_text(encoding="utf-8").rstrip()
        + "\n",
        encoding="utf-8",
    )


def generate_texture(profile: dict[str, Any], destination: Path) -> None:
    source = project_path(profile["texture_png_source"])
    sys.path.insert(0, str(SCRIPTS_DIR))
    from PIL import Image
    from agonImages import img_to_rgba2, img_to_rgba8

    image = Image.open(source)
    expected_size = (profile["texture_width"], profile["texture_height"])
    if image.size != expected_size:
        raise ValueError(
            f"{source.relative_to(PROJECT_ROOT)} is {image.size}, "
            f"profile declares {expected_size}"
        )
    if profile["texture_format"] == "rgba2222":
        img_to_rgba2(image, destination)
    else:
        img_to_rgba8(image, destination)


def generate_model(
    profile: dict[str, Any],
    destination: Path,
    texture_path: Path,
) -> None:
    source = project_path(profile["model_obj_source"])
    sys.path.insert(0, str(SCRIPTS_DIR))
    from blender_obj_to_asm import parse_obj_file, write_data

    model_data = parse_obj_file(source)
    write_data(
        source.stem,
        *model_data,
        destination,
        texture_path,
        (profile["texture_width"], profile["texture_height"]),
        symbol_prefix="model",
        authoritative_input=source.relative_to(PROJECT_ROOT).as_posix(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile",
        type=Path,
        help="profile JSON (absolute or relative to the current directory)",
    )
    parser.add_argument("--no-assemble", action="store_true")
    parser.add_argument(
        "--fixture-suffix",
        default="",
        help="suffix for an isolated generated fixture name",
    )
    parser.add_argument(
        "--fixture-name",
        help="exact name for an isolated generated fixture",
    )
    parser.add_argument(
        "--warmup-frames",
        type=int,
        help="override the profile warmup count for this generated fixture",
    )
    parser.add_argument(
        "--series-runs",
        type=int,
        help="override the profile series count for this generated fixture",
    )
    parser.add_argument(
        "--translation-motion-from",
        type=Path,
        help="reuse translation_motion from another validated profile",
    )
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    profile = load_profile(profile_path)
    overrides = []
    if args.fixture_name and args.fixture_suffix:
        raise ValueError("fixture name and fixture suffix are mutually exclusive")
    if args.fixture_name:
        if Path(args.fixture_name).name != args.fixture_name:
            raise ValueError("fixture name must not contain a path separator")
        profile["name"] = args.fixture_name
        overrides.append(f"fixture_name={args.fixture_name}")
    if args.fixture_suffix:
        if "/" in args.fixture_suffix or args.fixture_suffix in {".", ".."}:
            raise ValueError("fixture suffix must not contain a path separator")
        profile["name"] += args.fixture_suffix
        overrides.append(f"fixture_suffix={args.fixture_suffix}")
    if args.warmup_frames is not None:
        if args.warmup_frames < 0:
            raise ValueError("warmup frames must not be negative")
        profile["warmup_frames"] = args.warmup_frames
        overrides.append(f"warmup_frames={args.warmup_frames}")
    if args.series_runs is not None:
        if not 1 <= args.series_runs <= 255:
            raise ValueError("series runs must be between 1 and 255")
        profile["series_runs"] = args.series_runs
        overrides.append(f"series_runs={args.series_runs}")
    if args.translation_motion_from is not None:
        motion_profile_path = args.translation_motion_from.resolve()
        motion_profile = load_profile(motion_profile_path)
        if "translation_motion" not in motion_profile:
            raise ValueError(
                f"motion profile has no translation_motion: {motion_profile_path}"
            )
        profile["translation_motion"] = motion_profile["translation_motion"]
        try:
            motion_source = motion_profile_path.relative_to(PROJECT_ROOT)
        except ValueError:
            motion_source = motion_profile_path
        overrides.append(f"translation_motion_from={motion_source}")
    profile["_generation_overrides"] = overrides
    fixture_root = FIXTURES_ROOT / profile["name"]
    source_dir = fixture_root / "src"
    target_dir = fixture_root / "tgt"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    if "texture_source" in profile:
        texture_source = project_path(profile["texture_source"])
        texture_name = profile.get("texture_filename", texture_source.name)
        texture_target = target_dir / texture_name
        shutil.copy2(texture_source, texture_target)
    else:
        texture_png = project_path(profile["texture_png_source"])
        suffix = ".rgba2" if profile["texture_format"] == "rgba2222" else ".rgba8"
        texture_name = profile.get("texture_filename", texture_png.stem + suffix)
        texture_target = target_dir / texture_name
        generate_texture(profile, texture_target)

    profile["_texture_size"] = texture_target.stat().st_size
    if overrides:
        effective_profile = {
            key: value for key, value in profile.items() if not key.startswith("_")
        }
        effective_profile["_generated_by"] = GENERATOR
        effective_profile["_generation_overrides"] = overrides
        (fixture_root / "effective-profile.json").write_text(
            json.dumps(effective_profile, indent=2) + "\n",
            encoding="utf-8",
        )
    if "model_source" in profile:
        model_source = project_path(profile["model_source"])
        generated_copy(model_source, source_dir / "model.inc", profile_path)
    else:
        generate_model(profile, source_dir / "model.inc", texture_target)
    generated_copy(VDU_HELPERS, source_dir / "vdu_pingo.inc", profile_path)
    (source_dir / "benchmark.asm").write_text(
        assembly(profile, profile_path, texture_name),
        encoding="utf-8",
    )
    output = target_dir / "benchmark.bin"
    if not args.no_assemble:
        output.unlink(missing_ok=True)
        subprocess.run(
            ["ez80asm", "benchmark.asm", "../tgt/benchmark.bin"],
            cwd=source_dir,
            check=True,
        )

    print(f"Generated {fixture_root.relative_to(PROJECT_ROOT)}")
    if not args.no_assemble:
        print(f"Assembled {output.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
