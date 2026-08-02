#!/usr/bin/env python3
"""Export assets and assemble the rigid Lara animation application."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "apps" / "anim"
PROFILE_PATH = APP_ROOT / "profile.json"
SOURCE_DIR = APP_ROOT / "src"
TARGET_DIR = APP_ROOT / "tgt"
METADATA_DIR = APP_ROOT / "assets"
METADATA_PATH = METADATA_DIR / "lara-running.export.json"
EXPORTER = (
    PROJECT_ROOT
    / "blender/anim/bandai_namco/run_normal_001/scripts/"
    "export_pingo_rigid_animation.py"
)
EARTH_PARTY_SOURCE = PROJECT_ROOT / "apps" / "earth-party-tex" / "src"
GENERATOR = "build/scripts/build_anim.py"
ASSEMBLY_FILENAME = "anim.asm"
OUTPUT_FILENAME = "anim.bin"
MESH_INCLUDE = "lara-meshes.inc"
POSE_INCLUDE = "lara-poses.inc"
EZ80_APPLICATION_WINDOW = 0x80000
EXPECTED_TRACKS = 15
EXPECTED_FRAMES = 23
EXPECTED_LOOP_SUCCESSOR_FRAME = 24
EXPECTED_LOOP_CLOSURE_START = 15
EXPECTED_RECORD_BYTES = 12
EXPECTED_POSE_BYTES = EXPECTED_TRACKS * EXPECTED_FRAMES * EXPECTED_RECORD_BYTES
QUALIFIED_SOURCE_KEYS = (
    "source_blend",
    "rest_blend",
    "source_texture",
    "model_obj",
    "model_mtl",
    "source_motion",
    "motion_annotation",
    "motion_license",
    "asset_notice",
    "motion_provenance",
    "model_provenance",
    "scene_builder",
    "texture_converter",
)

HAND_WRITTEN_SOURCE = (
    Path("anim.asm"),
    Path("lara-animation.inc"),
)
SNAPSHOT_SOURCE = {
    Path("input.inc"): EARTH_PARTY_SOURCE / "input.inc",
    Path("timer.inc"): EARTH_PARTY_SOURCE / "timer.inc",
    Path("vdu_pingo.inc"): EARTH_PARTY_SOURCE / "vdu_pingo.inc",
    Path("render-async.inc"): EARTH_PARTY_SOURCE / "render-async.inc",
    Path("agon/3d.inc"): EARTH_PARTY_SOURCE / "agon/3d.inc",
    Path("agon/3d_sincos_table.inc"): (
        EARTH_PARTY_SOURCE / "agon/3d_sincos_table.inc"
    ),
}
GENERATED_SOURCE = (
    *SNAPSHOT_SOURCE,
    Path(MESH_INCLUDE),
    Path(POSE_INCLUDE),
)


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    return path


def load_profile() -> dict[str, Any]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    required = {
        "name",
        "qualified_blender_version",
        "source_blend",
        "rest_blend",
        "scene",
        "rest_scene",
        "frames",
        "loop_successor_frame",
        "source_texture",
        "model_obj",
        "model_mtl",
        "source_motion",
        "motion_annotation",
        "motion_license",
        "asset_notice",
        "motion_provenance",
        "model_provenance",
        "scene_builder",
        "texture_converter",
        "source_sha256",
        "qualified_output_sha256",
        "texture_filename",
        "texture_size",
        "resolution",
        "control_id",
        "texture_bitmap_id",
        "target_bitmap_id",
        "render_notification_token",
        "object_scale",
        "normalization_max_abs",
        "camera_offset",
        "source_rate_hz",
        "default_root_mode",
        "preserves_root_motion",
        "loopable",
        "semantic_meshes",
        "tracks",
    }
    missing = sorted(required - profile.keys())
    if missing:
        raise ValueError(f"animation profile is missing: {', '.join(missing)}")
    if profile["name"] != "anim":
        raise ValueError("profile name must be 'anim'")
    source_hashes = profile["source_sha256"]
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(
        QUALIFIED_SOURCE_KEYS
    ):
        raise ValueError("source_sha256 must cover every qualified source exactly")
    for source_key in QUALIFIED_SOURCE_KEYS:
        source = project_path(str(profile[source_key]))
        if not source.is_file():
            raise ValueError(f"missing source: {profile[source_key]}")
        expected_hash = str(source_hashes[source_key])
        if len(expected_hash) != 64 or any(
            character not in "0123456789abcdef" for character in expected_hash
        ):
            raise ValueError(f"invalid SHA-256 for {source_key}")
        actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"qualified source changed: {profile[source_key]}: "
                f"expected {expected_hash}, found {actual_hash}"
            )
    if not EXPORTER.is_file():
        raise ValueError(f"missing Blender exporter: {EXPORTER}")
    if profile["frames"] != [1, 23] or profile["source_rate_hz"] != 30:
        raise ValueError("qualified animation must be frames 1..23 at 30 Hz")
    if profile["loop_successor_frame"] != EXPECTED_LOOP_SUCCESSOR_FRAME:
        raise ValueError("qualified loop successor must be source frame 24")
    if profile["scene"] != "RUNNING_NORMAL_001" or profile["rest_scene"] != "REST_POSE":
        raise ValueError("qualified running/rest scene names changed")
    if profile["qualified_blender_version"] != "4.0.2":
        raise ValueError("qualified Blender version must be 4.0.2")
    if profile["default_root_mode"] != "controlled":
        raise ValueError("qualified default root mode must be controlled")
    if profile["preserves_root_motion"] is not True or profile["loopable"] is not True:
        raise ValueError("qualified clip must preserve root motion and be loopable")
    tracks = profile["tracks"]
    if not isinstance(tracks, list) or len(tracks) != EXPECTED_TRACKS:
        raise ValueError(f"profile must declare {EXPECTED_TRACKS} tracks")
    semantic_meshes = profile["semantic_meshes"]
    if not isinstance(semantic_meshes, list) or len(semantic_meshes) != 17:
        raise ValueError("profile must declare 17 semantic meshes")
    semantic_names = [item.get("name") for item in semantic_meshes if isinstance(item, dict)]
    track_sources = [source for track in tracks for source in track.get("sources", [])]
    if semantic_names != track_sources:
        raise ValueError("semantic mesh order must match track source order")
    if sum(int(item.get("vertices", 0)) for item in semantic_meshes) != 300:
        raise ValueError("semantic vertex inventory changed")
    if sum(int(item.get("triangles", 0)) for item in semantic_meshes) != 526:
        raise ValueError("semantic triangle inventory changed")

    texture_filename = str(profile["texture_filename"])
    texture_path = Path(texture_filename)
    if (
        texture_path.name != texture_filename
        or texture_path.suffix.lower() != ".rgba2"
        or texture_filename == OUTPUT_FILENAME
    ):
        raise ValueError(f"unsafe texture filename: {texture_filename!r}")
    texture_size = profile["texture_size"]
    resolution = profile["resolution"]
    camera_offset = profile["camera_offset"]
    if not isinstance(texture_size, list) or len(texture_size) != 2:
        raise ValueError("texture_size must contain width and height")
    if not isinstance(resolution, list) or len(resolution) != 2:
        raise ValueError("resolution must contain width and height")
    if not isinstance(camera_offset, list) or len(camera_offset) != 3:
        raise ValueError("camera_offset must contain X, Y, and Z")
    normalization = float(profile["normalization_max_abs"])
    if normalization != 0.7247999906539917:
        raise ValueError("qualified whole-character normalization changed")

    qualified_outputs = profile["qualified_output_sha256"]
    expected_output_names = {MESH_INCLUDE, POSE_INCLUDE, texture_filename}
    if not isinstance(qualified_outputs, dict) or set(qualified_outputs) != expected_output_names:
        raise ValueError("qualified_output_sha256 has an unexpected inventory")
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in qualified_outputs.values()
    ):
        raise ValueError("qualified output hashes must be lowercase SHA-256 values")

    global_ids = [
        int(profile["control_id"]),
        int(profile["texture_bitmap_id"]),
        int(profile["target_bitmap_id"]),
    ]
    if len(global_ids) != len(set(global_ids)):
        raise ValueError("control, texture, and target IDs must be distinct")
    if any(value <= 0 or value >= 65535 for value in global_ids):
        raise ValueError("global IDs must be in 1..65534")
    token = int(profile["render_notification_token"])
    if not 0 <= token <= 65535:
        raise ValueError("render notification token must fit 16 bits")
    return profile


def generated_banner(source: Path, *, selected_by_profile: bool = False) -> str:
    source_label = source.relative_to(PROJECT_ROOT).as_posix()
    if selected_by_profile:
        source_label += "; token selected by apps/anim/profile.json"
    return (
        "; =============================================================================\n"
        "; AUTO-GENERATED FILE - DO NOT EDIT\n"
        f"; Generated by: {GENERATOR}\n"
        f"; Generated from: {source_label}\n"
        "; Edit the generator or its authoritative inputs instead.\n"
        "; =============================================================================\n\n"
    )


def normalized_assembly(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def write_snapshot(
    source: Path,
    destination: Path,
    *,
    render_token: int | None = None,
) -> None:
    text = source.read_text(encoding="utf-8")
    selected_by_profile = render_token is not None
    if render_token is not None:
        old = "render_notify_token: equ 0C35Ah"
        if text.count(old) != 1:
            raise ValueError(f"unexpected render token declaration in {source}")
        text = text.replace(old, f"render_notify_token: equ 0{render_token:04X}h")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        generated_banner(source, selected_by_profile=selected_by_profile)
        + normalized_assembly(text),
        encoding="utf-8",
        newline="\n",
    )


def run_blender_export(profile: dict[str, Any], generated_source: Path, metadata: Path) -> None:
    blender = shutil.which("blender")
    if blender is None:
        raise RuntimeError("Blender executable was not found in PATH")
    subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python",
            str(EXPORTER),
            "--",
            "--profile",
            str(PROFILE_PATH),
            "--mesh-output",
            str(generated_source / MESH_INCLUDE),
            "--pose-output",
            str(generated_source / POSE_INCLUDE),
            "--metadata-output",
            str(metadata),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def generate_texture(profile: dict[str, Any], payload: Path) -> Path:
    sys.path.insert(0, str(PROJECT_ROOT / "build" / "scripts"))
    from PIL import Image
    from agonImages import img_to_rgba2

    source = project_path(str(profile["source_texture"]))
    expected_size = tuple(int(value) for value in profile["texture_size"])
    target = payload / str(profile["texture_filename"])
    with Image.open(source) as image:
        if image.size != expected_size:
            raise ValueError(
                f"{source.relative_to(PROJECT_ROOT)} is {image.size}, "
                f"profile declares {expected_size}"
            )
        img_to_rgba2(image, target)
    expected_bytes = expected_size[0] * expected_size[1]
    if target.stat().st_size != expected_bytes:
        raise ValueError(
            f"RGBA2222 texture is {target.stat().st_size} bytes, "
            f"expected {expected_bytes}"
        )
    return target


def validate_export(
    profile: dict[str, Any],
    metadata_path: Path,
    mesh_include: Path,
    pose_include: Path,
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 2:
        raise ValueError("export metadata schema changed")
    if metadata.get("generator") != EXPORTER.relative_to(PROJECT_ROOT).as_posix():
        raise ValueError("export metadata generator changed")
    source = metadata["source"]
    expected_inputs = {
        key: {
            "path": str(profile[key]),
            "sha256": str(profile["source_sha256"][key]),
        }
        for key in QUALIFIED_SOURCE_KEYS
    }
    if source["inputs"] != expected_inputs:
        raise ValueError("export metadata source inventory changed")
    if source["profile"] != {
        "path": PROFILE_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest(),
    }:
        raise ValueError("export metadata profile provenance changed")
    if source["exporter_sha256"] != hashlib.sha256(EXPORTER.read_bytes()).hexdigest():
        raise ValueError("export metadata exporter provenance changed")
    if source["blender_version"] != profile["qualified_blender_version"]:
        raise ValueError("export used an unqualified Blender version")

    contract = metadata["contract"]
    geometry = metadata["geometry"]
    if contract["basis"] != {
        "pingo_xyz": ["blender_x", "blender_z", "-blender_y"]
    }:
        raise ValueError("exported coordinate basis changed")
    if contract["normalization_max_abs"] != profile["normalization_max_abs"]:
        raise ValueError("exported normalization changed")
    if contract["object_scale_word"] != profile["object_scale"]:
        raise ValueError("exported object scale changed")
    if contract["frame_start"] != profile["frames"][0]:
        raise ValueError("exported first frame changed")
    if contract["frame_end"] != profile["frames"][1]:
        raise ValueError("exported final frame changed")
    if contract["frame_count"] != EXPECTED_FRAMES:
        raise ValueError("exported frame count changed")
    if contract["loop_successor_frame"] != profile["loop_successor_frame"]:
        raise ValueError("exported loop successor changed")
    if contract["loop_closure_start"] != EXPECTED_LOOP_CLOSURE_START:
        raise ValueError("exported loop-closure start changed")
    if contract["loop_closure_space"] != "pose-bone local quaternion/location/scale":
        raise ValueError("exported loop-closure space changed")
    if contract["loop_closure_order"] != "discrete C1":
        raise ValueError("exported loop-closure order changed")
    if contract["loop_forward_step_command_units"] != 77:
        raise ValueError("exported loop forward step changed")
    if contract["cycle_forward_command_units"] != 2131:
        raise ValueError("exported cycle forward distance changed")
    if contract["nominal_forward_step_command_units"] != 93:
        raise ValueError("exported nominal forward step changed")
    if contract["source_rate_hz"] != profile["source_rate_hz"]:
        raise ValueError("exported source rate changed")
    if contract["track_count"] != EXPECTED_TRACKS:
        raise ValueError("exported track count changed")
    if contract["pose_record_bytes"] != EXPECTED_RECORD_BYTES:
        raise ValueError("exported pose record size changed")
    if contract["pose_table_bytes"] != EXPECTED_POSE_BYTES:
        raise ValueError("exported pose table size changed")
    if contract["record_fields"] != ["tx", "ty", "tz", "rx", "ry", "rz"]:
        raise ValueError("exported pose fields changed")
    if contract["preserves_root_motion"] is not True or contract["loopable"] is not True:
        raise ValueError("exported root/loop policy changed")
    if geometry["semantic_parts"] != 17 or geometry["runtime_meshes"] != 15:
        raise ValueError("exported semantic/runtime mesh inventory changed")
    if geometry["positions"] != 300 or geometry["triangles"] != 526:
        raise ValueError("exported geometry inventory changed")
    expected_tracks = []
    semantic_by_name = {item["name"]: item for item in profile["semantic_meshes"]}
    for index, track in enumerate(profile["tracks"]):
        expected_tracks.append(
            {
                "index": index,
                "mesh_id": index + 1,
                "object_id": index + 1,
                "name": track["name"],
                "sources": track["sources"],
                "driver": track["driver"],
            }
        )
    for actual, expected in zip(geometry["tracks"], expected_tracks, strict=True):
        for key, value in expected.items():
            if actual[key] != value:
                raise ValueError(f"exported track contract changed: {key}")
        if sum(item["positions"] for item in actual["source_counts"]) != actual["positions"]:
            raise ValueError("track source position counts do not close")
        if sum(item["triangles"] for item in actual["source_counts"]) != actual["triangles"]:
            raise ValueError("track source triangle counts do not close")
        if [item["name"] for item in actual["source_counts"]] != expected["sources"]:
            raise ValueError("track source order changed")
        for item in actual["source_counts"]:
            semantic = semantic_by_name[item["name"]]
            if item != {
                "name": semantic["name"],
                "positions": semantic["vertices"],
                "triangles": semantic["triangles"],
                "driver": semantic["driver"],
                "rest_geometry_sha256": semantic["geometry_sha256"],
                "run_geometry_sha256": semantic["geometry_sha256"],
            }:
                raise ValueError(f"semantic source identity changed: {item['name']}")

    validation = metadata["validation"]
    if validation["pelvis_holster_matrix_error_max"] != 0.0:
        raise ValueError("pelvis/holster transforms diverged")
    if validation["scale_deviation_max"] >= 5.0e-5:
        raise ValueError("source scale residue exceeded the qualified gate")
    if validation["decomposition_coefficient_error_max"] >= 5.0e-5:
        raise ValueError("rigid decomposition error exceeded the qualified gate")
    if validation["quantized_rotation_coefficient_error_max"] >= 0.001:
        raise ValueError("quantized rotation error exceeded the qualified gate")
    if validation["quantized_transformed_vertex_error_max"] >= 0.01:
        raise ValueError("quantized vertex error exceeded the qualified gate")
    if max(validation["adjacent_euler_step_degrees_max"]) >= 45.0:
        raise ValueError("adjacent Euler step exceeded the qualified gate")
    if validation["loop_endpoint_translation_word_error_max"] > 1.0:
        raise ValueError("loop endpoint translation closure changed")
    if validation["loop_endpoint_rotation_degrees_max"] > 0.01:
        raise ValueError("loop endpoint rotation closure changed")
    if validation["loop_velocity_translation_word_error_max"] > 24.0:
        raise ValueError("loop translation-velocity residual changed")
    if validation["loop_velocity_rotation_degrees_max"] > 2.0:
        raise ValueError("loop rotation-velocity residual changed")
    for filename, path in (
        (MESH_INCLUDE, mesh_include),
        (POSE_INCLUDE, pose_include),
    ):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if metadata["outputs"][filename] != digest:
            raise ValueError(f"metadata hash mismatch for {filename}")
        if profile["qualified_output_sha256"][filename] != digest:
            raise ValueError(f"qualified output changed: {filename}")


def finalize_metadata(
    metadata_path: Path,
    profile: dict[str, Any],
    source_dir: Path,
    executable: Path,
    texture: Path,
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    texture_hash = hashlib.sha256(texture.read_bytes()).hexdigest()
    if texture_hash != profile["qualified_output_sha256"][texture.name]:
        raise ValueError(f"qualified output changed: {texture.name}")
    metadata["build"] = {
        "builder": Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix(),
        "builder_sha256": hashlib.sha256(
            Path(__file__).resolve().read_bytes()
        ).hexdigest(),
        "assembler": assembler_identity(),
        "assembly_inputs": {
            path.relative_to(source_dir).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(source_dir.rglob("*"))
            if path.is_file()
        },
        "outputs": {
            executable.name: {
                "bytes": executable.stat().st_size,
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            },
            texture.name: {
                "bytes": texture.stat().st_size,
                "sha256": texture_hash,
            },
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def assemble(source_dir: Path, output: Path) -> None:
    output_argument = os.path.relpath(output.resolve(), source_dir.resolve())
    subprocess.run(
        ["ez80asm", ASSEMBLY_FILENAME, output_argument],
        cwd=source_dir,
        check=True,
    )


def assembler_identity() -> dict[str, str]:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise RuntimeError("ez80asm executable was not found in PATH")
    executable = Path(assembler).resolve()
    version = subprocess.run(
        [str(executable), "-v"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "name": "ez80asm",
        "version": (version.stdout + version.stderr).strip(),
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }


def validate_staging_window(executable: Path, texture: Path) -> None:
    required = executable.stat().st_size + texture.stat().st_size
    if required >= EZ80_APPLICATION_WINDOW:
        raise ValueError(
            f"executable plus staged texture requires {required} bytes; "
            f"eZ80 application window is {EZ80_APPLICATION_WINDOW} bytes"
        )


def promote_target(payload: Path, temporary_root: Path) -> None:
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


def build() -> Path:
    profile = load_profile()
    for relative in HAND_WRITTEN_SOURCE:
        if not (SOURCE_DIR / relative).is_file():
            raise RuntimeError(f"missing hand-written application source: {relative}")
    for source in SNAPSHOT_SOURCE.values():
        if not source.is_file():
            raise RuntimeError(f"missing modern Earth Party source: {source}")

    temporary_root = Path(tempfile.mkdtemp(prefix=".anim-build-", dir=APP_ROOT))
    generated_source = temporary_root / "src"
    payload = temporary_root / "tgt"
    metadata = temporary_root / "lara-running.export.json"
    generated_source.mkdir()
    payload.mkdir()
    try:
        for relative in HAND_WRITTEN_SOURCE:
            destination = generated_source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE_DIR / relative, destination)

        render_token = int(profile["render_notification_token"])
        for relative, source in SNAPSHOT_SOURCE.items():
            write_snapshot(
                source,
                generated_source / relative,
                render_token=render_token if relative == Path("render-async.inc") else None,
            )

        run_blender_export(profile, generated_source, metadata)
        validate_export(
            profile,
            metadata,
            generated_source / MESH_INCLUDE,
            generated_source / POSE_INCLUDE,
        )
        texture = generate_texture(profile, payload)
        executable = payload / OUTPUT_FILENAME
        assemble(generated_source, executable)
        validate_staging_window(executable, texture)
        finalize_metadata(metadata, profile, generated_source, executable, texture)

        for relative in GENERATED_SOURCE:
            destination = SOURCE_DIR / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            (generated_source / relative).replace(destination)
        METADATA_DIR.mkdir(parents=True, exist_ok=True)
        metadata.replace(METADATA_PATH)
        promote_target(payload, temporary_root)
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
