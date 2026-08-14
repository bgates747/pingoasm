#!/usr/bin/env python3
"""Qualify the FSIM launcher lifecycle in a private headless emulator run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import capture_p3dm_loader_probe as capture
import trace_koak_input as input_trace
import trace_koak_takeoff as takeoff_trace


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "moslets/fsim/tgt/fsim.bin"
LAUNCHER_SYMBOLS = ROOT / "moslets/fsim/tgt/fsim.symbols"
NESTED_FIXTURE = ROOT / "fixtures/nested-agnb-loader-probe/tgt"
NESTED_PROGRAM = NESTED_FIXTURE / "nested-agnb-loader-probe.bin"
MOS_MAP = input_trace.MOS_BINARY.with_suffix(".map")

CALLER_CWD = "/caller"
FIXTURE_CWD = (
    "/mystuff/pingoasm/apps/fsim/fixtures/nested-agnb-loader-probe/tgt"
)
CONFIG_ROOT = "/mystuff/pingoasm/apps/fsim"
SELECTION_SCANCODE = 0x003E  # Top-row 8 in Fab's PS/2 set-2 table.
ESCAPE_SCANCODE = input_trace.SET2_CODES["ESCAPE"]
TAP_HOLD_VBLANKS = 4
CWD_WITNESS_ENTRY = 0x040100
CWD_WITNESS_NAME = "CWDOK.BIN"
BITMAP_ID = capture.BITMAP_ID
SEQUENCE = capture.SEQUENCE
EXPECTED_DUMP_MARKER = (
    f"PINGO_DUMP seq={SEQUENCE} bmid={BITMAP_ID} status=ok"
)

SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")
MAP_SYMBOL_RE = re.compile(
    r"^([^\s]+)\s+[CD]:([0-9a-fA-F]{6})\s+",
    re.MULTILINE,
)
STATE_RE = re.compile(
    r"(?m)^\r?\* ([0-9a-fA-F]{6}):[^\r\n]*\bAF:([0-9a-fA-F]{4})\b"
)
EXTRA_FATAL_MARKERS = (
    "replace_mesh_from_buffer:",
    "CPU paused (out of bounds",
    "CPU paused (I/O breakpoint)",
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=input_trace.DEFAULT_VDP,
        help="real diagnostic PingoWolf VDP module",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new directory in which to retain qualification evidence",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="overall emulator deadline in seconds (default: 60)",
    )
    return parser.parse_args()


def parse_assembler_symbols(path: Path, required: set[str]) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        match = SYMBOL_RE.fullmatch(line)
        if match is None:
            continue
        name, address_text = match.groups()
        address = int(address_text, 16)
        previous = symbols.setdefault(name, address)
        if previous != address:
            raise SystemExit(
                f"Assembler exported conflicting values for {name}: "
                f"0x{previous:06x} and 0x{address:06x}"
            )
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"FSIM symbol export omitted required labels: {missing}")
    return symbols


def parse_mos_map(path: Path, required: set[str]) -> dict[str, int]:
    symbols: dict[str, int] = {}
    contents = path.read_text(encoding="ascii", errors="replace")
    for name, address_text in MAP_SYMBOL_RE.findall(contents):
        if name not in required:
            continue
        address = int(address_text, 16)
        previous = symbols.setdefault(name, address)
        if previous != address:
            raise SystemExit(
                f"MOS map contains conflicting values for {name}: "
                f"0x{previous:06x} and 0x{address:06x}"
            )
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"MOS map omitted required symbols: {missing}")
    return symbols


def clean_log(contents: str) -> str:
    return takeoff_trace.ANSI_RE.sub("", contents)


def state_records(contents: str) -> list[dict[str, int]]:
    return [
        {"pc": int(match.group(1), 16), "af": int(match.group(2), 16)}
        for match in STATE_RE.finditer(clean_log(contents))
    ]


def qualification_failures(contents: str) -> list[str]:
    failures = input_trace.find_failures(contents)
    failures.extend(
        marker for marker in EXTRA_FATAL_MARKERS if marker in contents
    )
    return sorted(set(failures))


def wait_for_log(
    log_path: Path,
    predicate,
    process: subprocess.Popen[bytes],
    deadline: float,
    description: str,
) -> str:
    contents = takeoff_trace.wait_for_log(
        log_path,
        lambda value: predicate(value)
        or bool(qualification_failures(value)),
        process,
        deadline,
        description,
    )
    failures = qualification_failures(contents)
    if failures:
        raise SystemExit(
            f"FSIM qualification failed ({', '.join(failures)}); "
            f"see {log_path}"
        )
    return contents


def wait_for_breakpoint(
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    record_count: int,
    expected_pc: int,
    description: str,
) -> tuple[int, dict[str, int]]:
    contents = wait_for_log(
        log_path,
        lambda value: len(state_records(value)) > record_count,
        process,
        deadline,
        description,
    )
    records = state_records(contents)
    if len(records) != record_count + 1:
        raise SystemExit(
            f"Expected one new debugger stop for {description}, got "
            f"{len(records) - record_count}; see {log_path}"
        )
    record = records[-1]
    if record["pc"] != expected_pc:
        raise SystemExit(
            f"Expected {description} at 0x{expected_pc:06x}, stopped at "
            f"0x{record['pc']:06x}; see {log_path}"
        )
    return len(records), record


def debugger_read_span(
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    address: int,
    length: int,
) -> bytes:
    if length <= 0:
        raise ValueError("debugger span length must be positive")
    last_line = address + ((length - 1) // 16) * 16
    line_re = re.compile(rf"(?m)^\r?(?:>> )?{last_line:06x}:")
    before = clean_log(log_path.read_text(encoding="utf-8", errors="replace"))
    previous_count = len(line_re.findall(before))
    takeoff_trace.write_debugger(process, f"memory 0x{address:x} {length}")
    contents = wait_for_log(
        log_path,
        lambda value: len(line_re.findall(clean_log(value))) > previous_count,
        process,
        deadline,
        f"debugger memory 0x{address:06x}+{length}",
    )
    memory = takeoff_trace.parse_memory(contents)
    try:
        return takeoff_trace.read_span(memory, address, length)
    except KeyError as error:
        raise SystemExit(
            f"Debugger returned an incomplete span at 0x{address:06x}; "
            f"see {log_path}"
        ) from error


def debugger_read_c_string(
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    address: int,
    capacity: int = 256,
) -> str:
    data = debugger_read_span(log_path, process, deadline, address, capacity)
    terminator = data.find(b"\0")
    if terminator < 0:
        raise SystemExit(
            f"C string at 0x{address:06x} lacks a terminator within "
            f"{capacity} bytes"
        )
    try:
        return data[:terminator].decode("ascii")
    except UnicodeDecodeError as error:
        raise SystemExit(
            f"C string at 0x{address:06x} is not ASCII"
        ) from error


def record_mos_cached_cwd(
    milestones: list[dict[str, int | str]],
    name: str,
    state: dict[str, int],
    expected: str | None,
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    cwd_address: int,
) -> None:
    actual = debugger_read_c_string(
        log_path, process, deadline, cwd_address
    )
    if expected is not None and actual != expected:
        raise SystemExit(
            f"{name} MOS cached cwd is {actual!r}, expected {expected!r}; "
            f"see {log_path}"
        )
    milestones.append(
        {
            "name": name,
            "pc": state["pc"],
            "af": state["af"],
            "mos_cached_cwd": actual,
        }
    )


def build_cwd_witness() -> bytes:
    """Return a tiny ADL executable with a unique post-launcher entry."""

    payload = bytearray(b"\xff" * 0x105)
    payload[0:4] = bytes((0xC3, 0x00, 0x01, 0x04))
    payload[0x40:0x45] = b"MOS\0\1"
    payload[0x100:0x105] = bytes((0x21, 0x00, 0x00, 0x00, 0xC9))
    return bytes(payload)


def inject_tap(
    control_fd: int,
    scancode: int,
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    description: str,
) -> list[dict[str, int | str]]:
    before_contents = log_path.read_text(encoding="utf-8", errors="replace")
    previous_count = len(input_trace.input_records(before_contents))
    input_trace.write_command(
        control_fd,
        f"tap 0x{scancode:04x} {TAP_HOLD_VBLANKS}",
    )
    contents = wait_for_log(
        log_path,
        lambda value: len(input_trace.input_records(value))
        >= previous_count + 2,
        process,
        deadline,
        description,
    )
    new_records = input_trace.input_records(contents)[previous_count:]
    if len(new_records) != 2:
        raise SystemExit(
            f"{description} produced {len(new_records)} events instead of 2"
        )
    expected = (("down", "fifo-tap"), ("up", "tap-release"))
    for record, (action, source) in zip(new_records, expected, strict=True):
        if (
            record["action"] != action
            or record["scancode"] != scancode
            or record["source"] != source
        ):
            raise SystemExit(
                f"Unexpected {description} event: {record}; see {log_path}"
            )
    frame_delta = int(new_records[1]["host_vblank"]) - int(
        new_records[0]["host_vblank"]
    )
    if frame_delta != TAP_HOLD_VBLANKS:
        raise SystemExit(
            f"{description} lasted {frame_delta} vblanks, expected "
            f"{TAP_HOLD_VBLANKS}"
        )
    return new_records


def validate_capture(output: Path) -> dict[str, int | str]:
    raw = input_trace.require_file(
        output / f"pingo-{BITMAP_ID}-{SEQUENCE}.rgba2",
        "nested-probe RGBA2222 target",
    )
    depth = input_trace.require_file(
        output / f"pingo-{BITMAP_ID}-{SEQUENCE}.z32le",
        "nested-probe depth target",
    )
    expected_pixels = capture.WIDTH * capture.HEIGHT
    packed = raw.read_bytes()
    if len(packed) != expected_pixels:
        raise SystemExit(
            f"Expected {expected_pixels} RGBA2222 bytes, got {len(packed)}"
        )
    depth_bytes = depth.read_bytes()
    if len(depth_bytes) != expected_pixels * 4:
        raise SystemExit(
            f"Expected {expected_pixels * 4} depth bytes, got "
            f"{len(depth_bytes)}"
        )
    populated_color = sum(value != 0 for value in packed)
    populated_depth = sum(
        depth_bytes[offset : offset + 4] != b"\0\0\0\0"
        for offset in range(0, len(depth_bytes), 4)
    )
    if populated_color == 0 or populated_depth != populated_color:
        raise SystemExit(
            "Nested-probe capture is blank or color/depth coverage disagrees: "
            f"color={populated_color}, depth={populated_depth}"
        )
    ppm = output / f"pingo-{BITMAP_ID}-{SEQUENCE}.ppm"
    capture.write_ppm(raw, ppm)
    return {
        "width": capture.WIDTH,
        "height": capture.HEIGHT,
        "populated_pixels": populated_color,
        "rgba2_sha256": input_trace.sha256(raw),
        "depth_sha256": input_trace.sha256(depth),
        "ppm_sha256": input_trace.sha256(ppm),
    }


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    emulator = input_trace.require_file(
        input_trace.FAB_BINARY, "Fab executable"
    )
    mos = input_trace.require_file(input_trace.MOS_BINARY, "MOS image")
    mos_map = input_trace.require_file(MOS_MAP, "matching MOS map")
    real_vdp = input_trace.require_file(
        arguments.vdp_module, "diagnostic VDP module"
    )
    launcher = input_trace.require_file(LAUNCHER, "FSIM launcher")
    launcher_symbols = input_trace.require_file(
        LAUNCHER_SYMBOLS, "FSIM symbol export"
    )
    program = input_trace.require_file(
        NESTED_PROGRAM, "nested AGNB probe"
    )
    proxy_source = input_trace.require_file(
        input_trace.PROXY_SOURCE, "input-proxy source"
    )
    if not NESTED_FIXTURE.is_dir():
        raise SystemExit(f"Missing nested AGNB runtime: {NESTED_FIXTURE}")

    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)

    fsim_symbols = parse_assembler_symbols(
        launcher_symbols,
        {
            "fixture_entry",
            "launcher_menu_wait",
            "launcher_after_fixture",
            "launcher_return_to_mos",
        },
    )
    if fsim_symbols["fixture_entry"] != 0x040000:
        raise SystemExit("FSIM fixture entry is no longer 0x040000")
    mos_symbols = parse_mos_map(
        mos_map, {"_mos_input", "_cwd", "_scrmode"}
    )

    proxy = output / "vdp_input_trace_proxy.so"
    exports = input_trace.build_proxy(proxy_source, proxy)
    log_path = output / "emulator.log"
    # This is a harness-local autoexec, never the project's profile file.  The
    # older Console8 MOS updates FatFS cwd through API 3 without refreshing its
    # printable `_cwd` cache, so the relative CWDOK load is the authoritative
    # proof that FSIM restored the real caller directory.
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /caller\r\n"
        b"fsim\r\n"
        b"load CWDOK.BIN\r\n"
        b"run\r\n"
    )
    config = (CONFIG_ROOT + "\r\n").encode("ascii")
    (output / "autoexec.txt").write_bytes(autoexec)
    (output / "fsim.cfg").write_bytes(config)
    cwd_witness = output / "cwd-witness.bin"
    cwd_witness.write_bytes(build_cwd_witness())

    milestones: list[dict[str, int | str]] = []
    injected_events: list[dict[str, int | str]] = []
    shutdown_method = "not-started"
    process: subprocess.Popen[bytes] | None = None

    with (
        tempfile.TemporaryDirectory(prefix="pingo-fsim-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="pingo-fsim-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="pingo-fsim-fifo-") as fifo_name,
    ):
        sd_root = Path(sd_name)
        mos_dir = sd_root / "mos"
        mos_dir.mkdir(parents=True)
        shutil.copy2(launcher, mos_dir / "fsim.bin")
        (mos_dir / "fsim.cfg").write_bytes(config)
        staged_fixture = (
            sd_root
            / "mystuff/pingo_terrain/fixtures/"
            "nested-agnb-loader-probe/tgt"
        )
        shutil.copytree(NESTED_FIXTURE, staged_fixture)
        caller_dir = sd_root / "caller"
        caller_dir.mkdir()
        shutil.copy2(cwd_witness, caller_dir / CWD_WITNESS_NAME)
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
                "PINGO_RENDER_TARGET_DUMP_FRAMES": (
                    f"{BITMAP_ID}:{SEQUENCE}"
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

        breakpoint_addresses = (
            fsim_symbols["launcher_menu_wait"],
            fsim_symbols["fixture_entry"],
            fsim_symbols["launcher_after_fixture"],
            fsim_symbols["launcher_return_to_mos"],
            CWD_WITNESS_ENTRY,
            mos_symbols["_mos_input"],
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
        for address in breakpoint_addresses:
            command.extend(("--breakpoint", f"0x{address:x}"))

        (output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "environment": {
                        "SDL_VIDEODRIVER": "dummy",
                        "SDL_AUDIODRIVER": "dummy",
                        "FAB_INPUT_REAL_VDP": str(real_vdp),
                        "FAB_INPUT_FIFO": "<private named pipe>",
                        "PINGO_RENDER_TARGET_DUMP_FRAMES": (
                            f"{BITMAP_ID}:{SEQUENCE}"
                        ),
                        "PINGO_RENDER_TARGET_DUMP_DIR": str(output),
                    },
                    "private_sd_layout": {
                        "caller": CALLER_CWD,
                        "config_root": CONFIG_ROOT,
                        "selected_fixture": FIXTURE_CWD,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        deadline = time.monotonic() + arguments.timeout
        completed = False
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

                state_count = 0
                state_count, state = wait_for_breakpoint(
                    log_path,
                    process,
                    deadline,
                    state_count,
                    fsim_symbols["launcher_menu_wait"],
                    "initial FSIM menu",
                )
                record_mos_cached_cwd(
                    milestones,
                    "initial-menu",
                    state,
                    CALLER_CWD,
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_cwd"],
                )
                injected_events.extend(
                    inject_tap(
                        control_fd,
                        SELECTION_SCANCODE,
                        log_path,
                        process,
                        deadline,
                        "fixture-8 selection",
                    )
                )
                takeoff_trace.write_debugger(process, "continue")

                state_count, state = wait_for_breakpoint(
                    log_path,
                    process,
                    deadline,
                    state_count,
                    fsim_symbols["fixture_entry"],
                    "nested fixture common entry",
                )
                record_mos_cached_cwd(
                    milestones,
                    "fixture-entry",
                    state,
                    None,
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_cwd"],
                )
                milestones[-1]["relative_fixture_program_loaded"] = True
                takeoff_trace.write_debugger(
                    process, f"delete 0x{fsim_symbols['fixture_entry']:x}"
                )
                takeoff_trace.write_debugger(process, "continue")

                contents = wait_for_log(
                    log_path,
                    lambda value: EXPECTED_DUMP_MARKER in value
                    or len(state_records(value)) > state_count,
                    process,
                    deadline,
                    "nested AGNB render target",
                )
                if EXPECTED_DUMP_MARKER not in contents:
                    raise SystemExit(
                        "Nested fixture returned before publishing its target; "
                        f"see {log_path}"
                    )
                milestones[-1]["relative_fixture_assets_loaded"] = True
                injected_events.extend(
                    inject_tap(
                        control_fd,
                        ESCAPE_SCANCODE,
                        log_path,
                        process,
                        deadline,
                        "fixture Escape",
                    )
                )

                state_count, state = wait_for_breakpoint(
                    log_path,
                    process,
                    deadline,
                    state_count,
                    fsim_symbols["launcher_after_fixture"],
                    "fixture return to FSIM",
                )
                record_mos_cached_cwd(
                    milestones,
                    "fixture-return",
                    state,
                    None,
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_cwd"],
                )
                takeoff_trace.write_debugger(process, "continue")

                state_count, state = wait_for_breakpoint(
                    log_path,
                    process,
                    deadline,
                    state_count,
                    fsim_symbols["launcher_menu_wait"],
                    "restored FSIM menu",
                )
                record_mos_cached_cwd(
                    milestones,
                    "restored-menu",
                    state,
                    CALLER_CWD,
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_cwd"],
                )
                injected_events.extend(
                    inject_tap(
                        control_fd,
                        ESCAPE_SCANCODE,
                        log_path,
                        process,
                        deadline,
                        "launcher Escape",
                    )
                )
                takeoff_trace.write_debugger(process, "continue")

                state_count, state = wait_for_breakpoint(
                    log_path,
                    process,
                    deadline,
                    state_count,
                    fsim_symbols["launcher_return_to_mos"],
                    "FSIM return boundary",
                )
                record_mos_cached_cwd(
                    milestones,
                    "launcher-return",
                    state,
                    CALLER_CWD,
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_cwd"],
                )
                takeoff_trace.write_debugger(process, "continue")

                state_count, state = wait_for_breakpoint(
                    log_path,
                    process,
                    deadline,
                    state_count,
                    CWD_WITNESS_ENTRY,
                    "caller-relative cwd witness",
                )
                record_mos_cached_cwd(
                    milestones,
                    "cwd-witness",
                    state,
                    CALLER_CWD,
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_cwd"],
                )
                milestones[-1]["relative_caller_witness_loaded"] = True
                takeoff_trace.write_debugger(process, "continue")

                state_count, state = wait_for_breakpoint(
                    log_path,
                    process,
                    deadline,
                    state_count,
                    mos_symbols["_mos_input"],
                    "ordinary MOS prompt",
                )
                record_mos_cached_cwd(
                    milestones,
                    "mos-prompt",
                    state,
                    CALLER_CWD,
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_cwd"],
                )
                screen_mode = debugger_read_span(
                    log_path,
                    process,
                    deadline,
                    mos_symbols["_scrmode"],
                    1,
                )[0]
                if screen_mode != 0:
                    raise SystemExit(
                        f"MOS prompt screen mode is {screen_mode}, expected 0"
                    )
                milestones[-1]["screen_mode"] = screen_mode

                final_contents = log_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                final_states = state_records(final_contents)
                if len(final_states) != 7:
                    raise SystemExit(
                        f"Expected exactly 7 lifecycle stops, got "
                        f"{len(final_states)}"
                    )
                takeoff_trace.write_debugger(process, "exit")
                try:
                    process.wait(
                        timeout=max(1.0, deadline - time.monotonic())
                    )
                except subprocess.TimeoutExpired as error:
                    raise SystemExit(
                        "Debugger did not shut the emulator down"
                    ) from error
                shutdown_method = "debugger-exit"
                completed = True
        finally:
            if process is not None and process.poll() is None:
                shutdown_method = input_trace.stop_process(process)
            os.close(control_fd)

        if not completed or process is None:
            raise SystemExit("FSIM qualification did not reach MOS")
        if process.returncode != 0:
            raise SystemExit(
                f"Emulator shutdown returned {process.returncode}; "
                f"see {log_path}"
            )

    contents = log_path.read_text(encoding="utf-8", errors="replace")
    failures = qualification_failures(contents)
    if failures:
        raise SystemExit(
            f"Final FSIM log contains failures: {failures}; see {log_path}"
        )
    all_events = input_trace.input_records(contents)
    if all_events != injected_events:
        raise SystemExit(
            "Final proxy event stream differs from the six driven events"
        )
    capture_evidence = validate_capture(output)

    report = {
        "schema": "pingo-terrain-fsim-launcher-qualification-v1",
        "headless": {"video": "dummy", "audio": "dummy", "renderer": "sw"},
        "private_sd": True,
        "production_autoexec_used": False,
        "cwd_witness": {
            "path": str(cwd_witness),
            "entry": CWD_WITNESS_ENTRY,
            "sha256": input_trace.sha256(cwd_witness),
            "relative_load_observed": True,
        },
        "selection": {
            "menu_number": 8,
            "scancode": SELECTION_SCANCODE,
            "fixture": str(program),
            "fixture_sha256": input_trace.sha256(program),
        },
        "launcher": {
            "path": str(launcher),
            "sha256": input_trace.sha256(launcher),
            "symbols_path": str(launcher_symbols),
            "symbols_sha256": input_trace.sha256(launcher_symbols),
            "breakpoints": {
                name: fsim_symbols[name]
                for name in (
                    "launcher_menu_wait",
                    "fixture_entry",
                    "launcher_after_fixture",
                    "launcher_return_to_mos",
                )
            },
        },
        "mos": {
            "path": str(mos),
            "sha256": input_trace.sha256(mos),
            "map_path": str(mos_map),
            "map_sha256": input_trace.sha256(mos_map),
            "symbols": mos_symbols,
        },
        "emulator": {
            "path": str(emulator),
            "sha256": input_trace.sha256(emulator),
            "exit_status": process.returncode,
            "shutdown": shutdown_method,
        },
        "real_vdp": {
            "path": str(real_vdp),
            "sha256": input_trace.sha256(real_vdp),
        },
        "proxy": {
            "path": str(proxy),
            "sha256": input_trace.sha256(proxy),
            "source": str(proxy_source),
            "source_sha256": input_trace.sha256(proxy_source),
            "exports": sorted(exports),
        },
        "dump_marker": EXPECTED_DUMP_MARKER,
        "dump_marker_observed": True,
        "milestones": milestones,
        "events": all_events,
        "capture": capture_evidence,
        "emulator_log": {
            "path": str(log_path),
            "sha256": input_trace.sha256(log_path),
        },
    }
    report_path = output / "fsim-launcher-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Headless FSIM launcher qualification passed: {report_path}")
    print(
        "Lifecycle: /caller -> fixture 8 -> /caller menu -> "
        "/caller MOS prompt"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
