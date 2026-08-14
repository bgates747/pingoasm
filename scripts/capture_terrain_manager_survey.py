#!/usr/bin/env python3
"""Silently qualify initial universal-manager hex-disk publication."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import capture_koak_flight as capture


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VDP = (
    Path.home()
    / "Agon/mystuff/agon-vdp/video/build/"
    "userspace-p3dm-loader-diagnostics/vdp_combined.so"
)
FIXTURE = ROOT / "build/p3dm/bay-area-hex-full-l0"
PROGRAM_NAME = "P3DHXMG.BIN"
PROGRAM = FIXTURE / PROGRAM_NAME
MANIFEST = FIXTURE / "MANAGER.json"
WORLD = FIXTURE / "WORLD.json"
RESOURCE_NAMES = ("MATID.RG2", "PATLUT.BIN", "PATTERN.RG2")
TERRAIN_RECORD_ROOT = "TRH"
BITMAP_ID = 257
WIDTH = 320
HEIGHT = 240
DEFAULT_RADIUS = 2
SEQUENCES = (0, 18)
START_CELL = (90, 121)
SLOT_COUNT = 91
MESH_ID_BASE = 1
OBJECT_ID_BASE = 1
STAGE_BUFFER_ID = 0x7400
EXPECTED_P3DM_SHAPE = {
    "data_bytes": 3310,
    "vertices": 121,
    "position_indices": 630,
    "texture_coordinates": 16,
    "texture_indices": 630,
}
MANIFEST_SCHEMA = "pingo-terrain-manager-survey-v1"
CAPTURE_SCHEMA = "pingo-terrain-manager-survey-capture-v1"
CAPTURE_REPORT_NAME = "terrain-manager-survey-capture.json"
CAPTURE_LABEL = "hex manager survey"
REQUIRED_POSE_MARKER = b"PINGO_WIDE object_translation=ok oid=%u"
REQUIRED_DIAGNOSTIC_MARKERS = (
    b"PINGO_DUMP seq=%u bmid=%u status=%s",
    b"PINGO_STREAM mesh_replace=ok",
    b"PINGO_STREAM object_active=ok",
    REQUIRED_POSE_MARKER,
)
OBJECT_TRANSLATION_RE = re.compile(
    r"PINGO_WIDE object_translation=ok oid=(\d+) "
    r"raw_x=(-?\d+) raw_y=(-?\d+) raw_z=(-?\d+)"
)
RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+) bmid=(\d+)")

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import HexCell, disk_offsets  # noqa: E402


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=DEFAULT_VDP,
        help="P3DM-loader diagnostic PingoWolf VDP module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_diagnostic_vdp(path: Path) -> None:
    payload = path.read_bytes()
    missing = [
        marker.decode("ascii")
        for marker in REQUIRED_DIAGNOSTIC_MARKERS
        if marker not in payload
    ]
    if missing:
        raise SystemExit(f"VDP module lacks required manager diagnostics: {missing}")


def expected_cells(
    radius: int | None = None,
    origin: tuple[int, int] | None = None,
) -> dict[int, tuple[int, int, int]]:
    """Return stable object IDs and exact command-52 translations in load order."""

    if radius is None:
        radius = DEFAULT_RADIUS
    if origin is None:
        origin = START_CELL
    result: dict[int, tuple[int, int, int]] = {}
    q0, r0 = origin
    for dq, dr in disk_offsets(radius):
        q, r = q0 + dq, r0 + dr
        slot = (5 * q + 11 * r) % SLOT_COUNT
        object_id = OBJECT_ID_BASE + slot
        if object_id in result:
            raise AssertionError(
                f"radius-{radius} axial disk collided in stable slot {slot}"
            )
        result[object_id] = (
            dq * 4400 + dr * 8800,
            9728,
            -dq * 7680,
        )
    return result


def terrain_record_paths(
    radius: int | None = None,
    origin: tuple[int, int] | None = None,
) -> tuple[Path, ...]:
    """Return the runtime paths needed by one stationary axial disk."""

    if radius is None:
        radius = DEFAULT_RADIUS
    if origin is None:
        origin = START_CELL
    q0, r0 = origin
    result = []
    for dq, dr in disk_offsets(radius):
        cell_id = HexCell(q0 + dq, r0 + dr).cell_id
        result.append(
            Path(TERRAIN_RECORD_ROOT)
            / "L0"
            / f"{cell_id >> 8:02X}"
            / f"{cell_id & 0xFF:02X}.AGN"
        )
    return tuple(result)


def parse_runtime_evidence(contents: str) -> dict[str, object]:
    """Parse diagnostic records without applying fixture-specific expectations."""

    replacements = [
        {
            "log_offset": match.start(),
            "stage_buffer_id": int(match.group(1)),
            "mesh_id": int(match.group(2)),
            "data_bytes": int(match.group(3)),
            "vertices": int(match.group(4)),
            "position_indices": int(match.group(5)),
            "texture_coordinates": int(match.group(6)),
            "texture_indices": int(match.group(7)),
            "publication_us": int(match.group(8)),
        }
        for match in capture.MESH_REPLACE_RE.finditer(contents)
    ]
    activity = [
        {
            "log_offset": match.start(),
            "object_id": int(match.group(1)),
            "active": int(match.group(2)),
        }
        for match in capture.OBJECT_ACTIVE_RE.finditer(contents)
    ]
    translations = [
        {
            "log_offset": match.start(),
            "object_id": int(match.group(1)),
            "translation": tuple(
                int(match.group(axis)) for axis in range(2, 5)
            ),
        }
        for match in OBJECT_TRANSLATION_RE.finditer(contents)
    ]
    dumps = [
        {
            "log_offset": match.start(),
            "sequence": int(match.group(1)),
            "bitmap_id": int(match.group(2)),
            "status": match.group(3),
        }
        for match in capture.DUMP_RE.finditer(contents)
    ]
    renders = [
        {
            "log_offset": match.start(),
            "sequence": int(match.group(1)),
            "bitmap_id": int(match.group(2)),
        }
        for match in RENDER_RE.finditer(contents)
    ]
    return {
        "replacements": replacements,
        "activity": activity,
        "translations": translations,
        "dumps": dumps,
        "renders": renders,
    }


def expected_publication_shapes() -> dict[int, dict[str, int]]:
    """Return the exact P3DM publication shape for each default-disk mesh."""

    return {
        mesh_id: dict(EXPECTED_P3DM_SHAPE)
        for mesh_id in expected_cells()
    }


def validate_runtime_evidence(contents: str) -> dict[str, object]:
    """Require one uninterrupted center-to-radius-two publication lifecycle."""

    expected = expected_cells()
    expected_ids = set(expected)
    expected_order = list(expected)
    expected_shapes = expected_publication_shapes()
    if set(expected_shapes) != expected_ids:
        raise ValueError("publication-shape identities differ from the desired disk")
    parsed = parse_runtime_evidence(contents)
    errors: list[str] = []

    generic_failures = capture.find_log_failures(contents)
    if generic_failures:
        errors.append(f"fatal diagnostics {generic_failures}")

    replacements = parsed["replacements"]
    replacement_ids = [item["mesh_id"] for item in replacements]
    if replacement_ids != expected_order:
        errors.append(
            "mesh publication identity/order/multiplicity changed: "
            f"expected {expected_order}, got {replacement_ids}"
        )
    for item in replacements:
        actual_shape = {name: item[name] for name in EXPECTED_P3DM_SHAPE}
        if item["stage_buffer_id"] != STAGE_BUFFER_ID:
            errors.append(
                f"mesh {item['mesh_id']} used stage {item['stage_buffer_id']}, "
                f"expected {STAGE_BUFFER_ID}"
            )
        expected_shape = expected_shapes.get(item["mesh_id"])
        if actual_shape != expected_shape:
            errors.append(
                f"mesh {item['mesh_id']} publication shape changed: "
                f"{actual_shape} != {expected_shape}"
            )

    translations = parsed["translations"]
    translation_ids = [item["object_id"] for item in translations]
    if translation_ids != expected_order:
        errors.append(
            "command-52 identity/order/multiplicity changed: "
            f"expected {expected_order}, got {translation_ids}"
        )
    for item in translations:
        object_id = item["object_id"]
        if object_id in expected and item["translation"] != expected[object_id]:
            errors.append(
                f"object {object_id} command-52 transform "
                f"{item['translation']} != {expected[object_id]}"
            )

    activity = parsed["activity"]
    transitions: dict[int, list[int]] = defaultdict(list)
    for item in activity:
        transitions[item["object_id"]].append(item["active"])
    expected_slot_ids = set(range(OBJECT_ID_BASE, OBJECT_ID_BASE + SLOT_COUNT))
    if set(transitions) != expected_slot_ids:
        errors.append(
            "scene bootstrap object IDs changed: "
            f"expected {sorted(expected_slot_ids)}, got {sorted(transitions)}"
        )
    for object_id in sorted(expected_slot_ids):
        expected_transitions = [0, 1] if object_id in expected_ids else [0]
        if transitions.get(object_id) != expected_transitions:
            errors.append(
                f"object {object_id} activation lifecycle "
                f"{transitions.get(object_id)} != {expected_transitions}"
            )
    final_activity = {
        object_id: states[-1]
        for object_id, states in transitions.items()
        if states
    }
    active_ids = {
        object_id for object_id, active in final_activity.items() if active
    }
    if active_ids != expected_ids:
        errors.append(
            f"final active set {sorted(active_ids)} != {sorted(expected_ids)}"
        )

    dumps = parsed["dumps"]
    dump_keys = [
        (item["bitmap_id"], item["sequence"], item["status"])
        for item in dumps
    ]
    expected_dump_keys = [
        (BITMAP_ID, sequence, "ok") for sequence in SEQUENCES
    ]
    if dump_keys != expected_dump_keys:
        errors.append(
            f"target-dump lifecycle {dump_keys} != {expected_dump_keys}"
        )
    if len(dumps) == len(SEQUENCES):
        initial_offset = dumps[0]["log_offset"]
        complete_offset = dumps[-1]["log_offset"]
        initial_publications = [
            item["mesh_id"]
            for item in replacements
            if item["log_offset"] < initial_offset
        ]
        complete_publications = [
            item["mesh_id"]
            for item in replacements
            if item["log_offset"] < complete_offset
        ]
        if initial_publications != expected_order[:1]:
            errors.append(
                "sequence 0 was not the center-only population barrier: "
                f"{initial_publications}"
            )
        if complete_publications != expected_order:
            errors.append(
                "sequence 18 arrived before the complete radius-two disk: "
                f"{complete_publications}"
            )

    renders = [
        item["sequence"]
        for item in parsed["renders"]
        if item["bitmap_id"] == BITMAP_ID
    ]
    if not renders or renders[0] != 0 or max(renders) < SEQUENCES[-1]:
        errors.append(f"incomplete render lifecycle {renders}")
    elif renders != list(range(renders[-1] + 1)):
        errors.append(
            "render sequence repeated or skipped (possible VDP/eZ80 reset): "
            f"{renders}"
        )

    if errors:
        raise ValueError("; ".join(errors))

    return {
        "default_radius": DEFAULT_RADIUS,
        "initial_sequence": SEQUENCES[0],
        "initial_population_mesh_ids": expected_order[:1],
        "complete_sequence": SEQUENCES[-1],
        "complete_population_mesh_ids": expected_order,
        "mesh_replace_count": len(replacements),
        "unique_mesh_publications": len(expected_ids),
        "published_mesh_ids": sorted(expected_ids),
        "unique_active_objects": len(active_ids),
        "final_active_object_ids": sorted(active_ids),
        "validated_object_translations": len(translations),
        "object_activation_transition_count": len(activity),
        "render_sequences": renders,
        "maximum_publication_us": max(
            item["publication_us"] for item in replacements
        ),
        "command_52_transforms": {
            str(object_id): list(expected[object_id])
            for object_id in expected_order
        },
    }


def validate_fixture_contract(
    fixture: Path,
    program: Path,
    manifest: Path,
    world: Path,
) -> dict[str, object]:
    """Validate the build manifest before presenting its files to MOS."""

    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit(f"Unexpected manager manifest schema: {manifest}")
    manager = document.get("manager", {})
    expected_manager = {
        "default_radius": DEFAULT_RADIUS,
        "maximum_radius": 5,
        "stable_slots": SLOT_COUNT,
        "mesh_id_range": [MESH_ID_BASE, MESH_ID_BASE + SLOT_COUNT - 1],
        "object_id_range": [OBJECT_ID_BASE, OBJECT_ID_BASE + SLOT_COUNT - 1],
        "publication_budget_per_idle_pass": 1,
        "radius_cell_counts": [1, 7, 19, 37, 61, 91],
        "topology": "flat-top-axial-hex",
        "translation_command": 52,
    }
    for name, expected_value in expected_manager.items():
        if manager.get(name) != expected_value:
            raise SystemExit(
                f"Manager manifest {name}={manager.get(name)!r}, "
                f"expected {expected_value!r}"
            )
    binary = document.get("binary", {})
    if binary.get("sha256") != sha256(program):
        raise SystemExit(f"Manager manifest binary checksum mismatch: {program}")
    resources = document.get("resources", {})
    if set(resources) != set(RESOURCE_NAMES):
        raise SystemExit(
            f"Manager manifest must name exactly {RESOURCE_NAMES}: {manifest}"
        )
    validated_resources: dict[str, dict[str, object]] = {}
    for name in RESOURCE_NAMES:
        path = capture.require_file(fixture / name, f"manager resource {name}")
        metadata = resources[name]
        actual = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        if actual != metadata:
            raise SystemExit(
                f"Manager resource metadata mismatch for {name}: "
                f"{actual} != {metadata}"
            )
        validated_resources[name] = actual
    record_root = fixture / TERRAIN_RECORD_ROOT
    if not record_root.is_dir():
        raise SystemExit(f"Missing hex terrain record tree: {record_root}")
    if document.get("corpus", {}).get("world_sha256") != sha256(world):
        raise SystemExit(f"Manager manifest WORLD checksum mismatch: {world}")
    world_document = json.loads(world.read_text(encoding="utf-8"))
    raw_records = world_document.get("records")
    if not isinstance(raw_records, list):
        raise SystemExit(f"Manager WORLD record index is malformed: {world}")
    indexed_records = {
        record.get("path"): record
        for record in raw_records
        if isinstance(record, dict) and isinstance(record.get("path"), str)
    }
    expected_paths = terrain_record_paths()
    validated_records: dict[str, dict[str, object]] = {}
    for relative in expected_paths:
        relative_name = relative.as_posix()
        metadata = indexed_records.get(relative_name)
        if metadata is None:
            raise SystemExit(
                f"Manager WORLD omits default-disk record: {relative_name}"
            )
        path = capture.require_file(
            fixture / relative,
            f"manager terrain record {relative_name}",
        )
        actual = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        expected = {
            "bytes": metadata.get("bytes"),
            "sha256": metadata.get("sha256"),
        }
        if actual != expected:
            raise SystemExit(
                f"Manager terrain metadata mismatch for {relative_name}: "
                f"{actual} != {expected}"
            )
        validated_records[relative_name] = actual
    return {
        "program": {"bytes": program.stat().st_size, "sha256": sha256(program)},
        "resources": validated_resources,
        "terrain_record_root": str(record_root.resolve()),
        "terrain_records": validated_records,
    }


def stage_private_sd(sd_root: Path, fixture: Path) -> Path:
    """Copy the executable, resources, and exact stationary-disk records."""

    runtime = sd_root / "survey"
    runtime.mkdir()
    for name in (PROGRAM_NAME, *RESOURCE_NAMES):
        shutil.copy2(fixture / name, runtime / name)
    for relative in terrain_record_paths():
        source = fixture / relative
        if not source.is_file():
            raise SystemExit(f"Missing required default-disk record: {source}")
        destination = runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return runtime


def analyze_frame(raw_path: Path, depth_path: Path, *, require_geometry: bool) -> dict:
    packed = raw_path.read_bytes()
    depth = depth_path.read_bytes()
    expected_pixels = WIDTH * HEIGHT
    if len(packed) != expected_pixels or len(depth) != expected_pixels * 4:
        raise SystemExit(f"Unexpected hex-manager target dimensions: {raw_path}")
    depth_words = tuple(
        int.from_bytes(depth[offset : offset + 4], "little")
        for offset in range(0, len(depth), 4)
    )
    populated_depth = sum(value != 0 for value in depth_words)
    nonzero_color = sum(value != 0 for value in packed)
    color_without_depth = sum(
        color != 0 and zeta == 0
        for color, zeta in zip(packed, depth_words, strict=True)
    )
    if require_geometry and (populated_depth == 0 or nonzero_color == 0):
        raise SystemExit(f"Frame contains no visible geometry: {raw_path}")
    if color_without_depth:
        raise SystemExit(
            f"Frame has color without depth in {color_without_depth} pixels: {raw_path}"
        )
    nonzero_depth = tuple(value for value in depth_words if value)
    return {
        "rgba2_bytes": len(packed),
        "rgba2_sha256": sha256(raw_path),
        "rgba2_unique_values": len(set(packed)),
        "nonzero_color_pixels": nonzero_color,
        "depth_bytes": len(depth),
        "depth_sha256": sha256(depth_path),
        "depth_unique_values": len(set(depth_words)),
        "populated_depth_pixels": populated_depth,
        "nonzero_color_without_depth": color_without_depth,
        "minimum_nonzero_depth_u32": min(nonzero_depth) if nonzero_depth else None,
        "maximum_nonzero_depth_u32": max(nonzero_depth) if nonzero_depth else None,
    }


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    emulator = capture.require_file(capture.FAB_BINARY, "Fab executable")
    mos = capture.require_file(capture.MOS_BINARY, "MOS image")
    vdp = capture.require_file(arguments.vdp_module, "diagnostic VDP module")
    require_diagnostic_vdp(vdp)
    program = capture.require_file(PROGRAM, f"{CAPTURE_LABEL} camera survey")
    manifest = capture.require_file(MANIFEST, f"{CAPTURE_LABEL} manifest")
    world = capture.require_file(WORLD, f"{CAPTURE_LABEL} WORLD manifest")
    fixture_contract = validate_fixture_contract(
        FIXTURE, program, manifest, world
    )

    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    selectors = ",".join(f"{BITMAP_ID}:{sequence}" for sequence in SEQUENCES)
    markers = {
        f"PINGO_DUMP seq={sequence} bmid={BITMAP_ID} status=ok"
        for sequence in SEQUENCES
    }
    log_path = output / "emulator.log"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /survey\r\n"
        + f"load {PROGRAM_NAME}\r\n".encode("ascii")
        + b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    shutdown = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="hex-manager-survey-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="hex-manager-survey-run-") as run_name,
    ):
        sd_root = Path(sd_name)
        runtime = stage_private_sd(sd_root, FIXTURE)
        staged_files = {
            name: {
                "bytes": (runtime / name).stat().st_size,
                "sha256": sha256(runtime / name),
            }
            for name in (PROGRAM_NAME, *RESOURCE_NAMES)
        }
        staged_records = {
            str(relative): {
                "bytes": (runtime / relative).stat().st_size,
                "sha256": sha256(runtime / relative),
            }
            for relative in terrain_record_paths()
        }
        private_sd_stage = {
            "copied_files": staged_files,
            "copied_terrain_records": staged_records,
            "copied_terrain_record_count": len(staged_records),
        }
        (sd_root / "autoexec.txt").write_bytes(autoexec)
        environment = os.environ.copy()
        environment.update(
            {
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
                "PINGO_RENDER_TARGET_DUMP_FRAMES": selectors,
                "PINGO_RENDER_TARGET_DUMP_DIR": str(output),
            }
        )
        local_sdl = Path.home() / ".local/lib"
        old_library_path = environment.get("LD_LIBRARY_PATH")
        environment["LD_LIBRARY_PATH"] = (
            str(local_sdl)
            if not old_library_path
            else f"{local_sdl}:{old_library_path}"
        )
        command = [
            str(emulator),
            "--renderer", "sw",
            "--firmware", "console8",
            "--mos", str(mos),
            "--vdp", str(vdp),
            "--sdcard", str(sd_root),
            "--verbose", "-z", "-u",
        ]
        (output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "selectors": selectors,
                    "headless_environment": {
                        "SDL_VIDEODRIVER": "dummy",
                        "SDL_AUDIODRIVER": "dummy",
                        "PINGO_RENDER_TARGET_DUMP_FRAMES": selectors,
                    },
                    "private_sd_stage": private_sd_stage,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=run_name,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + arguments.timeout
            try:
                while time.monotonic() < deadline:
                    log.flush()
                    contents = log_path.read_text(encoding="utf-8", errors="replace")
                    failures = capture.find_log_failures(contents)
                    if failures:
                        raise SystemExit(
                            f"{CAPTURE_LABEL} diagnostic failure: {failures}"
                        )
                    if all(marker in contents for marker in markers):
                        break
                    if process.poll() is not None:
                        raise SystemExit(
                            f"Emulator exited early with {process.returncode}: {log_path}"
                        )
                    time.sleep(0.05)
                else:
                    raise SystemExit(
                        f"Timed out waiting for {CAPTURE_LABEL} frames: {log_path}"
                    )
            finally:
                shutdown = capture.stop_process_group(process)

    contents = log_path.read_text(encoding="utf-8", errors="replace")
    failures = capture.find_log_failures(contents)
    if failures:
        raise SystemExit(f"{CAPTURE_LABEL} diagnostic failures: {failures}")
    try:
        stream = validate_runtime_evidence(contents)
    except ValueError as error:
        raise SystemExit(f"{CAPTURE_LABEL} runtime evidence failed: {error}") from error
    if shutdown != "sigint" or process.returncode != 0:
        raise SystemExit(
            "Emulator did not terminate cleanly after qualification: "
            f"shutdown={shutdown}, status={process.returncode}"
        )

    capture.WIDTH = WIDTH
    capture.HEIGHT = HEIGHT
    frames = []
    for sequence in SEQUENCES:
        raw = output / f"pingo-{BITMAP_ID}-{sequence}.rgba2"
        depth = output / f"pingo-{BITMAP_ID}-{sequence}.z32le"
        if not raw.is_file() or not depth.is_file():
            raise SystemExit(f"Missing hex-manager target dump for sequence {sequence}")
        ppm = output / f"pingo-{BITMAP_ID}-{sequence}.ppm"
        capture.write_ppm(raw, ppm, WIDTH, HEIGHT)
        frame = analyze_frame(raw, depth, require_geometry=sequence != 0)
        frame.update(
            {
                "bitmap_id": BITMAP_ID,
                "sequence": sequence,
                "population": (
                    "center-only" if sequence == SEQUENCES[0] else "radius-2-complete"
                ),
                "ppm_path": ppm.name,
                "ppm_sha256": sha256(ppm),
            }
        )
        frames.append(frame)
    if frames[0]["rgba2_sha256"] == frames[-1]["rgba2_sha256"]:
        raise SystemExit("Centre-only and complete default-disk frames are identical")
    if (
        frames[-1]["nonzero_color_pixels"] == 0
        or frames[-1]["populated_depth_pixels"] == 0
    ):
        raise SystemExit("Complete default hex disk rendered no geometry")

    report = {
        "schema": CAPTURE_SCHEMA,
        "program": {"path": str(program), "sha256": sha256(program)},
        "manager_manifest": {"path": str(manifest), "sha256": sha256(manifest)},
        "world_manifest": {"path": str(world), "sha256": sha256(world)},
        "vdp": {"path": str(vdp), "sha256": sha256(vdp)},
        "emulator": {"path": str(emulator), "sha256": sha256(emulator)},
        "mos": {"path": str(mos), "sha256": sha256(mos)},
        "fixture_contract": fixture_contract,
        "private_sd_stage": private_sd_stage,
        "requested_sequences": list(SEQUENCES),
        "frames": frames,
        "stream": stream,
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
        "qualified": True,
    }
    report_path = output / CAPTURE_REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless {CAPTURE_LABEL} passed: {report_path}")
    print(
        f"published={stream['mesh_replace_count']} "
        f"active={len(stream['final_active_object_ids'])} "
        f"pixels={frames[-1]['nonzero_color_pixels']} shutdown={shutdown}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
