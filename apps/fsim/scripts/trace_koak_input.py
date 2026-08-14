#!/usr/bin/env python3
"""Prove deterministic headless input against the streamed KOAK fixture."""

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
FIXTURE = ROOT / "build/p3dm/bay-area-koak-proof"
PROGRAM = FIXTURE / "P3DFSIM.BIN"
PROXY_SOURCE = ROOT / "tools/vdp_input_trace_proxy.c"
BITMAP_ID = 257
WIDTH = 320
HEIGHT = 148

# PS/2 set-2 make codes, matching Fab's src/sdl2ps2.rs conversion table.
SET2_CODES = {
    "W": 0x001D,
    "S": 0x001B,
    "A": 0x001C,
    "D": 0x0023,
    "V": 0x002A,
    "UP": 0xE075,
    "DOWN": 0xE072,
    "LEFT": 0xE06B,
    "RIGHT": 0xE074,
    "ESCAPE": 0x0076,
}

INPUT_RE = re.compile(
    r"FAB_INPUT frame=(\d+) action=(down|up) "
    r"scancode=0x([0-9a-fA-F]{4}) source=([^\s]+)"
)
FATAL_MARKERS = (
    "FAB_INPUT_FATAL",
    "FAB_INPUT_ERROR",
    "PINGO_SCENE active_overflow=1",
    "P3DM startup error",
    "VDP error:",
    "panicked at",
    "Guru Meditation",
)
REQUIRED_PROXY_EXPORTS = frozenset(
    {
        "vdp_setup",
        "vdp_loop",
        "vdp_shutdown",
        "signal_vblank",
        "copyVgaFramebuffer",
        "set_startup_screen_mode",
        "z80_uart0_is_cts",
        "z80_send_to_vdp",
        "z80_recv_from_vdp",
        "sendVKeyEventToFabgl",
        "sendPS2KbEventToFabgl",
        "sendHostMouseEventToFabgl",
        "setVdpDebugLogging",
        "getAudioSamples",
        "dump_vdp_mem_stats",
    }
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=DEFAULT_VDP,
        help=f"real diagnostic VDP module (default: {DEFAULT_VDP})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new evidence directory",
    )
    parser.add_argument(
        "--trigger-sequence",
        type=int,
        default=30,
        help="completed cockpit render after which V is tapped (default: 30)",
    )
    parser.add_argument(
        "--chase-sequence",
        type=int,
        default=60,
        help="later chase render to retain (default: 60)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="overall emulator deadline in seconds (default: 90)",
    )
    return parser.parse_args()


def require_file(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"Missing {description}: {resolved}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def proxy_exports(path: Path) -> frozenset[str]:
    result = subprocess.run(
        ["nm", "-D", "--defined-only", str(path)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return frozenset(
        line.split()[-1] for line in result.stdout.splitlines() if line.split()
    )


def build_proxy(source: Path, output: Path) -> frozenset[str]:
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-fPIC",
            "-shared",
            str(source),
            "-o",
            str(output),
            "-ldl",
            "-pthread",
        ],
        check=True,
    )
    exports = proxy_exports(output)
    missing = sorted(REQUIRED_PROXY_EXPORTS - exports)
    if missing:
        raise SystemExit(f"Input proxy omitted required Fab ABI exports: {missing}")
    return exports


def input_records(contents: str) -> list[dict[str, int | str]]:
    return [
        {
            "host_vblank": int(match.group(1)),
            "action": match.group(2),
            "scancode": int(match.group(3), 16),
            "source": match.group(4),
        }
        for match in INPUT_RE.finditer(contents)
    ]


def write_command(control_fd: int, command: str) -> None:
    payload = (command.rstrip("\n") + "\n").encode("ascii")
    written = os.write(control_fd, payload)
    if written != len(payload):
        raise SystemExit(
            f"Short input FIFO write: expected {len(payload)}, wrote {written}"
        )


def write_ppm(source: Path, destination: Path) -> None:
    packed = source.read_bytes()
    if len(packed) != WIDTH * HEIGHT:
        raise SystemExit(
            f"Expected {WIDTH * HEIGHT} RGBA2222 bytes, got {len(packed)}"
        )
    rgb = bytearray(len(packed) * 3)
    for index, value in enumerate(packed):
        rgb[index * 3 + 0] = (value & 0x03) * 85
        rgb[index * 3 + 1] = ((value >> 2) & 0x03) * 85
        rgb[index * 3 + 2] = ((value >> 4) & 0x03) * 85
    destination.write_bytes(
        f"P6\n{WIDTH} {HEIGHT}\n255\n".encode("ascii") + rgb
    )


def stop_process(process: subprocess.Popen[bytes]) -> str:
    if process.poll() is not None:
        return "already-exited"

    # --debugger owns SIGINT and turns it into a CPU pause. Its existing
    # stdin "exit" command then requests orderly main-loop/VDP shutdown.
    os.kill(process.pid, signal.SIGINT)
    time.sleep(0.4)
    try:
        assert process.stdin is not None
        process.stdin.write(b"exit\n")
        process.stdin.flush()
        process.wait(timeout=5)
        return "debugger-exit"
    except (BrokenPipeError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
            return "sigterm"
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return "sigkill"


def find_failures(contents: str) -> list[str]:
    return [marker for marker in FATAL_MARKERS if marker in contents]


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if arguments.trigger_sequence < 0:
        raise SystemExit("--trigger-sequence must be non-negative")
    if arguments.chase_sequence <= arguments.trigger_sequence:
        raise SystemExit("--chase-sequence must follow --trigger-sequence")

    emulator = require_file(FAB_BINARY, "Fab executable")
    mos = require_file(MOS_BINARY, "MOS image")
    real_vdp = require_file(arguments.vdp_module, "diagnostic VDP module")
    program = require_file(PROGRAM, "streamed KOAK fixture")
    proxy_source = require_file(PROXY_SOURCE, "input proxy source")
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)

    proxy = output / "vdp_input_trace_proxy.so"
    exports = build_proxy(proxy_source, proxy)
    log_path = output / "emulator.log"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /flight\r\n"
        b"load P3DFSIM.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)

    trigger_sequence = arguments.trigger_sequence
    chase_sequence = arguments.chase_sequence
    dump_sequences = (0, trigger_sequence, chase_sequence)
    dump_selectors = ",".join(
        f"{BITMAP_ID}:{sequence}" for sequence in dump_sequences
    )
    trigger_marker = (
        f"PINGO_DUMP seq={trigger_sequence} bmid={BITMAP_ID} status=ok"
    )
    chase_marker = (
        f"PINGO_DUMP seq={chase_sequence} bmid={BITMAP_ID} status=ok"
    )
    active_marker = "PINGO_STREAM object_active=ok oid=201 active=1"
    v_down_marker = "action=down scancode=0x002a"
    v_up_marker = "action=up scancode=0x002a"
    escape_down_marker = "action=down scancode=0x0076"
    escape_up_marker = "action=up scancode=0x0076"
    shutdown_method = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="pingo-input-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="pingo-input-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="pingo-input-fifo-") as fifo_name,
    ):
        sd_root = Path(sd_name)
        shutil.copytree(FIXTURE, sd_root / "flight")
        (sd_root / "autoexec.txt").write_bytes(autoexec)
        fifo_path = Path(fifo_name) / "keyboard.fifo"
        os.mkfifo(fifo_path, 0o600)

        # O_RDWR keeps the FIFO available before and between proxy reads while
        # this process uses the descriptor strictly as its command writer.
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
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            injected_v = False
            injected_escape = False
            deadline = time.monotonic() + arguments.timeout
            try:
                while time.monotonic() < deadline:
                    log.flush()
                    contents = log_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    failures = find_failures(contents)
                    if failures:
                        raise SystemExit(
                            "Headless input trace failed: "
                            + ", ".join(failures)
                            + f"; see {log_path}"
                        )
                    if not injected_v and trigger_marker in contents:
                        write_command(
                            control_fd,
                            f"tap 0x{SET2_CODES['V']:04x} 4",
                        )
                        injected_v = True
                    chase_ready = (
                        injected_v
                        and v_down_marker in contents
                        and v_up_marker in contents
                        and active_marker in contents
                        and chase_marker in contents
                    )
                    if chase_ready and not injected_escape:
                        write_command(
                            control_fd,
                            f"tap 0x{SET2_CODES['ESCAPE']:04x} 4",
                        )
                        injected_escape = True
                    if (
                        injected_escape
                        and escape_down_marker in contents
                        and escape_up_marker in contents
                    ):
                        break
                    if process.poll() is not None:
                        raise SystemExit(
                            "Emulator exited before the input trace completed "
                            f"(status {process.returncode}); see {log_path}"
                        )
                    time.sleep(0.02)
                else:
                    raise SystemExit(
                        "Timed out before deterministic input evidence was "
                        f"complete; see {log_path}"
                    )
            finally:
                shutdown_method = stop_process(process)
                os.close(control_fd)

    contents = log_path.read_text(encoding="utf-8", errors="replace")
    failures = find_failures(contents)
    if failures:
        raise SystemExit(
            "Final input trace log contains failures: "
            + ", ".join(failures)
            + f"; see {log_path}"
        )
    if process.returncode != 0:
        raise SystemExit(
            f"Emulator shutdown status was {process.returncode}; see {log_path}"
        )

    records = input_records(contents)
    expected_pairs = {
        ("down", SET2_CODES["V"]),
        ("up", SET2_CODES["V"]),
        ("down", SET2_CODES["ESCAPE"]),
        ("up", SET2_CODES["ESCAPE"]),
    }
    actual_pairs = {
        (str(record["action"]), int(record["scancode"]))
        for record in records
    }
    missing_pairs = sorted(expected_pairs - actual_pairs)
    if missing_pairs:
        raise SystemExit(f"Input proxy omitted expected events: {missing_pairs}")
    if active_marker not in contents:
        raise SystemExit("V make event did not activate exterior object 201")

    frames = []
    for sequence in dump_sequences:
        raw = output / f"pingo-{BITMAP_ID}-{sequence}.rgba2"
        depth = output / f"pingo-{BITMAP_ID}-{sequence}.z32le"
        require_file(raw, f"RGBA2222 render sequence {sequence}")
        require_file(depth, f"depth render sequence {sequence}")
        ppm = output / f"pingo-{BITMAP_ID}-{sequence}.ppm"
        write_ppm(raw, ppm)
        frames.append(
            {
                "sequence": sequence,
                "rgba2_sha256": sha256(raw),
                "depth_sha256": sha256(depth),
                "ppm_sha256": sha256(ppm),
            }
        )
    trigger_hash = frames[1]["rgba2_sha256"]
    chase_hash = frames[2]["rgba2_sha256"]
    if trigger_hash == chase_hash:
        raise SystemExit("Cockpit trigger and chase frames are byte-identical")

    report = {
        "schema": "pingo-terrain-headless-input-trace-v1",
        "mechanism": "vblank-drained FIFO through sendPS2KbEventToFabgl",
        "headless": {"video": "dummy", "audio": "dummy", "renderer": "sw"},
        "program": {"path": str(program), "sha256": sha256(program)},
        "real_vdp": {"path": str(real_vdp), "sha256": sha256(real_vdp)},
        "proxy": {
            "path": str(proxy),
            "sha256": sha256(proxy),
            "source": str(proxy_source),
            "source_sha256": sha256(proxy_source),
            "required_exports": sorted(REQUIRED_PROXY_EXPORTS),
            "exports": sorted(exports),
        },
        "set2_codes": SET2_CODES,
        "events": records,
        "view_activation_marker": active_marker,
        "view_activation_observed": True,
        "frames": frames,
        "cockpit_chase_distinct": True,
        "shutdown": shutdown_method,
        "emulator_exit_status": process.returncode,
        "emulator_log": {
            "path": str(log_path),
            "sha256": sha256(log_path),
        },
    }
    report_path = output / "input-trace-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Headless KOAK input trace passed: {report_path}")
    print(
        f"V toggled object 201; cockpit {trigger_sequence} "
        f"{trigger_hash[:16]} != chase {chase_sequence} {chase_hash[:16]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

