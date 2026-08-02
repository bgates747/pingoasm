#!/usr/bin/env python3
"""Silently qualify the nested-family mixed-LOD KOAK fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent.parent
AGON_ROOT = Path.home() / "Agon"
FAB_ROOT = AGON_ROOT / "mystuff/fab-agon-emulator"
FAB_BINARY = FAB_ROOT / "target/release/fab-agon-emulator"
MOS_BINARY = FAB_ROOT / "firmware/mos_console8.bin"
DEFAULT_VDP = (
    AGON_ROOT
    / "mystuff/agon-vdp/video/build/"
    "userspace-p3dm-loader-diagnostics/vdp_combined.so"
)
FIXTURE = ROOT / "build/p3dm/bay-area-koak-family-proof"
PROGRAM = FIXTURE / "P3DLOD.BIN"
FLIGHT_MANIFEST = FIXTURE / "FAMILY.json"
CORPUS_MANIFEST_NAMES = ("FAMPLAN.JSN",)
BITMAP_ID = 257
WIDTH = 320
HEIGHT = 148
DEFAULT_SEQUENCES = (0, 30)
EXPECTED_MESH_IDS = frozenset((*range(1, 38), 101, 102))
EXPECTED_ACTIVE_IDS = frozenset(
    (*range(1, 9), *range(17, 25), *range(29, 37), 101, 102)
)
AIRCRAFT_OBJECT_ID = 201

MESH_REPLACE_RE = re.compile(
    r"PINGO_STREAM mesh_replace=ok stage=(\d+) mid=(\d+) bytes=(\d+) "
    r"v=(\d+) i=(\d+) u=(\d+) t=(\d+) us=(\d+)"
)
OBJECT_ACTIVE_RE = re.compile(
    r"PINGO_STREAM object_active=ok oid=(\d+) active=([01])"
)
DUMP_RE = re.compile(r"PINGO_DUMP seq=(\d+) bmid=(\d+) status=([^\s]+)")
FATAL_LOG_MARKERS = (
    "replace_mesh_from_buffer:",
    "PINGO_SCENE active_overflow=1",
    "P3DM startup error",
    "VDP error:",
    "ez80 cpu thread terminated",
    "panicked at",
    "Guru Meditation",
)
REQUIRED_VDP_DIAGNOSTIC_MARKERS = (
    b"PINGO_DUMP seq=%u bmid=%u status=%s",
    b"PINGO_STREAM mesh_replace=ok",
    b"PINGO_STREAM object_active=ok",
    b"PINGO_SCENE active_overflow=1",
)


def parse_sequences(value: str) -> tuple[int, ...]:
    try:
        sequences = tuple(int(item.strip(), 10) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "sequences must be comma-separated non-negative integers"
        ) from error
    if any(sequence < 0 for sequence in sequences):
        raise argparse.ArgumentTypeError("sequences must be non-negative")
    if len(sequences) < 2 or 0 not in sequences or not any(sequences):
        raise argparse.ArgumentTypeError(
            "capture must include sequence 0 and at least one later sequence"
        )
    if len(set(sequences)) != len(sequences):
        raise argparse.ArgumentTypeError("sequences must not repeat")
    return tuple(sorted(sequences))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=DEFAULT_VDP,
        help=f"diagnostic native VDP module (default: {DEFAULT_VDP})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new directory in which to retain captures and evidence",
    )
    parser.add_argument(
        "--sequences",
        type=parse_sequences,
        default=DEFAULT_SEQUENCES,
        metavar="N,N",
        help="render sequences to dump; must include 0 and a later frame "
        "(default: 0,30)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="deadline for all requested frames in seconds (default: 90)",
    )
    return parser.parse_args()


def require_file(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"Missing {description}: {resolved}")
    return resolved


def require_diagnostic_vdp(path: Path) -> None:
    image = path.read_bytes()
    missing = [
        marker.decode("ascii")
        for marker in REQUIRED_VDP_DIAGNOSTIC_MARKERS
        if marker not in image
    ]
    if missing:
        raise SystemExit(
            "VDP module lacks required KOAK diagnostic records "
            f"{missing}; rebuild it with DIAGNOSTICS=1: {path}"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_ppm(source: Path, destination: Path, width: int, height: int) -> None:
    packed = source.read_bytes()
    if len(packed) != width * height:
        raise SystemExit(
            f"Expected {width * height} RGBA2222 bytes, got {len(packed)}"
        )
    rgb = bytearray(len(packed) * 3)
    for index, value in enumerate(packed):
        rgb[index * 3 + 0] = (value & 0x03) * 85
        rgb[index * 3 + 1] = ((value >> 2) & 0x03) * 85
        rgb[index * 3 + 2] = ((value >> 4) & 0x03) * 85
    destination.write_bytes(
        f"P6\n{width} {height}\n255\n".encode("ascii") + rgb
    )


def stop_process_group(process: subprocess.Popen[bytes]) -> str:
    if process.poll() is not None:
        return "already-exited"
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return "already-exited"
    try:
        process.wait(timeout=3)
        return "sigint"
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
        return "sigterm"
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return "sigkill"


def find_log_failures(contents: str) -> list[str]:
    failures = [marker for marker in FATAL_LOG_MARKERS if marker in contents]
    for sequence, bitmap_id, status in DUMP_RE.findall(contents):
        if status != "ok":
            failures.append(
                f"PINGO_DUMP seq={sequence} bmid={bitmap_id} status={status}"
            )
    return failures


def parse_stream_evidence(contents: str) -> dict[str, object]:
    replacements = [
        {
            "stage_buffer_id": int(match.group(1)),
            "mesh_id": int(match.group(2)),
            "data_bytes": int(match.group(3)),
            "vertices": int(match.group(4)),
            "position_indices": int(match.group(5)),
            "texture_coordinates": int(match.group(6)),
            "texture_indices": int(match.group(7)),
            "publication_us": int(match.group(8)),
        }
        for match in MESH_REPLACE_RE.finditer(contents)
    ]
    published_ids = {entry["mesh_id"] for entry in replacements}
    missing_ids = sorted(EXPECTED_MESH_IDS - published_ids)
    unexpected_ids = sorted(published_ids - EXPECTED_MESH_IDS)

    final_activity: dict[int, int] = {}
    transitions = []
    for match in OBJECT_ACTIVE_RE.finditer(contents):
        object_id = int(match.group(1))
        active = int(match.group(2))
        final_activity[object_id] = active
        transitions.append({"object_id": object_id, "active": active})
    inactive_expected = sorted(
        object_id
        for object_id in EXPECTED_ACTIVE_IDS
        if final_activity.get(object_id) != 1
    )
    active_ids = sorted(
        object_id for object_id, active in final_activity.items() if active
    )
    unexpected_active_ids = sorted(set(active_ids) - EXPECTED_ACTIVE_IDS)
    return {
        "mesh_replacements": replacements,
        "mesh_replace_count": len(replacements),
        "published_mesh_ids": sorted(published_ids),
        "missing_mesh_ids": missing_ids,
        "unexpected_mesh_ids": unexpected_ids,
        "object_active_transition_count": len(transitions),
        "final_active_object_ids": active_ids,
        "inactive_expected_object_ids": inactive_expected,
        "unexpected_active_object_ids": unexpected_active_ids,
        "aircraft_object_active": bool(final_activity.get(AIRCRAFT_OBJECT_ID, 0)),
    }


def analyze_frame(raw_path: Path, depth_path: Path) -> dict[str, object]:
    packed = raw_path.read_bytes()
    depth = depth_path.read_bytes()
    expected_pixels = WIDTH * HEIGHT
    if len(packed) != expected_pixels:
        raise SystemExit(
            f"Unexpected RGBA2222 size for {raw_path}: {len(packed)}"
        )
    if len(depth) != expected_pixels * 4:
        raise SystemExit(
            f"Unexpected depth-buffer size for {depth_path}: {len(depth)}"
        )

    depth_words = [
        int.from_bytes(depth[offset : offset + 4], "little")
        for offset in range(0, len(depth), 4)
    ]
    populated_depth = sum(value != 0 for value in depth_words)
    nonzero_color = sum(value != 0 for value in packed)
    color_without_depth = sum(
        color != 0 and zeta == 0
        for color, zeta in zip(packed, depth_words, strict=True)
    )
    if populated_depth == 0 or nonzero_color == 0:
        raise SystemExit(f"Frame contains no visible geometry: {raw_path}")
    if color_without_depth:
        raise SystemExit(
            f"Frame has {color_without_depth} nonzero color pixels without depth: "
            f"{raw_path}"
        )
    nonzero_depth_values = [value for value in depth_words if value]
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
        "minimum_nonzero_depth_u32": min(nonzero_depth_values),
        "maximum_nonzero_depth_u32": max(nonzero_depth_values),
    }


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    emulator = require_file(FAB_BINARY, "Fab executable")
    mos = require_file(MOS_BINARY, "MOS image")
    vdp = require_file(arguments.vdp_module, "diagnostic VDP module")
    require_diagnostic_vdp(vdp)
    program = require_file(PROGRAM, "streamed KOAK fixture")
    flight_manifest = require_file(FLIGHT_MANIFEST, "KOAK flight manifest")
    corpus_manifests = {
        name: require_file(FIXTURE / name, f"KOAK {name} manifest")
        for name in CORPUS_MANIFEST_NAMES
    }
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output directory: {output}")
    output.mkdir(parents=True)

    sequences = tuple(arguments.sequences)
    requested_markers = {
        f"PINGO_DUMP seq={sequence} bmid={BITMAP_ID} status=ok"
        for sequence in sequences
    }
    selectors = ",".join(f"{BITMAP_ID}:{sequence}" for sequence in sequences)
    log_path = output / "emulator.log"
    shutdown_method = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="pingo-koak-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="pingo-koak-run-") as run_name,
    ):
        sd_root = Path(sd_name)
        runtime = sd_root / "flight"
        shutil.copytree(FIXTURE, runtime)
        autoexec = (
            b"SET KEYBOARD 1\r\n"
            b"cd /flight\r\n"
            b"load P3DLOD.BIN\r\n"
            b"run\r\n"
        )
        (sd_root / "autoexec.txt").write_bytes(autoexec)
        (output / "autoexec.txt").write_bytes(autoexec)

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
            "--renderer",
            "sw",
            "--firmware",
            "console8",
            "--mos",
            str(mos),
            "--vdp",
            str(vdp),
            "--sdcard",
            str(sd_root),
            "--verbose",
            "-z",
            "-u",
        ]
        (output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "headless_environment": {
                        "SDL_VIDEODRIVER": "dummy",
                        "SDL_AUDIODRIVER": "dummy",
                        "PINGO_RENDER_TARGET_DUMP_FRAMES": selectors,
                    },
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
                    contents = log_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    failures = find_log_failures(contents)
                    if failures:
                        raise SystemExit(
                            "Diagnostic failure before final capture: "
                            + ", ".join(failures)
                            + f"; see {log_path}"
                        )
                    if requested_markers.issubset(set(contents.splitlines())):
                        break
                    # Force-debug records may share a line with verbose serial
                    # output. Substring matching remains unambiguous here.
                    if all(marker in contents for marker in requested_markers):
                        break
                    returncode = process.poll()
                    if returncode is not None:
                        raise SystemExit(
                            "Emulator exited before all KOAK frames "
                            f"(status {returncode}); see {log_path}"
                        )
                    time.sleep(0.05)
                else:
                    missing = sorted(
                        marker
                        for marker in requested_markers
                        if marker not in contents
                    )
                    raise SystemExit(
                        "Timed out before KOAK captures "
                        f"{missing}; see {log_path}"
                    )
            finally:
                shutdown_method = stop_process_group(process)

    contents = log_path.read_text(encoding="utf-8", errors="replace")
    failures = find_log_failures(contents)
    if failures:
        raise SystemExit(
            "Diagnostic log contains failures: "
            + ", ".join(failures)
            + f"; see {log_path}"
        )

    stream = parse_stream_evidence(contents)
    if stream["missing_mesh_ids"]:
        raise SystemExit(
            "Later frame arrived before all regional meshes were published; "
            f"missing IDs {stream['missing_mesh_ids']}; see {log_path}"
        )
    if stream["unexpected_mesh_ids"]:
        raise SystemExit(
            "Unexpected command-50 mesh publications: "
            f"{stream['unexpected_mesh_ids']}; see {log_path}"
        )
    if stream["inactive_expected_object_ids"]:
        raise SystemExit(
            "Later frame arrived with regional objects inactive: "
            f"{stream['inactive_expected_object_ids']}; see {log_path}"
        )
    if stream["unexpected_active_object_ids"]:
        raise SystemExit(
            "Later frame has unexpected active objects: "
            f"{stream['unexpected_active_object_ids']}; see {log_path}"
        )
    if stream["aircraft_object_active"]:
        raise SystemExit(
            "Cockpit qualification unexpectedly exposed the exterior aircraft; "
            f"see {log_path}"
        )

    frames: list[dict[str, object]] = []
    for sequence in sequences:
        raw_path = output / f"pingo-{BITMAP_ID}-{sequence}.rgba2"
        depth_path = output / f"pingo-{BITMAP_ID}-{sequence}.z32le"
        if not raw_path.is_file() or not depth_path.is_file():
            raise SystemExit(
                f"Diagnostic VDP omitted sequence {sequence} dumps; see {log_path}"
            )
        ppm_path = output / f"pingo-{BITMAP_ID}-{sequence}.ppm"
        write_ppm(raw_path, ppm_path, WIDTH, HEIGHT)
        frame = {
            "bitmap_id": BITMAP_ID,
            "sequence": sequence,
            **analyze_frame(raw_path, depth_path),
            "ppm_sha256": sha256(ppm_path),
        }
        frames.append(frame)

    distinct_frame_hashes = len({frame["rgba2_sha256"] for frame in frames})
    if distinct_frame_hashes < 2:
        raise SystemExit(
            "First and later KOAK targets are byte-identical despite streaming; "
            f"see {log_path}"
        )

    report = {
        "schema": "pingo-terrain-koak-family-lod-capture-v1",
        "fixture": str(program),
        "fixture_sha256": sha256(program),
        "flight_manifest": str(flight_manifest),
        "flight_manifest_sha256": sha256(flight_manifest),
        "corpus_manifests": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in corpus_manifests.items()
        },
        "vdp_module": str(vdp),
        "vdp_module_sha256": sha256(vdp),
        "emulator": str(emulator),
        "emulator_sha256": sha256(emulator),
        "mos": str(mos),
        "mos_sha256": sha256(mos),
        "width": WIDTH,
        "height": HEIGHT,
        "requested_sequences": list(sequences),
        "distinct_frame_hashes": distinct_frame_hashes,
        "frames": frames,
        "stream": stream,
        "shutdown_method": shutdown_method,
        "log_sha256": sha256(log_path),
    }
    (output / "capture.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Qualified KOAK family-LOD sequences {','.join(map(str, sequences))}: {output}\n"
        f"first={frames[0]['rgba2_sha256']} "
        f"later={frames[-1]['rgba2_sha256']}\n"
        f"published_meshes={stream['mesh_replace_count']} "
        f"active_objects={len(stream['final_active_object_ids'])} "
        f"shutdown={shutdown_method}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
