#!/usr/bin/env python3
"""Tee VDP debug serial traffic to the terminal and a persistent log."""

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import select
import struct
import sys
import termios
import time
import tty
from datetime import datetime
from pathlib import Path


DEFAULT_PORT = Path("/dev/ttyUSB0")
DEFAULT_BAUD = 115200
DEFAULT_RETRY_SECONDS = 1.0

BAUD_RATES = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
    230400: termios.B230400,
}


def status(message: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"\n[{stamp}] {message}", file=sys.stderr, flush=True)


def configure_port(fd: int, baud: int) -> None:
    speed = BAUD_RATES.get(baud)
    if speed is None:
        supported = ", ".join(str(value) for value in sorted(BAUD_RATES))
        raise ValueError(f"unsupported baud {baud}; choose one of: {supported}")

    attributes = termios.tcgetattr(fd)
    attributes[0] = 0
    attributes[1] = 0
    attributes[2] &= ~(
        termios.CSIZE
        | termios.PARENB
        | termios.CSTOPB
        | getattr(termios, "CRTSCTS", 0)
        | termios.HUPCL
    )
    attributes[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
    attributes[3] = 0
    attributes[4] = speed
    attributes[5] = speed
    attributes[6][termios.VMIN] = 0
    attributes[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attributes)


def open_port(port: Path, baud: int) -> int:
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        # Prevent a second listener or uploader from silently sharing the tty.
        fcntl.ioctl(fd, termios.TIOCEXCL)
        configure_port(fd, baud)
    except Exception:
        os.close(fd)
        raise
    return fd


def pulse_reset(fd: int) -> None:
    """Pulse ESP32 EN through the CP210x RTS line without closing the port."""
    dtr = struct.pack("I", termios.TIOCM_DTR)
    rts = struct.pack("I", termios.TIOCM_RTS)
    fcntl.ioctl(fd, termios.TIOCMBIC, dtr)
    fcntl.ioctl(fd, termios.TIOCMBIS, rts)
    time.sleep(0.1)
    fcntl.ioctl(fd, termios.TIOCMBIC, rts)


class Keyboard:
    def __init__(self) -> None:
        self.fd: int | None = None
        self.saved_attributes: list | None = None

    def __enter__(self) -> "Keyboard":
        if sys.stdin.isatty():
            self.fd = sys.stdin.fileno()
            self.saved_attributes = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            status("Keyboard control enabled: press R to reset, Ctrl+C to stop")
        else:
            status("Keyboard control unavailable because stdin is not a TTY")
        return self

    def __exit__(self, *_: object) -> None:
        if self.fd is not None and self.saved_attributes is not None:
            termios.tcsetattr(
                self.fd,
                termios.TCSADRAIN,
                self.saved_attributes,
            )


def listen(port: Path, baud: int, log_path: Path, retry_seconds: float) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status(f"Logging raw VDP traffic to {log_path}")

    fd: int | None = None
    with Keyboard() as keyboard, log_path.open("ab", buffering=0) as log_file:
        while True:
            if fd is None:
                try:
                    fd = open_port(port, baud)
                    status(f"Connected to {port} at {baud} baud")
                except (FileNotFoundError, PermissionError, OSError) as exc:
                    if isinstance(exc, OSError) and exc.errno not in {
                        errno.ENOENT,
                        errno.EACCES,
                        errno.EBUSY,
                        errno.ENXIO,
                        errno.EIO,
                    }:
                        raise
                    status(f"Waiting for {port}: {exc}")
                    time.sleep(retry_seconds)
                    continue

            try:
                inputs = [fd]
                if keyboard.fd is not None:
                    inputs.append(keyboard.fd)
                readable, _, exceptional = select.select(inputs, [], [fd], 1.0)
                if exceptional:
                    raise OSError(errno.EIO, "serial device reported an exception")
                if keyboard.fd is not None and keyboard.fd in readable:
                    key = os.read(keyboard.fd, 1)
                    if key.lower() == b"r":
                        status(f"Resetting VDP through {port}")
                        pulse_reset(fd)
                if fd in readable:
                    data = os.read(fd, 4096)
                    if not data:
                        raise OSError(errno.EIO, "serial device disconnected")
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                    log_file.write(data)
            except OSError as exc:
                status(f"Disconnected from {port}: {exc}")
                os.close(fd)
                fd = None
                time.sleep(retry_seconds)


def main() -> int:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=Path, default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(f"vdp-debug-{timestamp}.log"),
        help="raw append-only log path (default: timestamped file in cwd)",
    )
    parser.add_argument(
        "--retry-seconds",
        type=float,
        default=DEFAULT_RETRY_SECONDS,
        help="delay between reconnect attempts (default: 1.0)",
    )
    args = parser.parse_args()
    if args.retry_seconds <= 0:
        parser.error("--retry-seconds must be positive")

    try:
        listen(
            args.port.expanduser(),
            args.baud,
            args.log.expanduser(),
            args.retry_seconds,
        )
    except KeyboardInterrupt:
        status("Listener stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
