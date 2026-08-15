#!/usr/bin/env python3
"""Profile accepted regular-LOD P3DM cold-load phases in a fresh Fab process.

This diagnostic deliberately does not contribute render or host-wall timing to
the regular-LOD benchmark.  It alternates exact call-site and post-call
debugger breakpoints around the accepted loader's read, validation, mirror,
VDU staging, and command-50 enqueue calls.  Every cycle sample is bound to the
corresponding checksum-qualified initial-view P3DM record and its exact byte
and element counts.
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

import capture_regular_lod_manager_survey as regular_capture
import capture_terrain_manager_survey as survey
import trace_koak_input as input_trace
import trace_koak_takeoff as debugger
import trace_regular_lod_staged_north_transitions as staged
from pingo_terrain.regular_lod_profile import (
    MeshReplaceRecord,
    ProfileEvidenceError,
    parse_mesh_replace_records,
    parse_selector_cycle_pairs,
    summarize_distribution,
)


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "pingo-terrain-regular-lod-cold-load-cycle-profile-v1"
REPORT_NAME = "regular-lod-cold-load-cycle-profile.json"
MODE = "complete-cold-fill"
EXPECTED_RECORDS = regular_capture.ACTIVE_COUNT
PROGRAM_LOAD_ADDRESS = staged.PROGRAM_LOAD_ADDRESS
STAGE_BUFFER_ID = 0x7400
P3DM_DATA_OFFSET = 100


class ColdLoadProfileError(ValueError):
    """The program topology or captured cold-load evidence changed."""


@dataclass(frozen=True, slots=True)
class PhaseSpec:
    name: str
    target_symbol: str


@dataclass(frozen=True, slots=True)
class PhaseSpan:
    name: str
    target_symbol: str
    target: int
    call: int
    post_call: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "name": self.name,
            "target_symbol": self.target_symbol,
            "target": self.target,
            "call": self.call,
            "post_call": self.post_call,
        }


PHASE_SPECS = (
    PhaseSpec("read_container_fatfs", "p3dm_read_container"),
    PhaseSpec("validate_container", "p3dm_validate_container"),
    PhaseSpec("mirror_validated_z", "p3dm_mirror_validated_z"),
    PhaseSpec("upload_vdu_staging", "p3dm_upload_data"),
    PhaseSpec("command50_enqueue", "pingo_replace_mesh_from_buffer"),
)
PHASE_NAMES = tuple(item.name for item in PHASE_SPECS)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--program", type=Path, default=staged.DEFAULT_PROGRAM
    )
    parser.add_argument(
        "--symbols", type=Path, default=staged.DEFAULT_SYMBOLS
    )
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=survey.DEFAULT_VDP,
        help="diagnostic PingoWolf VDP module used only for stream validation",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ColdLoadProfileError(f"missing profile artifact: {resolved}")
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def _call_offsets(image: bytes, encoded_call: bytes) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    while True:
        offset = image.find(encoded_call, cursor)
        if offset < 0:
            return offsets
        offsets.append(offset)
        cursor = offset + 1


def resolve_phase_spans(
    program: Path, symbols: Mapping[str, int]
) -> tuple[PhaseSpan, ...]:
    """Resolve the five calls from the exact accepted top-level loader body.

    eZ80 ADL ``call`` is one opcode plus a 24-bit little-endian target.  The
    top-level body ends exactly where ``p3dm_read_container`` begins, so calls
    elsewhere in the binary cannot silently satisfy this gate.
    """

    required = {
        "p3dm_load_component",
        "p3dm_read_container",
        *(item.target_symbol for item in PHASE_SPECS),
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise ColdLoadProfileError(f"profile symbols omit: {missing}")
    image = program.read_bytes()
    body_start = int(symbols["p3dm_load_component"])
    body_end = int(symbols["p3dm_read_container"])
    image_end = PROGRAM_LOAD_ADDRESS + len(image)
    if not (
        PROGRAM_LOAD_ADDRESS <= body_start < body_end <= image_end
        and body_end - body_start <= 512
    ):
        raise ColdLoadProfileError(
            "p3dm_load_component does not have a bounded in-program body"
        )
    start_offset = body_start - PROGRAM_LOAD_ADDRESS
    end_offset = body_end - PROGRAM_LOAD_ADDRESS
    body = image[start_offset:end_offset]
    result: list[PhaseSpan] = []
    for spec in PHASE_SPECS:
        target = int(symbols[spec.target_symbol])
        if not 0 <= target <= 0xFFFFFF:
            raise ColdLoadProfileError(
                f"{spec.target_symbol} lies outside 24-bit address space"
            )
        encoded = bytes((0xCD,)) + target.to_bytes(3, "little")
        offsets = _call_offsets(body, encoded)
        if len(offsets) != 1:
            raise ColdLoadProfileError(
                f"expected one top-level call to {spec.target_symbol}, "
                f"found {len(offsets)}"
            )
        call = body_start + offsets[0]
        result.append(
            PhaseSpan(spec.name, spec.target_symbol, target, call, call + 4)
        )

    calls = [item.call for item in result]
    if calls != sorted(calls) or len(calls) != len(set(calls)):
        raise ColdLoadProfileError("cold-load phase call order changed")
    for previous, current in zip(result, result[1:]):
        if previous.post_call > current.call:
            raise ColdLoadProfileError(
                f"cold-load phases overlap: {previous.name}, {current.name}"
            )
    shared = shared_boundary_roles(result)
    expected_shared = {
        result[2].post_call: (
            "mirror_validated_z.post_call",
            "upload_vdu_staging.call",
        )
    }
    if shared != expected_shared:
        raise ColdLoadProfileError(
            f"cold-load shared boundary topology changed: {shared!r}"
        )
    return tuple(result)


def boundary_roles(phases: Sequence[PhaseSpan]) -> dict[int, tuple[str, ...]]:
    roles: dict[int, list[str]] = {}
    for phase in phases:
        roles.setdefault(phase.call, []).append(f"{phase.name}.call")
        roles.setdefault(phase.post_call, []).append(
            f"{phase.name}.post_call"
        )
    return {address: tuple(names) for address, names in roles.items()}


def shared_boundary_roles(
    phases: Sequence[PhaseSpan],
) -> dict[int, tuple[str, ...]]:
    return {
        address: roles
        for address, roles in boundary_roles(phases).items()
        if len(roles) > 1
    }


def execution_boundary_sequence(
    phases: Sequence[PhaseSpan],
) -> tuple[int, ...]:
    sequence: list[int] = []
    for phase in phases:
        for address in (phase.call, phase.post_call):
            if not sequence or sequence[-1] != address:
                sequence.append(address)
    if len(sequence) != len(set(sequence)):
        raise ColdLoadProfileError(
            "a cold-load boundary repeats non-consecutively"
        )
    return tuple(sequence)


class ColdLoadCycleProfiler:
    """Service every unique phase boundary for an exact number of records."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        phases: Sequence[PhaseSpan],
        expected_records: int,
        start_offset: int = 0,
    ) -> None:
        if expected_records <= 0:
            raise ValueError("expected_records must be positive")
        self.process = process
        self.boundaries = execution_boundary_sequence(phases)
        self.expected_records = expected_records
        self.cursor = start_offset
        self.event_index = 0
        self.record_count = 0
        self.current_pc: int | None = None
        self.waiting_for_state = False
        self.complete = False

    def service(self, contents: str) -> None:
        if self.complete:
            return
        if not self.waiting_for_state:
            pause = staged.SELECTOR_PAUSE_RE.search(contents, self.cursor)
            if pause is None:
                return
            candidates = []
            for address in self.boundaries:
                marker = contents.find(f"* {address:06x}:", pause.end())
                if marker >= 0:
                    candidates.append((marker, address))
            if not candidates:
                return
            marker, address = min(candidates)
            expected = self.boundaries[self.event_index]
            if address != expected:
                raise ColdLoadProfileError(
                    "cold-load breakpoint order changed: "
                    f"{address:06x} != {expected:06x} at record "
                    f"{self.record_count} event {self.event_index}"
                )
            self.current_pc = address
            self.cursor = marker + len(f"* {address:06x}:")
            self.waiting_for_state = True
            debugger.write_debugger(self.process, "state")
            return

        cycles = staged.SELECTOR_CYCLES_RE.search(contents, self.cursor)
        if cycles is None:
            return
        value = int(cycles.group(1))
        if value < 0:
            raise ColdLoadProfileError("debugger reported negative guest cycles")
        self.cursor = cycles.end()
        self.waiting_for_state = False
        self.current_pc = None
        self.event_index += 1
        if self.event_index == len(self.boundaries):
            self.event_index = 0
            self.record_count += 1
        if self.record_count == self.expected_records:
            for address in self.boundaries:
                debugger.write_debugger(self.process, f"delete 0x{address:x}")
            self.complete = True
        debugger.write_debugger(self.process, "continue")

    def require_complete(self) -> dict[str, object]:
        if (
            not self.complete
            or self.record_count != self.expected_records
            or self.event_index != 0
            or self.waiting_for_state
        ):
            raise ColdLoadProfileError(
                "cold-load cycle profile is incomplete: "
                f"records={self.record_count}/{self.expected_records} "
                f"event={self.event_index}/{len(self.boundaries)}"
            )
        return {
            "record_count": self.record_count,
            "unique_breakpoint_count": len(self.boundaries),
            "unique_breakpoints": list(self.boundaries),
        }


def parse_phase_cycles(
    contents: str,
    phases: Sequence[PhaseSpan],
    expected_records: int,
) -> dict[str, list[int]]:
    """Parse phase pairs and prove exact cross-phase record ordering."""

    pairs_by_name = {}
    for phase in phases:
        pairs = parse_selector_cycle_pairs(
            contents,
            entry_address=phase.call,
            post_call_address=phase.post_call,
        )
        if len(pairs) != expected_records:
            raise ColdLoadProfileError(
                f"{phase.name} has {len(pairs)} samples, "
                f"expected {expected_records}"
            )
        pairs_by_name[phase.name] = pairs

    for index in range(expected_records):
        previous = None
        for phase in phases:
            pair = pairs_by_name[phase.name][index]
            if pair.entry.line_number >= pair.post_call.line_number:
                raise ColdLoadProfileError(
                    f"{phase.name} record {index} has a reversed pair"
                )
            if previous is not None:
                previous_phase, previous_pair = previous
                shared = previous_phase.post_call == phase.call
                if shared:
                    same_state = (
                        previous_pair.post_call.line_number
                        == pair.entry.line_number
                        and previous_pair.post_call.cycles_line_number
                        == pair.entry.cycles_line_number
                    )
                    if not same_state:
                        raise ColdLoadProfileError(
                            f"record {index} did not coalesce shared boundary "
                            f"{phase.call:06x}"
                        )
                elif previous_pair.post_call.line_number >= pair.entry.line_number:
                    raise ColdLoadProfileError(
                        f"record {index} phase order changed between "
                        f"{previous_phase.name} and {phase.name}"
                    )
            previous = (phase, pair)
        if index:
            prior = pairs_by_name[phases[-1].name][index - 1]
            current = pairs_by_name[phases[0].name][index]
            if prior.post_call.line_number >= current.entry.line_number:
                raise ColdLoadProfileError(
                    f"cold-load record order changed at record {index}"
                )
    return {
        phase.name: [
            pair.selector_cycles for pair in pairs_by_name[phase.name]
        ]
        for phase in phases
    }


def _uint(record: Mapping[str, object], name: str, order: int) -> int:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ColdLoadProfileError(
            f"initial record {order} has invalid {name}: {value!r}"
        )
    return value


def validate_record_bindings(
    expected: Sequence[Mapping[str, object]],
    publications: Sequence[MeshReplaceRecord],
    phase_cycles: Mapping[str, Sequence[int]],
) -> list[dict[str, object]]:
    """Bind nth exact phase sample to nth manifest record and VDP witness."""

    count = len(expected)
    if count == 0 or len(publications) != count:
        raise ColdLoadProfileError(
            f"publication count {len(publications)} != record count {count}"
        )
    if set(phase_cycles) != set(PHASE_NAMES):
        raise ColdLoadProfileError(
            f"phase sample names changed: {sorted(phase_cycles)}"
        )
    for name, samples in phase_cycles.items():
        if len(samples) != count or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in samples
        ):
            raise ColdLoadProfileError(
                f"phase {name} does not contain {count} non-negative samples"
            )

    result = []
    publication_fields = {
        "data_bytes": "data_bytes",
        "vertices": "vertices",
        "position_indices": "position_indices",
        "texture_coordinates": "texture_coordinates",
        "texture_indices": "texture_indices",
    }
    for order, (record, publication) in enumerate(zip(expected, publications)):
        if _uint(record, "order", order) != order:
            raise ColdLoadProfileError(f"initial record order changed at {order}")
        values = {
            name: _uint(record, name, order)
            for name in (
                "bytes",
                "data_bytes",
                "vertices",
                "position_indices",
                "texture_coordinates",
                "texture_indices",
                "triangles",
                "mesh_id",
                "object_id",
                "slot",
                "lod",
                "identity_q",
                "identity_r",
            )
        }
        if values["mesh_id"] != values["slot"] + 1 or values[
            "object_id"
        ] != values["mesh_id"]:
            raise ColdLoadProfileError(
                f"initial record {order} cold slot identity changed"
            )
        if values["position_indices"] != values["texture_indices"]:
            raise ColdLoadProfileError(
                f"initial record {order} index streams differ"
            )
        if values["position_indices"] != values["triangles"] * 3:
            raise ColdLoadProfileError(
                f"initial record {order} triangle count changed"
            )
        computed_data = (
            6 * values["vertices"]
            + 2 * values["position_indices"]
            + 4 * values["texture_coordinates"]
            + 2 * values["texture_indices"]
        )
        if values["data_bytes"] != computed_data:
            raise ColdLoadProfileError(
                f"initial record {order} DATA byte equation changed"
            )
        expected_file_bytes = P3DM_DATA_OFFSET + (
            (values["data_bytes"] + 3) & ~3
        )
        if values["bytes"] != expected_file_bytes:
            raise ColdLoadProfileError(
                f"initial record {order} container byte equation changed"
            )
        if publication.stage_buffer_id != STAGE_BUFFER_ID:
            raise ColdLoadProfileError(
                f"record {order} used stage {publication.stage_buffer_id}"
            )
        if publication.mesh_id != values["mesh_id"]:
            raise ColdLoadProfileError(
                f"record {order} mesh ID {publication.mesh_id} != "
                f"{values['mesh_id']}"
            )
        for manifest_name, publication_name in publication_fields.items():
            actual = getattr(publication, publication_name)
            if actual != values[manifest_name]:
                raise ColdLoadProfileError(
                    f"record {order} {manifest_name} {actual} != "
                    f"{values[manifest_name]}"
                )

        path = record.get("path")
        checksum = record.get("sha256")
        level = record.get("level")
        if not isinstance(path, str) or not path:
            raise ColdLoadProfileError(f"initial record {order} has no path")
        if (
            not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise ColdLoadProfileError(
                f"initial record {order} has invalid checksum"
            )
        if not isinstance(level, str) or not level:
            raise ColdLoadProfileError(f"initial record {order} has no level")
        cycles = {name: int(phase_cycles[name][order]) for name in PHASE_NAMES}
        result.append(
            {
                "order": order,
                "path": path,
                "file_bytes": values["bytes"],
                "file_sha256": checksum,
                "level": level,
                "lod": values["lod"],
                "identity": [values["identity_q"], values["identity_r"]],
                "slot": values["slot"],
                "mesh_id": values["mesh_id"],
                "object_id": values["object_id"],
                "data_bytes": values["data_bytes"],
                "counts": {
                    "vertices": values["vertices"],
                    "position_indices": values["position_indices"],
                    "texture_coordinates": values["texture_coordinates"],
                    "texture_indices": values["texture_indices"],
                    "triangles": values["triangles"],
                },
                "phase_guest_cycles": cycles,
                "measured_phase_guest_cycles_total": sum(cycles.values()),
            }
        )
    return result


def shutdown_debugger(
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
        "final cold-profile debugger pause",
    )
    debugger.write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise ColdLoadProfileError("debugger did not exit after cold profile") from error
    if process.returncode != 0:
        raise ColdLoadProfileError(
            f"debugger shutdown returned {process.returncode}"
        )
    return log_path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    source_program = staged.require_file(
        arguments.program, "accepted regular fixture"
    )
    source_symbols = staged.require_file(arguments.symbols, "accepted symbols")
    assembled = staged.require_file(
        staged.ASSEMBLED_PROGRAM, "tracked accepted regular fixture"
    )
    if sha256(source_program) != sha256(assembled):
        raise SystemExit("profile program does not match the accepted fixture")
    emulator = staged.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = staged.require_file(input_trace.MOS_BINARY, "MOS image")
    vdp = staged.require_file(arguments.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    program = output / "accepted-regular-lod.profiled.bin"
    symbols_path = output / "accepted-regular-lod.profiled.symbols"
    shutil.copyfile(source_program, program)
    shutil.copyfile(source_symbols, symbols_path)
    if sha256(program) != sha256(source_program) or sha256(
        symbols_path
    ) != sha256(source_symbols):
        raise SystemExit("failed to pin exact profile inputs in evidence root")

    symbols = staged.parse_symbols(symbols_path)
    try:
        phases = resolve_phase_spans(program, symbols)
        fixture_contract = regular_capture.validate_fixture_contract(
            regular_capture.FIXTURE,
            program,
            regular_capture.MANIFEST,
            regular_capture.WORLD,
        )
        expected_records = regular_capture.initial_records()
    except ColdLoadProfileError as error:
        raise SystemExit(f"regular-LOD cold profile setup failed: {error}") from error
    if len(expected_records) != EXPECTED_RECORDS:
        raise SystemExit("accepted cold-fill record count changed")

    log_path = output / "emulator.log"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /survey\r\n"
        b"load P3DRGL.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    breakpoints = execution_boundary_sequence(phases)
    roles = boundary_roles(phases)
    profiler: ColdLoadCycleProfiler | None = None
    process: subprocess.Popen[bytes] | None = None
    deadline = time.monotonic() + arguments.timeout
    shutdown = "not-started"

    with (
        tempfile.TemporaryDirectory(prefix="regular-cold-profile-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="regular-cold-profile-run-") as run_name,
    ):
        sd_root = Path(sd_name)
        staged.stage_fixture(sd_root, program)
        (sd_root / "autoexec.txt").write_bytes(autoexec)
        environment = os.environ.copy()
        environment.update(
            {
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
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
            str(vdp),
            "--sdcard",
            str(sd_root),
            "--verbose",
            "--debugger",
            "-z",
            "-u",
        ]
        for address in breakpoints:
            command.extend(("--breakpoint", f"0x{address:x}"))
        (output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "mode": MODE,
                    "expected_records": EXPECTED_RECORDS,
                    "program": artifact(program),
                    "symbols": artifact(symbols_path),
                    "source_program": artifact(source_program),
                    "source_symbols": artifact(source_symbols),
                    "phases": [phase.as_dict() for phase in phases],
                    "breakpoint_roles": {
                        f"0x{address:06x}": list(names)
                        for address, names in roles.items()
                    },
                    "environment": {
                        "SDL_VIDEODRIVER": "dummy",
                        "SDL_AUDIODRIVER": "dummy",
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
                profiler = ColdLoadCycleProfiler(
                    process, phases, EXPECTED_RECORDS
                )
                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: staged.COLD_RENDER_MARKER in value,
                    "profiled 227-record regular-LOD cold endpoint",
                    service=profiler.service,
                )
                profiler.require_complete()
                contents = shutdown_debugger(process, log_path, deadline)
                shutdown = "debugger-exit-after-complete-cold-fill"
        finally:
            if process is not None and process.poll() is None:
                shutdown = input_trace.stop_process(process)

    assert process is not None and profiler is not None
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    try:
        live = profiler.require_complete()
        cold = staged.validate_cold_endpoint(contents)
        phase_cycles = parse_phase_cycles(
            contents, phases, EXPECTED_RECORDS
        )
        publications = parse_mesh_replace_records(contents)
        records = validate_record_bindings(
            expected_records, publications, phase_cycles
        )
    except (ColdLoadProfileError, ProfileEvidenceError, staged.EvidenceError) as error:
        raise SystemExit(
            f"regular-LOD cold-load cycle profile failed: {error}"
        ) from error
    if process.returncode != 0:
        raise SystemExit(f"emulator shutdown returned {process.returncode}")

    phase_reports = {}
    for phase in phases:
        samples = phase_cycles[phase.name]
        phase_reports[phase.name] = {
            **phase.as_dict(),
            "cycles": samples,
            "summary": summarize_distribution(samples).as_dict(),
        }
    totals = [
        int(record["measured_phase_guest_cycles_total"])
        for record in records
    ]
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "mode": MODE,
        "scope": {
            "fresh_process": True,
            "accepted_fixture": True,
            "complete_cold_fill": True,
            "record_count": EXPECTED_RECORDS,
            "measurement": "paused-debugger-call-to-post-call-guest-cycles",
            "measured_phases": list(PHASE_NAMES),
            "render_timing_source": None,
            "render_timing_excluded": True,
            "host_wall_time_excluded": True,
            "native_vdp_microseconds_excluded": True,
            "unmeasured": [
                "provider path and request setup",
                "post-load scale and placement",
                "manager activation and render submission",
                "physical SD-card latency",
            ],
        },
        "identity": {
            "program": artifact(program),
            "symbols": artifact(symbols_path),
            "source_program": artifact(source_program),
            "source_symbols": artifact(source_symbols),
            "manager_manifest": artifact(regular_capture.MANIFEST),
            "world_manifest": artifact(regular_capture.WORLD),
            "emulator": artifact(emulator),
            "mos": artifact(mos),
            "vdp": artifact(vdp),
        },
        "fixture_contract": fixture_contract,
        "breakpoints": {
            **live,
            "roles": {
                f"0x{address:06x}": list(names)
                for address, names in roles.items()
            },
            "shared_boundaries": {
                f"0x{address:06x}": list(names)
                for address, names in shared_boundary_roles(phases).items()
            },
        },
        "cold_endpoint": cold,
        "phases": phase_reports,
        "records": records,
        "measured_phase_guest_cycles_total": {
            "cycles": totals,
            "summary": summarize_distribution(totals).as_dict(),
            "aggregate": sum(totals),
        },
        "binding": {
            "manifest_record_order_exact": True,
            "manifest_file_bytes_and_sha256_validated": True,
            "vdp_publication_order_and_counts_exact": True,
            "phase_sample_count_per_record_exact": True,
        },
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Accepted regular-LOD cold-load cycle profile passed: {report_path}")
    print(
        f"records={EXPECTED_RECORDS} unique_breakpoints={len(breakpoints)} "
        f"aggregate_measured_phase_cycles={sum(totals)}"
    )
    for phase in phases:
        summary = phase_reports[phase.name]["summary"]
        print(
            f"{phase.name}: total={summary['total']} "
            f"median={summary['median']} p95={summary['p95']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
