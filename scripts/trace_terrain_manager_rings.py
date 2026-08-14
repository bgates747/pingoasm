#!/usr/bin/env python3
"""Qualify live universal-manager radius expansion and contraction."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import capture_koak_flight as capture
import capture_terrain_manager_survey as survey
import trace_koak_input as input_trace
import trace_koak_takeoff as debugger


RADIUS_FIVE_SCANCODE = 0x002E
RADIUS_ZERO_SCANCODE = 0x0045
KEY_HOLD_VBLANKS = 4
SEQUENCES = (18, 110, 220)
RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+)[^\r\n]*")
TRACE_SCHEMA = "pingo-terrain-manager-ring-trace-v1"
TRACE_REPORT_NAME = "terrain-manager-ring-trace.json"
TRACE_LABEL = "terrain-manager ring trace"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=survey.DEFAULT_VDP,
        help="P3DM-loader diagnostic PingoWolf VDP module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def wait_for(
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    predicate,
    description: str,
) -> str:
    while time.monotonic() < deadline:
        contents = log_path.read_text(encoding="utf-8", errors="replace")
        failures = sorted(
            set(capture.find_log_failures(contents) + input_trace.find_failures(contents))
        )
        if failures:
            raise SystemExit(f"{TRACE_LABEL} failure: {failures}")
        if predicate(contents):
            return contents
        if process.poll() is not None:
            raise SystemExit(
                f"Emulator exited early with {process.returncode}: {log_path}"
            )
        time.sleep(0.05)
    raise SystemExit(f"Timed out waiting for {description}: {log_path}")


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    emulator = capture.require_file(capture.FAB_BINARY, "Fab executable")
    mos = capture.require_file(capture.MOS_BINARY, "MOS image")
    vdp = capture.require_file(arguments.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    program = capture.require_file(survey.PROGRAM, survey.CAPTURE_LABEL)
    proxy_source = capture.require_file(
        input_trace.PROXY_SOURCE, "input proxy source"
    )

    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    proxy = output / "vdp_input_trace_proxy.so"
    exports = input_trace.build_proxy(proxy_source, proxy)
    selectors = ",".join(
        f"{survey.BITMAP_ID}:{sequence}" for sequence in SEQUENCES
    )
    markers = {
        sequence: f"PINGO_DUMP seq={sequence} bmid={survey.BITMAP_ID} status=ok"
        for sequence in SEQUENCES
    }
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        + b"cd /survey\r\n"
        + f"load {survey.PROGRAM_NAME}\r\n".encode("ascii")
        + b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    log_path = output / "emulator.log"
    shutdown = "not-started"
    contents = ""

    with (
        tempfile.TemporaryDirectory(prefix="hex-manager-rings-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="hex-manager-rings-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="hex-manager-rings-fifo-") as fifo_name,
    ):
        sd_root = Path(sd_name)
        (sd_root / "survey").symlink_to(survey.FIXTURE, target_is_directory=True)
        (sd_root / "autoexec.txt").write_bytes(autoexec)
        fifo_path = Path(fifo_name) / "keyboard.fifo"
        os.mkfifo(fifo_path, 0o600)
        control_fd = os.open(fifo_path, os.O_RDWR | os.O_NONBLOCK)
        environment = os.environ.copy()
        environment.update(
            {
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
                "FAB_INPUT_REAL_VDP": str(vdp),
                "FAB_INPUT_FIFO": str(fifo_path),
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
            "--vdp", str(proxy),
            "--sdcard", str(sd_root),
            "--verbose", "-z", "-u",
        ]
        (output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "selectors": selectors,
                    "input": {
                        "radius_five_scancode": f"0x{RADIUS_FIVE_SCANCODE:04x}",
                        "radius_zero_scancode": f"0x{RADIUS_ZERO_SCANCODE:04x}",
                        "hold_vblanks": KEY_HOLD_VBLANKS,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        process: subprocess.Popen[bytes] | None = None
        deadline = time.monotonic() + arguments.timeout
        try:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    command,
                    cwd=run_name,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                wait_for(
                    log_path,
                    process,
                    deadline,
                    lambda value: markers[18] in value,
                    "default radius-two disk",
                )
                debugger.write_command_batch(
                    control_fd,
                    [f"tap 0x{RADIUS_FIVE_SCANCODE:04x} {KEY_HOLD_VBLANKS}"],
                )
                wait_for(
                    log_path,
                    process,
                    deadline,
                    lambda value: (
                        markers[110] in value
                        and len(capture.MESH_REPLACE_RE.findall(value)) == 91
                    ),
                    "radius-five disk",
                )
                debugger.write_command_batch(
                    control_fd,
                    [f"tap 0x{RADIUS_ZERO_SCANCODE:04x} {KEY_HOLD_VBLANKS}"],
                )
                contents = wait_for(
                    log_path,
                    process,
                    deadline,
                    lambda value: markers[220] in value,
                    "radius-zero contraction",
                )
        finally:
            os.close(control_fd)
            if process is not None:
                shutdown = capture.stop_process_group(process)

    assert process is not None
    expected_five = survey.expected_cells(5)
    replacements = [
        int(match.group(2)) for match in capture.MESH_REPLACE_RE.finditer(contents)
    ]
    if len(replacements) != 91 or set(replacements) != set(range(1, 92)):
        raise SystemExit("Radius five did not publish every stable mesh exactly once")

    final_activity: dict[int, int] = {}
    for match in capture.OBJECT_ACTIVE_RE.finditer(contents):
        final_activity[int(match.group(1))] = int(match.group(2))
    final_active = {object_id for object_id, active in final_activity.items() if active}
    centre_id = next(iter(survey.expected_cells(0)))
    if final_active != {centre_id}:
        raise SystemExit(
            f"Radius-zero contraction left active objects: {sorted(final_active)}"
        )

    translations = {
        int(match.group(1)): tuple(int(match.group(axis)) for axis in range(2, 5))
        for match in survey.OBJECT_TRANSLATION_RE.finditer(contents)
        if int(match.group(1)) in expected_five
    }
    if translations != expected_five:
        raise SystemExit("Radius-five translations differ from the exact axial disk")

    inputs = input_trace.input_records(contents)
    observed = [(item["action"], item["scancode"]) for item in inputs]
    expected_inputs = [
        ("down", RADIUS_FIVE_SCANCODE),
        ("up", RADIUS_FIVE_SCANCODE),
        ("down", RADIUS_ZERO_SCANCODE),
        ("up", RADIUS_ZERO_SCANCODE),
    ]
    if observed != expected_inputs:
        raise SystemExit(f"Radius-key trace changed: {observed}")

    frames = []
    for sequence in SEQUENCES:
        raw = output / f"pingo-{survey.BITMAP_ID}-{sequence}.rgba2"
        depth = output / f"pingo-{survey.BITMAP_ID}-{sequence}.z32le"
        if not raw.is_file() or not depth.is_file():
            raise SystemExit(f"Missing ring trace target dump {sequence}")
        ppm = output / f"pingo-{survey.BITMAP_ID}-{sequence}.ppm"
        capture.write_ppm(raw, ppm, survey.WIDTH, survey.HEIGHT)
        frame = survey.analyze_frame(
            raw, depth, require_geometry=sequence in (18, 110)
        )
        frame.update({"sequence": sequence, "ppm_sha256": survey.sha256(ppm)})
        frames.append(frame)
    if frames[1]["populated_depth_pixels"] <= frames[0]["populated_depth_pixels"]:
        raise SystemExit("Radius-five frame did not expand visible terrain coverage")

    report = {
        "schema": TRACE_SCHEMA,
        "program": {"path": str(program), "sha256": survey.sha256(program)},
        "vdp": {"path": str(vdp), "sha256": survey.sha256(vdp)},
        "proxy": {"sha256": survey.sha256(proxy), "exports": sorted(exports)},
        "input_events": inputs,
        "frames": frames,
        "stream": {
            "mesh_replace_count": len(replacements),
            "mesh_ids": sorted(set(replacements)),
            "radius_five_transforms": len(translations),
            "final_radius_zero_active_ids": sorted(final_active),
        },
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": survey.sha256(log_path),
        "qualified": True,
    }
    report_path = output / TRACE_REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless {TRACE_LABEL} passed: {report_path}")
    print(
        f"published={len(replacements)} radius5={len(translations)} "
        f"radius0_active={sorted(final_active)} shutdown={shutdown}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
