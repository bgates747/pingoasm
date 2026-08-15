#!/usr/bin/env python3
"""Live-qualify accepted versus register-CRC regular-LOD cold loading.

Each repeat starts fresh Fab processes for the accepted control and isolated
CRC sibling.  Eleven debugger boundaries reconstruct the same five complete
cold-load phases while also splitting validation into pre-CRC, CRC, and
post-CRC segments.  All 227 manifest records, VDP publications, final manager
state, final IX, CRC result bytes, and (for the sibling) L/H/E/D CRC registers
are bound exactly.  Two additional fresh guest runs prove CRC error 9 and
index error 10 precedence with a recomputed valid CRC.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import tempfile
import time
from typing import Mapping, Sequence
import zlib

import build_regular_lod_crc_register_sibling as sibling
import capture_regular_lod_manager_survey as regular_capture
import capture_terrain_manager_survey as survey
import profile_regular_lod_cold_load as cold
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
DEFAULT_OUTPUT = (
    ROOT / "build/evidence/regular-lod-crc-register-sibling-profile-v3"
)
REPORT_NAME = "regular-lod-crc-register-sibling-profile.json"
SCHEMA = "pingo-terrain-regular-lod-crc-register-sibling-live-profile-v1"
EXPECTED_RECORDS = sibling.EXPECTED_RECORDS
STAGE_BUFFER_ID = 0x7400
PHASE_NAMES = cold.PHASE_NAMES
CRC_VALUE_BYTES = 4
LEGACY_CONTROL_ARTIFACTS = {
    "legacy_control_program": (
        "bin",
        142_763,
        sibling.ACCEPTED_PROGRAM_SHA256,
    ),
    "legacy_control_listing": (
        "lst",
        2_304_719,
        "4951950b4f80c56a96c46246c56e1f314e5eae070600ddc9fce0111073439696",
    ),
    "legacy_control_symbols": (
        "symbols",
        66_112,
        "b1a9d5e35560df89c556f276b0910c6abf687416f0292d99882d891b46b07262",
    ),
}


class CrcSiblingProfileError(RuntimeError):
    """A build, live state, timing, corruption, or equivalence gate failed."""


@dataclass(frozen=True, slots=True)
class CrcLayout:
    read_call: int
    read_post: int
    validate_call: int
    crc_entry: int
    crc_post: int
    validate_post: int
    mirror_call: int
    mirror_upload_shared: int
    upload_post: int
    command_call: int
    command_post: int
    crc_value: int
    file_buffer: int
    return_error: int

    @property
    def events(self) -> tuple[tuple[str, int], ...]:
        return (
            ("read_call", self.read_call),
            ("read_post", self.read_post),
            ("validate_call", self.validate_call),
            ("crc_entry", self.crc_entry),
            ("crc_post", self.crc_post),
            ("validate_post", self.validate_post),
            ("mirror_call", self.mirror_call),
            ("mirror_upload_shared", self.mirror_upload_shared),
            ("upload_post", self.upload_post),
            ("command_call", self.command_call),
            ("command_post", self.command_post),
        )

    @property
    def breakpoints(self) -> tuple[int, ...]:
        addresses = tuple(address for _name, address in self.events)
        if len(addresses) != len(set(addresses)):
            raise CrcSiblingProfileError("CRC profile boundaries are not unique")
        return addresses

    def as_dict(self) -> dict[str, object]:
        return {
            "events": [
                {"name": name, "address": address}
                for name, address in self.events
            ],
            "crc_value": self.crc_value,
            "file_buffer": self.file_buffer,
            "return_error": self.return_error,
        }


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--resume-positives-from",
        type=Path,
        help=(
            "reuse complete accepted/candidate transcript directories from a "
            "prior run of this exact profiler; all 227x11 states, CRC snapshots, "
            "cold endpoint, artifacts, and shutdown pause are revalidated"
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help=(
            "fresh accepted/candidate pairs (default: 1; one exhaustive pair "
            "takes roughly 12-14 minutes under debugger instrumentation)"
        ),
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--vdp-module", type=Path, default=survey.DEFAULT_VDP
    )
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, key: str | None = None) -> dict[str, object]:
    resolved = path.resolve()
    if key is None:
        try:
            key = str(resolved.relative_to(ROOT))
        except ValueError:
            key = resolved.name
    return {
        "key": key,
        "bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CrcSiblingProfileError(f"unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CrcSiblingProfileError(f"JSON root is not an object: {path}")
    return value


def validate_legacy_control(
    build: Path, receipt: Mapping[str, object] | None = None
) -> tuple[Path, Path, Path]:
    """Resolve the private CRC1 control emitted beside the CRC sibling.

    These ignored scratch artifacts deliberately replace the former dependency
    on the canonical ``tgt`` program and debug sidecars.  The executable is the
    exact historical 27f09d image; its listing and symbols are regenerated from
    the current integrated source with CRC policy 1 selected in a temporary
    mirror, so their identities are separately pinned here.
    """

    build = build.expanduser().resolve()
    if receipt is None:
        receipt = load_json(build / "BUILD.json")
    if receipt.get("schema") != sibling.SCHEMA or receipt.get("qualified") is not True:
        raise CrcSiblingProfileError("CRC sibling build receipt is not qualified")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise CrcSiblingProfileError("CRC sibling receipt omits artifacts")
    resolved: list[Path] = []
    for name, (suffix, expected_bytes, expected_sha256) in (
        LEGACY_CONTROL_ARTIFACTS.items()
    ):
        path = build / f"{sibling.CONTROL_PROGRAM_STEM}.{suffix}"
        entry = artifacts.get(name)
        expected = {
            "key": f"artifacts/{path.name}",
            "bytes": expected_bytes,
            "sha256": expected_sha256,
        }
        if (
            path.is_symlink()
            or not path.is_file()
            or not isinstance(entry, Mapping)
            or dict(entry) != expected
            or path.stat().st_size != expected_bytes
            or sha256(path) != expected_sha256
        ):
            raise CrcSiblingProfileError(
                f"private legacy CRC1 artifact identity changed: {name}"
            )
        resolved.append(path)
    patch = receipt.get("source_patch")
    if not isinstance(patch, Mapping) or (
        patch.get("temporary_control_crc_policy") != "legacy-memory-bitwise"
        or patch.get("temporary_control_program_sha256")
        != sibling.ACCEPTED_PROGRAM_SHA256
        or patch.get("temporary_control_program_exact") is not True
        or patch.get("accepted_files_modified") is not False
    ):
        raise CrcSiblingProfileError("private legacy CRC1 source binding changed")
    return resolved[0], resolved[1], resolved[2]


def validate_build(build: Path) -> tuple[Path, Path, dict[str, object]]:
    receipt_path = build / "BUILD.json"
    receipt = load_json(receipt_path)
    if receipt.get("schema") != sibling.SCHEMA or receipt.get("qualified") is not True:
        raise CrcSiblingProfileError("CRC sibling build receipt is not qualified")
    scope = receipt.get("scope")
    if not isinstance(scope, dict) or any(
        scope.get(name) is not False
        for name in (
            "accepted_loader_modified",
            "accepted_source_modified",
            "accepted_binary_modified",
            "accepted_sidecars_modified",
            "launcher_modified",
        )
    ):
        raise CrcSiblingProfileError("CRC sibling build scope changed")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CrcSiblingProfileError("CRC sibling receipt omits artifacts")

    def checked(name: str, suffix: str) -> Path:
        entry = artifacts.get(name)
        path = build / f"{sibling.PROGRAM_STEM}.{suffix}"
        if not isinstance(entry, dict) or not path.is_file():
            raise CrcSiblingProfileError(f"missing sibling artifact: {name}")
        if (
            entry.get("key") != f"artifacts/{path.name}"
            or entry.get("bytes") != path.stat().st_size
            or entry.get("sha256") != sha256(path)
        ):
            raise CrcSiblingProfileError(f"sibling artifact receipt mismatch: {name}")
        return path

    program = checked("program", "bin")
    symbols = checked("symbols", "symbols")
    if sha256(program) != "a4a88621ee4ed3af42ad6006bebf5e48037d19ad4375568b3b9032594f139992":
        raise CrcSiblingProfileError("CRC sibling program hash changed")
    patch = receipt.get("source_patch")
    if not isinstance(patch, dict) or (
        patch.get("canonical_block_sha256") != sibling.CANONICAL_CRC_BLOCK_SHA256
        or patch.get("candidate_block_sha256") != sibling.CANDIDATE_CRC_BLOCK_SHA256
        or patch.get("temporary_control_program_sha256")
        != sibling.ACCEPTED_PROGRAM_SHA256
        or patch.get("temporary_control_program_exact") is not True
    ):
        raise CrcSiblingProfileError("CRC sibling source/control binding changed")
    validate_legacy_control(build, receipt)
    return program, symbols, receipt


def resolve_layout(program: Path, symbols_path: Path) -> CrcLayout:
    symbols = staged.parse_symbols(symbols_path)
    phases = cold.resolve_phase_spans(program, symbols)
    by_name = {phase.name: phase for phase in phases}
    required = {
        "p3dm_validate_container",
        "p3dm_retain_descriptor",
        "p3dm_validate_crc32",
        "p3dm_crc_value",
        "p3dm_file_buffer",
        "p3dm_return_error",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise CrcSiblingProfileError(f"profile symbols omit: {missing}")
    image = program.read_bytes()
    body_start = symbols["p3dm_validate_container"]
    body_end = symbols["p3dm_retain_descriptor"]
    crc_entry = symbols["p3dm_validate_crc32"]
    if not (
        staged.PROGRAM_LOAD_ADDRESS <= body_start < body_end <= crc_entry
        < staged.PROGRAM_LOAD_ADDRESS + len(image)
    ):
        raise CrcSiblingProfileError("CRC call topology escaped validation/program")
    body = image[
        body_start - staged.PROGRAM_LOAD_ADDRESS :
        body_end - staged.PROGRAM_LOAD_ADDRESS
    ]
    encoded_call = bytes((0xCD,)) + crc_entry.to_bytes(3, "little")
    offsets = cold._call_offsets(body, encoded_call)
    if len(offsets) != 1:
        raise CrcSiblingProfileError(
            f"expected one validation call to CRC, found {len(offsets)}"
        )
    crc_call = body_start + offsets[0]
    if not body_start <= crc_call < crc_call + 4 <= body_end:
        raise CrcSiblingProfileError("CRC call/post escaped validation body")
    layout = CrcLayout(
        read_call=by_name["read_container_fatfs"].call,
        read_post=by_name["read_container_fatfs"].post_call,
        validate_call=by_name["validate_container"].call,
        crc_entry=crc_entry,
        crc_post=crc_call + 4,
        validate_post=by_name["validate_container"].post_call,
        mirror_call=by_name["mirror_validated_z"].call,
        mirror_upload_shared=by_name["mirror_validated_z"].post_call,
        upload_post=by_name["upload_vdu_staging"].post_call,
        command_call=by_name["command50_enqueue"].call,
        command_post=by_name["command50_enqueue"].post_call,
        crc_value=symbols["p3dm_crc_value"],
        file_buffer=symbols["p3dm_file_buffer"],
        return_error=symbols["p3dm_return_error"],
    )
    if layout.mirror_upload_shared != by_name["upload_vdu_staging"].call:
        raise CrcSiblingProfileError("mirror/upload shared boundary changed")
    layout.breakpoints
    if not (
        layout.read_call < layout.read_post < layout.validate_call
        < layout.validate_post < layout.mirror_call
        <= layout.mirror_upload_shared < layout.upload_post
        < layout.command_call < layout.command_post
    ):
        raise CrcSiblingProfileError("top-level cold phase order changed")
    return layout


MEMORY_RE_TEMPLATE = r"{address:06x}:((?:\s+[0-9A-Fa-f]{{2}}){{4}})"


class LiveBoundaryProfiler:
    """Drive exact nested boundaries and snapshot four CRC bytes per record."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        layout: CrcLayout,
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
        self.cycles: list[dict[str, int | str]] = []
        self.crc_memory: list[bytes] = []
        self.complete = False

    def _advance(self) -> None:
        self.event_index += 1
        if self.event_index == len(self.events):
            self.event_index = 0
            self.record_index += 1
        if self.record_index == self.expected_records:
            for address in self.layout.breakpoints:
                debugger.write_debugger(self.process, f"delete 0x{address:x}")
            self.complete = True
        self.waiting = "pause"
        debugger.write_debugger(self.process, "continue")

    def service(self, contents: str) -> None:
        if self.complete:
            return
        expected_name, expected_address = self.events[self.event_index]
        if self.waiting == "pause":
            pause = staged.SELECTOR_PAUSE_RE.search(contents, self.cursor)
            if pause is None:
                return
            candidates = []
            for _name, address in self.events:
                marker = contents.find(f"* {address:06x}:", pause.end())
                if marker >= 0:
                    candidates.append((marker, address))
            if not candidates:
                return
            marker, address = min(candidates)
            if address != expected_address:
                raise CrcSiblingProfileError(
                    f"boundary order changed at record {self.record_index}: "
                    f"0x{address:06x} != {expected_name}=0x{expected_address:06x}"
                )
            self.cursor = marker + len(f"* {address:06x}:")
            self.waiting = "state"
            debugger.write_debugger(self.process, "state")
            return
        if self.waiting == "state":
            cycles = staged.SELECTOR_CYCLES_RE.search(contents, self.cursor)
            if cycles is None:
                return
            self.cycles.append(
                {
                    "record": self.record_index,
                    "event": expected_name,
                    "address": expected_address,
                    "cycles_since_previous_boundary": int(cycles.group(1)),
                }
            )
            self.cursor = cycles.end()
            if expected_name == "crc_post":
                self.waiting = "memory"
                debugger.write_debugger(
                    self.process, f"memory 0x{self.layout.crc_value:x} 4"
                )
            else:
                self._advance()
            return
        if self.waiting == "memory":
            pattern = re.compile(
                MEMORY_RE_TEMPLATE.format(address=self.layout.crc_value)
            )
            match = pattern.search(contents, self.cursor)
            if match is None:
                return
            value = bytes(int(token, 16) for token in match.group(1).split())
            if len(value) != CRC_VALUE_BYTES:
                raise CrcSiblingProfileError("debugger CRC memory length changed")
            self.crc_memory.append(value)
            self.cursor = match.end()
            self._advance()

    def require_complete(self) -> dict[str, object]:
        if (
            not self.complete
            or self.record_index != self.expected_records
            or self.event_index != 0
            or self.waiting != "pause"
            or len(self.cycles) != self.expected_records * len(self.events)
            or len(self.crc_memory) != self.expected_records
        ):
            raise CrcSiblingProfileError(
                f"incomplete live boundary profile: records={self.record_index}/"
                f"{self.expected_records}, event={self.event_index}, "
                f"cycles={len(self.cycles)}, crc_memory={len(self.crc_memory)}"
            )
        return {
            "record_count": self.record_index,
            "event_count_per_record": len(self.events),
            "cycle_state_count": len(self.cycles),
            "crc_memory_snapshot_count": len(self.crc_memory),
        }


STATE_RE = re.compile(r"\*\s+([0-9A-Fa-f]{6}):")
CYCLES_RE = re.compile(r"Cycles since last break:\s*(\d+)")
REGISTER_RE = re.compile(
    r"\bAF:([0-9A-Fa-f]{4})\s+BC:([0-9A-Fa-f]{6})\s+"
    r"DE:([0-9A-Fa-f]{6})\s+HL:([0-9A-Fa-f]{6}).*?\sIX:([0-9A-Fa-f]{6})\b"
)


def parse_boundary_states(
    contents: str, layout: CrcLayout, expected_records: int
) -> list[dict[str, int | str]]:
    targets = set(layout.breakpoints)
    pending: tuple[int, int, str] | None = None
    states: list[tuple[int, int, str, int]] = []
    for line_number, line in enumerate(contents.splitlines(), 1):
        state_matches = tuple(STATE_RE.finditer(line))
        if len(state_matches) > 1:
            raise CrcSiblingProfileError(
                f"debugger line {line_number} has multiple states"
            )
        if state_matches:
            address = int(state_matches[0].group(1), 16)
            if pending is not None:
                pending_address, _pending_line, _pending_text = pending
                if address != pending_address:
                    raise CrcSiblingProfileError("debugger state lacks cycle report")
                pending = (address, line_number, line)
            else:
                pending = (address, line_number, line) if address in targets else None
        cycle_matches = tuple(CYCLES_RE.finditer(line))
        if len(cycle_matches) > 1:
            raise CrcSiblingProfileError("debugger line has multiple cycle reports")
        if cycle_matches and pending is not None:
            address, state_line, state_text = pending
            states.append(
                (address, state_line, state_text, int(cycle_matches[0].group(1)))
            )
            pending = None
    if pending is not None:
        raise CrcSiblingProfileError("final debugger state lacks cycle report")
    expected = layout.events * expected_records
    if len(states) != len(expected):
        raise CrcSiblingProfileError(
            f"parsed {len(states)} boundary states, expected {len(expected)}"
        )
    result = []
    for index, ((address, line_number, text, cycles), (name, wanted)) in enumerate(
        zip(states, expected)
    ):
        if address != wanted:
            raise CrcSiblingProfileError(
                f"parsed boundary {index} changed: {address:06x} != {wanted:06x}"
            )
        registers = REGISTER_RE.search(text)
        if registers is None:
            raise CrcSiblingProfileError(
                f"full register state missing at line {line_number}"
            )
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
                "ix": int(registers.group(5), 16),
            }
        )
    return result


def parse_crc_memory(contents: str, address: int) -> list[bytes]:
    pattern = re.compile(MEMORY_RE_TEMPLATE.format(address=address))
    return [
        bytes(int(token, 16) for token in match.group(1).split())
        for match in pattern.finditer(debugger.ANSI_RE.sub("", contents))
    ]


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


def expected_record_payload(record: Mapping[str, object]) -> tuple[bytes, bytes, int]:
    relative = record.get("path")
    if not isinstance(relative, str):
        raise CrcSiblingProfileError("initial record has no path")
    payload = (regular_capture.FIXTURE / relative).read_bytes()
    data_bytes = int(record["data_bytes"])
    data = payload[sibling.P3DM_DATA_OFFSET : sibling.P3DM_DATA_OFFSET + data_bytes]
    stored = int.from_bytes(
        payload[sibling.P3DM_DESC_CRC32 : sibling.P3DM_DESC_CRC32 + 4], "little"
    )
    return payload, data, stored


def reconstruct_records(
    states: Sequence[Mapping[str, int | str]],
    crc_memory: Sequence[bytes],
    layout: CrcLayout,
    expected: Sequence[Mapping[str, object]],
    publications: Sequence[MeshReplaceRecord],
    *,
    register_resident: bool,
) -> tuple[list[dict[str, object]], dict[str, list[int]]]:
    event_count = len(layout.events)
    if len(states) != len(expected) * event_count or len(crc_memory) != len(expected):
        raise CrcSiblingProfileError("state/CRC record counts changed")
    phase_cycles = {name: [] for name in PHASE_NAMES}
    result = []
    for order, record in enumerate(expected):
        chunk = states[order * event_count : (order + 1) * event_count]
        by_name = {str(item["event"]): item for item in chunk}
        if len(by_name) != event_count:
            raise CrcSiblingProfileError(f"record {order} boundary names changed")
        validation_segments = {
            "pre_crc": int(by_name["crc_entry"]["cycles_since_previous_boundary"]),
            "crc32": int(by_name["crc_post"]["cycles_since_previous_boundary"]),
            "post_crc": int(by_name["validate_post"]["cycles_since_previous_boundary"]),
        }
        phases = {
            "read_container_fatfs": int(
                by_name["read_post"]["cycles_since_previous_boundary"]
            ),
            "validate_container": sum(validation_segments.values()),
            "mirror_validated_z": int(
                by_name["mirror_upload_shared"]["cycles_since_previous_boundary"]
            ),
            "upload_vdu_staging": int(
                by_name["upload_post"]["cycles_since_previous_boundary"]
            ),
            "command50_enqueue": int(
                by_name["command_post"]["cycles_since_previous_boundary"]
            ),
        }
        for name in PHASE_NAMES:
            phase_cycles[name].append(phases[name])
        payload, data, stored = expected_record_payload(record)
        del payload
        expected_crc_bytes = stored.to_bytes(4, "little")
        memory = crc_memory[order]
        if memory != expected_crc_bytes:
            raise CrcSiblingProfileError(
                f"record {order} final p3dm_crc_value changed: "
                f"{memory.hex()} != {expected_crc_bytes.hex()}"
            )
        post = by_name["crc_post"]
        expected_ix = layout.file_buffer + sibling.P3DM_DATA_OFFSET + len(data)
        if int(post["ix"]) != expected_ix:
            raise CrcSiblingProfileError(
                f"record {order} final IX changed: {int(post['ix']):06x} "
                f"!= {expected_ix:06x}"
            )
        if (int(post["af"]) >> 8) != 0 or int(post["bc"]) != 0:
            raise CrcSiblingProfileError(
                f"record {order} CRC success A/BC changed"
            )
        register_bytes = None
        if register_resident:
            hl = int(post["hl"])
            de = int(post["de"])
            register_bytes = bytes(
                (hl & 0xFF, (hl >> 8) & 0xFF, de & 0xFF, (de >> 8) & 0xFF)
            )
            if register_bytes != expected_crc_bytes:
                raise CrcSiblingProfileError(
                    f"record {order} L/H/E/D CRC changed: "
                    f"{register_bytes.hex()} != {expected_crc_bytes.hex()}"
                )
        result.append(
            {
                "order": order,
                "path": record["path"],
                "file_sha256": record["sha256"],
                "data_bytes": len(data),
                "stored_crc32": f"{stored:08x}",
                "p3dm_crc_value_hex": memory.hex(),
                "final_ix": int(post["ix"]),
                "expected_final_ix": expected_ix,
                "final_ix_from_file_buffer": int(post["ix"]) - layout.file_buffer,
                "register_crc_hex": (
                    None if register_bytes is None else register_bytes.hex()
                ),
                "validation_guest_cycles": validation_segments,
                "phase_guest_cycles": phases,
                "measured_phase_guest_cycles_total": sum(phases.values()),
            }
        )
    # Reuse the accepted binder for exact manifest counts/order and VDP shapes.
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
        lambda value: debugger.ANSI_RE.sub("", value).count("CPU paused")
        > pause_count,
        "final CRC-profile debugger pause",
    )
    debugger.write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise CrcSiblingProfileError("debugger did not exit") from error
    if process.returncode != 0:
        raise CrcSiblingProfileError(
            f"debugger shutdown returned {process.returncode}"
        )
    return log_path.read_text(encoding="utf-8", errors="replace")


def emulator_command(
    sd_root: Path, vdp: Path, breakpoints: Sequence[int]
) -> list[str]:
    emulator = staged.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = staged.require_file(input_trace.MOS_BINARY, "MOS image")
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
    for address in breakpoints:
        command.extend(("--breakpoint", f"0x{address:x}"))
    return command


def emulator_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
    local_sdl = Path.home() / ".local/lib"
    old = environment.get("LD_LIBRARY_PATH")
    environment["LD_LIBRARY_PATH"] = (
        str(local_sdl) if not old else f"{local_sdl}:{old}"
    )
    return environment


AUTOEXEC = b"SET KEYBOARD 1\r\ncd /survey\r\nload P3DRGL.BIN\r\nrun\r\n"


def analyze_positive_log(
    *,
    variant: str,
    repeat: int,
    program_copy: Path,
    symbols_copy: Path,
    log_path: Path,
    register_resident: bool,
    emulator_exit_status: int,
    expected_live_crc_memory: Sequence[bytes] | None = None,
) -> dict[str, object]:
    layout = resolve_layout(program_copy, symbols_copy)
    expected = regular_capture.initial_records()
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    states = parse_boundary_states(contents, layout, EXPECTED_RECORDS)
    memory = parse_crc_memory(contents, layout.crc_value)
    if expected_live_crc_memory is not None and list(memory) != list(
        expected_live_crc_memory
    ):
        raise CrcSiblingProfileError("live/reparsed CRC memory evidence differs")
    if len(states) != EXPECTED_RECORDS * len(layout.events) or len(memory) != EXPECTED_RECORDS:
        raise CrcSiblingProfileError("positive transcript is not an exhaustive run")
    live = {
        "record_count": EXPECTED_RECORDS,
        "event_count_per_record": len(layout.events),
        "cycle_state_count": len(states),
        "crc_memory_snapshot_count": len(memory),
    }
    cold_endpoint = staged.validate_cold_endpoint(contents)
    publications = parse_mesh_replace_records(contents)
    records, phase_cycles = reconstruct_records(
        states,
        memory,
        layout,
        expected,
        publications,
        register_resident=register_resident,
    )
    if emulator_exit_status != 0:
        raise CrcSiblingProfileError(
            f"{variant} emulator returned {emulator_exit_status}"
        )
    phases = {
        name: {
            "cycles": phase_cycles[name],
            "summary": summarize_distribution(phase_cycles[name]).as_dict(),
        }
        for name in PHASE_NAMES
    }
    crc_cycles = [
        int(record["validation_guest_cycles"]["crc32"]) for record in records
    ]
    validation_pre = [
        int(record["validation_guest_cycles"]["pre_crc"]) for record in records
    ]
    validation_post = [
        int(record["validation_guest_cycles"]["post_crc"]) for record in records
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
        "validation_segments": {
            "pre_crc": {
                "cycles": validation_pre,
                "summary": summarize_distribution(validation_pre).as_dict(),
            },
            "crc32": {
                "cycles": crc_cycles,
                "summary": summarize_distribution(crc_cycles).as_dict(),
            },
            "post_crc": {
                "cycles": validation_post,
                "summary": summarize_distribution(validation_post).as_dict(),
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
            "final_crc_memory_snapshots": len(memory),
            "final_ix_exact": True,
            "register_crc_exact": register_resident,
            "no_policy_abi_expected": True,
        },
        "log": artifact(log_path),
        "emulator_exit_status": emulator_exit_status,
    }


def resume_positive(
    *,
    variant: str,
    repeat: int,
    program: Path,
    symbols_path: Path,
    source: Path,
    output: Path,
    register_resident: bool,
) -> dict[str, object]:
    name = f"{variant}-repeat-{repeat + 1}"
    source_run = source / name
    destination = output / name
    if not source_run.is_dir():
        raise CrcSiblingProfileError(f"resume transcript is missing: {source_run}")
    shutil.copytree(source_run, destination)
    program_copy = destination / f"{variant}.profiled.bin"
    symbols_copy = destination / f"{variant}.profiled.symbols"
    log_path = destination / "emulator.log"
    if (
        not program_copy.is_file()
        or not symbols_copy.is_file()
        or not log_path.is_file()
        or sha256(program_copy) != sha256(program)
        or sha256(symbols_copy) != sha256(symbols_path)
    ):
        raise CrcSiblingProfileError(f"resume artifacts changed for {name}")
    plain = debugger.ANSI_RE.sub(
        "", log_path.read_text(encoding="utf-8", errors="replace")
    )
    if (
        plain.count("CPU paused (breakpoint)")
        != EXPECTED_RECORDS * 11
        or plain.count("CPU paused\n") != 1
        or staged.COLD_RENDER_MARKER not in plain
    ):
        raise CrcSiblingProfileError(
            f"resume transcript lacks exact breakpoint/cold/shutdown topology: {name}"
        )
    result = analyze_positive_log(
        variant=variant,
        repeat=repeat,
        program_copy=program_copy,
        symbols_copy=symbols_copy,
        log_path=log_path,
        register_resident=register_resident,
        emulator_exit_status=0,
    )
    result["transcript_provenance"] = {
        "resumed": True,
        "source_key": source.name,
        "exact_breakpoint_count": EXPECTED_RECORDS * 11,
        "final_shutdown_pause_exact": True,
        "original_runner_reached_post_process_analysis": True,
    }
    return result


def run_positive(
    *,
    variant: str,
    repeat: int,
    program: Path,
    symbols_path: Path,
    vdp: Path,
    output: Path,
    timeout: float,
    register_resident: bool,
) -> dict[str, object]:
    layout = resolve_layout(program, symbols_path)
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
        tempfile.TemporaryDirectory(prefix=f"crc-{variant}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"crc-{variant}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        staged.stage_fixture(sd_root, program_copy)
        (sd_root / "autoexec.txt").write_bytes(AUTOEXEC)
        command = emulator_command(sd_root, vdp, layout.breakpoints)
        (run_output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "variant": variant,
                    "repeat": repeat + 1,
                    "expected_records": EXPECTED_RECORDS,
                    "program": artifact(program_copy),
                    "symbols": artifact(symbols_copy),
                    "layout": layout.as_dict(),
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
    profiler.require_complete()
    return analyze_positive_log(
        variant=variant,
        repeat=repeat,
        program_copy=program_copy,
        symbols_copy=symbols_copy,
        log_path=log_path,
        register_resident=register_resident,
        emulator_exit_status=int(process.returncode),
        expected_live_crc_memory=profiler.crc_memory,
    )


def first_record() -> tuple[Mapping[str, object], Path, bytes]:
    record = regular_capture.initial_records()[0]
    relative = Path(str(record["path"]))
    payload = (regular_capture.FIXTURE / relative).read_bytes()
    if relative.as_posix() != "TRH/L0/49/ED.AGN":
        raise CrcSiblingProfileError(f"first cold record changed: {relative}")
    return record, relative, payload


def mutate_negative(
    kind: str, record: Mapping[str, object], payload: bytes
) -> tuple[bytes, dict[str, object]]:
    changed = bytearray(payload)
    data_bytes = int(record["data_bytes"])
    data_start = sibling.P3DM_DATA_OFFSET
    if kind == "crc-data":
        offset = data_start
        changed[offset] ^= 1
        expected_error = 9
        mutation = {"file_offset": offset, "before": payload[offset], "after": changed[offset]}
    elif kind == "index-valid-crc":
        vertices = int(record["vertices"])
        offset = data_start + 6 * vertices
        before = bytes(changed[offset : offset + 2])
        changed[offset : offset + 2] = vertices.to_bytes(2, "little")
        data = changed[data_start : data_start + data_bytes]
        crc = zlib.crc32(data) & 0xFFFFFFFF
        changed[
            sibling.P3DM_DESC_CRC32 : sibling.P3DM_DESC_CRC32 + 4
        ] = crc.to_bytes(4, "little")
        expected_error = 10
        mutation = {
            "file_offset": offset,
            "before_hex": before.hex(),
            "after_hex": bytes(changed[offset : offset + 2]).hex(),
            "invalid_index": vertices,
            "recomputed_stored_crc32": f"{crc:08x}",
        }
    else:
        raise ValueError(kind)
    differences = [
        index for index, (old, new) in enumerate(zip(payload, changed)) if old != new
    ]
    data = changed[data_start : data_start + data_bytes]
    stored = int.from_bytes(
        changed[sibling.P3DM_DESC_CRC32 : sibling.P3DM_DESC_CRC32 + 4], "little"
    )
    return bytes(changed), {
        "kind": kind,
        "expected_error": expected_error,
        "mutation": mutation,
        "changed_file_offsets": differences,
        "original_sha256": hashlib.sha256(payload).hexdigest(),
        "mutated_sha256": hashlib.sha256(changed).hexdigest(),
        "stored_crc32": f"{stored:08x}",
        "actual_data_crc32": f"{zlib.crc32(data) & 0xFFFFFFFF:08x}",
    }


def parse_last_full_state(contents: str, address: int) -> dict[str, int]:
    lines = [
        line
        for line in debugger.ANSI_RE.sub("", contents).splitlines()
        if f"* {address:06x}:" in line and REGISTER_RE.search(line) is not None
    ]
    if not lines:
        raise CrcSiblingProfileError(f"no full debugger state at 0x{address:06x}")
    match = REGISTER_RE.search(lines[-1])
    assert match is not None
    return {
        "af": int(match.group(1), 16),
        "bc": int(match.group(2), 16),
        "de": int(match.group(3), 16),
        "hl": int(match.group(4), 16),
        "ix": int(match.group(5), 16),
    }


def run_negative(
    *,
    kind: str,
    program: Path,
    symbols_path: Path,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    layout = resolve_layout(program, symbols_path)
    record, relative, original = first_record()
    mutated, mutation = mutate_negative(kind, record, original)
    run_output = output / f"negative-{kind}"
    run_output.mkdir()
    (run_output / "autoexec.txt").write_bytes(AUTOEXEC)
    log_path = run_output / "emulator.log"
    deadline = time.monotonic() + timeout
    process: subprocess.Popen[bytes] | None = None
    breakpoints = [layout.return_error]
    if kind == "index-valid-crc":
        # If index precedence regresses, the CRC entry wins this race.
        breakpoints.append(layout.crc_entry)
    with (
        tempfile.TemporaryDirectory(prefix=f"crc-negative-{kind}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"crc-negative-{kind}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        staged.stage_fixture(sd_root, program)
        tree = sd_root / "survey/TRH"
        if not tree.is_symlink():
            raise CrcSiblingProfileError("staged TRH is not the expected symlink")
        tree.unlink()
        target = sd_root / "survey" / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(mutated)
        (sd_root / "autoexec.txt").write_bytes(AUTOEXEC)
        command = emulator_command(sd_root, vdp, breakpoints)
        (run_output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "kind": kind,
                    "record": dict(record),
                    "mutation": mutation,
                    "program": artifact(program),
                    "symbols": artifact(symbols_path),
                    "breakpoints": breakpoints,
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
                staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: "CPU paused (breakpoint)" in value,
                    f"guest {kind} failure breakpoint",
                )
                debugger.write_debugger(process, "state")
                staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: staged.SELECTOR_CYCLES_RE.search(value) is not None,
                    f"guest {kind} failure state",
                )
                debugger.write_debugger(process, f"memory 0x{layout.crc_value:x} 4")
                pattern = re.compile(
                    MEMORY_RE_TEMPLATE.format(address=layout.crc_value)
                )
                staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: pattern.search(debugger.ANSI_RE.sub("", value))
                    is not None,
                    f"guest {kind} CRC result memory",
                )
                debugger.write_debugger(process, "exit")
                process.wait(timeout=max(1.0, deadline - time.monotonic()))
        finally:
            if process is not None and process.poll() is None:
                input_trace.stop_process(process)
    assert process is not None
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    plain = debugger.ANSI_RE.sub("", contents)
    pause_addresses = [int(value, 16) for value in re.findall(r"\* ([0-9a-fA-F]{6}):", plain)]
    first_target = next((value for value in pause_addresses if value in breakpoints), None)
    if first_target != layout.return_error:
        raise CrcSiblingProfileError(
            f"{kind} reached 0x{first_target or 0:06x}, expected return_error"
        )
    state = parse_last_full_state(contents, layout.return_error)
    error = (state["af"] >> 8) & 0xFF
    expected_error = int(mutation["expected_error"])
    if error != expected_error:
        raise CrcSiblingProfileError(f"{kind} guest error {error} != {expected_error}")
    memory = parse_crc_memory(contents, layout.crc_value)
    if len(memory) != 1:
        raise CrcSiblingProfileError(f"{kind} returned {len(memory)} CRC snapshots")
    if parse_mesh_replace_records(contents):
        raise CrcSiblingProfileError(f"{kind} published a mesh before rejection")
    if staged.COLD_RENDER_MARKER in contents:
        raise CrcSiblingProfileError(f"{kind} reached the cold render endpoint")
    actual_crc = int(str(mutation["actual_data_crc32"]), 16)
    stored_crc = int(str(mutation["stored_crc32"]), 16)
    if kind == "crc-data":
        if memory[0] != actual_crc.to_bytes(4, "little") or actual_crc == stored_crc:
            raise CrcSiblingProfileError("guest error-9 CRC result/mismatch changed")
    else:
        if actual_crc != stored_crc:
            raise CrcSiblingProfileError("index negative no longer has a valid CRC")
        if first_target == layout.crc_entry:
            raise CrcSiblingProfileError("CRC ran before invalid-index rejection")
    if process.returncode != 0:
        raise CrcSiblingProfileError(f"{kind} emulator returned {process.returncode}")
    return {
        "kind": kind,
        "fresh_process": True,
        "guest_executed": True,
        "record_order": 0,
        "path": relative.as_posix(),
        "mutation": mutation,
        "first_breakpoint": first_target,
        "return_error_address": layout.return_error,
        "crc_entry_address": layout.crc_entry,
        "guest_error": error,
        "p3dm_crc_value_hex": memory[0].hex(),
        "mesh_publications_before_rejection": 0,
        "cold_endpoint_reached": False,
        "emulator_exit_status": process.returncode,
        "log": artifact(log_path),
    }


def assert_semantic_equivalence(
    accepted: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    for name in ("cold_endpoint", "publication_semantics"):
        if accepted.get(name) != candidate.get(name):
            raise CrcSiblingProfileError(f"accepted/candidate {name} differs")
    accepted_records = accepted.get("records")
    candidate_records = candidate.get("records")
    if not isinstance(accepted_records, list) or not isinstance(candidate_records, list):
        raise CrcSiblingProfileError("run records are missing")
    if len(accepted_records) != EXPECTED_RECORDS or len(candidate_records) != EXPECTED_RECORDS:
        raise CrcSiblingProfileError("run record counts differ")
    stable_fields = (
        "order", "path", "file_sha256", "data_bytes", "stored_crc32",
        "p3dm_crc_value_hex", "final_ix_from_file_buffer",
    )
    for order, (left, right) in enumerate(zip(accepted_records, candidate_records)):
        if any(left.get(field) != right.get(field) for field in stable_fields):
            raise CrcSiblingProfileError(f"semantic record differs at {order}")


def run_aggregate(run: Mapping[str, object], path: Sequence[str]) -> int:
    value: object = run
    for name in path:
        if not isinstance(value, Mapping):
            raise CrcSiblingProfileError(f"run aggregate path failed: {path}")
        value = value.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CrcSiblingProfileError(f"run aggregate is not an integer: {path}")
    return value


def comparison(runs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    accepted = [run for run in runs if run.get("variant") == "accepted"]
    candidate = [run for run in runs if run.get("variant") == "crc-register"]
    if len(accepted) != len(candidate) or not accepted:
        raise CrcSiblingProfileError("paired repeat topology changed")
    metrics = {
        "crc32": ("validation_segments", "crc32", "summary", "total"),
        "validate_container": ("phases", "validate_container", "summary", "total"),
        "complete_measured_cold_phases": (
            "measured_phase_guest_cycles_total", "aggregate"
        ),
    }
    result: dict[str, object] = {}
    for name, path in metrics.items():
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
        raise CrcSiblingProfileError("--repeats and --timeout must be positive")
    build = args.build.expanduser().resolve()
    output = args.output.expanduser().resolve()
    resume_source = (
        None
        if args.resume_positives_from is None
        else args.resume_positives_from.expanduser().resolve()
    )
    if output.exists():
        raise CrcSiblingProfileError(f"refusing to replace existing output: {output}")
    program, symbols, receipt = validate_build(build)
    control_program, control_listing, control_symbols = validate_legacy_control(
        build, receipt
    )
    vdp = staged.require_file(args.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    output.mkdir(parents=True)
    runs: list[dict[str, object]] = []
    for repeat in range(args.repeats):
        if resume_source is None:
            accepted = run_positive(
                variant="accepted",
                repeat=repeat,
                program=control_program,
                symbols_path=control_symbols,
                vdp=vdp,
                output=output,
                timeout=args.timeout,
                register_resident=False,
            )
            candidate = run_positive(
                variant="crc-register",
                repeat=repeat,
                program=program,
                symbols_path=symbols,
                vdp=vdp,
                output=output,
                timeout=args.timeout,
                register_resident=True,
            )
        else:
            accepted = resume_positive(
                variant="accepted",
                repeat=repeat,
                program=control_program,
                symbols_path=control_symbols,
                source=resume_source,
                output=output,
                register_resident=False,
            )
            candidate = resume_positive(
                variant="crc-register",
                repeat=repeat,
                program=program,
                symbols_path=symbols,
                source=resume_source,
                output=output,
                register_resident=True,
            )
        assert_semantic_equivalence(accepted, candidate)
        runs.extend((accepted, candidate))
    negatives = [
        run_negative(
            kind=kind,
            program=program,
            symbols_path=symbols,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        for kind in ("crc-data", "index-valid-crc")
    ]
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "fresh_process_per_run": True,
            "repeat_count_per_variant": args.repeats,
            "complete_cold_fill_records_per_positive_run": EXPECTED_RECORDS,
            "full_measured_phases": list(PHASE_NAMES),
            "validation_segments": ["pre_crc", "crc32", "post_crc"],
            "measurement": "paused-debugger-boundary-to-boundary guest cycles",
            "nested_validation_total": "pre_crc + crc32 + post_crc",
            "render_timing_excluded": True,
            "host_wall_time_excluded": True,
            "physical_sd_latency_excluded": True,
            "no_policy_abi_expected": True,
            "positive_transcripts_resumed": resume_source is not None,
            "timing_repeatability": (
                "not claimed by the default single exhaustive pair; additional "
                "fresh pairs remain an optional follow-up"
            ),
        },
        "identity": {
            "build_receipt": artifact(build / "BUILD.json"),
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
        },
        "semantic_equivalence": {
            "all_repeats_exact": True,
            "cold_endpoint_exact": True,
            "publication_order_and_shapes_exact": True,
            "manifest_file_and_crc_binding_exact": True,
            "final_ix_exact_all_records": True,
            "final_p3dm_crc_value_exact_all_records": True,
            "candidate_l_h_e_d_crc_exact_all_records": True,
        },
        "comparison": comparison(runs),
        "runs": runs,
        "negative_guest_execution": negatives,
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Regular-LOD CRC-register live profile passed: {report_path}")
    for name, metric in report["comparison"].items():
        pairs = metric["paired"]
        deltas = [float(pair["candidate_vs_accepted_percent"]) for pair in pairs]
        print(
            f"{name}: accepted={metric['accepted_aggregate_cycles']} "
            f"candidate={metric['candidate_aggregate_cycles']} "
            f"paired_percent={deltas}"
        )
    print("negative_guest_errors=9,10 publications_before_rejection=0,0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        CrcSiblingProfileError,
        sibling.CrcSiblingBuildError,
        cold.ColdLoadProfileError,
        ProfileEvidenceError,
        staged.EvidenceError,
    ) as error:
        raise SystemExit(f"regular-LOD CRC-register live profile failed: {error}") from error
