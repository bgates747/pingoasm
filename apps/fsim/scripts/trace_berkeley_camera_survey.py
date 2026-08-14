#!/usr/bin/env python3
"""Qualify direct camera controls in a silent Berkeley survey emulator run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

import capture_berkeley_dither as capture
import trace_koak_input as input_trace
import trace_koak_takeoff as debugger


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/berkeley-flight-triangular-dither/tgt"
PROGRAM = FIXTURE / "berkeley-camera-survey.bin"
SYMBOLS = FIXTURE / "berkeley-camera-survey.symbols"
BITMAP_ID = 257
SEQUENCE = 0
CAMERA_SIZE = 36
INITIAL_POSITION = (0, -1144, 16384)
INITIAL_ROTATION = (0, 0, 0)
EXPECTED_INITIAL_RGBA2_SHA256 = (
    "b234d54e166ce74e40f39bdb3ae25836efbfda1003706629e48e89e54320f86c"
)
SET2 = {
    "EQUALS": 0x0055,
    "UP": 0xE075,
    "DOWN": 0xE072,
    "W": 0x001D,
    "PAGE_UP": 0xE07D,
}
SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")
RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+)[^\r\n]*")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=capture.DEFAULT_VDP,
        help="real terrain-diagnostic PingoWolf VDP module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=75.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_symbols(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        match = SYMBOL_RE.fullmatch(line)
        if match is None:
            continue
        name, value = match.groups()
        address = int(value, 16)
        previous = symbols.setdefault(name, address)
        if previous != address:
            raise SystemExit(f"Conflicting assembler values for {name}")
    required = {
        "camera_state",
        "p3d_camera_dirty",
        "p3d_camera_world_position",
        "p3d_camera_pingo_rotation",
        "p3d_camera_orientation",
        "p3d_camera_size",
        "survey_translation_rate",
        "simulate_camera_step",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"Camera-survey symbols omit: {missing}")
    if symbols["p3d_camera_size"] != CAMERA_SIZE:
        raise SystemExit("Unexpected packed camera-state size")
    return symbols


def wait_for_log(
    log_path: Path,
    predicate,
    process: subprocess.Popen[bytes],
    deadline: float,
    description: str,
) -> str:
    return debugger.wait_for_log(
        log_path, predicate, process, deadline, description
    )


def snapshot_at_next_camera_quantum(
    process: subprocess.Popen[bytes],
    log_path: Path,
    symbols: dict[str, int],
    deadline: float,
) -> str:
    before = log_path.read_text(encoding="utf-8", errors="replace")
    pause_count = debugger.ANSI_RE.sub("", before).count("CPU paused")
    os.kill(process.pid, signal.SIGINT)
    wait_for_log(
        log_path,
        lambda contents: debugger.ANSI_RE.sub("", contents).count("CPU paused")
        > pause_count,
        process,
        deadline,
        "initial debugger pause",
    )
    debugger.write_debugger(
        process, f"break 0x{symbols['simulate_camera_step']:x}"
    )
    debugger.write_debugger(process, "continue")
    wait_for_log(
        log_path,
        lambda contents: debugger.ANSI_RE.sub("", contents).count("CPU paused")
        > pause_count + 1,
        process,
        deadline,
        "next fixed camera quantum",
    )

    spans = (
        (symbols["camera_state"], CAMERA_SIZE),
        (symbols["survey_translation_rate"], 2),
    )
    for address, length in spans:
        debugger.write_debugger(process, f"memory 0x{address:x} {length}")
    final_address = spans[-1][0]
    wait_for_log(
        log_path,
        lambda contents: f"{final_address:06x}:"
        in debugger.ANSI_RE.sub("", contents),
        process,
        deadline,
        "camera-state debugger memory",
    )
    debugger.write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise SystemExit("Debugger did not shut the emulator down") from error
    if process.returncode != 0:
        raise SystemExit(f"Debugger shutdown returned {process.returncode}")
    return log_path.read_text(encoding="utf-8", errors="replace")


def signed_words(data: bytes, offset: int) -> tuple[int, int, int]:
    return tuple(
        int.from_bytes(data[offset + axis * 2 : offset + axis * 2 + 2],
                       "little", signed=True)
        for axis in range(3)
    )  # type: ignore[return-value]


def decode_state(memory: dict[int, int], symbols: dict[str, int]) -> dict:
    camera = debugger.read_span(memory, symbols["camera_state"], CAMERA_SIZE)
    rate_bytes = debugger.read_span(
        memory, symbols["survey_translation_rate"], 2
    )
    return {
        "dirty": camera[symbols["p3d_camera_dirty"]],
        "position": list(
            signed_words(camera, symbols["p3d_camera_world_position"])
        ),
        "rotation": list(
            signed_words(camera, symbols["p3d_camera_pingo_rotation"])
        ),
        "translation_rate": int.from_bytes(rate_bytes, "little"),
    }


def validate_events(records: list[dict[str, int | str]]) -> dict[str, int]:
    if len(records) != 10:
        raise SystemExit(f"Expected ten controlled key events, got {len(records)}")
    specs = (
        ("equals_down", "down", "EQUALS", "fifo-tap"),
        ("up_down", "down", "UP", "fifo-tap"),
        ("up_up", "up", "UP", "tap-release"),
        ("down_down", "down", "DOWN", "tapafter-make"),
        ("down_up", "up", "DOWN", "tapafter-release"),
        ("w_down", "down", "W", "tapafter-make"),
        ("w_up", "up", "W", "tapafter-release"),
        ("page_down", "down", "PAGE_UP", "tapafter-make"),
        ("equals_up", "up", "EQUALS", "tap-release"),
        ("page_up", "up", "PAGE_UP", "tapafter-release"),
    )
    events: dict[str, dict[str, int | str]] = {}
    for name, action, key, source in specs:
        matches = [
            record
            for record in records
            if record["action"] == action
            and record["scancode"] == SET2[key]
            and record["source"] == source
        ]
        if len(matches) != 1:
            raise SystemExit(f"Unexpected event record for {name}: {matches}")
        events[name] = matches[0]
    origin = int(events["equals_down"]["host_vblank"])
    observed = {
        "pitch_hold": int(events["up_up"]["host_vblank"])
        - int(events["up_down"]["host_vblank"]),
        "reverse_start": int(events["down_down"]["host_vblank"]) - origin,
        "reverse_hold": int(events["down_up"]["host_vblank"])
        - int(events["down_down"]["host_vblank"]),
        "w_start": int(events["w_down"]["host_vblank"]) - origin,
        "w_hold": int(events["w_up"]["host_vblank"])
        - int(events["w_down"]["host_vblank"]),
        "page_start": int(events["page_down"]["host_vblank"]) - origin,
        "page_hold": int(events["page_up"]["host_vblank"])
        - int(events["page_down"]["host_vblank"]),
        "equals_hold": int(events["equals_up"]["host_vblank"]) - origin,
    }
    expected = {
        "pitch_hold": 120,
        "reverse_start": 130,
        "reverse_hold": 120,
        "w_start": 260,
        "w_hold": 20,
        "page_start": 290,
        "page_hold": 20,
        "equals_hold": 320,
    }
    if observed != expected:
        raise SystemExit(f"Input schedule changed: {observed} != {expected}")
    return observed


def validate_state(state: dict) -> None:
    x, y, z = state["position"]
    pitch, yaw, roll = state["rotation"]
    if x != INITIAL_POSITION[0]:
        raise SystemExit(f"Pitch leaked into horizontal X translation: {x}")
    if y <= INITIAL_POSITION[1]:
        raise SystemExit(f"Page Up did not increase world Y: {y}")
    if z >= INITIAL_POSITION[2]:
        raise SystemExit(f"W did not advance along yaw-zero local -Z: {z}")
    if not (0 < pitch < 2000) or (yaw, roll) != (0, 0):
        raise SystemExit(
            "Pitch did not reverse continuously away from the negative clamp: "
            f"{(pitch, yaw, roll)}"
        )
    if state["translation_rate"] != 64:
        raise SystemExit(
            "A held Equals key did not produce exactly one speed edge: "
            f"{state['translation_rate']}"
        )


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    emulator = input_trace.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = input_trace.require_file(input_trace.MOS_BINARY, "MOS image")
    real_vdp = input_trace.require_file(arguments.vdp_module, "terrain VDP")
    program = input_trace.require_file(PROGRAM, "camera-survey fixture")
    symbols_path = input_trace.require_file(SYMBOLS, "camera-survey symbols")
    proxy_source = input_trace.require_file(
        input_trace.PROXY_SOURCE, "input proxy source"
    )
    symbols = parse_symbols(symbols_path)

    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    proxy = output / "vdp_input_trace_proxy.so"
    exports = input_trace.build_proxy(proxy_source, proxy)
    log_path = output / "emulator.log"
    raw_path = output / f"pingo-{BITMAP_ID}-{SEQUENCE}.rgba2"
    depth_path = output / f"pingo-{BITMAP_ID}-{SEQUENCE}.z32le"
    marker = f"PINGO_DUMP seq={SEQUENCE} bmid={BITMAP_ID} status=ok"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /survey\r\n"
        b"load berkeley-camera-survey.bin\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    deadline = time.monotonic() + arguments.timeout
    process: subprocess.Popen[bytes] | None = None
    contents = ""
    shutdown = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="camera-survey-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="camera-survey-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="camera-survey-fifo-") as fifo_name,
    ):
        sd_root = Path(sd_name)
        (sd_root / "survey").symlink_to(FIXTURE, target_is_directory=True)
        (sd_root / "autoexec.txt").write_bytes(autoexec)
        fifo_path = Path(fifo_name) / "keyboard.fifo"
        os.mkfifo(fifo_path, 0o600)
        control_fd = os.open(fifo_path, os.O_RDWR | os.O_NONBLOCK)

        environment = os.environ.copy()
        environment.update(
            {
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
                "FAB_INPUT_REAL_VDP": str(real_vdp),
                "FAB_INPUT_FIFO": str(fifo_path),
                "PINGO_RENDER_TARGET_DUMP_FRAMES": f"{BITMAP_ID}:{SEQUENCE}",
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
            "--verbose", "--debugger", "-z", "-u",
        ]
        (output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "environment": {
                        "SDL_VIDEODRIVER": "dummy",
                        "SDL_AUDIODRIVER": "dummy",
                        "FAB_INPUT_REAL_VDP": str(real_vdp),
                        "FAB_INPUT_FIFO": "<temporary named pipe>",
                        "PINGO_RENDER_TARGET_DUMP_FRAMES": f"{BITMAP_ID}:{SEQUENCE}",
                        "PINGO_RENDER_TARGET_DUMP_DIR": str(output),
                    },
                    "symbols": {
                        name: symbols[name]
                        for name in (
                            "camera_state",
                            "survey_translation_rate",
                            "simulate_camera_step",
                        )
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        try:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    command,
                    cwd=run_name,
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                wait_for_log(
                    log_path,
                    lambda value: marker in value,
                    process,
                    deadline,
                    "initial Berkeley survey frame",
                )
                debugger.write_command_batch(
                    control_fd,
                    [
                        f"tap 0x{SET2['EQUALS']:04x} 320",
                        f"tap 0x{SET2['UP']:04x} 120",
                        f"tapafter 0x{SET2['DOWN']:04x} 130 120",
                        f"tapafter 0x{SET2['W']:04x} 260 20",
                        f"tapafter 0x{SET2['PAGE_UP']:04x} 290 20",
                    ],
                )
                wait_for_log(
                    log_path,
                    lambda value: len(input_trace.input_records(value)) >= 10,
                    process,
                    deadline,
                    "complete survey-control schedule",
                )
                contents = snapshot_at_next_camera_quantum(
                    process, log_path, symbols, deadline
                )
                shutdown = "debugger-memory-exit"
        finally:
            os.close(control_fd)
            if process is not None and process.poll() is None:
                shutdown = input_trace.stop_process(process)

    assert process is not None
    failures = input_trace.find_failures(contents)
    if failures:
        raise SystemExit(f"Camera-survey log failures: {failures}")
    if not raw_path.is_file() or not depth_path.is_file():
        raise SystemExit("Terrain VDP did not emit the initial color/depth pair")
    if raw_path.stat().st_size != capture.WIDTH * capture.HEIGHT:
        raise SystemExit("Unexpected survey target dimensions")
    initial_hash = sha256(raw_path)
    if initial_hash != EXPECTED_INITIAL_RGBA2_SHA256:
        raise SystemExit(
            "Survey initial frame differs from accepted fixture 3: "
            f"{initial_hash}"
        )
    ppm_path = output / f"pingo-{BITMAP_ID}-{SEQUENCE}.ppm"
    capture.write_ppm(raw_path, ppm_path)
    events = input_trace.input_records(contents)
    timing = validate_events(events)
    state = decode_state(debugger.parse_memory(contents), symbols)
    validate_state(state)
    render_records = []
    for match in RENDER_RE.finditer(contents):
        line = match.group(0)
        fields = {
            name: int(value)
            for name, value in re.findall(r"\b(ofr|ti|ras)=(\d+)", line)
        }
        if fields.keys() != {"ofr", "ti", "ras"}:
            raise SystemExit(f"Incomplete PINGO_RENDER diagnostic: {line}")
        render_records.append(
            {
                "sequence": int(match.group(1)),
                "objects_outside_frustum": fields["ofr"],
                "triangles_input": fields["ti"],
                "rasterized": fields["ras"],
            }
        )
    if len(render_records) < 60:
        raise SystemExit("Pitch reversal did not leave a continuing render trace")
    recovered_records = [
        item
        for item in render_records[-10:]
        if item["triangles_input"] > 0 and item["rasterized"] > 0
    ]
    if not recovered_records:
        raise SystemExit("Terrain rasterization did not recover after reversing pitch")

    report = {
        "schema": "pingo-terrain-camera-survey-trace-v2",
        "program": {"path": str(program), "sha256": sha256(program)},
        "symbols": {"path": str(symbols_path), "sha256": sha256(symbols_path)},
        "real_vdp": {"path": str(real_vdp), "sha256": sha256(real_vdp)},
        "proxy": {"sha256": sha256(proxy), "exports": sorted(exports)},
        "initial_control": {
            "position": list(INITIAL_POSITION),
            "rotation": list(INITIAL_ROTATION),
            "rgba2_sha256": initial_hash,
            "matches_accepted_fixture_3": True,
            "depth_sha256": sha256(depth_path),
        },
        "input_timing_vblanks": timing,
        "events": events,
        "final_state": state,
        "pitch_reversal": {
            "renders_observed": len(render_records),
            "minimum_triangles_input": min(
                item["triangles_input"] for item in render_records
            ),
            "last_render": render_records[-1],
            "recovered_in_final_ten": len(recovered_records),
        },
        "qualified": True,
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "emulator_log": {"path": str(log_path), "sha256": sha256(log_path)},
    }
    report_path = output / "camera-survey-trace-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless Berkeley camera survey passed: {report_path}")
    print(
        "Final",
        f"position={state['position']}",
        f"rotation={state['rotation']}",
        f"rate={state['translation_rate']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
