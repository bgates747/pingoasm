#!/usr/bin/env python3
"""Live-profile the accepted P3DRGL binary under pinned and THRE MOS images.

The normative pair has only three debugger boundaries per publication:
``p3dm_read_container`` call, ``p3dm_upload_data`` call, and the matching
startup/loop ``submit_current_render`` call.  No breakpoint occurs after the
upload begins and before submit.  The nth successful VDP mesh publication must
already precede that submit boundary, making read-to-submit and
upload-to-submit publication-complete comparisons.

A separate fresh pair measures the ordinary five loader call spans.  Those
spans are diagnostic only: a MOS-wide THRE change also affects consolidate,
command 50, and every other UART0 TX caller, so ordinary call/return endpoints
do not leave equivalent transmitter state.
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

import build_regular_lod_mos_uart_thre_sibling as builder
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
DEFAULT_BUILD = builder.DEFAULT_OUTPUT
DEFAULT_OUTPUT = ROOT / "build/evidence/regular-lod-mos-uart-thre-sibling-profile-v3"
REPORT_NAME = "regular-lod-mos-uart-thre-sibling-profile.json"
SCHEMA = "pingo-terrain-regular-lod-mos-uart-thre-sibling-live-profile-v1"
EXPECTED_RECORDS = 227
MAX_POST_ENDPOINT_RENDER_TAIL = 32
PROGRAM_LOAD_ADDRESS = 0x040000
STARTUP_SUBMIT_CALL = 0x0629C1
LOOP_SUBMIT_CALL = 0x062A09
SUBMIT_TARGET = 0x042E27
AUTOEXEC = b"SET KEYBOARD 1\r\ncd /survey\r\nload P3DRGL.BIN\r\nrun\r\n"
AUTOEXEC_SHA256 = "9f6405f015f45625cea87a16c3468ec5ebd79ea95fe512a5b92d05ac107629d4"
PUBLICATION_MARKER = "PINGO_STREAM mesh_replace=ok "
RENDER_LINE_RE = re.compile(r"PINGO_RENDER seq=(\d+)\b([^\r\n]*)")
RENDER_REQUIRED_FIELDS = (
    "bmid", "d", "w", "h", "fmt", "far", "out", "ob", "obt", "ofr",
    "ta", "ti", "tz", "tfr", "tc", "tu", "tg", "tp", "tf", "td",
    "to", "tr", "tv", "pt", "pc", "pz", "pd", "pu", "ps",
)
# ``out`` is renderer timing/overhead, not retained scene state.  In the
# diagnostic accounting it contributes to the unattributed command time
# (cmd - (pre + render_us + out)), and can therefore change in the bounded
# shutdown tail without any scene mutation.  Keep it mandatory and reported,
# but exclude it from the structural endpoint-stability comparison.
RENDER_STABLE_FIELDS = tuple(
    name for name in RENDER_REQUIRED_FIELDS if name != "out"
)
POST_ENDPOINT_MUTATION_MARKERS = (
    PUBLICATION_MARKER,
    "PINGO_STREAM object_active=ok ",
    "PINGO_WIDE object_translation=ok ",
)


class MosUartThreProfileError(RuntimeError):
    """A build, boundary, publication, semantic, or timing gate failed."""


@dataclass(frozen=True, slots=True)
class NormativeLayout:
    read_call: int
    upload_call: int
    startup_submit_call: int
    loop_submit_call: int

    def events_for_record(self, record: int) -> tuple[tuple[str, int], ...]:
        submit = self.startup_submit_call if record == 0 else self.loop_submit_call
        return (
            ("read_call", self.read_call),
            ("upload_call", self.upload_call),
            ("publication_complete_submit", submit),
        )

    @property
    def breakpoints(self) -> tuple[int, ...]:
        addresses = (
            self.read_call,
            self.upload_call,
            self.startup_submit_call,
            self.loop_submit_call,
        )
        if len(addresses) != len(set(addresses)):
            raise MosUartThreProfileError("normative boundaries are not unique")
        return addresses

    def as_dict(self) -> dict[str, object]:
        return {
            "events_per_record": 3,
            "read_call": self.read_call,
            "upload_call": self.upload_call,
            "startup_submit_call": self.startup_submit_call,
            "loop_submit_call": self.loop_submit_call,
            "submit_target": SUBMIT_TARGET,
            "no_breakpoint_after_upload_before_submit": True,
        }


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
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
        raise MosUartThreProfileError(f"missing artifact: {resolved}")
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
        raise MosUartThreProfileError(f"unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise MosUartThreProfileError(f"JSON root is not an object: {path}")
    return value


def validate_build(build: Path) -> tuple[Path, Path, dict[str, object]]:
    receipt_path = build / builder.REPORT_NAME
    receipt = load_json(receipt_path)
    if receipt.get("schema") != builder.SCHEMA or receipt.get("qualified") is not True:
        raise MosUartThreProfileError("MOS sibling build receipt is not qualified")
    scope = receipt.get("scope")
    if not isinstance(scope, dict) or any(
        scope.get(name) is not False
        for name in (
            "external_fab_checkout_modified",
            "pinned_mos_modified",
            "pinned_map_modified",
            "accepted_application_modified",
            "accepted_artifacts_modified",
            "docs_modified",
        )
    ):
        raise MosUartThreProfileError("MOS sibling build scope changed")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        raise MosUartThreProfileError("MOS sibling receipt omits artifacts")

    def checked(name: str, filename: str, digest: str) -> Path:
        path = build / filename
        entry = artifacts.get(name)
        if not path.is_file() or not isinstance(entry, dict):
            raise MosUartThreProfileError(f"missing MOS artifact: {name}")
        if (
            entry.get("key") != f"artifacts/{filename}"
            or entry.get("bytes") != builder.PINNED_MOS_BYTES
            or entry.get("sha256") != digest
            or sha256(path) != digest
        ):
            raise MosUartThreProfileError(f"MOS artifact identity changed: {name}")
        return path

    control = checked(
        "control_mos", builder.CONTROL_MOS_NAME, builder.PINNED_MOS_SHA256
    )
    candidate = checked(
        "patched_mos", builder.CANDIDATE_MOS_NAME, builder.PATCHED_MOS_SHA256
    )
    patch = receipt.get("patch")
    if not isinstance(patch, dict) or (
        patch.get("changed_offsets") != [builder.UART0_TX_MASK_OFFSET]
        or patch.get("before") != builder.TEMT_MASK
        or patch.get("after") != builder.THRE_MASK
        or patch.get("all_other_bytes_exact") is not True
        or patch.get("reverse_patch_exact") is not True
    ):
        raise MosUartThreProfileError("MOS one-byte patch receipt changed")
    validate_crc1_control(build, receipt)
    runtime_corpus = receipt.get("runtime_corpus")
    if not isinstance(runtime_corpus, dict) or (
        runtime_corpus.get("qualified") is not True
        or runtime_corpus.get("coverage_digest_sha256")
        != builder.EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256
        or runtime_corpus.get("aggregates")
        != {
            "records": builder.EXPECTED_RECORDS,
            "container_bytes": builder.EXPECTED_CONTAINER_BYTES,
            "data_bytes": builder.EXPECTED_DATA_BYTES,
            "maximum_record_bytes": builder.EXPECTED_MAXIMUM_RECORD_BYTES,
        }
        or not isinstance(runtime_corpus.get("records"), list)
        or len(runtime_corpus["records"]) != builder.EXPECTED_RECORDS
    ):
        raise MosUartThreProfileError("runtime corpus build binding changed")
    return control, candidate, receipt


def validate_crc1_control(
    build: Path, receipt: Mapping[str, object] | None = None
) -> tuple[Path, Path, Path]:
    """Resolve the MOS build's private copy of the historical CRC1 trio."""

    build = build.expanduser().resolve()
    if receipt is None:
        receipt = load_json(build / builder.REPORT_NAME)
    if receipt.get("schema") != builder.SCHEMA or receipt.get("qualified") is not True:
        raise MosUartThreProfileError("MOS sibling build receipt is not qualified")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise MosUartThreProfileError("MOS sibling receipt omits artifacts")
    paths: list[Path] = []
    for name, (suffix, size, digest) in builder.CRC1_CONTROL_ARTIFACTS.items():
        path = build / f"{builder.crc_builder.CONTROL_PROGRAM_STEM}.{suffix}"
        entry = artifacts.get(name)
        if (
            path.is_symlink()
            or not path.is_file()
            or not isinstance(entry, Mapping)
            or dict(entry)
            != {
                "key": f"artifacts/{path.name}",
                "bytes": size,
                "sha256": digest,
            }
            or path.stat().st_size != size
            or sha256(path) != digest
        ):
            raise MosUartThreProfileError(
                f"private CRC1 MOS-build artifact identity changed: {name}"
            )
        paths.append(path)
    control = receipt.get("historical_crc1_control")
    if not isinstance(control, Mapping) or (
        control.get("canonical_target_consulted") is not False
        or control.get("program_sha256")
        != builder.crc_builder.ACCEPTED_PROGRAM_SHA256
        or control.get("crc_policy") != "legacy-memory-bitwise"
    ):
        raise MosUartThreProfileError("private CRC1 MOS-build binding changed")
    return paths[0], paths[1], paths[2]


def _offsets(payload: bytes, needle: bytes) -> list[int]:
    result: list[int] = []
    cursor = 0
    while True:
        offset = payload.find(needle, cursor)
        if offset < 0:
            return result
        result.append(offset)
        cursor = offset + 1


def resolve_normative_layout(program: Path, symbols_path: Path) -> NormativeLayout:
    symbols = staged.parse_symbols(symbols_path)
    phases = cold.resolve_phase_spans(program, symbols)
    required = {"main", "manager_survey_apply_radius_request", "submit_current_render"}
    missing = sorted(required - symbols.keys())
    if missing:
        raise MosUartThreProfileError(f"accepted symbols omit: {missing}")
    if symbols["submit_current_render"] != SUBMIT_TARGET:
        raise MosUartThreProfileError("submit_current_render target changed")
    image = program.read_bytes()
    main_start = symbols["main"]
    main_end = symbols["manager_survey_apply_radius_request"]
    if not PROGRAM_LOAD_ADDRESS <= main_start < main_end <= PROGRAM_LOAD_ADDRESS + len(image):
        raise MosUartThreProfileError("accepted main body is not bounded")
    body = image[main_start - PROGRAM_LOAD_ADDRESS : main_end - PROGRAM_LOAD_ADDRESS]
    encoded = bytes((0xCD,)) + SUBMIT_TARGET.to_bytes(3, "little")
    calls = [main_start + offset for offset in _offsets(body, encoded)]
    if calls != [STARTUP_SUBMIT_CALL, LOOP_SUBMIT_CALL]:
        raise MosUartThreProfileError(f"submit call sites changed: {calls}")
    windows = {
        STARTUP_SUBMIT_CALL: bytes.fromhex("cd272e04cd6c0004"),
        LOOP_SUBMIT_CALL: bytes.fromhex("cd272e0418b6cdf4"),
    }
    for address, expected in windows.items():
        actual = image[address - PROGRAM_LOAD_ADDRESS : address - PROGRAM_LOAD_ADDRESS + 8]
        if actual != expected:
            raise MosUartThreProfileError(
                f"submit opcode window changed at 0x{address:06x}"
            )
    by_name = {phase.name: phase for phase in phases}
    layout = NormativeLayout(
        read_call=by_name["read_container_fatfs"].call,
        upload_call=by_name["upload_vdu_staging"].call,
        startup_submit_call=STARTUP_SUBMIT_CALL,
        loop_submit_call=LOOP_SUBMIT_CALL,
    )
    layout.breakpoints
    return layout


class NormativeProfiler:
    """Service three events per record and require publication before submit."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        layout: NormativeLayout,
        expected_records: int,
    ) -> None:
        self.process = process
        self.layout = layout
        self.expected_records = expected_records
        self.record = 0
        self.event = 0
        self.cursor = 0
        self.waiting = "pause"
        self.complete = False
        self.state_count = 0

    def service(self, contents: str) -> None:
        if self.complete:
            return
        events = self.layout.events_for_record(self.record)
        expected_name, expected_address = events[self.event]
        if self.waiting == "pause":
            pause = staged.SELECTOR_PAUSE_RE.search(contents, self.cursor)
            if pause is None:
                return
            candidates = []
            for address in self.layout.breakpoints:
                marker = contents.find(f"* {address:06x}:", pause.end())
                if marker >= 0:
                    candidates.append((marker, address))
            if not candidates:
                return
            marker, address = min(candidates)
            if address != expected_address:
                raise MosUartThreProfileError(
                    f"normative boundary order changed at record {self.record}: "
                    f"0x{address:06x} != {expected_name}=0x{expected_address:06x}"
                )
            if expected_name == "publication_complete_submit":
                publications = contents[:marker].count(PUBLICATION_MARKER)
                if publications != self.record + 1:
                    raise MosUartThreProfileError(
                        f"record {self.record} reached submit with {publications} "
                        f"successful publications, expected {self.record + 1}"
                    )
            self.cursor = marker + len(f"* {address:06x}:")
            self.waiting = "state"
            debugger.write_debugger(self.process, "state")
            return
        cycles = staged.SELECTOR_CYCLES_RE.search(contents, self.cursor)
        if cycles is None:
            return
        self.cursor = cycles.end()
        self.state_count += 1
        self.waiting = "pause"
        self.event += 1
        if self.event == len(events):
            self.event = 0
            self.record += 1
        if self.record == self.expected_records:
            for address in self.layout.breakpoints:
                debugger.write_debugger(self.process, f"delete 0x{address:x}")
            self.complete = True
        debugger.write_debugger(self.process, "continue")

    def require_complete(self) -> dict[str, object]:
        if (
            not self.complete
            or self.record != self.expected_records
            or self.event != 0
            or self.waiting != "pause"
            or self.state_count != self.expected_records * 3
        ):
            raise MosUartThreProfileError(
                f"incomplete normative profile: records={self.record}, "
                f"event={self.event}, states={self.state_count}"
            )
        return {
            "record_count": self.record,
            "events_per_record": 3,
            "cycle_state_count": self.state_count,
            "publication_before_submit_count": self.record,
        }


STATE_RE = re.compile(r"\*\s+([0-9A-Fa-f]{6}):")
CYCLES_RE = re.compile(r"Cycles since last break:\s*(\d+)")


def normative_expected_events(
    layout: NormativeLayout, expected_records: int
) -> tuple[tuple[int, str, int], ...]:
    return tuple(
        (record, name, address)
        for record in range(expected_records)
        for name, address in layout.events_for_record(record)
    )


def parse_normative_states(
    contents: str, layout: NormativeLayout, expected_records: int
) -> list[dict[str, int | str]]:
    targets = set(layout.breakpoints)
    pending: tuple[int, int, int] | None = None
    states: list[tuple[int, int, int, int]] = []
    log_offset = 0
    for line_number, raw_line in enumerate(contents.splitlines(keepends=True), 1):
        line = debugger.ANSI_RE.sub("", raw_line)
        matches = tuple(STATE_RE.finditer(line))
        if len(matches) > 1:
            raise MosUartThreProfileError("debugger line has multiple states")
        if matches:
            address = int(matches[0].group(1), 16)
            if pending is not None and address != pending[0]:
                raise MosUartThreProfileError("debugger state lacks cycle report")
            if pending is None:
                pending = (
                    (address, line_number, log_offset + raw_line.find("*"))
                    if address in targets
                    else None
                )
        cycles = tuple(CYCLES_RE.finditer(line))
        if len(cycles) > 1:
            raise MosUartThreProfileError("debugger line has multiple cycle reports")
        if cycles and pending is not None:
            states.append(
                (pending[0], pending[1], pending[2], int(cycles[0].group(1)))
            )
            pending = None
        log_offset += len(raw_line)
    if pending is not None:
        raise MosUartThreProfileError("final debugger state lacks cycle report")
    expected = normative_expected_events(layout, expected_records)
    if len(states) != len(expected):
        raise MosUartThreProfileError(
            f"parsed {len(states)} normative states, expected {len(expected)}"
        )
    result = []
    for (address, line_number, marker_offset, cycles), (record, name, wanted) in zip(
        states, expected
    ):
        if address != wanted:
            raise MosUartThreProfileError(
                f"normative state order changed: 0x{address:06x} != 0x{wanted:06x}"
            )
        result.append(
            {
                "record": record,
                "event": name,
                "address": address,
                "line_number": line_number,
                "breakpoint_log_offset": marker_offset,
                "cycles_since_previous_boundary": cycles,
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


def publication_marker_offsets(contents: str) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    while True:
        offset = contents.find(PUBLICATION_MARKER, cursor)
        if offset < 0:
            return offsets
        offsets.append(offset)
        cursor = offset + len(PUBLICATION_MARKER)


def bind_publications(
    publications: Sequence[MeshReplaceRecord],
) -> list[dict[str, object]]:
    expected = regular_capture.initial_records()
    zero_cycles = {name: [0] * EXPECTED_RECORDS for name in cold.PHASE_NAMES}
    return cold.validate_record_bindings(expected, publications, zero_cycles)


def reconstruct_normative_records(
    states: Sequence[Mapping[str, int | str]],
    publications: Sequence[MeshReplaceRecord],
    exact_publication_offsets: Sequence[int],
    bound: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if (
        not publications
        or len(states) != len(publications) * 3
        or len(publications) != len(bound)
        or len(exact_publication_offsets) != len(publications)
    ):
        raise MosUartThreProfileError("normative record cardinality changed")
    records = []
    for order, (publication, publication_offset, binding) in enumerate(
        zip(publications, exact_publication_offsets, bound)
    ):
        chunk = states[order * 3 : (order + 1) * 3]
        by_name = {str(item["event"]): item for item in chunk}
        if set(by_name) != {
            "read_call", "upload_call", "publication_complete_submit"
        }:
            raise MosUartThreProfileError(f"record {order} normative events changed")
        read = by_name["read_call"]
        upload = by_name["upload_call"]
        submit = by_name["publication_complete_submit"]
        if not (
            int(upload["breakpoint_log_offset"])
            < publication_offset
            < int(submit["breakpoint_log_offset"])
        ):
            raise MosUartThreProfileError(
                f"record {order} publication does not occur between upload and submit"
            )
        upload_to_submit = int(submit["cycles_since_previous_boundary"])
        read_to_submit = (
            int(upload["cycles_since_previous_boundary"]) + upload_to_submit
        )
        records.append(
            {
                "order": order,
                "path": binding["path"],
                "file_sha256": binding["file_sha256"],
                "data_bytes": binding["data_bytes"],
                "mesh_id": binding["mesh_id"],
                "publication_line": publication.line_number,
                "publication_marker_log_offset": publication_offset,
                "publication_line_start_log_offset": publication.log_offset,
                "upload_call_line": upload["line_number"],
                "upload_call_log_offset": upload["breakpoint_log_offset"],
                "submit_line": submit["line_number"],
                "submit_log_offset": submit["breakpoint_log_offset"],
                "submit_call": submit["address"],
                "upload_to_publication_complete_submit_guest_cycles": upload_to_submit,
                "read_to_publication_complete_submit_guest_cycles": read_to_submit,
            }
        )
    return records


def shutdown(
    process: subprocess.Popen[bytes], log_path: Path, deadline: float
) -> None:
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    pause_count = debugger.ANSI_RE.sub("", contents).count("CPU paused")
    os.kill(process.pid, signal.SIGINT)
    staged.wait_for_log(
        log_path,
        process,
        deadline,
        lambda value: debugger.ANSI_RE.sub("", value).count("CPU paused") > pause_count,
        "final MOS-profile debugger pause",
    )
    debugger.write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise MosUartThreProfileError("debugger did not exit") from error
    if process.returncode != 0:
        raise MosUartThreProfileError(
            f"debugger shutdown returned {process.returncode}"
        )


def emulator_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
    local_sdl = Path.home() / ".local/lib"
    old = environment.get("LD_LIBRARY_PATH")
    environment["LD_LIBRARY_PATH"] = str(local_sdl) if not old else f"{local_sdl}:{old}"
    return environment


def emulator_command(
    sd_root: Path,
    vdp: Path,
    mos: Path,
    expected_mos_sha256: str,
    breakpoints: Sequence[int],
) -> list[str]:
    emulator = staged.require_file(input_trace.FAB_BINARY, "Fab executable")
    if sha256(mos) != expected_mos_sha256:
        raise MosUartThreProfileError("run MOS identity changed")
    mos_map = mos.with_suffix(".map")
    if not mos_map.is_file() or sha256(mos_map) != builder.PINNED_MAP_SHA256:
        raise MosUartThreProfileError(
            "run MOS lacks its exact same-stem pinned map required for hostfs"
        )
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


def validate_render_sequence_evidence(contents: str) -> dict[str, object]:
    rows = []
    for match in RENDER_LINE_RE.finditer(contents):
        fields: dict[str, int] = {}
        for name, value in re.findall(r"\b([a-z]+)=(-?\d+)\b", match.group(2)):
            fields[name] = int(value)
        missing = [name for name in RENDER_REQUIRED_FIELDS if name not in fields]
        if missing:
            raise MosUartThreProfileError(
                f"render sequence {match.group(1)} omits required fields: {missing}"
            )
        rows.append(
            {
                "sequence": int(match.group(1)),
                "log_offset": match.start(),
                "stable_counters": {
                    name: fields[name] for name in RENDER_STABLE_FIELDS
                },
                "timing_counters": {"out": fields["out"]},
            }
        )
    sequences = [int(row["sequence"]) for row in rows]
    if (
        len(sequences) < EXPECTED_RECORDS
        or sequences != list(range(len(sequences)))
    ):
        raise MosUartThreProfileError(
            "render sequence is not one exact contiguous prefix beginning at zero"
        )
    tail = sequences[EXPECTED_RECORDS:]
    if len(tail) > MAX_POST_ENDPOINT_RENDER_TAIL:
        raise MosUartThreProfileError(
            f"post-endpoint render tail is too long: {len(tail)}"
        )
    endpoint_row = rows[EXPECTED_RECORDS - 1]
    endpoint_offset = int(endpoint_row["log_offset"])
    endpoint_counters = endpoint_row["stable_counters"]
    for row in rows[EXPECTED_RECORDS:]:
        if row["stable_counters"] != endpoint_counters:
            raise MosUartThreProfileError(
                f"post-endpoint render {row['sequence']} changed stable counters"
            )
    post_endpoint = contents[endpoint_offset:]
    mutations = {
        marker: post_endpoint.count(marker) for marker in POST_ENDPOINT_MUTATION_MARKERS
    }
    if any(mutations.values()):
        raise MosUartThreProfileError(
            f"post-endpoint scene mutation observed: {mutations}"
        )
    return {
        "qualified_prefix": list(range(EXPECTED_RECORDS)),
        "global_sequence_count": len(sequences),
        "global_sequence_last": sequences[-1],
        "post_endpoint_shutdown_tail": tail,
        "post_endpoint_shutdown_tail_count": len(tail),
        "post_endpoint_shutdown_tail_bound": MAX_POST_ENDPOINT_RENDER_TAIL,
        "post_endpoint_tail_is_non_semantic": True,
        "post_endpoint_mutation_counts": mutations,
        "endpoint_stable_counters": endpoint_counters,
        "tail_stable_counters_identical": True,
        "required_render_fields": list(RENDER_REQUIRED_FIELDS),
        "structural_stable_fields": list(RENDER_STABLE_FIELDS),
        "out_required": True,
        "out_classification": "timing_overhead_not_scene_state",
        "endpoint_out": rows[EXPECTED_RECORDS - 1]["timing_counters"]["out"],
        "post_endpoint_tail_out": [
            row["timing_counters"]["out"] for row in rows[EXPECTED_RECORDS:]
        ],
    }


def validate_run_semantics(
    contents: str,
) -> tuple[dict[str, object], list[MeshReplaceRecord], dict[str, object]]:
    endpoint = staged.validate_cold_endpoint(contents)
    publications = parse_mesh_replace_records(contents)
    if len(publications) != EXPECTED_RECORDS:
        raise MosUartThreProfileError("live publication count changed")
    render_evidence = validate_render_sequence_evidence(contents)
    return endpoint, publications, render_evidence


def require_exact_run_copy(path: Path, artifact_name: str) -> None:
    _suffix, expected_bytes, expected_sha256 = builder.CRC1_CONTROL_ARTIFACTS[
        artifact_name
    ]
    if (
        not path.is_file()
        or path.stat().st_size != expected_bytes
        or sha256(path) != expected_sha256
    ):
        raise MosUartThreProfileError(
            f"run-local private CRC1 {artifact_name} identity changed"
        )


def corpus_witness(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "qualified": evidence.get("qualified"),
        "aggregates": evidence.get("aggregates"),
        "coverage_digest_sha256": evidence.get("coverage_digest_sha256"),
        "all_manifest_order_path_size_sha256_and_data_extents_exact": evidence.get(
            "all_manifest_order_path_size_sha256_and_data_extents_exact"
        ),
    }


def write_exact_autoexec(path: Path) -> None:
    path.write_bytes(AUTOEXEC)
    if (
        path.stat().st_size != len(AUTOEXEC)
        or sha256(path) != AUTOEXEC_SHA256
        or path.read_bytes() != AUTOEXEC
    ):
        raise MosUartThreProfileError("run-local autoexec identity changed")


def prepare_run_output(
    output: Path,
    name: str,
    mos: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    run_output = output / name
    run_output.mkdir()
    control_program, _control_listing, control_symbols = validate_crc1_control(
        mos.parent
    )
    program_copy = run_output / "P3DRGL.accepted.bin"
    symbols_copy = run_output / "P3DRGL.accepted.symbols"
    mos_copy = run_output / mos.name
    mos_map_copy = mos_copy.with_suffix(".map")
    shutil.copyfile(control_program, program_copy)
    shutil.copyfile(control_symbols, symbols_copy)
    shutil.copyfile(mos, mos_copy)
    shutil.copyfile(builder.PINNED_MAP, mos_map_copy)
    require_exact_run_copy(program_copy, "legacy_control_program")
    require_exact_run_copy(symbols_copy, "legacy_control_symbols")
    if sha256(mos_map_copy) != builder.PINNED_MAP_SHA256:
        raise MosUartThreProfileError("staged same-stem MOS map identity changed")
    write_exact_autoexec(run_output / "autoexec.txt")
    return run_output, program_copy, symbols_copy, mos_copy, mos_map_copy


def run_normative(
    *,
    variant: str,
    mos: Path,
    mos_sha256: str,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    run_output, program, symbols, mos_copy, mos_map_copy = prepare_run_output(
        output, f"normative-{variant}", mos
    )
    layout = resolve_normative_layout(program, symbols)
    log_path = run_output / "emulator.log"
    process: subprocess.Popen[bytes] | None = None
    profiler: NormativeProfiler | None = None
    corpus_before: dict[str, object] | None = None
    corpus_after: dict[str, object] | None = None
    deadline = time.monotonic() + timeout
    with (
        tempfile.TemporaryDirectory(prefix=f"mos-norm-{variant}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"mos-norm-{variant}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        staged.stage_fixture(sd_root, program)
        corpus_before = builder.validate_runtime_corpus(sd_root / "survey")
        write_exact_autoexec(sd_root / "autoexec.txt")
        command = emulator_command(
            sd_root, vdp, mos_copy, mos_sha256, layout.breakpoints
        )
        command_path = run_output / "command.json"
        command_path.write_text(
            json.dumps(
                {
                    "argv": command,
                    "mode": "normative-publication-complete",
                    "variant": variant,
                    "program": artifact(program),
                    "symbols": artifact(symbols),
                    "mos": artifact(mos_copy),
                    "mos_map": artifact(mos_map_copy),
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
                profiler = NormativeProfiler(process, layout, EXPECTED_RECORDS)
                staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: staged.COLD_RENDER_MARKER in value and profiler.complete,
                    f"{variant} normative cold fill and publication boundaries",
                    service=profiler.service,
                )
                profiler.require_complete()
                shutdown(process, log_path, deadline)
                corpus_after = builder.validate_runtime_corpus(sd_root / "survey")
                if corpus_after != corpus_before:
                    raise MosUartThreProfileError(
                        f"{variant} staged runtime corpus changed during normative run"
                    )
        finally:
            if process is not None and process.poll() is None:
                input_trace.stop_process(process)
    assert (
        process is not None
        and profiler is not None
        and corpus_before is not None
        and corpus_after is not None
    )
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    endpoint, publications, render_evidence = validate_run_semantics(contents)
    bound = bind_publications(publications)
    states = parse_normative_states(contents, layout, EXPECTED_RECORDS)
    exact_publication_offsets = publication_marker_offsets(contents)
    records = reconstruct_normative_records(
        states, publications, exact_publication_offsets, bound
    )
    upload_cycles = [
        int(record["upload_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    read_cycles = [
        int(record["read_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    return {
        "mode": "normative-publication-complete",
        "variant": variant,
        "fresh_process": True,
        "program": artifact(program),
        "symbols": artifact(symbols),
        "mos": artifact(mos_copy),
        "mos_map": artifact(mos_map_copy),
        "runtime_corpus": {
            "before": corpus_witness(corpus_before),
            "after": corpus_witness(corpus_after),
            "unchanged": True,
        },
        "command": artifact(run_output / "command.json"),
        "autoexec": artifact(run_output / "autoexec.txt"),
        "log": artifact(log_path),
        "layout": layout.as_dict(),
        "live": profiler.require_complete(),
        "cold_endpoint": endpoint,
        "publication_semantics": publication_semantics(publications),
        "render_sequences": render_evidence["qualified_prefix"],
        "render_evidence": render_evidence,
        "metrics": {
            "upload_to_publication_complete_submit": {
                "cycles": upload_cycles,
                "summary_all_227": summarize_distribution(upload_cycles).as_dict(),
                "summary_loop_226": summarize_distribution(upload_cycles[1:]).as_dict(),
                "startup_record_0": upload_cycles[0],
                "completion_equivalent": True,
            },
            "read_to_publication_complete_submit": {
                "cycles": read_cycles,
                "summary_all_227": summarize_distribution(read_cycles).as_dict(),
                "summary_loop_226": summarize_distribution(read_cycles[1:]).as_dict(),
                "startup_record_0": read_cycles[0],
                "completion_equivalent": True,
            },
        },
        "records": records,
        "emulator_exit_status": process.returncode,
    }


def run_diagnostic(
    *,
    variant: str,
    mos: Path,
    mos_sha256: str,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    run_output, program, symbols, mos_copy, mos_map_copy = prepare_run_output(
        output, f"diagnostic-{variant}", mos
    )
    symbol_values = staged.parse_symbols(symbols)
    phases = cold.resolve_phase_spans(program, symbol_values)
    boundaries = cold.execution_boundary_sequence(phases)
    log_path = run_output / "emulator.log"
    process: subprocess.Popen[bytes] | None = None
    profiler: cold.ColdLoadCycleProfiler | None = None
    corpus_before: dict[str, object] | None = None
    corpus_after: dict[str, object] | None = None
    deadline = time.monotonic() + timeout
    with (
        tempfile.TemporaryDirectory(prefix=f"mos-diag-{variant}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"mos-diag-{variant}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        staged.stage_fixture(sd_root, program)
        corpus_before = builder.validate_runtime_corpus(sd_root / "survey")
        write_exact_autoexec(sd_root / "autoexec.txt")
        command = emulator_command(sd_root, vdp, mos_copy, mos_sha256, boundaries)
        (run_output / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "mode": "diagnostic-five-call-spans",
                    "variant": variant,
                    "program": artifact(program),
                    "symbols": artifact(symbols),
                    "mos": artifact(mos_copy),
                    "mos_map": artifact(mos_map_copy),
                    "phases": [phase.as_dict() for phase in phases],
                    "breakpoints": list(boundaries),
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
                profiler = cold.ColdLoadCycleProfiler(
                    process, phases, EXPECTED_RECORDS
                )
                staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: staged.COLD_RENDER_MARKER in value and profiler.complete,
                    f"{variant} diagnostic cold fill and phase boundaries",
                    service=profiler.service,
                )
                profiler.require_complete()
                shutdown(process, log_path, deadline)
                corpus_after = builder.validate_runtime_corpus(sd_root / "survey")
                if corpus_after != corpus_before:
                    raise MosUartThreProfileError(
                        f"{variant} staged runtime corpus changed during diagnostic run"
                    )
        finally:
            if process is not None and process.poll() is None:
                input_trace.stop_process(process)
    assert (
        process is not None
        and profiler is not None
        and corpus_before is not None
        and corpus_after is not None
    )
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    endpoint, publications, render_evidence = validate_run_semantics(contents)
    phase_cycles = cold.parse_phase_cycles(contents, phases, EXPECTED_RECORDS)
    bound = cold.validate_record_bindings(
        regular_capture.initial_records(), publications, phase_cycles
    )
    return {
        "mode": "diagnostic-five-call-spans",
        "variant": variant,
        "fresh_process": True,
        "program": artifact(program),
        "symbols": artifact(symbols),
        "mos": artifact(mos_copy),
        "mos_map": artifact(mos_map_copy),
        "runtime_corpus": {
            "before": corpus_witness(corpus_before),
            "after": corpus_witness(corpus_after),
            "unchanged": True,
        },
        "command": artifact(run_output / "command.json"),
        "autoexec": artifact(run_output / "autoexec.txt"),
        "log": artifact(log_path),
        "cold_endpoint": endpoint,
        "publication_semantics": publication_semantics(publications),
        "render_sequences": render_evidence["qualified_prefix"],
        "render_evidence": render_evidence,
        "live": profiler.require_complete(),
        "phases": {
            name: {
                "cycles": phase_cycles[name],
                "summary": summarize_distribution(phase_cycles[name]).as_dict(),
                "completion_equivalent": False,
            }
            for name in cold.PHASE_NAMES
        },
        "records": bound,
        "emulator_exit_status": process.returncode,
    }


def assert_semantic_equivalence(
    control: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    for name in ("cold_endpoint", "publication_semantics", "render_sequences"):
        if control.get(name) != candidate.get(name):
            raise MosUartThreProfileError(f"control/candidate {name} differs")
    left = control.get("records")
    right = candidate.get("records")
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != EXPECTED_RECORDS:
        raise MosUartThreProfileError("semantic records are missing")
    if len(right) != len(left):
        raise MosUartThreProfileError("semantic record counts differ")
    stable = ("order", "path", "file_sha256", "data_bytes")
    for order, (before, after) in enumerate(zip(left, right)):
        if any(before.get(name) != after.get(name) for name in stable):
            raise MosUartThreProfileError(f"semantic record differs at {order}")


def paired_metric(
    control: Mapping[str, object],
    candidate: Mapping[str, object],
    metric: str,
    summary: str,
) -> dict[str, object]:
    control_metrics = control.get("metrics")
    candidate_metrics = candidate.get("metrics")
    if not isinstance(control_metrics, Mapping) or not isinstance(candidate_metrics, Mapping):
        raise MosUartThreProfileError("normative metrics are missing")
    before_metric = control_metrics.get(metric)
    after_metric = candidate_metrics.get(metric)
    if not isinstance(before_metric, Mapping) or not isinstance(after_metric, Mapping):
        raise MosUartThreProfileError(f"normative metric missing: {metric}")
    before_summary = before_metric.get(summary)
    after_summary = after_metric.get(summary)
    if not isinstance(before_summary, Mapping) or not isinstance(after_summary, Mapping):
        raise MosUartThreProfileError(f"normative summary missing: {metric}/{summary}")
    before = before_summary.get("total")
    after = after_summary.get("total")
    if not isinstance(before, int) or not isinstance(after, int) or before <= 0:
        raise MosUartThreProfileError("normative total is invalid")
    return {
        "control_cycles": before,
        "candidate_cycles": after,
        "delta_cycles": after - before,
        "candidate_vs_control_percent": (after - before) * 100.0 / before,
        "completion_equivalent": True,
        "boundary": summary,
    }


def diagnostic_comparison(
    control: Mapping[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    left = control.get("phases")
    right = candidate.get("phases")
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise MosUartThreProfileError("diagnostic phase metrics are missing")
    result = {}
    for name in cold.PHASE_NAMES:
        before_phase = left.get(name)
        after_phase = right.get(name)
        if not isinstance(before_phase, Mapping) or not isinstance(after_phase, Mapping):
            raise MosUartThreProfileError(f"diagnostic phase missing: {name}")
        before_summary = before_phase.get("summary")
        after_summary = after_phase.get("summary")
        if not isinstance(before_summary, Mapping) or not isinstance(after_summary, Mapping):
            raise MosUartThreProfileError(f"diagnostic summary missing: {name}")
        before = before_summary.get("total")
        after = after_summary.get("total")
        if not isinstance(before, int) or not isinstance(after, int) or before <= 0:
            raise MosUartThreProfileError(f"diagnostic total invalid: {name}")
        result[name] = {
            "control_cycles": before,
            "candidate_cycles": after,
            "delta_cycles": after - before,
            "candidate_vs_control_percent": (after - before) * 100.0 / before,
            "completion_equivalent": False,
        }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    if args.timeout <= 0:
        raise MosUartThreProfileError("--timeout must be positive")
    build = args.build.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise MosUartThreProfileError(f"refusing to replace existing output: {output}")
    control_mos, candidate_mos, receipt = validate_build(build)
    control_program, control_listing, control_symbols = validate_crc1_control(
        build, receipt
    )
    builder.require_accepted_inputs()
    canonical_corpus = builder.validate_runtime_corpus()
    builder.validate_pinned_contract()
    builder.validate_reference_source_context()
    vdp = staged.require_file(args.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    emulator_sha256 = sha256(input_trace.FAB_BINARY)
    vdp_sha256 = sha256(vdp)
    profile_script_sha256 = sha256(Path(__file__))
    build_receipt_sha256 = sha256(build / builder.REPORT_NAME)
    output.mkdir(parents=True)

    normative_control = run_normative(
        variant="pinned-temt",
        mos=control_mos,
        mos_sha256=builder.PINNED_MOS_SHA256,
        vdp=vdp,
        output=output,
        timeout=args.timeout,
    )
    normative_candidate = run_normative(
        variant="patched-thre",
        mos=candidate_mos,
        mos_sha256=builder.PATCHED_MOS_SHA256,
        vdp=vdp,
        output=output,
        timeout=args.timeout,
    )
    assert_semantic_equivalence(normative_control, normative_candidate)

    diagnostic_control = run_diagnostic(
        variant="pinned-temt",
        mos=control_mos,
        mos_sha256=builder.PINNED_MOS_SHA256,
        vdp=vdp,
        output=output,
        timeout=args.timeout,
    )
    diagnostic_candidate = run_diagnostic(
        variant="patched-thre",
        mos=candidate_mos,
        mos_sha256=builder.PATCHED_MOS_SHA256,
        vdp=vdp,
        output=output,
        timeout=args.timeout,
    )
    assert_semantic_equivalence(diagnostic_control, diagnostic_candidate)
    if normative_control["publication_semantics"] != diagnostic_control["publication_semantics"]:
        raise MosUartThreProfileError("normative/diagnostic control semantics differ")
    if normative_candidate["publication_semantics"] != diagnostic_candidate["publication_semantics"]:
        raise MosUartThreProfileError("normative/diagnostic candidate semantics differ")

    builder.require_accepted_inputs()
    if builder.validate_runtime_corpus() != canonical_corpus:
        raise MosUartThreProfileError("canonical runtime corpus changed during profile")
    builder.validate_pinned_contract()
    builder.validate_reference_source_context()
    final_control_mos, final_candidate_mos, _final_receipt = validate_build(build)
    if final_control_mos != control_mos or final_candidate_mos != candidate_mos:
        raise MosUartThreProfileError("MOS build artifact paths changed during profile")
    if sha256(input_trace.FAB_BINARY) != emulator_sha256:
        raise MosUartThreProfileError("emulator identity changed during profile")
    if sha256(vdp) != vdp_sha256:
        raise MosUartThreProfileError("VDP identity changed during profile")
    if sha256(Path(__file__)) != profile_script_sha256:
        raise MosUartThreProfileError("profile script changed during execution")
    if sha256(build / builder.REPORT_NAME) != build_receipt_sha256:
        raise MosUartThreProfileError("MOS build receipt changed during profile")
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "unmodified_accepted_p3drgl_every_run": True,
            "accepted_p3drgl_source": "private ignored CRC1 build artifact",
            "canonical_target_consulted": False,
            "run_local_program_and_symbols_size_sha256_exact_before_launch": True,
            "run_local_autoexec_exact_before_launch": True,
            "all_227_runtime_files_exact_before_and_after_every_run": True,
            "fresh_process_per_run": True,
            "normative_pair_count": 1,
            "diagnostic_pair_count": 1,
            "records_per_run": EXPECTED_RECORDS,
            "normative_breakpoints_per_record": 3,
            "no_normative_breakpoint_after_upload_before_submit": True,
            "publication_must_precede_matching_submit": True,
            "raw_five_phase_spans_are_diagnostic_only": True,
            "exact_image_emulator_evidence_only": True,
            "hardware_timing_excluded": True,
            "render_host_wall_time_excluded": True,
            "post_endpoint_render_tail_recorded_not_hidden": True,
            "post_endpoint_render_tail_maximum_frames": MAX_POST_ENDPOINT_RENDER_TAIL,
        },
        "identity": {
            "profile_script": artifact(Path(__file__)),
            "build_receipt": artifact(build / builder.REPORT_NAME),
            "historical_crc1_program": artifact(control_program),
            "historical_crc1_listing": artifact(control_listing),
            "historical_crc1_symbols": artifact(control_symbols),
            "control_mos": artifact(control_mos),
            "candidate_mos": artifact(candidate_mos),
            "pinned_map": artifact(builder.PINNED_MAP),
            "manager_manifest": artifact(builder.MANAGER_MANIFEST),
            "world_manifest": artifact(builder.WORLD_MANIFEST),
            "emulator": artifact(input_trace.FAB_BINARY),
            "vdp": artifact(vdp),
            "one_byte_patch": receipt["patch"],
            "runtime_corpus": corpus_witness(canonical_corpus),
        },
        "semantic_equivalence": {
            "all_four_runs_exact": True,
            "publications_each_run": EXPECTED_RECORDS,
            "publication_order_and_shapes_exact": True,
            "render_sequence_prefix_exact_0_through_226": True,
            "post_endpoint_render_tails_contiguous_and_scene_stable": True,
            "cold_endpoint_exact": True,
            "manifest_file_binding_exact": True,
            "accepted_application_byte_exact_all_runs": True,
            "stream_byte_order_static_proof": (
                "the sole MOS diff is the UART readiness mask; RST18, PUTCH, "
                "CTS, THR write, accepted app, counts, and data are unchanged"
            ),
        },
        "normative_comparison": {
            metric: {
                "loop_records_1_through_226": paired_metric(
                    normative_control,
                    normative_candidate,
                    metric,
                    "summary_loop_226",
                ),
                "all_records_including_startup_0": paired_metric(
                    normative_control,
                    normative_candidate,
                    metric,
                    "summary_all_227",
                ),
                "interpretation": (
                    "guest cycles through the matching submit call after the nth "
                    "successful VDP publication; includes command/tail scheduling"
                ),
            }
            for metric in (
                "upload_to_publication_complete_submit",
                "read_to_publication_complete_submit",
            )
        },
        "diagnostic_interpretation": {
            "completion_equivalent": False,
            "reason": (
                "MOS-wide THRE changes consolidate, command50, and all UART0 TX "
                "callers; call/post boundaries can leave different queued state"
            ),
            "debugger_pause_caveat": (
                "the separate nine-boundary runs are diagnostic and may change "
                "host CTS/VDP scheduling; they do not support normative claims"
            ),
        },
        "diagnostic_comparison": diagnostic_comparison(
            diagnostic_control, diagnostic_candidate
        ),
        "runs": [
            normative_control,
            normative_candidate,
            diagnostic_control,
            diagnostic_candidate,
        ],
        "limitations": {
            "binary_proof_for_rebuilding_the_older_pinned_console8_mos": True,
            "current_reference_source_already_uses_uart_lsr_eth": True,
            "reference_source_is_not_provenance_for_pinned_binary": True,
            "patch_affects_every_uart0_serial_tx_caller": True,
            "thre_return_does_not_imply_transmitter_idle": True,
            "must_not_install_or_distribute_patched_blob": True,
            "source_level_rebuild_in_mos_owning_repo_required_for_promotion": True,
            "physical_uart_cts_fifo_timing_qualification_open": True,
            "single_emulator_pair_does_not_establish_repeatability": True,
        },
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Regular-LOD MOS UART-THRE live profile passed: {report_path}")
    for metric, comparison in report["normative_comparison"].items():
        loop = comparison["loop_records_1_through_226"]
        print(
            f"{metric}: control={loop['control_cycles']} "
            f"candidate={loop['candidate_cycles']} "
            f"percent={loop['candidate_vs_control_percent']} "
            "publication_complete=True"
        )
    print("four_runs=4 records_each=227 publication_before_submit=227x2")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        MosUartThreProfileError,
        builder.MosUartThreBuildError,
        cold.ColdLoadProfileError,
        ProfileEvidenceError,
        staged.EvidenceError,
    ) as error:
        raise SystemExit(f"regular-LOD MOS UART-THRE profile failed: {error}") from error
