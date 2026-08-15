#!/usr/bin/env python3
"""Qualify the inactive-first Marina -> north regular-LOD transition.

This is a deliberately exact regression for the first due-north crossing from
the reviewed Berkeley Marina start.  It boots the cold 227-object radius-five
view, holds W only long enough to move the floating origin from (80, 125) to
(80, 126), releases W, and lets the terrain manager converge while stationary.

The diagnostic stream proves the ordering that prevents the old visible snap:

* all 22 new coarse meshes use MIDs/OIDs 228..249, which are inactive when the
  replacement command reaches the VDP;
* every replacement is followed by its command-52 pose and activation before
  the next replacement starts; and
* no stale fallback is deactivated until all 33 near/coarse publications have
  completed.

Finally, a Fab debugger snapshot is taken at a render-idle boundary.  That
checks the manager/provider state behind the VDP transcript without adding any
test-only instrumentation to the fixture itself.  The now-historical flag-zero
binary is reproduced with ``build_regular_lod_group_scratch.py
--group-staging 0`` and staged privately; the accepted installed fixture may
therefore advance without invalidating this rollback qualification.
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
import subprocess
import tempfile
import time

import capture_koak_flight as capture
import capture_terrain_manager_survey as survey
import trace_koak_input as input_trace
import trace_koak_takeoff as debugger


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
LEGACY_SCRATCH = Path("/tmp/pingo-terrain-regular-lod-legacy-scratch")
PROGRAM = LEGACY_SCRATCH / "terrain-manager-regular-lod-legacy-scratch.bin"
SYMBOLS = LEGACY_SCRATCH / "terrain-manager-regular-lod-legacy-scratch.symbols"

TRACE_SCHEMA = "pingo-terrain-regular-lod-north-transition-trace-v1"
TRACE_REPORT_NAME = "regular-lod-north-transition-trace.json"
COLD_SEQUENCE = 226
START_ORIGIN = (80, 125)
FINAL_ORIGIN = (80, 126)
SLOT_COUNT = 255
COLD_ACTIVE_COUNT = 227
FINAL_DESIRED_COUNT = 229
FINAL_RESIDENT_COUNT = 249
FINAL_ACTIVE_COUNT = 229
FINAL_COARSE_PLAN_COUNT = 138
COARSE_SLOT_CAPACITY = 164
FIRST_TRANSITION_COARSE_UNION = 158
KNOWN_MAXIMUM_ADJACENT_COARSE_UNION = 180
W_SCANCODE = input_trace.SET2_CODES["W"]
W_HOLD_VBLANKS = 30
POST_CONVERGENCE_RENDERS = 2
CAMERA_SIZE = 36

# Exact first-crossing publication order from the generated plan.  Slots and
# public mesh/object IDs differ by one because both public bases are one.
NEAR_PUBLICATION_IDS = (88, 2, 7, 12, 17, 22, 16, 10, 4, 89, 83)
COARSE_PUBLICATION_IDS = tuple(range(228, 250))
PUBLICATION_IDS = NEAR_PUBLICATION_IDS + COARSE_PUBLICATION_IDS
STALE_OBJECT_IDS = (
    95,
    96,
    99,
    100,
    102,
    103,
    111,
    117,
    118,
    119,
    120,
    121,
    220,
    221,
    222,
    223,
    224,
    225,
    226,
    227,
)

COLD_RENDER_RE = re.compile(rf"PINGO_RENDER seq={COLD_SEQUENCE}\b")
RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+)\b")
CAMERA_TRANSLATION_RE = re.compile(
    r"PINGO_POSE camera_translation "
    r"raw_x=(-?\d+) raw_y=(-?\d+) raw_z=(-?\d+)"
)
SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")


class EvidenceError(ValueError):
    """The live diagnostic transcript violated the transition contract."""


@dataclass(frozen=True)
class LocatedEvent:
    """One semantic VDP diagnostic and its byte offset in the complete log."""

    offset: int
    kind: str
    object_id: int
    active: int | None = None


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=PROGRAM)
    parser.add_argument("--symbols", type=Path, default=SYMBOLS)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=survey.DEFAULT_VDP,
        help="P3DM-loader diagnostic PingoWolf VDP module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _activity_matches(contents: str) -> list[re.Match[str]]:
    return list(capture.OBJECT_ACTIVE_RE.finditer(contents))


def _state_at(
    activity: list[re.Match[str]], offset: int
) -> dict[int, int]:
    state: dict[int, int] = {}
    for match in activity:
        if match.start() >= offset:
            break
        state[int(match.group(1))] = int(match.group(2))
    return state


def _publication_events(contents: str, cold_end: int) -> list[LocatedEvent]:
    """Return mesh, pose, and activity records after cold convergence."""

    events: list[LocatedEvent] = []
    for match in capture.MESH_REPLACE_RE.finditer(contents, cold_end):
        events.append(LocatedEvent(match.start(), "replace", int(match.group(2))))
    for match in survey.OBJECT_TRANSLATION_RE.finditer(contents, cold_end):
        events.append(LocatedEvent(match.start(), "pose", int(match.group(1))))
    for match in capture.OBJECT_ACTIVE_RE.finditer(contents, cold_end):
        events.append(
            LocatedEvent(
                match.start(),
                "active",
                int(match.group(1)),
                int(match.group(2)),
            )
        )
    return sorted(events, key=lambda item: item.offset)


def transition_complete(contents: str) -> bool:
    """Cheap polling predicate; strict validation happens after shutdown."""

    cold = COLD_RENDER_RE.search(contents)
    if cold is None:
        return False
    suffix = contents[cold.end() :]
    replacements = {
        int(match.group(2)) for match in capture.MESH_REPLACE_RE.finditer(suffix)
    }
    deactivated = {
        int(match.group(1))
        for match in capture.OBJECT_ACTIVE_RE.finditer(suffix)
        if int(match.group(2)) == 0
    }
    if not set(COARSE_PUBLICATION_IDS).issubset(replacements):
        return False
    if not set(STALE_OBJECT_IDS).issubset(deactivated):
        return False

    stale_offsets = [
        match.start()
        for match in capture.OBJECT_ACTIVE_RE.finditer(contents, cold.end())
        if int(match.group(2)) == 0
    ]
    if not stale_offsets:
        return False
    renders_after_last_stale = sum(
        match.start() > max(stale_offsets) for match in RENDER_RE.finditer(contents)
    )
    return renders_after_last_stale >= POST_CONVERGENCE_RENDERS


def analyze_transition_log(contents: str) -> dict[str, object]:
    """Parse and strictly validate one cold -> north -> converged transcript.

    This function is pure so unit tests can exercise the ordering assertions
    without starting Fab.  Byte offsets are used instead of line numbers
    because ESP32 debug chatter may prefix a diagnostic on the same line.
    """

    cold_markers = list(COLD_RENDER_RE.finditer(contents))
    _require(
        len(cold_markers) == 1,
        f"expected one cold seq-{COLD_SEQUENCE} marker, got {len(cold_markers)}",
    )
    cold = cold_markers[0]
    cold_end = cold.end()
    all_activity = _activity_matches(contents)
    cold_state = _state_at(all_activity, cold_end)
    _require(
        set(cold_state) == set(range(1, SLOT_COUNT + 1)),
        "cold transcript did not establish all 255 object activity states",
    )
    cold_active = {object_id for object_id, active in cold_state.items() if active}
    _require(
        cold_active == set(range(1, COLD_ACTIVE_COUNT + 1)),
        "cold transcript is not the exact active OID 1..227 Marina view",
    )

    replacements = list(capture.MESH_REPLACE_RE.finditer(contents, cold_end))
    replacement_ids = tuple(int(match.group(2)) for match in replacements)
    _require(
        replacement_ids == PUBLICATION_IDS,
        "north transition publication order changed: "
        f"{replacement_ids!r} != {PUBLICATION_IDS!r}",
    )

    events = _publication_events(contents, cold_end)
    completed_at: dict[int, int] = {}
    inactive_before_replace: list[int] = []
    for index, mesh_match in enumerate(replacements):
        object_id = int(mesh_match.group(2))
        replace_offset = mesh_match.start()
        next_replace = (
            replacements[index + 1].start()
            if index + 1 < len(replacements)
            else len(contents)
        )
        transaction = [
            event
            for event in events
            if replace_offset <= event.offset < next_replace
            and event.object_id == object_id
        ]
        semantic = [
            (event.kind, event.active)
            for event in transaction
            if event.kind != "active" or event.active == 1
        ]
        _require(
            semantic == [("replace", None), ("pose", None), ("active", 1)],
            f"OID {object_id} publication was not replace -> pose -> activate: "
            f"{semantic!r}",
        )
        completed_at[object_id] = transaction[-1].offset

        if object_id in COARSE_PUBLICATION_IDS:
            before = _state_at(all_activity, replace_offset)
            _require(
                before.get(object_id) == 0,
                f"coarse OID {object_id} was active immediately before replacement",
            )
            inactive_before_replace.append(object_id)

    post_activity = [
        match for match in all_activity if match.start() >= cold_end
    ]
    activated = tuple(
        int(match.group(1))
        for match in post_activity
        if int(match.group(2)) == 1
    )
    deactivated_matches = [
        match for match in post_activity if int(match.group(2)) == 0
    ]
    deactivated = tuple(int(match.group(1)) for match in deactivated_matches)
    _require(
        activated == PUBLICATION_IDS,
        f"transition activation order changed: {activated!r}",
    )
    _require(
        deactivated == STALE_OBJECT_IDS,
        f"stale fallback retirement order changed: {deactivated!r}",
    )
    last_publication = max(completed_at.values())
    _require(
        all(match.start() > last_publication for match in deactivated_matches),
        "a stale fallback was deactivated before all 33 publications completed",
    )

    final_state = _state_at(all_activity, len(contents) + 1)
    final_active = sorted(
        object_id for object_id, active in final_state.items() if active
    )
    _require(
        len(final_active) == FINAL_ACTIVE_COUNT,
        f"stream ended with {len(final_active)} active objects, expected 229",
    )

    camera_positions = [
        tuple(int(match.group(axis)) for axis in range(1, 4))
        for match in CAMERA_TRANSLATION_RE.finditer(contents, cold_end)
    ]
    _require(camera_positions, "north trace omitted camera translations")
    wrap_deltas = [
        current[0] - previous[0]
        for previous, current in zip(camera_positions, camera_positions[1:])
        if previous[0] > 0 and current[0] < 0
    ]
    _require(
        wrap_deltas == [-8768],
        f"expected one +32-step/-8800-rebase camera wrap, got {wrap_deltas!r}",
    )

    return {
        "cold_sequence": COLD_SEQUENCE,
        "cold_active_count": len(cold_active),
        "publication_count": len(replacement_ids),
        "near_publication_ids": list(NEAR_PUBLICATION_IDS),
        "coarse_publication_ids": list(COARSE_PUBLICATION_IDS),
        "coarse_inactive_before_replace": inactive_before_replace,
        "publication_order": "replace-pose-activate",
        "stale_deactivation_ids": list(deactivated),
        "stale_deactivation_after_all_publications": True,
        "final_stream_active_count": len(final_active),
        "final_stream_active_ids": final_active,
        "camera_wrap_deltas": wrap_deltas,
        "final_logged_camera_position": list(camera_positions[-1]),
    }


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
        "submit_current_render",
        "terrain_manager_status",
        "terrain_manager_status_size",
        "terrain_manager_status_state",
        "terrain_manager_status_ring",
        "terrain_manager_status_desired_count",
        "terrain_manager_status_resident_count",
        "terrain_manager_status_active_count",
        "terrain_manager_status_converged",
        "terrain_manager_status_last_operation",
        "terrain_manager_status_last_error",
        "terrain_manager_status_origin_q",
        "terrain_manager_status_origin_r",
        "terrain_manager_status_last_slot",
        "terrain_manager_status_last_q",
        "terrain_manager_status_last_r",
        "terrain_manager_status_generation",
        "terrain_manager_state_ready",
        "terrain_manager_operation_none",
        "terrain_manager_flag_resident",
        "terrain_manager_flag_active",
        "terrain_manager_proposed_origin_q",
        "terrain_manager_proposed_origin_r",
        "terrain_manager_origin_dirty",
        "terrain_manager_resident_flags",
        "regular_provider_plan_valid",
        "regular_provider_plan_count",
        "regular_provider_desired_count",
        "camera_state",
        "p3d_camera_size",
        "p3d_camera_world_position",
        "p3d_camera_pingo_rotation",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"Regular-LOD symbols omit: {missing}")
    if symbols["terrain_manager_status_size"] != 19:
        raise SystemExit("Unexpected terrain-manager status size")
    if symbols["p3d_camera_size"] != CAMERA_SIZE:
        raise SystemExit("Unexpected packed camera-state size")
    if symbols["terrain_manager_proposed_origin_r"] != (
        symbols["terrain_manager_proposed_origin_q"] + 2
    ):
        raise SystemExit("Proposed q/r words are no longer contiguous")
    if (
        symbols["regular_provider_plan_count"]
        != symbols["regular_provider_plan_valid"] + 1
        or symbols["regular_provider_desired_count"]
        != symbols["regular_provider_plan_valid"] + 2
    ):
        raise SystemExit("Provider plan summary bytes are no longer contiguous")
    return symbols


def _wait_for_log(
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    predicate,
    description: str,
) -> str:
    while time.monotonic() < deadline:
        contents = log_path.read_text(encoding="utf-8", errors="replace")
        failures = sorted(
            set(
                capture.find_log_failures(contents)
                + input_trace.find_failures(contents)
            )
        )
        if failures:
            raise SystemExit(f"north-transition trace failure: {failures}")
        if predicate(contents):
            return contents
        if process.poll() is not None:
            raise SystemExit(
                f"Emulator exited early with {process.returncode}: {log_path}"
            )
        time.sleep(0.02)
    raise SystemExit(f"Timed out waiting for {description}: {log_path}")


def snapshot_at_next_idle_render(
    process: subprocess.Popen[bytes],
    log_path: Path,
    symbols: dict[str, int],
    deadline: float,
) -> str:
    """Pause, advance to the next complete manager service, and read state."""

    before = log_path.read_text(encoding="utf-8", errors="replace")
    pause_count = debugger.ANSI_RE.sub("", before).count("CPU paused")
    os.kill(process.pid, signal.SIGINT)  # SIGINT is owned by Fab's debugger.
    _wait_for_log(
        log_path,
        process,
        deadline,
        lambda value: debugger.ANSI_RE.sub("", value).count("CPU paused")
        > pause_count,
        "initial debugger pause",
    )
    debugger.write_debugger(
        process, f"break 0x{symbols['submit_current_render']:x}"
    )
    debugger.write_debugger(process, "continue")
    _wait_for_log(
        log_path,
        process,
        deadline,
        lambda value: debugger.ANSI_RE.sub("", value).count("CPU paused")
        > pause_count + 1,
        "converged render-idle boundary",
    )

    spans = (
        (symbols["terrain_manager_status"], symbols["terrain_manager_status_size"]),
        (symbols["terrain_manager_proposed_origin_q"], 4),
        (symbols["regular_provider_plan_valid"], 3),
        (symbols["camera_state"], CAMERA_SIZE),
        (symbols["terrain_manager_resident_flags"], SLOT_COUNT),
        # This one-byte request is deliberately last.  Seeing its address in
        # the log proves all preceding, larger memory replies were emitted.
        (symbols["terrain_manager_origin_dirty"], 1),
    )
    for address, length in spans:
        debugger.write_debugger(process, f"memory 0x{address:x} {length}")
    final_address = spans[-1][0]
    _wait_for_log(
        log_path,
        process,
        deadline,
        lambda value: f"{final_address:06x}:" in debugger.ANSI_RE.sub("", value),
        "manager/provider debugger memory",
    )
    debugger.write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise SystemExit("Debugger did not shut Fab down") from error
    if process.returncode != 0:
        raise SystemExit(f"Debugger shutdown returned {process.returncode}")
    return log_path.read_text(encoding="utf-8", errors="replace")


def _signed_word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def _vec3_words(data: bytes, offset: int) -> list[int]:
    return [_signed_word(data, offset + axis * 2) for axis in range(3)]


def decode_snapshot(
    memory: dict[int, int], symbols: dict[str, int]
) -> dict[str, object]:
    status = debugger.read_span(
        memory,
        symbols["terrain_manager_status"],
        symbols["terrain_manager_status_size"],
    )
    proposed = debugger.read_span(
        memory, symbols["terrain_manager_proposed_origin_q"], 4
    )
    provider = debugger.read_span(
        memory, symbols["regular_provider_plan_valid"], 3
    )
    camera = debugger.read_span(memory, symbols["camera_state"], CAMERA_SIZE)
    slot_flags = debugger.read_span(
        memory, symbols["terrain_manager_resident_flags"], SLOT_COUNT
    )
    origin_dirty = debugger.read_span(
        memory, symbols["terrain_manager_origin_dirty"], 1
    )[0]

    resident_bit = symbols["terrain_manager_flag_resident"]
    active_bit = symbols["terrain_manager_flag_active"]
    resident_ids = [
        slot + 1
        for slot, flags in enumerate(slot_flags)
        if flags & resident_bit
    ]
    active_ids = [
        slot + 1
        for slot, flags in enumerate(slot_flags)
        if flags & active_bit
    ]
    return {
        "manager": {
            "state": status[symbols["terrain_manager_status_state"]],
            "ring": status[symbols["terrain_manager_status_ring"]],
            "desired_count": status[
                symbols["terrain_manager_status_desired_count"]
            ],
            "resident_count": status[
                symbols["terrain_manager_status_resident_count"]
            ],
            "active_count": status[
                symbols["terrain_manager_status_active_count"]
            ],
            "converged": status[symbols["terrain_manager_status_converged"]],
            "last_operation": status[
                symbols["terrain_manager_status_last_operation"]
            ],
            "last_error": status[symbols["terrain_manager_status_last_error"]],
            "origin": [
                _signed_word(status, symbols["terrain_manager_status_origin_q"]),
                _signed_word(status, symbols["terrain_manager_status_origin_r"]),
            ],
            "last_slot": status[symbols["terrain_manager_status_last_slot"]],
            "last_cell": [
                _signed_word(status, symbols["terrain_manager_status_last_q"]),
                _signed_word(status, symbols["terrain_manager_status_last_r"]),
            ],
            "generation": int.from_bytes(
                status[
                    symbols["terrain_manager_status_generation"] :
                    symbols["terrain_manager_status_generation"] + 2
                ],
                "little",
            ),
            "origin_dirty": origin_dirty,
            "proposed_origin": [
                _signed_word(proposed, 0),
                _signed_word(proposed, 2),
            ],
        },
        "provider": {
            "plan_valid": provider[0],
            "plan_count": provider[1],
            "desired_count": provider[2],
        },
        "camera": {
            "position": _vec3_words(
                camera, symbols["p3d_camera_world_position"]
            ),
            "rotation": _vec3_words(
                camera, symbols["p3d_camera_pingo_rotation"]
            ),
        },
        "slots": {
            "resident_count_from_flags": len(resident_ids),
            "active_count_from_flags": len(active_ids),
            "resident_ids": resident_ids,
            "active_ids": active_ids,
            "flags_sha256": hashlib.sha256(slot_flags).hexdigest(),
        },
    }


def validate_snapshot(
    state: dict[str, object], stream: dict[str, object], symbols: dict[str, int]
) -> None:
    manager = state["manager"]
    assert isinstance(manager, dict)
    expected_manager = {
        "state": symbols["terrain_manager_state_ready"],
        "ring": 5,
        "desired_count": FINAL_DESIRED_COUNT,
        "resident_count": FINAL_RESIDENT_COUNT,
        "active_count": FINAL_ACTIVE_COUNT,
        "converged": 1,
        "last_operation": symbols["terrain_manager_operation_none"],
        "last_error": 0,
        "origin": list(FINAL_ORIGIN),
        "origin_dirty": 0,
        "proposed_origin": list(FINAL_ORIGIN),
    }
    observed_manager = {name: manager[name] for name in expected_manager}
    _require(
        observed_manager == expected_manager,
        f"final manager state changed: {observed_manager!r} != {expected_manager!r}",
    )

    provider = state["provider"]
    assert isinstance(provider, dict)
    expected_provider = {
        "plan_valid": 1,
        "plan_count": FINAL_COARSE_PLAN_COUNT,
        "desired_count": FINAL_DESIRED_COUNT,
    }
    _require(
        provider == expected_provider,
        f"final provider summary changed: {provider!r} != {expected_provider!r}",
    )

    slots = state["slots"]
    assert isinstance(slots, dict)
    _require(
        slots["resident_count_from_flags"] == FINAL_RESIDENT_COUNT,
        "resident slot flags disagree with the manager count",
    )
    _require(
        slots["active_count_from_flags"] == FINAL_ACTIVE_COUNT,
        "active slot flags disagree with the manager count",
    )
    _require(
        slots["active_ids"] == stream["final_stream_active_ids"],
        "debugger active flags disagree with the VDP activity transcript",
    )
    resident_ids = set(slots["resident_ids"])
    active_ids = set(slots["active_ids"])
    _require(
        set(COARSE_PUBLICATION_IDS) <= active_ids,
        "one or more inactive-first coarse publications are not finally active",
    )
    _require(
        set(STALE_OBJECT_IDS) <= resident_ids - active_ids,
        "stale fallback meshes were not retained inactive after retirement",
    )
    _require(
        not (set(range(250, 256)) & resident_ids),
        "the first north crossing unexpectedly consumed slots 250..255",
    )

    camera = state["camera"]
    assert isinstance(camera, dict)
    x, y, z = camera["position"]
    _require(
        -4400 < x < -3500 and (y, z) == (8000, -466),
        f"camera did not stop inside the new north-origin frame: {camera['position']}",
    )
    _require(
        camera["rotation"] == [0, -8192, 0],
        f"north trace changed the level, due-north attitude: {camera['rotation']}",
    )


def validate_input(contents: str) -> dict[str, int | str]:
    records = [
        item
        for item in input_trace.input_records(contents)
        if item["scancode"] == W_SCANCODE
    ]
    _require(len(records) == 2, f"expected one W make/break pair, got {records!r}")
    _require(
        [(item["action"], item["source"]) for item in records]
        == [("down", "fifo-tap"), ("up", "tap-release")],
        f"unexpected W input records: {records!r}",
    )
    hold = int(records[1]["host_vblank"]) - int(records[0]["host_vblank"])
    _require(
        hold == W_HOLD_VBLANKS,
        f"W was held for {hold} vblanks, expected {W_HOLD_VBLANKS}",
    )
    return {
        "scancode": f"0x{W_SCANCODE:04x}",
        "hold_vblanks": hold,
        "down_host_vblank": int(records[0]["host_vblank"]),
        "up_host_vblank": int(records[1]["host_vblank"]),
    }


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    emulator = input_trace.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = input_trace.require_file(input_trace.MOS_BINARY, "MOS image")
    vdp = input_trace.require_file(arguments.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    program = input_trace.require_file(
        arguments.program, "legacy regular-LOD manager fixture"
    )
    symbols_path = input_trace.require_file(
        arguments.symbols, "legacy regular-LOD symbols"
    )
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
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /survey\r\n"
        b"load P3DRGL.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    shutdown = "not-started"
    contents = ""
    process: subprocess.Popen[bytes] | None = None
    deadline = time.monotonic() + arguments.timeout

    with (
        tempfile.TemporaryDirectory(prefix="regular-north-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="regular-north-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="regular-north-fifo-") as fifo_name,
    ):
        sd_root = Path(sd_name)
        survey_root = sd_root / "survey"
        survey_root.mkdir()
        for source in FIXTURE.iterdir():
            if source.name == "P3DRGL.BIN":
                continue
            (survey_root / source.name).symlink_to(
                source.resolve(), target_is_directory=source.is_dir()
            )
        (survey_root / "P3DRGL.BIN").symlink_to(program)
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
                        "FAB_INPUT_REAL_VDP": str(vdp),
                        "FAB_INPUT_FIFO": "<temporary named pipe>",
                    },
                    "input": {
                        "key": "W",
                        "set2_scancode": f"0x{W_SCANCODE:04x}",
                        "hold_vblanks": W_HOLD_VBLANKS,
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
                _wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: COLD_RENDER_RE.search(value) is not None,
                    "cold 227-object Marina convergence",
                )
                debugger.write_command_batch(
                    control_fd,
                    [f"tap 0x{W_SCANCODE:04x} {W_HOLD_VBLANKS}"],
                )
                _wait_for_log(
                    log_path,
                    process,
                    deadline,
                    transition_complete,
                    "one north crossing and stationary convergence",
                )
                contents = snapshot_at_next_idle_render(
                    process, log_path, symbols, deadline
                )
                shutdown = "debugger-memory-exit"
        finally:
            os.close(control_fd)
            if process is not None and process.poll() is None:
                shutdown = input_trace.stop_process(process)

    assert process is not None
    failures = sorted(
        set(capture.find_log_failures(contents) + input_trace.find_failures(contents))
    )
    if failures:
        raise SystemExit(f"north-transition trace failures: {failures}")
    try:
        stream = analyze_transition_log(contents)
        input_evidence = validate_input(contents)
        state = decode_snapshot(debugger.parse_memory(contents), symbols)
        validate_snapshot(state, stream, symbols)
    except EvidenceError as error:
        raise SystemExit(f"north-transition qualification failed: {error}") from error

    report = {
        "schema": TRACE_SCHEMA,
        "program": {"path": str(program), "sha256": sha256(program)},
        "symbols": {"path": str(symbols_path), "sha256": sha256(symbols_path)},
        "vdp": {"path": str(vdp), "sha256": sha256(vdp)},
        "proxy": {"sha256": sha256(proxy), "exports": sorted(exports)},
        "transition": {
            "start_origin": list(START_ORIGIN),
            "final_origin": list(FINAL_ORIGIN),
            **stream,
        },
        "input": input_evidence,
        "final_state": state,
        "capacity_scope": {
            "manager_slots": SLOT_COUNT,
            "first_transition_coarse_union": FIRST_TRANSITION_COARSE_UNION,
            "coarse_slot_capacity": COARSE_SLOT_CAPACITY,
            "unused_slots_after_transition": (
                COARSE_SLOT_CAPACITY - FIRST_TRANSITION_COARSE_UNION
            ),
            "qualified_only_for_this_transition": True,
            "known_maximum_adjacent_radius_five_coarse_union": (
                KNOWN_MAXIMUM_ADJACENT_COARSE_UNION
            ),
        },
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
        "qualified": True,
    }
    report_path = output / TRACE_REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless regular-LOD north transition passed: {report_path}")
    print(
        "coarse 228..249 inactive-before-replace; "
        "33 publications before 20 stale retirements; "
        f"manager={state['manager']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
