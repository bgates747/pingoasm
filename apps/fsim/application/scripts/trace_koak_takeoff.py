#!/usr/bin/env python3
"""Fly and inspect a deterministic headless KOAK 28L takeoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

import trace_koak_input as input_trace


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "fixtures/koak-flight-streamed/src"
STATE_LENGTH = 77
OBJECT_LENGTH = 64
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MEMORY_RE = re.compile(
    r"(?m)^(?:>> )?([0-9a-fA-F]{6}): ((?:[0-9a-fA-F]{2} )+)"
)
SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")
RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+)\b")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=input_trace.DEFAULT_VDP,
        help="real diagnostic VDP module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trigger-sequence", type=int, default=30)
    parser.add_argument("--final-sequence", type=int, default=520)
    parser.add_argument(
        "--pitch-delay-vblanks",
        type=int,
        default=380,
        help="delay from W make to the nose-up pulse (default: 380)",
    )
    parser.add_argument(
        "--pull-vblanks",
        type=int,
        default=8,
        help="Down-key pull duration (default: 8, about four physics ticks)",
    )
    parser.add_argument(
        "--counter-vblanks",
        type=int,
        default=0,
        help="optional immediate Up-key counter-pulse (default: disabled)",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_exact_symbols(stage: Path, program: Path) -> tuple[dict[str, int], Path]:
    """Reassemble an isolated source tree and export addresses for this binary."""

    fixture_root = stage / "fixtures"
    staged_source = fixture_root / "koak-flight-streamed/src"
    shutil.copytree(SOURCE, staged_source)
    for name in ("berkeley-flight-fdm", "p3dm-loader-probe", "_common"):
        shutil.copytree(ROOT / "fixtures" / name, fixture_root / name)
    shutil.copytree(ROOT / "build/aircraft", stage / "build/aircraft")

    staged_binary = stage / "P3DFSIM.BIN"
    subprocess.run(
        [
            "ez80asm",
            "-s",
            "koak-flight-streamed.asm",
            str(staged_binary),
        ],
        cwd=staged_source,
        check=True,
    )
    if sha256(staged_binary) != sha256(program):
        raise SystemExit(
            "Symbol-export assembly differs from the exact fixture under test"
        )

    symbol_path = staged_source / "koak-flight-streamed.symbols"
    symbols: dict[str, int] = {}
    for line in symbol_path.read_text(encoding="ascii").splitlines():
        match = SYMBOL_RE.fullmatch(line)
        if not match:
            continue
        name, address_text = match.groups()
        address = int(address_text, 16)
        previous = symbols.setdefault(name, address)
        if previous != address:
            raise SystemExit(
                f"Assembler exported conflicting values for {name}: "
                f"0x{previous:x} and 0x{address:x}"
            )
    required = {
        "flight_state",
        "flight_state_size",
        "object_state",
        "p3d_object_size",
        "streaming_coarse_x",
        "streaming_coarse_y",
        "submit_current_render",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"Symbol export omitted required state: {missing}")
    if symbols["flight_state_size"] != STATE_LENGTH:
        raise SystemExit("Unexpected packed flight-state length")
    if symbols["p3d_object_size"] != OBJECT_LENGTH:
        raise SystemExit("Unexpected packed object-state length")
    if symbols["streaming_coarse_y"] != symbols["streaming_coarse_x"] + 1:
        raise SystemExit("Coarse-cell bytes are no longer adjacent")
    return symbols, symbol_path


def wait_for_log(
    log_path: Path,
    predicate,
    process: subprocess.Popen[bytes],
    deadline: float,
    description: str,
) -> str:
    while time.monotonic() < deadline:
        contents = log_path.read_text(encoding="utf-8", errors="replace")
        failures = input_trace.find_failures(contents)
        if failures:
            raise SystemExit(
                f"Takeoff trace failed ({', '.join(failures)}); see {log_path}"
            )
        if predicate(contents):
            return contents
        if process.poll() is not None:
            raise SystemExit(
                f"Emulator exited early with {process.returncode}; see {log_path}"
            )
        time.sleep(0.02)
    raise SystemExit(f"Timed out waiting for {description}; see {log_path}")


def write_debugger(process: subprocess.Popen[bytes], command: str) -> None:
    if process.stdin is None:
        raise SystemExit("Debugger stdin is unavailable")
    process.stdin.write((command.rstrip("\n") + "\n").encode("ascii"))
    process.stdin.flush()


def debugger_snapshot(
    process: subprocess.Popen[bytes],
    log_path: Path,
    symbols: dict[str, int],
    deadline: float,
) -> str:
    before = log_path.read_text(encoding="utf-8", errors="replace")
    pause_count = ANSI_RE.sub("", before).count("CPU paused")
    os.kill(process.pid, signal.SIGINT)
    wait_for_log(
        log_path,
        lambda contents: ANSI_RE.sub("", contents).count("CPU paused") > pause_count,
        process,
        deadline,
        "debugger pause",
    )

    # SIGINT can stop inside a multi-byte state transaction. Continue to the
    # next render-submission boundary, where the fixture has finished physics,
    # rebasing, camera/object publication, and all fixed-width stores.
    write_debugger(
        process, f"break 0x{symbols['submit_current_render']:x}"
    )
    write_debugger(process, "continue")
    wait_for_log(
        log_path,
        lambda contents: ANSI_RE.sub("", contents).count("CPU paused")
        > pause_count + 1,
        process,
        deadline,
        "render-idle state boundary",
    )

    spans = (
        (symbols["flight_state"], STATE_LENGTH),
        (symbols["object_state"], OBJECT_LENGTH),
        (symbols["streaming_coarse_x"], 2),
    )
    for address, length in spans:
        write_debugger(process, f"memory 0x{address:x} {length}")
    last_address, last_length = spans[-1]
    expected_line = f"{last_address:06x}:"
    wait_for_log(
        log_path,
        lambda contents: expected_line in ANSI_RE.sub("", contents),
        process,
        deadline,
        "debugger memory snapshot",
    )
    write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise SystemExit("Debugger did not shut the emulator down") from error
    if process.returncode != 0:
        raise SystemExit(
            f"Debugger shutdown returned {process.returncode}; see {log_path}"
        )
    return log_path.read_text(encoding="utf-8", errors="replace")


def parse_memory(contents: str) -> dict[int, int]:
    memory: dict[int, int] = {}
    for match in MEMORY_RE.finditer(ANSI_RE.sub("", contents)):
        address = int(match.group(1), 16)
        for offset, byte in enumerate(match.group(2).split()):
            memory[address + offset] = int(byte, 16)
    return memory


def read_span(memory: dict[int, int], address: int, length: int) -> bytes:
    try:
        return bytes(memory[address + offset] for offset in range(length))
    except KeyError as error:
        raise SystemExit(
            f"Debugger snapshot omitted address 0x{int(error.args[0]):06x}"
        ) from error


def signed_word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def signed_24(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 3], "little", signed=True)


def vec3_words(data: bytes, offset: int) -> list[int]:
    return [signed_word(data, offset + axis * 2) for axis in range(3)]


def decode_state(
    memory: dict[int, int], symbols: dict[str, int]
) -> dict[str, object]:
    data = read_span(memory, symbols["flight_state"], STATE_LENGTH)
    object_data = read_span(memory, symbols["object_state"], OBJECT_LENGTH)
    coarse = read_span(memory, symbols["streaming_coarse_x"], 2)

    position_q8 = [signed_24(data, axis * 3) for axis in range(3)]
    ground_y_q8 = signed_24(data, 9)
    coarse_x, coarse_y = coarse
    global_x_counts_q8 = position_q8[0] + (coarse_y - 146) * 8192 * 256
    global_z_counts_q8 = position_q8[2] - (coarse_x - 94) * 8192 * 256
    start_x_q8 = 3088 * 256
    start_z_q8 = 2181 * 256
    delta_x_m = (global_x_counts_q8 - start_x_q8) / 256.0 * 0.0625
    delta_z_m = (global_z_counts_q8 - start_z_q8) / 256.0 * 0.0625
    flags = data[76]
    pingo_rotation = vec3_words(object_data, 16)
    angular_velocity = vec3_words(object_data, 52)

    return {
        "position_q8": position_q8,
        "ground_y_q8": ground_y_q8,
        "height_agl_m": (position_q8[1] - ground_y_q8) / 256.0 * 0.0625,
        "velocity_q8": vec3_words(data, 12),
        "force_q8": vec3_words(data, 18),
        "acceleration_q8": vec3_words(data, 24),
        "angular_acceleration": vec3_words(data, 30),
        "body_velocity_q8": vec3_words(data, 36),
        "local_force_q8": vec3_words(data, 42),
        "airspeed_q8": signed_word(data, 66),
        "lift_q8": signed_word(data, 68),
        "thrust_q8": signed_word(data, 70),
        "throttle": data[72],
        "controls": {
            "pitch": int.from_bytes(data[73:74], "little", signed=True),
            "roll": int.from_bytes(data[74:75], "little", signed=True),
            "yaw": int.from_bytes(data[75:76], "little", signed=True),
        },
        "flags": flags,
        "on_ground": bool(flags & 0x01),
        "arithmetic_failure": bool(flags & 0x02),
        "coarse_cell": [coarse_x, coarse_y],
        "displacement_m": [delta_x_m, delta_z_m],
        "horizontal_distance_m": math.hypot(delta_x_m, delta_z_m),
        "object_world_position_counts": vec3_words(object_data, 10),
        "object_pingo_rotation_words": pingo_rotation,
        "object_pingo_rotation_degrees": [
            value * 360.0 / 32768.0 for value in pingo_rotation
        ],
        "object_local_angular_velocity": angular_velocity,
    }


def input_event(
    records: list[dict[str, int | str]], action: str, scancode: int
) -> dict[str, int | str]:
    matches = [
        record
        for record in records
        if record["action"] == action and record["scancode"] == scancode
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"Expected one {action} event for 0x{scancode:04x}, found {len(matches)}"
        )
    return matches[0]


def write_command_batch(control_fd: int, commands: list[str]) -> None:
    """Write one small, atomic FIFO schedule for a common vblank origin."""

    if not commands:
        raise SystemExit("Refusing to write an empty input schedule")
    if any("\n" in command or "\r" in command for command in commands):
        raise SystemExit("Input schedule commands must each occupy one line")
    payload = "".join(f"{command}\n" for command in commands).encode("ascii")
    # POSIX guarantees atomic FIFO writes through at least 512 bytes. Keeping
    # this invariant prevents a signal_vblank drain from observing half of the
    # initial V/W/pitch schedule.
    if len(payload) > 512:
        raise SystemExit("Input schedule exceeds the portable atomic FIFO limit")
    written = os.write(control_fd, payload)
    if written != len(payload):
        raise SystemExit(
            f"Short input FIFO write: expected {len(payload)}, wrote {written}"
        )


def validate_takeoff(
    state: dict[str, object],
    records: list[dict[str, int | str]],
    arguments: argparse.Namespace,
) -> dict[str, int]:
    event_specs = [
        ("w_down", "down", "W", "fifo"),
        ("w_up", "up", "W", "fifo"),
        ("down_down", "down", "DOWN", "tapafter-make"),
        ("down_up", "up", "DOWN", "tapafter-release"),
        ("v_down", "down", "V", "fifo-tap"),
        ("v_up", "up", "V", "tap-release"),
    ]
    if arguments.counter_vblanks:
        event_specs.extend(
            (
                ("up_down", "down", "UP", "tapafter-make"),
                ("up_up", "up", "UP", "tapafter-release"),
            )
        )
    events = {
        name: input_event(records, action, input_trace.SET2_CODES[key])
        for name, action, key, _source in event_specs
    }
    for name, _action, _key, source in event_specs:
        actual_source = events[name]["source"]
        if actual_source != source:
            raise SystemExit(
                f"Input event {name} came from {actual_source}, expected {source}"
            )
    frames = {name: int(event["host_vblank"]) for name, event in events.items()}
    expected = {
        "view_to_power": 0,
        "v_hold": 4,
        "pitch_delay": arguments.pitch_delay_vblanks,
        "pull_hold": arguments.pull_vblanks,
    }
    actual = {
        "view_to_power": frames["w_down"] - frames["v_down"],
        "v_hold": frames["v_up"] - frames["v_down"],
        "pitch_delay": frames["down_down"] - frames["w_down"],
        "pull_hold": frames["down_up"] - frames["down_down"],
    }
    if arguments.counter_vblanks:
        expected.update(
            {
                "counter_start": (
                    arguments.pitch_delay_vblanks + arguments.pull_vblanks
                ),
                "counter_hold": arguments.counter_vblanks,
            }
        )
        actual.update(
            {
                "counter_start": frames["up_down"] - frames["w_down"],
                "counter_hold": frames["up_up"] - frames["up_down"],
            }
        )
    if actual != expected:
        raise SystemExit(f"Input timing changed: expected {expected}, got {actual}")
    if bool(state["arithmetic_failure"]):
        raise SystemExit("Flight model reported an arithmetic failure")
    if bool(state["on_ground"]):
        raise SystemExit("Aircraft remained on runway support")
    velocity = state["velocity_q8"]
    assert isinstance(velocity, list)
    if int(velocity[1]) <= 0:
        raise SystemExit(f"Aircraft has no positive climb velocity: {velocity}")
    if int(state["airspeed_q8"]) < 3200:
        raise SystemExit(f"Aircraft did not reach takeoff speed: {state['airspeed_q8']}")
    if int(state["throttle"]) != 255 or int(state["thrust_q8"]) != 28:
        raise SystemExit("Full-power thrust state was not retained")
    if float(state["height_agl_m"]) <= 0.0:
        raise SystemExit("Aircraft did not climb above the support plane")
    if float(state["horizontal_distance_m"]) < 250.0:
        raise SystemExit("Aircraft did not travel a plausible takeoff distance")
    return actual


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if arguments.trigger_sequence < 0:
        raise SystemExit("--trigger-sequence must be non-negative")
    if arguments.final_sequence <= arguments.trigger_sequence:
        raise SystemExit("--final-sequence must follow --trigger-sequence")
    for name in ("pitch_delay_vblanks", "pull_vblanks"):
        if getattr(arguments, name) <= 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")
    if arguments.counter_vblanks < 0:
        raise SystemExit("--counter-vblanks must be non-negative")

    emulator = input_trace.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = input_trace.require_file(input_trace.MOS_BINARY, "MOS image")
    real_vdp = input_trace.require_file(arguments.vdp_module, "diagnostic VDP")
    program = input_trace.require_file(input_trace.PROGRAM, "KOAK fixture")
    proxy_source = input_trace.require_file(
        input_trace.PROXY_SOURCE, "input proxy source"
    )
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)

    proxy = output / "vdp_input_trace_proxy.so"
    exports = input_trace.build_proxy(proxy_source, proxy)
    log_path = output / "emulator.log"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /flight\r\n"
        b"load P3DFSIM.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    trigger = arguments.trigger_sequence
    final = arguments.final_sequence
    dump_sequences = (0, trigger, final)
    dump_selectors = ",".join(
        f"{input_trace.BITMAP_ID}:{sequence}" for sequence in dump_sequences
    )
    trigger_marker = (
        f"PINGO_DUMP seq={trigger} bmid={input_trace.BITMAP_ID} status=ok"
    )
    final_marker = (
        f"PINGO_DUMP seq={final} bmid={input_trace.BITMAP_ID} status=ok"
    )
    active_marker = "PINGO_STREAM object_active=ok oid=201 active=1"
    deadline = time.monotonic() + arguments.timeout
    process: subprocess.Popen[bytes] | None = None
    shutdown_method = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="kts-symbol-") as symbol_name,
        tempfile.TemporaryDirectory(prefix="kts-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="kts-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="kts-fifo-") as fifo_name,
    ):
        symbols, symbol_path = export_exact_symbols(Path(symbol_name), program)
        symbols_sha = sha256(symbol_path)

        sd_root = Path(sd_name)
        shutil.copytree(input_trace.FIXTURE, sd_root / "flight")
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
                "PINGO_RENDER_TARGET_DUMP_FRAMES": dump_selectors,
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
            str(proxy),
            "--sdcard",
            str(sd_root),
            "--verbose",
            "--debugger",
            "-z",
            "-u",
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
                        "PINGO_RENDER_TARGET_DUMP_FRAMES": dump_selectors,
                        "PINGO_RENDER_TARGET_DUMP_DIR": str(output),
                    },
                    "symbols": {
                        name: f"0x{symbols[name]:06x}"
                        for name in (
                            "flight_state",
                            "object_state",
                            "streaming_coarse_x",
                            "submit_current_render",
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
                    lambda contents: trigger_marker in contents,
                    process,
                    deadline,
                    f"render sequence {trigger}",
                )
                control_schedule = [
                    f"tap 0x{input_trace.SET2_CODES['V']:04x} 4",
                    f"down 0x{input_trace.SET2_CODES['W']:04x}",
                    (
                        "tapafter "
                        f"0x{input_trace.SET2_CODES['DOWN']:04x} "
                        f"{arguments.pitch_delay_vblanks} "
                        f"{arguments.pull_vblanks}"
                    ),
                ]
                if arguments.counter_vblanks:
                    control_schedule.append(
                        "tapafter "
                        f"0x{input_trace.SET2_CODES['UP']:04x} "
                        f"{arguments.pitch_delay_vblanks + arguments.pull_vblanks} "
                        f"{arguments.counter_vblanks}",
                    )
                write_command_batch(control_fd, control_schedule)
                wait_for_log(
                    log_path,
                    lambda contents: final_marker in contents
                    and active_marker in contents,
                    process,
                    deadline,
                    f"airborne chase render sequence {final}",
                )
                input_trace.write_command(
                    control_fd, f"up 0x{input_trace.SET2_CODES['W']:04x}"
                )
                wait_for_log(
                    log_path,
                    lambda contents: (
                        "action=up scancode=0x001d" in contents
                    ),
                    process,
                    deadline,
                    "W release",
                )
                contents = debugger_snapshot(process, log_path, symbols, deadline)
                shutdown_method = "debugger-memory-exit"
        finally:
            os.close(control_fd)
            if process is not None and process.poll() is None:
                shutdown_method = input_trace.stop_process(process)

    assert process is not None
    failures = input_trace.find_failures(contents)
    if failures:
        raise SystemExit(
            f"Final takeoff log contains failures: {failures}; see {log_path}"
        )
    memory = parse_memory(contents)
    state = decode_state(memory, symbols)
    records = input_trace.input_records(contents)
    timing = validate_takeoff(state, records, arguments)

    frames = []
    for sequence in dump_sequences:
        raw = input_trace.require_file(
            output / f"pingo-{input_trace.BITMAP_ID}-{sequence}.rgba2",
            f"RGBA2222 render sequence {sequence}",
        )
        depth = input_trace.require_file(
            output / f"pingo-{input_trace.BITMAP_ID}-{sequence}.z32le",
            f"depth render sequence {sequence}",
        )
        ppm = output / f"pingo-{input_trace.BITMAP_ID}-{sequence}.ppm"
        input_trace.write_ppm(raw, ppm)
        frames.append(
            {
                "sequence": sequence,
                "rgba2_sha256": sha256(raw),
                "depth_sha256": sha256(depth),
                "ppm_sha256": sha256(ppm),
            }
        )
    if len({frame["rgba2_sha256"] for frame in frames}) != len(frames):
        raise SystemExit("Initial, control-trigger, and airborne frames are not distinct")

    render_sequences = [int(value) for value in RENDER_RE.findall(contents)]
    report = {
        "schema": "pingo-terrain-headless-takeoff-trace-v1",
        "program": {"path": str(program), "sha256": sha256(program)},
        "real_vdp": {"path": str(real_vdp), "sha256": sha256(real_vdp)},
        "proxy": {
            "path": str(proxy),
            "sha256": sha256(proxy),
            "source_sha256": sha256(proxy_source),
            "exports": sorted(exports),
        },
        "symbol_export": {
            "sha256": symbols_sha,
            "exact_binary_match": True,
            "addresses": {
                name: symbols[name]
                for name in (
                    "flight_state",
                    "object_state",
                    "streaming_coarse_x",
                )
            },
        },
        "control_schedule": {
            "pitch_delay_vblanks": arguments.pitch_delay_vblanks,
            "pull_vblanks": arguments.pull_vblanks,
            "counter_vblanks": arguments.counter_vblanks,
            "observed_deltas": timing,
        },
        "events": records,
        "state": state,
        "frames": frames,
        "render_sequence_range": [min(render_sequences), max(render_sequences)],
        "takeoff_qualified": True,
        "shutdown": shutdown_method,
        "emulator_exit_status": process.returncode,
        "emulator_log": {"path": str(log_path), "sha256": sha256(log_path)},
    }
    report_path = output / "takeoff-trace-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless KOAK takeoff trace passed: {report_path}")
    print(
        "Airborne",
        f"height_agl_m={state['height_agl_m']:.3f}",
        f"velocity_q8={state['velocity_q8']}",
        f"distance_m={state['horizontal_distance_m']:.3f}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
