#!/usr/bin/env python3
"""Silently qualify initial 32-cell publication in the regional survey."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import capture_koak_flight as capture


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-full-l0"
PROGRAM = FIXTURE / "P3DSURV.BIN"
MANIFEST = FIXTURE / "SURVEY.json"
WORLD = FIXTURE / "WORLD.json"
BITMAP_ID = 257
WIDTH = 320
HEIGHT = 240
SEQUENCES = (0, 31)
EXPECTED_IDS = set(range(1, 33))
REQUIRED_POSE_MARKER = b"PINGO_POSE object_translation oid=%u"
OBJECT_TRANSLATION_RE = re.compile(
    r"PINGO_POSE object_translation oid=(\d+) "
    r"raw_x=(-?\d+) raw_y=(-?\d+) raw_z=(-?\d+)"
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=capture.DEFAULT_VDP,
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


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    emulator = capture.require_file(capture.FAB_BINARY, "Fab executable")
    mos = capture.require_file(capture.MOS_BINARY, "MOS image")
    vdp = capture.require_file(arguments.vdp_module, "diagnostic VDP module")
    capture.require_diagnostic_vdp(vdp)
    if REQUIRED_POSE_MARKER not in vdp.read_bytes():
        raise SystemExit(
            "VDP module lacks required PINGO_POSE object-translation diagnostics"
        )
    program = capture.require_file(PROGRAM, "regional camera survey")
    manifest = capture.require_file(MANIFEST, "regional survey manifest")
    world = capture.require_file(WORLD, "regional WORLD manifest")

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
        b"load P3DSURV.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    shutdown = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="regional-survey-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="regional-survey-run-") as run_name,
    ):
        sd_root = Path(sd_name)
        (sd_root / "survey").symlink_to(FIXTURE, target_is_directory=True)
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
            json.dumps({"argv": command, "selectors": selectors}, indent=2) + "\n",
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
                        raise SystemExit(f"Regional survey diagnostic failure: {failures}")
                    if all(marker in contents for marker in markers):
                        break
                    if process.poll() is not None:
                        raise SystemExit(
                            f"Emulator exited early with {process.returncode}: {log_path}"
                        )
                    time.sleep(0.05)
                else:
                    raise SystemExit(f"Timed out waiting for regional frames: {log_path}")
            finally:
                shutdown = capture.stop_process_group(process)

    contents = log_path.read_text(encoding="utf-8", errors="replace")
    failures = capture.find_log_failures(contents)
    if failures:
        raise SystemExit(f"Regional survey diagnostic failures: {failures}")
    replacements = [
        {
            "mesh_id": int(match.group(2)),
            "data_bytes": int(match.group(3)),
            "vertices": int(match.group(4)),
            "position_indices": int(match.group(5)),
            "publication_us": int(match.group(8)),
        }
        for match in capture.MESH_REPLACE_RE.finditer(contents)
    ]
    published = {item["mesh_id"] for item in replacements}
    if published != EXPECTED_IDS or len(replacements) != 32:
        raise SystemExit(
            f"Expected exactly meshes 1..32 once, got {len(replacements)} {sorted(published)}"
        )
    activity: dict[int, int] = {}
    for match in capture.OBJECT_ACTIVE_RE.finditer(contents):
        activity[int(match.group(1))] = int(match.group(2))
    active = {object_id for object_id, state in activity.items() if state}
    if active != EXPECTED_IDS:
        raise SystemExit(f"Expected active objects 1..32, got {sorted(active)}")
    translations = {
        int(match.group(1)): tuple(int(match.group(axis)) for axis in range(2, 5))
        for match in OBJECT_TRANSLATION_RE.finditer(contents)
    }
    expected_translations = {}
    coarse_x, coarse_y = 85, 179
    for dy in range(-2, 2):
        for dx in range(-2, 6):
            tile_x = coarse_x + dx
            tile_y = coarse_y + dy
            slot = (tile_y & 3) * 8 + (tile_x & 7)
            expected_translations[slot + 1] = (
                dy * 8192,
                9728,
                12288 - dx * 8192,
            )
    if translations != expected_translations:
        raise SystemExit(
            "Initial object transforms do not match the exact 8x4 regional window"
        )

    capture.WIDTH = WIDTH
    capture.HEIGHT = HEIGHT
    frames = []
    for sequence in SEQUENCES:
        raw = output / f"pingo-{BITMAP_ID}-{sequence}.rgba2"
        depth = output / f"pingo-{BITMAP_ID}-{sequence}.z32le"
        if not raw.is_file() or not depth.is_file():
            raise SystemExit(f"Missing regional target dump for sequence {sequence}")
        ppm = output / f"pingo-{BITMAP_ID}-{sequence}.ppm"
        capture.write_ppm(raw, ppm, WIDTH, HEIGHT)
        frame = capture.analyze_frame(raw, depth)
        frame.update({"sequence": sequence, "ppm_sha256": sha256(ppm)})
        frames.append(frame)
    if frames[0]["rgba2_sha256"] == frames[-1]["rgba2_sha256"]:
        raise SystemExit("Initial and fully populated regional frames are identical")
    if frames[-1]["nonzero_color_pixels"] == 0 or frames[-1]["populated_depth_pixels"] == 0:
        raise SystemExit("Fully populated regional window rendered no geometry")

    report = {
        "schema": "pingo-terrain-regional-camera-capture-v1",
        "program": {"path": str(program), "sha256": sha256(program)},
        "survey_manifest": {"path": str(manifest), "sha256": sha256(manifest)},
        "world_manifest": {"path": str(world), "sha256": sha256(world)},
        "vdp": {"path": str(vdp), "sha256": sha256(vdp)},
        "requested_sequences": list(SEQUENCES),
        "frames": frames,
        "stream": {
            "mesh_replace_count": len(replacements),
            "published_mesh_ids": sorted(published),
            "final_active_object_ids": sorted(active),
            "validated_object_translations": len(translations),
            "maximum_publication_us": max(item["publication_us"] for item in replacements),
        },
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
        "qualified": True,
    }
    report_path = output / "regional-camera-capture.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless regional camera survey passed: {report_path}")
    print(
        f"published={len(replacements)} active={len(active)} "
        f"pixels={frames[-1]['nonzero_color_pixels']} shutdown={shutdown}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
