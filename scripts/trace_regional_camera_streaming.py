#!/usr/bin/env python3
"""Qualify a live cell crossing in the full-region camera survey."""

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

import capture_koak_flight as capture
import trace_koak_input as input_trace
import trace_koak_takeoff as debugger


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-full-l0"
PROGRAM = FIXTURE / "P3DSURV.BIN"
SYMBOLS = ROOT / "fixtures/regional-camera-survey/tgt/regional-camera-survey.symbols"
BITMAP_ID = 257
STARTUP_SEQUENCE = 31
WIDTH = 320
HEIGHT = 240
CAMERA_SIZE = 36
SLOT_COUNT = 32
START_COARSE = (85, 179)
START_CANONICAL = (-1857, 3496, 3638)
FRAME_Z_BIAS = 12288
CELL_COUNTS = 8192
EQUALS = 0x0055
W = 0x001D
W_HOLD_VBLANKS = 360
EQUALS_HOLD_VBLANKS = 400
POST_RELEASE_RENDERS = 40

SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")
RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+)[^\r\n]*")
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
    parser.add_argument("--timeout", type=float, default=75.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
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
        "p3d_camera_size",
        "p3d_camera_world_position",
        "p3d_camera_pingo_rotation",
        "survey_translation_rate",
        "simulate_camera_step",
        "regional_coarse_x",
        "regional_coarse_y",
        "regional_slot_tile_x",
        "regional_slot_tile_y",
        "regional_slot_active",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"Regional-survey symbols omit: {missing}")
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
        "regional debugger pause",
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
        "next regional camera quantum",
    )

    spans = (
        (symbols["camera_state"], CAMERA_SIZE),
        (symbols["survey_translation_rate"], 2),
        (symbols["regional_coarse_x"], 1),
        (symbols["regional_coarse_y"], 1),
        (symbols["regional_slot_tile_x"], SLOT_COUNT),
        (symbols["regional_slot_tile_y"], SLOT_COUNT),
        (symbols["regional_slot_active"], SLOT_COUNT),
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
        "regional camera and slot memory",
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
        int.from_bytes(
            data[offset + axis * 2 : offset + axis * 2 + 2],
            "little",
            signed=True,
        )
        for axis in range(3)
    )  # type: ignore[return-value]


def decode_state(memory: dict[int, int], symbols: dict[str, int]) -> dict:
    camera = debugger.read_span(memory, symbols["camera_state"], CAMERA_SIZE)
    position = signed_words(camera, symbols["p3d_camera_world_position"])
    rotation = signed_words(camera, symbols["p3d_camera_pingo_rotation"])
    coarse = (
        debugger.read_span(memory, symbols["regional_coarse_x"], 1)[0],
        debugger.read_span(memory, symbols["regional_coarse_y"], 1)[0],
    )
    slot_x = debugger.read_span(
        memory, symbols["regional_slot_tile_x"], SLOT_COUNT
    )
    slot_y = debugger.read_span(
        memory, symbols["regional_slot_tile_y"], SLOT_COUNT
    )
    slot_active = debugger.read_span(
        memory, symbols["regional_slot_active"], SLOT_COUNT
    )
    canonical = (
        position[0] + (coarse[1] - START_COARSE[1]) * CELL_COUNTS,
        position[1],
        position[2]
        - FRAME_Z_BIAS
        - (coarse[0] - START_COARSE[0]) * CELL_COUNTS,
    )
    return {
        "local_position": list(position),
        "canonical_position": list(canonical),
        "rotation": list(rotation),
        "coarse_cell": list(coarse),
        "translation_rate": int.from_bytes(
            debugger.read_span(
                memory, symbols["survey_translation_rate"], 2
            ),
            "little",
        ),
        "slot_tile_x": list(slot_x),
        "slot_tile_y": list(slot_y),
        "slot_active": list(slot_active),
    }


def validate_input(records: list[dict[str, int | str]]) -> dict[str, int]:
    if len(records) != 4:
        raise SystemExit(f"Expected four controlled input events, got {len(records)}")
    events = {}
    for name, action, scancode in (
        ("equals_down", "down", EQUALS),
        ("w_down", "down", W),
        ("w_up", "up", W),
        ("equals_up", "up", EQUALS),
    ):
        matches = [
            record
            for record in records
            if record["action"] == action and record["scancode"] == scancode
        ]
        if len(matches) != 1:
            raise SystemExit(f"Unexpected regional input event {name}: {matches}")
        events[name] = matches[0]
    timing = {
        "w_hold": int(events["w_up"]["host_vblank"])
        - int(events["w_down"]["host_vblank"]),
        "equals_hold": int(events["equals_up"]["host_vblank"])
        - int(events["equals_down"]["host_vblank"]),
    }
    expected = {
        "w_hold": W_HOLD_VBLANKS,
        "equals_hold": EQUALS_HOLD_VBLANKS,
    }
    if timing != expected:
        raise SystemExit(f"Regional input timing changed: {timing} != {expected}")
    return timing


def validate_state(state: dict, contents: str) -> None:
    coarse_x, coarse_y = state["coarse_cell"]
    if coarse_x <= START_COARSE[0] or coarse_y != START_COARSE[1]:
        raise SystemExit(
            "Due-east traverse did not cross an eastward coarse-cell boundary: "
            f"{state['coarse_cell']}"
        )
    if state["canonical_position"][2] >= START_CANONICAL[2]:
        raise SystemExit("Due-east W translation did not decrease canonical Z")
    if state["rotation"] != [0, 0, 0]:
        raise SystemExit(f"Translation changed camera rotation: {state['rotation']}")
    if state["translation_rate"] != 64:
        raise SystemExit("Equals did not make exactly one 32-to-64 rate step")
    if state["slot_active"] != [1] * SLOT_COUNT:
        raise SystemExit("The rolling window was not fully active after traversal")

    expected: dict[int, tuple[int, int]] = {}
    for dy in range(-2, 2):
        for dx in range(-2, 6):
            tile_x = coarse_x + dx
            tile_y = coarse_y + dy
            slot = (tile_y & 3) * 8 + (tile_x & 7)
            expected[slot] = (tile_x, tile_y)
    actual = {
        slot: (state["slot_tile_x"][slot], state["slot_tile_y"][slot])
        for slot in range(SLOT_COUNT)
    }
    if actual != expected:
        raise SystemExit(
            "Resident slots do not equal the exact direct-mapped 8x4 window"
        )
    translations = {
        int(match.group(1)): tuple(int(match.group(axis)) for axis in range(2, 5))
        for match in OBJECT_TRANSLATION_RE.finditer(contents)
    }
    expected_translations = {
        slot + 1: (
            (tile_y - coarse_y) * CELL_COUNTS,
            9728,
            FRAME_Z_BIAS - (tile_x - coarse_x) * CELL_COUNTS,
        )
        for slot, (tile_x, tile_y) in expected.items()
    }
    if translations != expected_translations:
        raise SystemExit(
            "Final published object transforms do not match their resident cells"
        )


def render_records(contents: str) -> list[dict[str, int]]:
    records = []
    for match in RENDER_RE.finditer(contents):
        line = match.group(0)
        fields = {
            name: int(value)
            for name, value in re.findall(r"\b(ti|ras)=(\d+)", line)
        }
        if fields.keys() != {"ti", "ras"}:
            raise SystemExit(f"Incomplete PINGO_RENDER diagnostic: {line}")
        records.append(
            {
                "sequence": int(match.group(1)),
                "triangles_input": fields["ti"],
                "rasterized": fields["ras"],
            }
        )
    return records


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    emulator = input_trace.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = input_trace.require_file(input_trace.MOS_BINARY, "MOS image")
    vdp = input_trace.require_file(arguments.vdp_module, "diagnostic VDP module")
    capture.require_diagnostic_vdp(vdp)
    program = input_trace.require_file(PROGRAM, "regional camera survey")
    symbols_path = input_trace.require_file(SYMBOLS, "regional survey symbols")
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
    marker = f"PINGO_DUMP seq={STARTUP_SEQUENCE} bmid={BITMAP_ID} status=ok"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /survey\r\n"
        b"load P3DSURV.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    deadline = time.monotonic() + arguments.timeout
    process: subprocess.Popen[bytes] | None = None
    contents = ""
    shutdown = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="regional-trace-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="regional-trace-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="regional-trace-fifo-") as fifo_name,
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
                "FAB_INPUT_REAL_VDP": str(vdp),
                "FAB_INPUT_FIFO": str(fifo_path),
                "PINGO_RENDER_TARGET_DUMP_FRAMES": (
                    f"{BITMAP_ID}:{STARTUP_SEQUENCE}"
                ),
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
                    "input": {
                        "equals_hold_vblanks": EQUALS_HOLD_VBLANKS,
                        "w_hold_vblanks": W_HOLD_VBLANKS,
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
                    "complete initial regional window",
                )
                debugger.write_command_batch(
                    control_fd,
                    [
                        f"tap 0x{EQUALS:04x} {EQUALS_HOLD_VBLANKS}",
                        f"tap 0x{W:04x} {W_HOLD_VBLANKS}",
                    ],
                )
                contents = wait_for_log(
                    log_path,
                    lambda value: len(input_trace.input_records(value)) >= 4,
                    process,
                    deadline,
                    "regional translation release",
                )
                renders_after_release = len(render_records(contents))
                contents = wait_for_log(
                    log_path,
                    lambda value: len(render_records(value))
                    >= renders_after_release + POST_RELEASE_RENDERS,
                    process,
                    deadline,
                    "post-crossing terrain service passes",
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
    failures = sorted(
        set(input_trace.find_failures(contents) + capture.find_log_failures(contents))
    )
    if failures:
        raise SystemExit(f"Regional streaming trace failures: {failures}")
    timing = validate_input(input_trace.input_records(contents))
    state = decode_state(debugger.parse_memory(contents), symbols)
    validate_state(state, contents)
    replacements = [
        {
            "mesh_id": int(match.group(2)),
            "publication_us": int(match.group(8)),
        }
        for match in capture.MESH_REPLACE_RE.finditer(contents)
    ]
    if len(replacements) <= SLOT_COUNT:
        raise SystemExit("No post-startup terrain mesh replacement was observed")
    if {item["mesh_id"] for item in replacements} - set(range(1, 33)):
        raise SystemExit("Regional trace published an unexpected mesh ID")
    if len(replacements) != SLOT_COUNT + 4:
        raise SystemExit(
            "One eastward cell crossing must replace exactly four terrain slots: "
            f"got {len(replacements) - SLOT_COUNT}"
        )
    activity: dict[int, list[int]] = {}
    for match in capture.OBJECT_ACTIVE_RE.finditer(contents):
        activity.setdefault(int(match.group(1)), []).append(int(match.group(2)))
    recycled = {
        object_id
        for object_id, transitions in activity.items()
        if transitions == [0, 1, 0, 1]
    }
    if recycled != {4, 12, 20, 28}:
        raise SystemExit(f"Unexpected east-edge slot recycling: {sorted(recycled)}")
    if any(
        transitions not in ([0, 1], [0, 1, 0, 1])
        for transitions in activity.values()
    ):
        raise SystemExit("Unexpected regional object activation history")
    renders = render_records(contents)
    live_tail = [
        item
        for item in renders[-10:]
        if item["triangles_input"] > 0 and item["rasterized"] > 0
    ]
    if not live_tail:
        raise SystemExit("Terrain did not keep rasterizing after the cell crossing")

    raw = output / f"pingo-{BITMAP_ID}-{STARTUP_SEQUENCE}.rgba2"
    depth = output / f"pingo-{BITMAP_ID}-{STARTUP_SEQUENCE}.z32le"
    if not raw.is_file() or not depth.is_file():
        raise SystemExit("Initial full-window render target dump is missing")
    ppm = output / f"pingo-{BITMAP_ID}-{STARTUP_SEQUENCE}.ppm"
    capture.write_ppm(raw, ppm, WIDTH, HEIGHT)

    report = {
        "schema": "pingo-terrain-regional-streaming-trace-v1",
        "program": {"path": str(program), "sha256": sha256(program)},
        "symbols": {"path": str(symbols_path), "sha256": sha256(symbols_path)},
        "vdp": {"path": str(vdp), "sha256": sha256(vdp)},
        "proxy": {"sha256": sha256(proxy), "exports": sorted(exports)},
        "input_timing_vblanks": timing,
        "final_state": state,
        "stream": {
            "mesh_replace_count": len(replacements),
            "mesh_ids": sorted({item["mesh_id"] for item in replacements}),
            "maximum_publication_us": max(
                item["publication_us"] for item in replacements
            ),
            "validated_final_object_translations": SLOT_COUNT,
            "recycled_object_ids": sorted(recycled),
        },
        "render_tail": {
            "records": len(renders),
            "last": renders[-1],
            "live_in_final_ten": len(live_tail),
        },
        "initial_full_window": {
            "rgba2_sha256": sha256(raw),
            "depth_sha256": sha256(depth),
            "ppm_sha256": sha256(ppm),
        },
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
        "qualified": True,
    }
    report_path = output / "regional-streaming-trace.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless regional cell crossing passed: {report_path}")
    print(
        f"coarse={state['coarse_cell']} canonical={state['canonical_position']} "
        f"replacements={len(replacements)} renders={len(renders)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
