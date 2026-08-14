#!/usr/bin/env python3
"""Capture Berkeley's first patterned frame with the diagnostic native VDP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
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
    / "mystuff/agon-vdp/video/build/userspace-terrain-diagnostics/vdp_combined.so"
)
FIXTURE = ROOT / "fixtures/berkeley-flight-triangular-dither/tgt"
PROGRAM = FIXTURE / "berkeley-flight-triangular-dither.bin"
BITMAP_ID = 257
SEQUENCE = 0
WIDTH = 320
HEIGHT = 240


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module", type=Path, default=DEFAULT_VDP,
        help=f"diagnostic native VDP module (default: {DEFAULT_VDP})",
    )
    parser.add_argument(
        "--output", type=Path, required=True,
        help="new directory in which to retain the raw capture and evidence",
    )
    parser.add_argument(
        "--timeout", type=float, default=45.0,
        help="capture deadline in seconds (default: 45)",
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


def stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    emulator = require_file(FAB_BINARY, "Fab executable")
    mos = require_file(MOS_BINARY, "MOS image")
    vdp = require_file(arguments.vdp_module, "diagnostic VDP module")
    program = require_file(PROGRAM, "Berkeley fixture")
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output directory: {output}")
    output.mkdir(parents=True)

    log_path = output / "emulator.log"
    raw_path = output / f"pingo-{BITMAP_ID}-{SEQUENCE}.rgba2"
    depth_path = output / f"pingo-{BITMAP_ID}-{SEQUENCE}.z32le"
    expected_marker = (
        f"PINGO_DUMP seq={SEQUENCE} bmid={BITMAP_ID} status=ok"
    )

    with (
        tempfile.TemporaryDirectory(prefix="pingo-terrain-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="pingo-terrain-run-") as run_name,
    ):
        sd_root = Path(sd_name)
        runtime = sd_root / "terrain"
        runtime.symlink_to(FIXTURE, target_is_directory=True)
        autoexec = (
            b"SET KEYBOARD 1\r\n"
            b"cd /terrain\r\n"
            b"load berkeley-flight-triangular-dither.bin\r\n"
            b"run\r\n"
        )
        (sd_root / "autoexec.txt").write_bytes(autoexec)
        (output / "autoexec.txt").write_bytes(autoexec)

        environment = os.environ.copy()
        environment.update(
            {
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
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
            "--vdp", str(vdp),
            "--sdcard", str(sd_root),
            "--verbose", "-z", "-u",
        ]
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
                    if expected_marker in log_path.read_text(
                        encoding="utf-8", errors="replace"
                    ):
                        break
                    returncode = process.poll()
                    if returncode is not None:
                        raise SystemExit(
                            "Emulator exited before the first patterned frame "
                            f"(status {returncode}); see {log_path}"
                        )
                    time.sleep(0.05)
                else:
                    raise SystemExit(
                        "Timed out before the first patterned frame; "
                        f"see {log_path}"
                    )
            finally:
                stop_process_group(process)

    if not raw_path.is_file() or not depth_path.is_file():
        raise SystemExit(f"Diagnostic VDP did not create both dumps; see {log_path}")
    if depth_path.stat().st_size != WIDTH * HEIGHT * 4:
        raise SystemExit(f"Unexpected depth-buffer size: {depth_path.stat().st_size}")
    ppm_path = output / f"pingo-{BITMAP_ID}-{SEQUENCE}.ppm"
    write_ppm(raw_path, ppm_path)
    report = {
        "schema": "pingo-terrain-capture-v1",
        "fixture": str(program),
        "fixture_sha256": sha256(program),
        "vdp_module": str(vdp),
        "vdp_module_sha256": sha256(vdp),
        "emulator": str(emulator),
        "emulator_sha256": sha256(emulator),
        "mos": str(mos),
        "mos_sha256": sha256(mos),
        "bitmap_id": BITMAP_ID,
        "sequence": SEQUENCE,
        "width": WIDTH,
        "height": HEIGHT,
        "rgba2_bytes": raw_path.stat().st_size,
        "rgba2_sha256": sha256(raw_path),
        "depth_bytes": depth_path.stat().st_size,
        "depth_sha256": sha256(depth_path),
        "log_sha256": sha256(log_path),
    }
    (output / "capture.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Captured {WIDTH}x{HEIGHT} patterned frame: {raw_path}\n"
        f"RGBA2222 SHA-256: {report['rgba2_sha256']}\n"
        f"Evidence: {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
