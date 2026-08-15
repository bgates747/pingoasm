#!/usr/bin/env python3
"""Live A/B profile accepted RST18 versus DATA-only UART0 THRE loading.

Each paired repeat starts fresh Fab processes with the exact pinned Console8
MOS.  Eleven debugger boundaries cover the five complete cold-load phases and
isolate the DATA sender itself for every one of the 227 publications.  The
candidate's zero and RST18-fallback labels are armed as forbidden breakpoints;
any hit fails the run instead of silently timing a different path.

The raw sender-return span is a non-drain-equivalent diagnostic: RST18 returns
after TEMT while the THRE sibling may return with UART bytes still in flight.
The enclosing upload span includes the unchanged consolidate RST18 and is the
first transmitter-completion-equivalent performance boundary.

This is exact-image emulator evidence only.  The candidate reads a private MOS
RAM byte and the old Console8 GPIO-PD3 CTS path, so it must not be run with any
other MOS image and is not qualified for physical deployment here.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
from typing import Mapping, Sequence

import build_regular_lod_uart_thre_sibling as sibling
import build_regular_lod_crc_register_sibling as crc_builder
import capture_regular_lod_manager_survey as regular_capture
import capture_terrain_manager_survey as survey
import profile_regular_lod_cold_load as cold
import profile_regular_lod_crc_register_sibling as crc_profile
import trace_koak_input as input_trace
import trace_koak_takeoff as debugger
import trace_regular_lod_staged_north_transitions as staged
from pingo_terrain.regular_lod_profile import (
    MeshReplaceRecord,
    ProfileEvidenceError,
    parse_mesh_replace_records,
    summarize_distribution,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD = sibling.DEFAULT_OUTPUT
DEFAULT_CRC_BUILD = crc_builder.DEFAULT_OUTPUT
DEFAULT_OUTPUT = ROOT / "build/evidence/regular-lod-uart-thre-sibling-profile-v3"
REPORT_NAME = "regular-lod-uart-thre-sibling-profile.json"
SCHEMA = "pingo-terrain-regular-lod-uart-thre-sibling-live-profile-v1"
EXPECTED_RECORDS = sibling.EXPECTED_RECORDS
PHASE_NAMES = cold.PHASE_NAMES
AUTOEXEC = b"SET KEYBOARD 1\r\ncd /survey\r\nload P3DRGL.BIN\r\nrun\r\n"


class UartThreProfileError(RuntimeError):
    """A build, live-state, timing, or semantic-equivalence gate failed."""


@dataclass(frozen=True, slots=True)
class UartLayout:
    phases: tuple[cold.PhaseSpan, ...]
    sender_call: int
    sender_post: int
    file_buffer: int
    forbidden: tuple[tuple[str, int], ...]
    sender_kind: str

    @property
    def events(self) -> tuple[tuple[str, int], ...]:
        by_name = {phase.name: phase for phase in self.phases}
        return (
            ("read_call", by_name["read_container_fatfs"].call),
            ("read_post", by_name["read_container_fatfs"].post_call),
            ("validate_call", by_name["validate_container"].call),
            ("validate_post", by_name["validate_container"].post_call),
            ("mirror_call", by_name["mirror_validated_z"].call),
            ("mirror_upload_shared", by_name["mirror_validated_z"].post_call),
            ("sender_call", self.sender_call),
            ("sender_post", self.sender_post),
            ("upload_post", by_name["upload_vdu_staging"].post_call),
            ("command_call", by_name["command50_enqueue"].call),
            ("command_post", by_name["command50_enqueue"].post_call),
        )

    @property
    def breakpoints(self) -> tuple[int, ...]:
        addresses = tuple(address for _name, address in self.events)
        if len(addresses) != len(set(addresses)):
            raise UartThreProfileError("UART profile boundaries are not unique")
        return addresses

    def as_dict(self) -> dict[str, object]:
        return {
            "sender_kind": self.sender_kind,
            "events": [
                {"name": name, "address": address}
                for name, address in self.events
            ],
            "sender_call": self.sender_call,
            "sender_post": self.sender_post,
            "file_buffer": self.file_buffer,
            "forbidden": [
                {"name": name, "address": address}
                for name, address in self.forbidden
            ],
        }


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument(
        "--crc-build",
        type=Path,
        default=DEFAULT_CRC_BUILD,
        help="CRC-register build containing the private historical CRC1 control",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--vdp-module", type=Path, default=survey.DEFAULT_VDP)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, *, key: str | None = None) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise UartThreProfileError(f"missing artifact: {resolved}")
    if key is None:
        try:
            key = str(resolved.relative_to(ROOT))
        except ValueError:
            key = resolved.name
    return {"key": key, "bytes": resolved.stat().st_size, "sha256": sha256(resolved)}


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UartThreProfileError(f"unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise UartThreProfileError(f"JSON root is not an object: {path}")
    return value


def validate_build(build: Path) -> tuple[Path, Path, dict[str, object]]:
    receipt_path = build / "BUILD.json"
    receipt = load_json(receipt_path)
    if receipt.get("schema") != sibling.SCHEMA or receipt.get("qualified") is not True:
        raise UartThreProfileError("UART sibling build receipt is not qualified")
    scope = receipt.get("scope")
    if not isinstance(scope, dict) or any(
        scope.get(name) is not False
        for name in (
            "accepted_loader_modified",
            "accepted_source_modified",
            "accepted_binary_modified",
            "accepted_sidecars_modified",
            "crc_sibling_modified",
            "launcher_modified",
            "docs_modified",
        )
    ):
        raise UartThreProfileError("UART sibling build scope changed")
    limitations = receipt.get("limitations")
    if not isinstance(limitations, dict) or (
        limitations.get("must_not_run_or_deploy_with_another_mos") is not True
        or limitations.get("exact_mos_required_sha256")
        != sibling.CONSOLE8_MOS_SHA256
        or limitations.get("physical_qualification_requires_exact_pinned_mos")
        is not True
    ):
        raise UartThreProfileError("UART sibling exact-MOS limitation changed")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        raise UartThreProfileError("UART sibling receipt omits artifacts")

    def checked(name: str, suffix: str) -> Path:
        entry = artifacts.get(name)
        path = build / f"{sibling.PROGRAM_STEM}.{suffix}"
        if not isinstance(entry, dict) or not path.is_file():
            raise UartThreProfileError(f"missing sibling artifact: {name}")
        if (
            entry.get("key") != f"artifacts/{path.name}"
            or entry.get("bytes") != path.stat().st_size
            or entry.get("sha256") != sha256(path)
        ):
            raise UartThreProfileError(f"sibling artifact receipt mismatch: {name}")
        return path

    program = checked("program", "bin")
    symbols = checked("symbols", "symbols")
    if (
        program.stat().st_size != 142_828
        or sha256(program)
        != "65843171996faa8916f17f7d05eeaabe328b292eca625f17025876f64bdeb7eb"
    ):
        raise UartThreProfileError("UART sibling program identity changed")
    patch = receipt.get("source_patch")
    if not isinstance(patch, dict) or (
        patch.get("canonical_block_sha256")
        != sibling.CANONICAL_UPLOAD_BLOCK_SHA256
        or patch.get("candidate_block_sha256")
        != sibling.CANDIDATE_UPLOAD_BLOCK_SHA256
        or patch.get("temporary_control_program_sha256")
        != sibling.ACCEPTED_PROGRAM_SHA256
        or patch.get("temporary_control_program_exact") is not True
        or patch.get("candidate_independent_builds") != 2
    ):
        raise UartThreProfileError("UART sibling source/control binding changed")
    host = receipt.get("host_upload_transcripts")
    if not isinstance(host, dict) or (
        host.get("coverage_digest_sha256")
        != sibling.EXPECTED_UPLOAD_COVERAGE_DIGEST_SHA256
        or host.get("all_accepted_candidate_transcripts_byte_exact") is not True
        or host.get("all_return_register_contracts_exact") is not True
    ):
        raise UartThreProfileError("UART sibling host transcript binding changed")
    return program, symbols, receipt


def _offsets(image: bytes, needle: bytes) -> list[int]:
    result = []
    cursor = 0
    while True:
        offset = image.find(needle, cursor)
        if offset < 0:
            return result
        result.append(offset)
        cursor = offset + 1


def resolve_layout(
    program: Path,
    symbols_path: Path,
    *,
    candidate: bool,
) -> UartLayout:
    symbols = staged.parse_symbols(symbols_path)
    phases = cold.resolve_phase_spans(program, symbols)
    by_name = {phase.name: phase for phase in phases}
    required = {"p3dm_upload_data", "pingo_replace_mesh_from_buffer", "p3dm_file_buffer"}
    if candidate:
        required.update(
            {
                "p3dm_uart0_write_block_thre",
                "p3dm_uart0_write_block_zero",
                "p3dm_uart0_write_block_fallback",
            }
        )
    missing = sorted(required - symbols.keys())
    if missing:
        raise UartThreProfileError(f"profile symbols omit: {missing}")
    image = program.read_bytes()
    upload_start = symbols["p3dm_upload_data"]
    upload_end = symbols["pingo_replace_mesh_from_buffer"]
    if not (
        sibling.PROGRAM_LOAD_ADDRESS <= upload_start < upload_end
        <= sibling.PROGRAM_LOAD_ADDRESS + len(image)
    ):
        raise UartThreProfileError("upload body escapes program")
    body = image[
        upload_start - sibling.PROGRAM_LOAD_ADDRESS :
        upload_end - sibling.PROGRAM_LOAD_ADDRESS
    ]
    if candidate:
        target = symbols["p3dm_uart0_write_block_thre"]
        encoded = bytes((0xCD,)) + target.to_bytes(3, "little")
        offsets = _offsets(body, encoded)
        if len(offsets) != 1:
            raise UartThreProfileError(
                f"candidate upload has {len(offsets)} calls to direct sender"
            )
        sender_call = upload_start + offsets[0]
        sender_post = sender_call + 4
        forbidden = (
            ("zero_count", symbols["p3dm_uart0_write_block_zero"]),
            ("rst18_fallback", symbols["p3dm_uart0_write_block_fallback"]),
        )
        sender_kind = "application-local PD3-CTS plus UART0-THRE"
    else:
        offsets = _offsets(body, bytes.fromhex("5bdf"))
        if len(offsets) != 3:
            raise UartThreProfileError(
                f"accepted upload has {len(offsets)} RST18 instructions, expected 3"
            )
        sender_call = upload_start + offsets[2]
        sender_post = sender_call + 2
        forbidden = ()
        sender_kind = "Console8 RST18 counted DATA write"
    layout = UartLayout(
        phases=phases,
        sender_call=sender_call,
        sender_post=sender_post,
        file_buffer=symbols["p3dm_file_buffer"],
        forbidden=forbidden,
        sender_kind=sender_kind,
    )
    layout.breakpoints
    upload = by_name["upload_vdu_staging"]
    if not upload_start <= sender_call < sender_post <= upload_end:
        raise UartThreProfileError("DATA sender escaped p3dm_upload_data")
    if not upload.call < upload.post_call:
        raise UartThreProfileError("top-level upload call/post order changed")
    if by_name["mirror_validated_z"].post_call != upload.call:
        raise UartThreProfileError("mirror/upload shared boundary changed")
    if set(layout.breakpoints) & {address for _name, address in forbidden}:
        raise UartThreProfileError("forbidden candidate label aliases a boundary")
    return layout


class LiveBoundaryProfiler:
    """Drive exact nested boundaries and fail immediately on forbidden paths."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        layout: UartLayout,
        expected_records: int,
    ) -> None:
        self.process = process
        self.layout = layout
        self.events = layout.events
        self.expected_records = expected_records
        self.cursor = 0
        self.event_index = 0
        self.record_index = 0
        self.waiting = "pause"
        self.complete = False
        self.cycle_states = 0

    def service(self, contents: str) -> None:
        if self.complete:
            return
        expected_name, expected_address = self.events[self.event_index]
        if self.waiting == "pause":
            pause = staged.SELECTOR_PAUSE_RE.search(contents, self.cursor)
            if pause is None:
                return
            candidates = []
            for name, address in (*self.events, *self.layout.forbidden):
                marker = contents.find(f"* {address:06x}:", pause.end())
                if marker >= 0:
                    candidates.append((marker, name, address))
            if not candidates:
                return
            marker, name, address = min(candidates)
            forbidden = dict(self.layout.forbidden)
            if name in forbidden and forbidden[name] == address:
                raise UartThreProfileError(
                    f"candidate reached forbidden {name} at 0x{address:06x} "
                    f"during record {self.record_index}"
                )
            if address != expected_address or name != expected_name:
                raise UartThreProfileError(
                    f"boundary order changed at record {self.record_index}: "
                    f"{name}=0x{address:06x} != "
                    f"{expected_name}=0x{expected_address:06x}"
                )
            self.cursor = marker + len(f"* {address:06x}:")
            self.waiting = "state"
            debugger.write_debugger(self.process, "state")
            return
        cycles = staged.SELECTOR_CYCLES_RE.search(contents, self.cursor)
        if cycles is None:
            return
        self.cycle_states += 1
        self.cursor = cycles.end()
        self.waiting = "pause"
        self.event_index += 1
        if self.event_index == len(self.events):
            self.event_index = 0
            self.record_index += 1
        if self.record_index == self.expected_records:
            for address in (*self.layout.breakpoints, *(a for _n, a in self.layout.forbidden)):
                debugger.write_debugger(self.process, f"delete 0x{address:x}")
            self.complete = True
        debugger.write_debugger(self.process, "continue")

    def require_complete(self) -> dict[str, object]:
        if (
            not self.complete
            or self.record_index != self.expected_records
            or self.event_index != 0
            or self.waiting != "pause"
            or self.cycle_states != self.expected_records * len(self.events)
        ):
            raise UartThreProfileError(
                f"incomplete UART profile: records={self.record_index}/"
                f"{self.expected_records}, event={self.event_index}, "
                f"states={self.cycle_states}"
            )
        return {
            "record_count": self.record_index,
            "event_count_per_record": len(self.events),
            "cycle_state_count": self.cycle_states,
            "forbidden_breakpoint_hits": 0,
        }


STATE_RE = re.compile(r"\*\s+([0-9A-Fa-f]{6}):")
CYCLES_RE = re.compile(r"Cycles since last break:\s*(\d+)")
REGISTER_RE = re.compile(
    r"\bAF:([0-9A-Fa-f]{4})\s+BC:([0-9A-Fa-f]{6})\s+"
    r"DE:([0-9A-Fa-f]{6})\s+HL:([0-9A-Fa-f]{6})\s+"
    r"SPS:([0-9A-Fa-f]{4})\s+SPL:([0-9A-Fa-f]{6})\s+"
    r"IX:([0-9A-Fa-f]{6})\s+IY:([0-9A-Fa-f]{6})\s+"
    r"IR:([0-9A-Fa-f]{4})\s+MB:([0-9A-Fa-f]{2})\s+"
    r"ADL:([01])\s+MADL:([01])\s+IFF1:([01])\b"
)


def parse_boundary_states(
    contents: str,
    layout: UartLayout,
    expected_records: int,
) -> list[dict[str, int | str]]:
    targets = set(layout.breakpoints)
    pending: tuple[int, int, str] | None = None
    states: list[tuple[int, int, str, int]] = []
    plain = debugger.ANSI_RE.sub("", contents)
    for line_number, line in enumerate(plain.splitlines(), 1):
        matches = tuple(STATE_RE.finditer(line))
        if len(matches) > 1:
            raise UartThreProfileError(f"debugger line {line_number} has multiple states")
        if matches:
            address = int(matches[0].group(1), 16)
            if pending is not None:
                pending_address, _pending_line, _pending_text = pending
                if address != pending_address:
                    raise UartThreProfileError("debugger state lacks cycle report")
                pending = (address, line_number, line)
            else:
                pending = (address, line_number, line) if address in targets else None
        cycle_matches = tuple(CYCLES_RE.finditer(line))
        if len(cycle_matches) > 1:
            raise UartThreProfileError("debugger line has multiple cycle reports")
        if cycle_matches and pending is not None:
            address, state_line, state_text = pending
            states.append((address, state_line, state_text, int(cycle_matches[0].group(1))))
            pending = None
    if pending is not None:
        raise UartThreProfileError("final debugger state lacks cycle report")
    expected = layout.events * expected_records
    if len(states) != len(expected):
        raise UartThreProfileError(
            f"parsed {len(states)} boundary states, expected {len(expected)}"
        )
    result = []
    for index, ((address, line_number, text, cycles), (name, wanted)) in enumerate(
        zip(states, expected)
    ):
        if address != wanted:
            raise UartThreProfileError(
                f"parsed boundary {index} changed: {address:06x} != {wanted:06x}"
            )
        registers = REGISTER_RE.search(text)
        if registers is None:
            raise UartThreProfileError(f"full register state missing at line {line_number}")
        result.append(
            {
                "record": index // len(layout.events),
                "event": name,
                "address": address,
                "line_number": line_number,
                "cycles_since_previous_boundary": cycles,
                "af": int(registers.group(1), 16),
                "bc": int(registers.group(2), 16),
                "de": int(registers.group(3), 16),
                "hl": int(registers.group(4), 16),
                "sps": int(registers.group(5), 16),
                "spl": int(registers.group(6), 16),
                "ix": int(registers.group(7), 16),
                "iy": int(registers.group(8), 16),
                "ir": int(registers.group(9), 16),
                "mb": int(registers.group(10), 16),
                "adl": int(registers.group(11), 10),
                "madl": int(registers.group(12), 10),
                "iff1": int(registers.group(13), 10),
            }
        )
    return result


def publication_semantics(records: Sequence[MeshReplaceRecord]) -> list[tuple[int, ...]]:
    return [
        (
            record.stage_buffer_id,
            record.mesh_id,
            record.data_bytes,
            record.vertices,
            record.position_indices,
            record.texture_coordinates,
            record.texture_indices,
        )
        for record in records
    ]


def reconstruct_records(
    states: Sequence[Mapping[str, int | str]],
    layout: UartLayout,
    expected: Sequence[Mapping[str, object]],
    publications: Sequence[MeshReplaceRecord],
) -> tuple[list[dict[str, object]], dict[str, list[int]]]:
    event_count = len(layout.events)
    if len(states) != len(expected) * event_count:
        raise UartThreProfileError("state record count changed")
    phase_cycles = {name: [] for name in PHASE_NAMES}
    result = []
    for order, record in enumerate(expected):
        chunk = states[order * event_count : (order + 1) * event_count]
        by_name = {str(item["event"]): item for item in chunk}
        if len(by_name) != event_count:
            raise UartThreProfileError(f"record {order} boundary names changed")
        upload_segments = {
            "pre_data_sender": int(by_name["sender_call"]["cycles_since_previous_boundary"]),
            "data_sender": int(by_name["sender_post"]["cycles_since_previous_boundary"]),
            "post_data_sender": int(by_name["upload_post"]["cycles_since_previous_boundary"]),
        }
        phases = {
            "read_container_fatfs": int(by_name["read_post"]["cycles_since_previous_boundary"]),
            "validate_container": int(by_name["validate_post"]["cycles_since_previous_boundary"]),
            "mirror_validated_z": int(
                by_name["mirror_upload_shared"]["cycles_since_previous_boundary"]
            ),
            "upload_vdu_staging": sum(upload_segments.values()),
            "command50_enqueue": int(by_name["command_post"]["cycles_since_previous_boundary"]),
        }
        for name in PHASE_NAMES:
            phase_cycles[name].append(phases[name])

        data_bytes = int(record["data_bytes"])
        expected_start = layout.file_buffer + sibling.P3DM_DATA_OFFSET
        expected_end = expected_start + data_bytes
        expected_a_e = data_bytes >> 8
        entry = by_name["sender_call"]
        post = by_name["sender_post"]
        if (
            int(entry["hl"]) != expected_start
            or int(entry["bc"]) != data_bytes
            or int(entry["af"]) >> 8 != expected_a_e
        ):
            raise UartThreProfileError(f"record {order} sender entry contract changed")
        if (
            int(post["hl"]) != expected_end
            or int(post["bc"]) != 0
            or int(post["af"]) != 0x0044
            or int(post["de"]) & 0xFF != expected_a_e
        ):
            raise UartThreProfileError(f"record {order} sender return contract changed")
        for register in ("spl", "sps", "ix", "iy"):
            if int(entry[register]) != int(post[register]):
                raise UartThreProfileError(
                    f"record {order} sender changed {register.upper()}"
                )
        if int(entry["de"]) >> 8 != int(post["de"]) >> 8:
            raise UartThreProfileError(f"record {order} sender changed D/DEU")
        if (
            int(entry["adl"]) != 1
            or int(post["adl"]) != 1
            or int(entry["madl"]) != 1
            or int(post["madl"]) != 1
        ):
            raise UartThreProfileError(f"record {order} sender left ADL mode")
        if int(entry["mb"]) != 0 or int(post["mb"]) != 0:
            raise UartThreProfileError(f"record {order} sender MBASE is not zero")
        if int(entry["ir"]) >> 8 != int(post["ir"]) >> 8:
            raise UartThreProfileError(f"record {order} sender changed I")
        if int(entry["iff1"]) != int(post["iff1"]):
            raise UartThreProfileError(f"record {order} sender changed IFF1")
        result.append(
            {
                "order": order,
                "path": record["path"],
                "file_sha256": record["sha256"],
                "data_bytes": data_bytes,
                "sender_guest_cycles": upload_segments["data_sender"],
                "sender_entry": {
                    "A": int(entry["af"]) >> 8,
                    "BC": int(entry["bc"]),
                    "DE": int(entry["de"]),
                    "HL_from_file_buffer": int(entry["hl"]) - layout.file_buffer,
                    "IX_from_file_buffer": int(entry["ix"]) - layout.file_buffer,
                    "IY": int(entry["iy"]),
                    "SPS": int(entry["sps"]),
                    "SPL": int(entry["spl"]),
                    "I": int(entry["ir"]) >> 8,
                    "MB": int(entry["mb"]),
                    "ADL": int(entry["adl"]),
                    "MADL": int(entry["madl"]),
                    "IFF1": int(entry["iff1"]),
                },
                "sender_return": {
                    "AF": int(post["af"]),
                    "BC": int(post["bc"]),
                    "DE": int(post["de"]),
                    "HL_from_file_buffer": int(post["hl"]) - layout.file_buffer,
                    "IX_from_file_buffer": int(post["ix"]) - layout.file_buffer,
                    "IY": int(post["iy"]),
                    "SPS": int(post["sps"]),
                    "SPL": int(post["spl"]),
                    "I": int(post["ir"]) >> 8,
                    "MB": int(post["mb"]),
                    "ADL": int(post["adl"]),
                    "MADL": int(post["madl"]),
                    "IFF1": int(post["iff1"]),
                },
                "upload_guest_cycles": upload_segments,
                "phase_guest_cycles": phases,
                "measured_phase_guest_cycles_total": sum(phases.values()),
            }
        )
    cold.validate_record_bindings(expected, publications, phase_cycles)
    return result, phase_cycles


def shutdown(
    process: subprocess.Popen[bytes], log_path: Path, deadline: float
) -> str:
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    pause_count = debugger.ANSI_RE.sub("", contents).count("CPU paused")
    os.kill(process.pid, signal.SIGINT)
    staged.wait_for_log(
        log_path,
        process,
        deadline,
        lambda value: debugger.ANSI_RE.sub("", value).count("CPU paused") > pause_count,
        "final UART-profile debugger pause",
    )
    debugger.write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise UartThreProfileError("debugger did not exit") from error
    if process.returncode != 0:
        raise UartThreProfileError(f"debugger shutdown returned {process.returncode}")
    return log_path.read_text(encoding="utf-8", errors="replace")


def emulator_command(
    sd_root: Path,
    vdp: Path,
    layout: UartLayout,
) -> list[str]:
    emulator = staged.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = staged.require_file(input_trace.MOS_BINARY, "MOS image")
    if sha256(mos) != sibling.CONSOLE8_MOS_SHA256:
        raise UartThreProfileError("live MOS is not the exact pinned Console8 image")
    command = [
        str(emulator),
        "--renderer", "sw",
        "--firmware", "console8",
        "--mos", str(mos),
        "--vdp", str(vdp),
        "--sdcard", str(sd_root),
        "--verbose",
        "--debugger",
        "-z",
        "-u",
    ]
    for address in (*layout.breakpoints, *(a for _n, a in layout.forbidden)):
        command.extend(("--breakpoint", f"0x{address:x}"))
    return command


def emulator_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
    local_sdl = Path.home() / ".local/lib"
    old = environment.get("LD_LIBRARY_PATH")
    environment["LD_LIBRARY_PATH"] = str(local_sdl) if not old else f"{local_sdl}:{old}"
    return environment


def run_positive(
    *,
    variant: str,
    repeat: int,
    program: Path,
    symbols_path: Path,
    candidate: bool,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    layout = resolve_layout(program, symbols_path, candidate=candidate)
    expected = regular_capture.initial_records()
    run_output = output / f"{variant}-repeat-{repeat + 1}"
    run_output.mkdir()
    program_copy = run_output / f"{variant}.profiled.bin"
    symbols_copy = run_output / f"{variant}.profiled.symbols"
    shutil.copyfile(program, program_copy)
    shutil.copyfile(symbols_path, symbols_copy)
    (run_output / "autoexec.txt").write_bytes(AUTOEXEC)
    log_path = run_output / "emulator.log"
    profiler: LiveBoundaryProfiler | None = None
    process: subprocess.Popen[bytes] | None = None
    deadline = time.monotonic() + timeout
    with (
        tempfile.TemporaryDirectory(prefix=f"uart-{variant}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"uart-{variant}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        staged.stage_fixture(sd_root, program_copy)
        (sd_root / "autoexec.txt").write_bytes(AUTOEXEC)
        command = emulator_command(sd_root, vdp, layout)
        (run_output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "variant": variant,
                    "repeat": repeat + 1,
                    "program": artifact(program_copy),
                    "symbols": artifact(symbols_copy),
                    "layout": layout.as_dict(),
                    "expected_records": EXPECTED_RECORDS,
                    "exact_mos_required_sha256": sibling.CONSOLE8_MOS_SHA256,
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
                    cwd=cwd_name,
                    env=emulator_environment(),
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                profiler = LiveBoundaryProfiler(process, layout, EXPECTED_RECORDS)
                staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: staged.COLD_RENDER_MARKER in value,
                    f"{variant} repeat {repeat + 1} complete cold fill",
                    service=profiler.service,
                )
                profiler.require_complete()
                shutdown(process, log_path, deadline)
        finally:
            if process is not None and process.poll() is None:
                input_trace.stop_process(process)
    assert process is not None and profiler is not None
    live = profiler.require_complete()
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    states = parse_boundary_states(contents, layout, EXPECTED_RECORDS)
    cold_endpoint = staged.validate_cold_endpoint(contents)
    publications = parse_mesh_replace_records(contents)
    records, phase_cycles = reconstruct_records(
        states, layout, expected, publications
    )
    if process.returncode != 0:
        raise UartThreProfileError(f"{variant} emulator returned {process.returncode}")
    phases = {
        name: {
            "cycles": phase_cycles[name],
            "summary": summarize_distribution(phase_cycles[name]).as_dict(),
        }
        for name in PHASE_NAMES
    }
    sender_cycles = [int(record["sender_guest_cycles"]) for record in records]
    pre_cycles = [
        int(record["upload_guest_cycles"]["pre_data_sender"]) for record in records
    ]
    post_cycles = [
        int(record["upload_guest_cycles"]["post_data_sender"]) for record in records
    ]
    totals = [int(record["measured_phase_guest_cycles_total"]) for record in records]
    return {
        "variant": variant,
        "repeat": repeat + 1,
        "fresh_process": True,
        "program": artifact(program_copy),
        "symbols": artifact(symbols_copy),
        "layout": layout.as_dict(),
        "live": live,
        "cold_endpoint": cold_endpoint,
        "publication_semantics": publication_semantics(publications),
        "phases": phases,
        "upload_segments": {
            "pre_data_sender": {
                "cycles": pre_cycles,
                "summary": summarize_distribution(pre_cycles).as_dict(),
            },
            "data_sender": {
                "cycles": sender_cycles,
                "summary": summarize_distribution(sender_cycles).as_dict(),
            },
            "post_data_sender": {
                "cycles": post_cycles,
                "summary": summarize_distribution(post_cycles).as_dict(),
            },
        },
        "measured_phase_guest_cycles_total": {
            "cycles": totals,
            "summary": summarize_distribution(totals).as_dict(),
            "aggregate": sum(totals),
        },
        "records": records,
        "binding": {
            "manifest_records": EXPECTED_RECORDS,
            "vdp_publications": len(publications),
            "sender_entry_and_return_live_scope_exact": True,
            "candidate_forbidden_path_hits": 0 if candidate else None,
            "exact_mos_image": True,
        },
        "log": artifact(log_path),
        "emulator_exit_status": process.returncode,
    }


def assert_semantic_equivalence(
    accepted: Mapping[str, object],
    candidate: Mapping[str, object],
) -> None:
    for name in ("cold_endpoint", "publication_semantics"):
        if accepted.get(name) != candidate.get(name):
            raise UartThreProfileError(f"accepted/candidate {name} differs")
    left_records = accepted.get("records")
    right_records = candidate.get("records")
    if not isinstance(left_records, list) or not isinstance(right_records, list):
        raise UartThreProfileError("run records are missing")
    if len(left_records) != EXPECTED_RECORDS or len(right_records) != EXPECTED_RECORDS:
        raise UartThreProfileError("run record counts differ")
    stable_fields = ("order", "path", "file_sha256", "data_bytes")
    stable_entry = (
        "A", "BC", "DE", "HL_from_file_buffer", "IX_from_file_buffer",
        "IY", "SPS", "SPL", "I", "MB", "ADL", "MADL", "IFF1",
    )
    stable_return = (
        "AF", "BC", "DE", "HL_from_file_buffer", "IX_from_file_buffer",
        "IY", "SPS", "SPL", "I", "MB", "ADL", "MADL", "IFF1",
    )
    for order, (left, right) in enumerate(zip(left_records, right_records)):
        if any(left.get(field) != right.get(field) for field in stable_fields):
            raise UartThreProfileError(f"semantic record identity differs at {order}")
        for group, fields in (("sender_entry", stable_entry), ("sender_return", stable_return)):
            left_group = left.get(group)
            right_group = right.get(group)
            if not isinstance(left_group, Mapping) or not isinstance(right_group, Mapping):
                raise UartThreProfileError(f"semantic {group} missing at {order}")
            if any(left_group.get(field) != right_group.get(field) for field in fields):
                raise UartThreProfileError(f"semantic {group} differs at {order}")


def run_aggregate(run: Mapping[str, object], path: Sequence[str]) -> int:
    value: object = run
    for name in path:
        if not isinstance(value, Mapping):
            raise UartThreProfileError(f"run aggregate path failed: {path}")
        value = value.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise UartThreProfileError(f"run aggregate is not an integer: {path}")
    return value


def comparison(runs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    accepted = [run for run in runs if run.get("variant") == "accepted-rst18"]
    candidate = [run for run in runs if run.get("variant") == "uart-thre"]
    if len(accepted) != len(candidate) or not accepted:
        raise UartThreProfileError("paired repeat topology changed")
    metrics = {
        "data_sender": {
            "path": ("upload_segments", "data_sender", "summary", "total"),
            "transmitter_completion_equivalent": False,
            "interpretation": (
                "diagnostic sender-return latency only; accepted TEMT return and "
                "candidate THRE return leave different transmitter states"
            ),
        },
        "upload_vdu_staging": {
            "path": ("phases", "upload_vdu_staging", "summary", "total"),
            "transmitter_completion_equivalent": True,
            "interpretation": (
                "includes unchanged consolidate RST18, which TEMT-drains prior DATA"
            ),
        },
        "complete_measured_cold_phases": {
            "path": ("measured_phase_guest_cycles_total", "aggregate"),
            "transmitter_completion_equivalent": True,
            "interpretation": "sum of all five complete cold-load phases",
        },
    }
    result: dict[str, object] = {}
    for name, spec in metrics.items():
        path = spec["path"]
        control = [run_aggregate(run, path) for run in accepted]
        changed = [run_aggregate(run, path) for run in candidate]
        pairs = []
        for repeat, (before, after) in enumerate(zip(control, changed), 1):
            pairs.append(
                {
                    "repeat": repeat,
                    "accepted_cycles": before,
                    "candidate_cycles": after,
                    "delta_cycles": after - before,
                    "candidate_vs_accepted_percent": (after - before) * 100.0 / before,
                }
            )
        result[name] = {
            "transmitter_completion_equivalent": spec[
                "transmitter_completion_equivalent"
            ],
            "interpretation": spec["interpretation"],
            "accepted_aggregate_cycles": control,
            "candidate_aggregate_cycles": changed,
            "accepted_repeat_summary": summarize_distribution(control).as_dict(),
            "candidate_repeat_summary": summarize_distribution(changed).as_dict(),
            "paired": pairs,
        }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    if args.repeats <= 0 or args.timeout <= 0:
        raise UartThreProfileError("--repeats and --timeout must be positive")
    build = args.build.expanduser().resolve()
    crc_build = args.crc_build.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise UartThreProfileError(f"refusing to replace existing output: {output}")
    program, symbols, receipt = validate_build(build)
    control_program, control_listing, control_symbols = (
        crc_profile.validate_legacy_control(crc_build)
    )
    sibling.require_all_inputs()
    if sha256(input_trace.MOS_BINARY) != sibling.CONSOLE8_MOS_SHA256:
        raise UartThreProfileError("emulator MOS identity differs from build contract")
    vdp = staged.require_file(args.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    output.mkdir(parents=True)
    runs: list[dict[str, object]] = []
    for repeat in range(args.repeats):
        accepted = run_positive(
            variant="accepted-rst18",
            repeat=repeat,
            program=control_program,
            symbols_path=control_symbols,
            candidate=False,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        candidate_run = run_positive(
            variant="uart-thre",
            repeat=repeat,
            program=program,
            symbols_path=symbols,
            candidate=True,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        assert_semantic_equivalence(accepted, candidate_run)
        runs.extend((accepted, candidate_run))
    sibling.require_all_inputs()
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "fresh_process_per_run": True,
            "repeat_count_per_variant": args.repeats,
            "complete_cold_fill_records_per_run": EXPECTED_RECORDS,
            "full_measured_phases": list(PHASE_NAMES),
            "nested_upload_segments": [
                "pre_data_sender", "data_sender", "post_data_sender"
            ],
            "measurement": "paused-debugger-boundary-to-boundary guest cycles",
            "render_timing_excluded": True,
            "host_wall_time_excluded": True,
            "physical_sd_latency_excluded": True,
            "hardware_timing_excluded": True,
            "timing_repeatability": (
                "not claimed by the default single exhaustive pair; additional "
                "fresh pairs remain a follow-up"
            ),
            "exact_image_emulator_evidence_only": True,
            "must_not_run_or_deploy_with_another_mos": True,
        },
        "identity": {
            "build_receipt": artifact(build / "BUILD.json"),
            "crc_build_receipt": artifact(crc_build / "BUILD.json"),
            "historical_crc1_program": artifact(control_program),
            "historical_crc1_listing": artifact(control_listing),
            "historical_crc1_symbols": artifact(control_symbols),
            "candidate_program": artifact(program),
            "candidate_symbols": artifact(symbols),
            "manager_manifest": artifact(regular_capture.MANIFEST),
            "world_manifest": artifact(regular_capture.WORLD),
            "emulator": artifact(input_trace.FAB_BINARY),
            "mos": artifact(input_trace.MOS_BINARY),
            "vdp": artifact(vdp),
            "source_patch": receipt["source_patch"],
            "host_upload_transcripts": {
                "coverage_digest_sha256": receipt["host_upload_transcripts"][
                    "coverage_digest_sha256"
                ],
                "concatenated_transcript_sha256": receipt[
                    "host_upload_transcripts"
                ]["concatenated_transcript_sha256"],
            },
        },
        "semantic_equivalence": {
            "all_repeats_exact": True,
            "cold_endpoint_exact": True,
            "publication_order_and_shapes_exact": True,
            "manifest_file_binding_exact": True,
            "sender_entry_and_return_scoped_registers_exact_all_records": True,
            "live_scoped_registers": [
                "AF", "BC", "DE", "HL", "SPS", "SPL", "IX", "IY",
                "I", "MB", "ADL", "MADL", "IFF1",
            ],
            "candidate_zero_or_fallback_hits": 0,
            "candidate_fast_path_records": EXPECTED_RECORDS * args.repeats,
        },
        "comparison": comparison(runs),
        "runs": runs,
        "limitations": {
            "exact_mos_required_sha256": sibling.CONSOLE8_MOS_SHA256,
            "private_serial_flags_address": sibling.MOS_SERIAL_FLAGS_ADDRESS,
            "cts_wiring": "pinned old Console8 GPIO PD3; asserted low",
            "fallback_is_not_mos_identity_detection": True,
            "physical_qualification_requires_exact_pinned_mos": True,
            "raw_sender_latency_not_transmitter_completion_equivalent": True,
            "completion_equivalent_claims_begin_at_upload_vdu_staging": True,
            "mos_side_thre_change_preferred_before_any_promotion": True,
            "no_concurrent_uart_writer_required": True,
            "dlab_must_remain_clear_during_block": True,
            "uart_configuration_must_remain_stable_during_block": True,
            "stable_configuration_scope": (
                "LCR, FIFO configuration, PD3 input pin mux, and private MOS "
                "serial flags must remain stable; the CTS input signal may "
                "change normally and is polled for every byte"
            ),
        },
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Regular-LOD UART-THRE live profile passed: {report_path}")
    for name, metric in report["comparison"].items():
        pairs = metric["paired"]
        percents = [float(pair["candidate_vs_accepted_percent"]) for pair in pairs]
        print(
            f"{name}: accepted={metric['accepted_aggregate_cycles']} "
            f"candidate={metric['candidate_aggregate_cycles']} "
            f"paired_percent={percents} "
            f"transmitter_completion_equivalent="
            f"{metric['transmitter_completion_equivalent']}"
        )
    print("records=227 publications=227 candidate_forbidden_hits=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        UartThreProfileError,
        sibling.UartThreSiblingBuildError,
        cold.ColdLoadProfileError,
        ProfileEvidenceError,
        staged.EvidenceError,
    ) as error:
        raise SystemExit(f"regular-LOD UART-THRE live profile failed: {error}") from error
