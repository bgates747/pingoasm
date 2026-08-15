#!/usr/bin/env python3
"""Qualify staged regular-LOD handoffs and a radius cold restart.

This tracer is deliberately separate from
``trace_regular_lod_north_transition.py``.  That older qualification pins the
accepted inactive-first rollback binary and its exact first crossing.  This
one targets the accepted coverage-group staging build: it starts from the same
cold Marina scene, drives north through four adjacent origin changes, waits
for exact convergence, and presses top-row 4.  The resulting cold restart must
preserve the camera and regional origin, retire the entire radius-five endpoint
before publishing any radius-four mesh, and converge to the exact smaller
owner map.  The VDP command stream and a final debugger snapshot prove those
contracts.

The initial ``--cold-only`` mode proves that the manager/provider ABI has not
changed the accepted 227-object cold endpoint before any transition is
attempted.  ``--program`` and ``--symbols`` remain available for disposable
review builds, while the defaults always exercise the installed fixture and
its tracked symbols.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
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
from pingo_terrain.regular_lod_runtime import (
    build_terrain_owner_plan,
    schedule_terrain_transition,
)


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
DEFAULT_PROGRAM = FIXTURE / "P3DRGL.BIN"
ASSEMBLED_PROGRAM = (
    ROOT
    / "fixtures/terrain-manager-regular-lod-survey/tgt/"
    "terrain-manager-regular-lod-survey.bin"
)
DEFAULT_SYMBOLS = (
    ROOT
    / "fixtures/terrain-manager-regular-lod-survey/tgt/"
    "terrain-manager-regular-lod-survey.symbols"
)
REPORT_NAME = "regular-lod-staged-north-transitions.json"
SCHEMA = "pingo-terrain-regular-lod-staged-north-transitions-v2"

COLD_SEQUENCE = 226
SLOT_COUNT = 255
COLD_ACTIVE_COUNT = 227
COLD_RENDER_MARKER = f"PINGO_RENDER seq={COLD_SEQUENCE} "
START_ORIGIN = (80, 125)
FINAL_ORIGIN = (80, 129)
NORTH_TRANSITION_COUNT = FINAL_ORIGIN[1] - START_ORIGIN[1]
EXPECTED_FINAL_ACTIVE_COUNT = 227
EXPECTED_ENTERING_COUNT = 130
EXPECTED_RETIRING_COUNT = 130
POST_CONVERGENCE_RENDERS = 3
W_SCANCODE = input_trace.SET2_CODES["W"]
RADIUS_FOUR_SCANCODE = 0x0025
RESTART_RADIUS = 4
RESTART_ACTIVE_COUNT = 196
CAMERA_INITIAL_X = 4275
CAMERA_INITIAL_Y = 8000
CAMERA_INITIAL_Z = -466
ORIGIN_NORTH_STEP = 8800
CAMERA_SIZE = 36

RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+)\b")
CAMERA_TRANSLATION_RE = re.compile(
    r"PINGO_POSE camera_translation "
    r"raw_x=(-?\d+) raw_y=(-?\d+) raw_z=(-?\d+)"
)
SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")


class EvidenceError(ValueError):
    """The diagnostic transcript violated a staged-handoff invariant."""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=survey.DEFAULT_VDP,
        help="P3DM diagnostic PingoWolf module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--cold-only",
        action="store_true",
        help="stop after proving the unchanged 227-object cold endpoint",
    )
    parser.add_argument(
        "--crossings-only",
        action="store_true",
        help="stop after four staged crossings without testing radius restart",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"Missing {description}: {resolved}")
    return resolved


def wait_for_log(
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
            raise SystemExit(f"staged north trace failure: {failures}")
        if predicate(contents):
            return contents
        if process.poll() is not None:
            raise SystemExit(
                f"Emulator exited early with {process.returncode}: {log_path}"
            )
        time.sleep(0.02)
    raise SystemExit(f"Timed out waiting for {description}: {log_path}")


def activity_state_at(contents: str, offset: int) -> dict[int, int]:
    state: dict[int, int] = {}
    for match in capture.OBJECT_ACTIVE_RE.finditer(contents):
        if match.start() >= offset:
            break
        state[int(match.group(1))] = int(match.group(2))
    return state


def validate_cold_endpoint(contents: str) -> dict[str, object]:
    markers = [
        offset
        for offset in range(len(contents))
        if contents.startswith(COLD_RENDER_MARKER, offset)
    ]
    if len(markers) != 1:
        raise EvidenceError(
            f"expected one cold seq-{COLD_SEQUENCE} marker, got {len(markers)}"
        )
    marker = markers[0] + len(COLD_RENDER_MARKER)
    state = activity_state_at(contents, marker)
    if set(state) != set(range(1, SLOT_COUNT + 1)):
        raise EvidenceError("cold stream did not establish all 255 activity states")
    active = sorted(object_id for object_id, value in state.items() if value)
    expected = list(range(1, COLD_ACTIVE_COUNT + 1))
    if active != expected:
        raise EvidenceError(
            f"staged cold endpoint changed: {active!r} != OID 1..227"
        )
    replacements = [
        match
        for match in capture.MESH_REPLACE_RE.finditer(contents)
        if match.start() < marker
    ]
    if len(replacements) != COLD_ACTIVE_COUNT:
        raise EvidenceError(
            f"cold endpoint published {len(replacements)} meshes, expected 227"
        )
    return {
        "sequence": COLD_SEQUENCE,
        "active_count": len(active),
        "active_ids": active,
        "publication_count": len(replacements),
    }


def cold_end_offset(contents: str) -> int:
    offset = contents.find(COLD_RENDER_MARKER)
    if offset < 0:
        raise EvidenceError("cold render marker is absent")
    return offset + len(COLD_RENDER_MARKER)


def camera_evidence(contents: str, start: int) -> dict[str, object]:
    raw = [
        tuple(int(match.group(axis)) for axis in range(1, 4))
        for match in CAMERA_TRANSLATION_RE.finditer(contents, start)
    ]
    unwrapped: list[tuple[int, int, int]] = [
        (CAMERA_INITIAL_X, CAMERA_INITIAL_Y, CAMERA_INITIAL_Z)
    ]
    wrap_deltas: list[int] = []
    wraps = 0
    previous_raw_x = CAMERA_INITIAL_X
    for x, y, z in raw:
        delta = x - previous_raw_x
        if delta < -(ORIGIN_NORTH_STEP // 2):
            wraps += 1
            wrap_deltas.append(delta)
        unwrapped.append((x + wraps * ORIGIN_NORTH_STEP, y, z))
        previous_raw_x = x
    return {
        "raw": raw,
        "unwrapped": unwrapped,
        "wrap_count": wraps,
        "wrap_deltas": wrap_deltas,
    }


def four_wraps_observed(contents: str) -> bool:
    start = cold_end_offset(contents)
    return int(camera_evidence(contents, start)["wrap_count"]) >= 4


def transition_stream_complete(contents: str) -> bool:
    start = cold_end_offset(contents)
    records = [
        match
        for match in capture.OBJECT_ACTIVE_RE.finditer(contents, start)
    ]
    entering = sum(int(match.group(2)) == 1 for match in records)
    retiring = sum(int(match.group(2)) == 0 for match in records)
    if entering < EXPECTED_ENTERING_COUNT or retiring < EXPECTED_RETIRING_COUNT:
        return False
    if not records:
        return False
    renders_after = sum(
        match.start() > records[-1].start()
        for match in RENDER_RE.finditer(contents, start)
    )
    input_records = [
        record
        for record in input_trace.input_records(contents)
        if record["scancode"] == W_SCANCODE
    ]
    return (
        renders_after >= POST_CONVERGENCE_RENDERS
        and len(input_records) >= 2
        and input_records[-1]["action"] == "up"
    )


def input_matches(contents: str, scancode: int) -> list[re.Match[str]]:
    return [
        match
        for match in input_trace.INPUT_RE.finditer(contents)
        if int(match.group(3), 16) == scancode
    ]


def radius_restart_offset(contents: str) -> int:
    matches = input_matches(contents, RADIUS_FOUR_SCANCODE)
    if not matches or matches[0].group(2) != "down":
        raise EvidenceError("radius-four FIFO make event is absent")
    return matches[0].start()


def radius_restart_complete(contents: str) -> bool:
    matches = input_matches(contents, RADIUS_FOUR_SCANCODE)
    if [match.group(2) for match in matches] != ["down", "up"]:
        return False
    start = matches[0].start()
    activity = list(capture.OBJECT_ACTIVE_RE.finditer(contents, start))
    replacements = list(capture.MESH_REPLACE_RE.finditer(contents, start))
    retiring = sum(int(match.group(2)) == 0 for match in activity)
    entering = sum(int(match.group(2)) == 1 for match in activity)
    if (
        retiring < EXPECTED_FINAL_ACTIVE_COUNT
        or entering < RESTART_ACTIVE_COUNT
        or len(replacements) < RESTART_ACTIVE_COUNT
    ):
        return False
    last_offset = max(
        [match.start() for match in activity + replacements],
        default=start,
    )
    renders_after = sum(
        match.start() > last_offset
        for match in RENDER_RE.finditer(contents, start)
    )
    return renders_after >= POST_CONVERGENCE_RENDERS


def expected_group_shapes() -> list[list[tuple[int, int]]]:
    transitions: list[list[tuple[int, int]]] = []
    for origin_r in range(START_ORIGIN[1], FINAL_ORIGIN[1]):
        old = build_terrain_owner_plan(START_ORIGIN[0], origin_r, 5)
        new = build_terrain_owner_plan(START_ORIGIN[0], origin_r + 1, 5)
        schedule = schedule_terrain_transition(old, new)
        transitions.append(
            [
                (len(step.group.retiring), len(step.group.entering))
                for step in schedule.steps
            ]
        )
    return transitions


def validate_camera(contents: str, start: int) -> dict[str, object]:
    evidence = camera_evidence(contents, start)
    raw = evidence["raw"]
    unwrapped = evidence["unwrapped"]
    assert isinstance(raw, list)
    assert isinstance(unwrapped, list)
    if int(evidence["wrap_count"]) != NORTH_TRANSITION_COUNT:
        raise EvidenceError(
            f"expected four north rebases, got {evidence['wrap_count']}"
        )
    for previous, current in zip(unwrapped, unwrapped[1:]):
        delta = current[0] - previous[0]
        if delta < 0 or delta % 32:
            raise EvidenceError(
                f"canonical north motion is not monotone 32-count motion: "
                f"{previous!r} -> {current!r}"
            )
        if current[1:] != (CAMERA_INITIAL_Y, CAMERA_INITIAL_Z):
            raise EvidenceError(f"north drive changed camera Y/Z: {current!r}")
    evidence["raw"] = [list(item) for item in raw]
    evidence["unwrapped_first"] = list(unwrapped[0])
    evidence["unwrapped_last"] = list(unwrapped[-1])
    del evidence["unwrapped"]
    return evidence


def validate_input(contents: str) -> dict[str, object]:
    records = [
        record
        for record in input_trace.input_records(contents)
        if record["scancode"] == W_SCANCODE
    ]
    actions = [record["action"] for record in records]
    if actions != ["down", "up"]:
        raise EvidenceError(f"expected one W down/up pair, got {records!r}")
    if any(record["source"] != "fifo" for record in records):
        raise EvidenceError(f"W did not use explicit FIFO make/break: {records!r}")
    return {
        "scancode": f"0x{W_SCANCODE:04x}",
        "down_host_vblank": records[0]["host_vblank"],
        "up_host_vblank": records[1]["host_vblank"],
        "hold_vblanks": (
            int(records[1]["host_vblank"]) - int(records[0]["host_vblank"])
        ),
    }


def validate_transition_stream(
    contents: str,
    start: int,
    end: int | None = None,
) -> dict[str, object]:
    stop = len(contents) if end is None else end
    activity = list(capture.OBJECT_ACTIVE_RE.finditer(contents, start, stop))
    entering = [match for match in activity if int(match.group(2)) == 1]
    retiring = [match for match in activity if int(match.group(2)) == 0]
    if len(entering) != EXPECTED_ENTERING_COUNT:
        raise EvidenceError(
            f"staged stream activated {len(entering)} owners, expected 130"
        )
    if len(retiring) != EXPECTED_RETIRING_COUNT:
        raise EvidenceError(
            f"staged stream retired {len(retiring)} owners, expected 130"
        )

    cold_state = activity_state_at(contents, start)
    state = dict(cold_state)
    posed: set[int] = set()
    semantic: list[tuple[int, str, int]] = []
    for match in capture.MESH_REPLACE_RE.finditer(contents, start, stop):
        semantic.append((match.start(), "replace", int(match.group(2))))
    for match in survey.OBJECT_TRANSLATION_RE.finditer(contents, start, stop):
        semantic.append((match.start(), "pose", int(match.group(1))))
    for match in activity:
        semantic.append((match.start(), f"active-{match.group(2)}", int(match.group(1))))
    semantic.sort()

    inactive_replacements: list[int] = []
    for _, kind, object_id in semantic:
        if kind == "replace":
            if state.get(object_id) != 0:
                raise EvidenceError(
                    f"command 50 replaced active OID {object_id}"
                )
            posed.discard(object_id)
            inactive_replacements.append(object_id)
        elif kind == "pose":
            posed.add(object_id)
        elif kind == "active-0":
            if state.get(object_id) != 1:
                raise EvidenceError(
                    f"group retired non-active OID {object_id}"
                )
            state[object_id] = 0
            posed.discard(object_id)
        else:
            if state.get(object_id) != 0:
                raise EvidenceError(
                    f"group activated non-inactive OID {object_id}"
                )
            if object_id not in posed:
                raise EvidenceError(
                    f"group activated OID {object_id} without staged command-52 pose"
                )
            state[object_id] = 1
            posed.discard(object_id)

    final_active = sorted(object_id for object_id, value in state.items() if value)
    if len(final_active) != EXPECTED_FINAL_ACTIVE_COUNT:
        raise EvidenceError(
            f"stream ended with {len(final_active)} active objects, expected 227"
        )

    render_offsets = [
        match.start() for match in RENDER_RE.finditer(contents, start, stop)
    ]
    by_interval: dict[int, list[re.Match[str]]] = {}
    for match in activity:
        interval = bisect_right(render_offsets, match.start())
        by_interval.setdefault(interval, []).append(match)
    observed_shapes: list[tuple[int, int]] = []
    for interval in sorted(by_interval):
        records = by_interval[interval]
        values = [int(match.group(2)) for match in records]
        first_enter = values.index(1) if 1 in values else len(values)
        if any(value != 0 for value in values[:first_enter]) or any(
            value != 1 for value in values[first_enter:]
        ):
            raise EvidenceError(
                f"group interval {interval} did not retire before enter: {values!r}"
            )
        if any(
            first.start() < render < records[-1].start()
            for first in records[:1]
            for render in render_offsets
        ):
            raise EvidenceError(f"render interleaved group interval {interval}")
        observed_shapes.append((first_enter, len(values) - first_enter))

    expected_by_transition = expected_group_shapes()
    expected_flat = [shape for transition in expected_by_transition for shape in transition]
    if observed_shapes != expected_flat:
        raise EvidenceError(
            f"atomic group shapes changed: {observed_shapes!r} != {expected_flat!r}"
        )
    shaped: list[list[list[int]]] = []
    cursor = 0
    for transition in expected_by_transition:
        count = len(transition)
        shaped.append([list(item) for item in observed_shapes[cursor : cursor + count]])
        cursor += count

    return {
        "command50_count": len(inactive_replacements),
        "command50_all_inactive": True,
        "entering_count": len(entering),
        "retiring_count": len(retiring),
        "group_count": len(observed_shapes),
        "group_shapes_by_transition": shaped,
        "retire_before_enter": True,
        "render_inside_group_commit": False,
        "final_active_ids": final_active,
    }


def validate_radius_input(contents: str) -> dict[str, object]:
    matches = input_matches(contents, RADIUS_FOUR_SCANCODE)
    actions = [match.group(2) for match in matches]
    if actions != ["down", "up"]:
        raise EvidenceError(
            f"expected one radius-four down/up pair, got {actions!r}"
        )
    sources = [match.group(4) for match in matches]
    if sources != ["fifo-tap", "tap-release"]:
        raise EvidenceError(
            f"radius-four key did not use an explicit FIFO tap: {sources!r}"
        )
    frames = [int(match.group(1)) for match in matches]
    return {
        "radius": RESTART_RADIUS,
        "scancode": f"0x{RADIUS_FOUR_SCANCODE:04x}",
        "down_host_vblank": frames[0],
        "up_host_vblank": frames[1],
        "tap_vblanks": frames[1] - frames[0],
        "sources": sources,
    }


def last_camera_position_before(contents: str, end: int) -> list[int]:
    position = [CAMERA_INITIAL_X, CAMERA_INITIAL_Y, CAMERA_INITIAL_Z]
    for match in CAMERA_TRANSLATION_RE.finditer(contents, 0, end):
        position = [int(match.group(axis)) for axis in range(1, 4)]
    return position


def validate_radius_restart_stream(
    contents: str,
    start: int,
    pre_restart_active_ids: list[int],
) -> dict[str, object]:
    state = activity_state_at(contents, start)
    expected_pre = set(pre_restart_active_ids)
    observed_pre = {object_id for object_id, value in state.items() if value}
    if observed_pre != expected_pre:
        raise EvidenceError("radius restart began from the wrong active endpoint")

    activity = list(capture.OBJECT_ACTIVE_RE.finditer(contents, start))
    replacements = list(capture.MESH_REPLACE_RE.finditer(contents, start))
    poses = list(survey.OBJECT_TRANSLATION_RE.finditer(contents, start))
    if not replacements:
        raise EvidenceError("radius restart published no replacement meshes")
    first_replace = replacements[0].start()
    shutdown = [
        match
        for match in activity
        if match.start() < first_replace and int(match.group(2)) == 0
    ]
    shutdown_ids = [int(match.group(1)) for match in shutdown]
    if set(shutdown_ids) != expected_pre or len(shutdown_ids) != len(expected_pre):
        raise EvidenceError(
            "radius restart did not deactivate every old active exactly once "
            "before its first command 50"
        )
    if any(
        int(match.group(2)) != 0
        for match in activity
        if match.start() < first_replace
    ):
        raise EvidenceError("radius restart activated an object during shutdown")
    render_offsets = [match.start() for match in RENDER_RE.finditer(contents, start)]
    if shutdown and any(shutdown[0].start() < offset < shutdown[-1].start() for offset in render_offsets):
        raise EvidenceError("a render interleaved the radius shutdown transaction")

    semantic: list[tuple[int, str, int]] = []
    semantic.extend(
        (match.start(), "replace", int(match.group(2))) for match in replacements
    )
    semantic.extend((match.start(), "pose", int(match.group(1))) for match in poses)
    semantic.extend(
        (match.start(), f"active-{match.group(2)}", int(match.group(1)))
        for match in activity
    )
    semantic.sort()
    posed: set[int] = set()
    replaced: set[int] = set()
    replacement_ids: list[int] = []
    for _, kind, object_id in semantic:
        if kind == "replace":
            if state.get(object_id) != 0:
                raise EvidenceError(
                    f"radius command 50 replaced active OID {object_id}"
                )
            posed.discard(object_id)
            replaced.add(object_id)
            replacement_ids.append(object_id)
        elif kind == "pose":
            posed.add(object_id)
        elif kind == "active-0":
            if state.get(object_id) != 1:
                raise EvidenceError(
                    f"radius shutdown retired non-active OID {object_id}"
                )
            state[object_id] = 0
            posed.discard(object_id)
            replaced.discard(object_id)
        else:
            if state.get(object_id) != 0:
                raise EvidenceError(
                    f"radius refill activated non-inactive OID {object_id}"
                )
            if object_id not in replaced or object_id not in posed:
                raise EvidenceError(
                    f"radius refill activated OID {object_id} without replace/pose"
                )
            state[object_id] = 1
            posed.discard(object_id)
            replaced.discard(object_id)

    retiring = [match for match in activity if int(match.group(2)) == 0]
    entering = [match for match in activity if int(match.group(2)) == 1]
    if len(retiring) != EXPECTED_FINAL_ACTIVE_COUNT:
        raise EvidenceError(
            f"radius shutdown retired {len(retiring)} owners, expected 227"
        )
    if len(entering) != RESTART_ACTIVE_COUNT:
        raise EvidenceError(
            f"radius refill activated {len(entering)} owners, expected 196"
        )
    if len(replacement_ids) != RESTART_ACTIVE_COUNT:
        raise EvidenceError(
            f"radius refill published {len(replacement_ids)} meshes, expected 196"
        )
    final_active = sorted(object_id for object_id, value in state.items() if value)
    if len(final_active) != RESTART_ACTIVE_COUNT:
        raise EvidenceError(
            f"radius refill ended with {len(final_active)} active objects"
        )
    return {
        "old_active_count": len(expected_pre),
        "shutdown_count": len(shutdown),
        "shutdown_complete_before_first_replace": True,
        "render_inside_shutdown": False,
        "command50_count": len(replacement_ids),
        "command50_all_inactive": True,
        "refill_activation_count": len(entering),
        "final_active_ids": final_active,
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
        "terrain_manager_state_ready",
        "terrain_manager_operation_none",
        "terrain_manager_proposed_origin_q",
        "terrain_manager_origin_dirty",
        "terrain_manager_staged_count",
        "terrain_manager_resident_q",
        "terrain_manager_resident_r",
        "terrain_manager_resident_lod",
        "terrain_manager_resident_flags",
        "terrain_manager_flag_resident",
        "terrain_manager_flag_active",
        "terrain_manager_flag_staged",
        "regular_provider_plan_valid",
        "regular_provider_plan_count",
        "regular_provider_desired_count",
        "regular_provider_plan",
        "regular_provider_plan_max",
        "regular_provider_plan_record_bytes",
        "regular_provider_plan_record_lod",
        "regular_provider_plan_record_q",
        "regular_provider_plan_record_row",
        "regular_provider_plan_record_slot",
        "regular_provider_near_slots",
        "regular_provider_near_valid",
        "regular_provider_endpoint_count",
        "regular_provider_endpoint_near_limit",
        "regular_provider_unified_slots",
        "regular_transition_state",
        "regular_transition_state_idle",
        "camera_state",
        "p3d_camera_size",
        "p3d_camera_world_position",
        "p3d_camera_pingo_rotation",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"Staged symbols omit: {missing}")
    if symbols["terrain_manager_status_size"] != 19:
        raise SystemExit("Unexpected manager status size")
    if symbols["p3d_camera_size"] != CAMERA_SIZE:
        raise SystemExit("Unexpected packed camera size")
    return symbols


def snapshot_at_next_idle_render(
    process: subprocess.Popen[bytes],
    log_path: Path,
    symbols: dict[str, int],
    deadline: float,
) -> str:
    before = log_path.read_text(encoding="utf-8", errors="replace")
    pause_count = debugger.ANSI_RE.sub("", before).count("CPU paused")
    os.kill(process.pid, signal.SIGINT)
    wait_for_log(
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
    wait_for_log(
        log_path,
        process,
        deadline,
        lambda value: debugger.ANSI_RE.sub("", value).count("CPU paused")
        > pause_count + 1,
        "final staged render-idle boundary",
    )

    spans = (
        (symbols["terrain_manager_status"], symbols["terrain_manager_status_size"]),
        (symbols["terrain_manager_proposed_origin_q"], 4),
        (symbols["terrain_manager_staged_count"], 1),
        (symbols["terrain_manager_resident_q"], SLOT_COUNT * 2),
        (symbols["terrain_manager_resident_r"], SLOT_COUNT * 2),
        (symbols["terrain_manager_resident_lod"], SLOT_COUNT),
        (symbols["terrain_manager_resident_flags"], SLOT_COUNT),
        (symbols["regular_provider_plan_valid"], 3),
        (symbols["regular_provider_endpoint_count"], 1),
        (symbols["regular_provider_endpoint_near_limit"], 1),
        (symbols["regular_provider_unified_slots"], 1),
        (symbols["regular_transition_state"], 1),
        (symbols["regular_provider_near_slots"], 91),
        (symbols["regular_provider_near_valid"], 91),
        (
            symbols["regular_provider_plan"],
            symbols["regular_provider_plan_max"]
            * symbols["regular_provider_plan_record_bytes"],
        ),
        (symbols["camera_state"], CAMERA_SIZE),
        (symbols["terrain_manager_origin_dirty"], 1),
    )
    for address, length in spans:
        debugger.write_debugger(process, f"memory 0x{address:x} {length}")
    final_address = spans[-1][0]
    wait_for_log(
        log_path,
        process,
        deadline,
        lambda value: f"{final_address:06x}:" in debugger.ANSI_RE.sub("", value),
        "staged manager/provider debugger memory",
    )
    debugger.write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise SystemExit("Debugger did not shut Fab down") from error
    if process.returncode != 0:
        raise SystemExit(f"Debugger shutdown returned {process.returncode}")
    return log_path.read_text(encoding="utf-8", errors="replace")


def signed_word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def vec3_words(data: bytes, offset: int) -> list[int]:
    return [signed_word(data, offset + axis * 2) for axis in range(3)]


def decode_and_validate_snapshot(
    contents: str,
    symbols: dict[str, int],
    stream: dict[str, object],
    *,
    expected_origin: tuple[int, int] = FINAL_ORIGIN,
    expected_radius: int = 5,
    expected_unified_slots: int = 1,
    expected_camera_position: list[int] | None = None,
    require_exact_residency: bool = False,
) -> dict[str, object]:
    memory = debugger.parse_memory(contents)
    status = debugger.read_span(
        memory,
        symbols["terrain_manager_status"],
        symbols["terrain_manager_status_size"],
    )
    proposed = debugger.read_span(
        memory, symbols["terrain_manager_proposed_origin_q"], 4
    )
    staged_count = debugger.read_span(
        memory, symbols["terrain_manager_staged_count"], 1
    )[0]
    q_values = debugger.read_span(
        memory, symbols["terrain_manager_resident_q"], SLOT_COUNT * 2
    )
    r_values = debugger.read_span(
        memory, symbols["terrain_manager_resident_r"], SLOT_COUNT * 2
    )
    lod_values = debugger.read_span(
        memory, symbols["terrain_manager_resident_lod"], SLOT_COUNT
    )
    flags = debugger.read_span(
        memory, symbols["terrain_manager_resident_flags"], SLOT_COUNT
    )
    provider_summary = debugger.read_span(
        memory, symbols["regular_provider_plan_valid"], 3
    )
    endpoint_count = debugger.read_span(
        memory, symbols["regular_provider_endpoint_count"], 1
    )[0]
    endpoint_near_limit = debugger.read_span(
        memory, symbols["regular_provider_endpoint_near_limit"], 1
    )[0]
    unified_slots = debugger.read_span(
        memory, symbols["regular_provider_unified_slots"], 1
    )[0]
    transition_state = debugger.read_span(
        memory, symbols["regular_transition_state"], 1
    )[0]
    near_slots = debugger.read_span(
        memory, symbols["regular_provider_near_slots"], 91
    )
    near_valid = debugger.read_span(
        memory, symbols["regular_provider_near_valid"], 91
    )
    plan = debugger.read_span(
        memory,
        symbols["regular_provider_plan"],
        symbols["regular_provider_plan_max"]
        * symbols["regular_provider_plan_record_bytes"],
    )
    camera = debugger.read_span(memory, symbols["camera_state"], CAMERA_SIZE)
    origin_dirty = debugger.read_span(
        memory, symbols["terrain_manager_origin_dirty"], 1
    )[0]

    manager = {
        "state": status[symbols["terrain_manager_status_state"]],
        "ring": status[symbols["terrain_manager_status_ring"]],
        "desired_count": status[symbols["terrain_manager_status_desired_count"]],
        "resident_count": status[symbols["terrain_manager_status_resident_count"]],
        "active_count": status[symbols["terrain_manager_status_active_count"]],
        "converged": status[symbols["terrain_manager_status_converged"]],
        "last_operation": status[symbols["terrain_manager_status_last_operation"]],
        "last_error": status[symbols["terrain_manager_status_last_error"]],
        "origin": [
            signed_word(status, symbols["terrain_manager_status_origin_q"]),
            signed_word(status, symbols["terrain_manager_status_origin_r"]),
        ],
        "proposed_origin": [signed_word(proposed, 0), signed_word(proposed, 2)],
        "origin_dirty": origin_dirty,
        "staged_count": staged_count,
    }
    expected_plan = build_terrain_owner_plan(*expected_origin, expected_radius)
    expected_active_count = len(expected_plan.owners)
    expected_manager = {
        "state": symbols["terrain_manager_state_ready"],
        "ring": expected_radius,
        "desired_count": expected_active_count,
        "active_count": expected_active_count,
        "converged": 1,
        "last_operation": symbols["terrain_manager_operation_none"],
        "last_error": 0,
        "origin": list(expected_origin),
        "proposed_origin": list(expected_origin),
        "origin_dirty": 0,
        "staged_count": 0,
    }
    observed_contract = {
        key: manager[key]
        for key in expected_manager
    }
    if observed_contract != expected_manager:
        raise EvidenceError(
            f"final manager state changed: {observed_contract!r} "
            f"!= {expected_manager!r}"
        )

    resident_bit = symbols["terrain_manager_flag_resident"]
    active_bit = symbols["terrain_manager_flag_active"]
    staged_bit = symbols["terrain_manager_flag_staged"]
    resident_slots = [slot for slot, value in enumerate(flags) if value & resident_bit]
    active_slots = [slot for slot, value in enumerate(flags) if value & active_bit]
    staged_slots = [slot for slot, value in enumerate(flags) if value & staged_bit]
    if len(resident_slots) != manager["resident_count"]:
        raise EvidenceError("resident flags disagree with the manager count")
    if not expected_active_count <= len(resident_slots) <= SLOT_COUNT:
        raise EvidenceError(
            f"final resident count lies outside active..capacity: {len(resident_slots)}"
        )
    if require_exact_residency and len(resident_slots) != expected_active_count:
        raise EvidenceError(
            f"cold restart retained {len(resident_slots)} residents, "
            f"expected exactly {expected_active_count}"
        )
    if len(active_slots) != expected_active_count:
        raise EvidenceError("active flags disagree with the manager count")
    if staged_slots:
        raise EvidenceError(f"final slots remain staged: {staged_slots!r}")
    active_ids = [slot + 1 for slot in active_slots]
    if active_ids != stream["final_active_ids"]:
        raise EvidenceError("manager active flags disagree with the VDP stream")

    def identity_at(slot: int) -> tuple[int, int, int]:
        return (
            lod_values[slot],
            signed_word(q_values, slot * 2),
            signed_word(r_values, slot * 2),
        )

    active_identities = [identity_at(slot) for slot in active_slots]
    expected = expected_plan
    expected_identities = {
        *((0, entry.q, entry.r) for entry in expected.near_entries),
        *((entry.lod, entry.anchor_q, entry.anchor_offset_row) for entry in expected.coarse_entries),
    }
    if len(active_identities) != len(set(active_identities)):
        raise EvidenceError("final active manager slots contain duplicate owners")
    if set(active_identities) != expected_identities:
        missing = sorted(expected_identities - set(active_identities))
        extra = sorted(set(active_identities) - expected_identities)
        raise EvidenceError(
            f"final owner set mismatch; missing={missing!r}, extra={extra!r}"
        )

    provider = {
        "plan_valid": provider_summary[0],
        "plan_count": provider_summary[1],
        "desired_count": provider_summary[2],
        "endpoint_count": endpoint_count,
        "endpoint_near_limit": endpoint_near_limit,
        "unified_slots": unified_slots,
        "transition_state": transition_state,
    }
    expected_provider = {
        "plan_valid": 1,
        "plan_count": len(expected.coarse_entries),
        "desired_count": len(expected.owners),
        "endpoint_count": len(expected.owners),
        "endpoint_near_limit": len(expected.near_entries),
        "unified_slots": expected_unified_slots,
        "transition_state": symbols["regular_transition_state_idle"],
    }
    if provider != expected_provider:
        raise EvidenceError(
            f"final provider state changed: {provider!r} != {expected_provider!r}"
        )
    if near_valid[: len(expected.near_entries)] != bytes([1]) * len(
        expected.near_entries
    ):
        raise EvidenceError("selected final near-valid map is not all ones")
    for ordinal, entry in enumerate(expected.near_entries):
        slot = near_slots[ordinal]
        if slot not in active_slots or identity_at(slot) != (0, entry.q, entry.r):
            raise EvidenceError(
                f"near ordinal {ordinal} does not map to its active owner"
            )

    stride = symbols["regular_provider_plan_record_bytes"]
    for ordinal, entry in enumerate(expected.coarse_entries):
        offset = ordinal * stride
        observed = (
            plan[offset + symbols["regular_provider_plan_record_lod"]],
            signed_word(plan, offset + symbols["regular_provider_plan_record_q"]),
            signed_word(plan, offset + symbols["regular_provider_plan_record_row"]),
        )
        wanted = (entry.lod, entry.anchor_q, entry.anchor_offset_row)
        slot = plan[offset + symbols["regular_provider_plan_record_slot"]]
        if observed != wanted:
            raise EvidenceError(
                f"coarse ordinal {ordinal} identity changed: {observed} != {wanted}"
            )
        if slot not in active_slots or identity_at(slot) != wanted:
            raise EvidenceError(
                f"coarse ordinal {ordinal} does not map to its active owner"
            )

    camera_state = {
        "position": vec3_words(camera, symbols["p3d_camera_world_position"]),
        "rotation": vec3_words(camera, symbols["p3d_camera_pingo_rotation"]),
    }
    if camera_state["position"][1:] != [CAMERA_INITIAL_Y, CAMERA_INITIAL_Z]:
        raise EvidenceError(f"final camera Y/Z changed: {camera_state!r}")
    if (
        expected_camera_position is not None
        and camera_state["position"] != expected_camera_position
    ):
        raise EvidenceError(
            f"cold restart moved camera: {camera_state['position']!r} "
            f"!= {expected_camera_position!r}"
        )
    if camera_state["rotation"] != [0, -8192, 0]:
        raise EvidenceError(f"final camera attitude changed: {camera_state!r}")

    return {
        "manager": manager,
        "provider": provider,
        "slots": {
            "resident_count_from_flags": len(resident_slots),
            "active_count_from_flags": len(active_slots),
            "active_ids": active_ids,
            "owner_set_exact": True,
            "near_map_exact": True,
            "coarse_map_exact": True,
            "flags_sha256": hashlib.sha256(flags).hexdigest(),
        },
        "camera": camera_state,
    }


def stage_fixture(sd_root: Path, program: Path) -> None:
    survey_root = sd_root / "survey"
    survey_root.mkdir()
    for source in FIXTURE.iterdir():
        if source.name == "P3DRGL.BIN":
            continue
        (survey_root / source.name).symlink_to(
            source.resolve(), target_is_directory=source.is_dir()
        )
    (survey_root / "P3DRGL.BIN").symlink_to(program)


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if arguments.cold_only and arguments.crossings_only:
        raise SystemExit("--cold-only and --crossings-only are mutually exclusive")

    emulator = require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = require_file(input_trace.MOS_BINARY, "MOS image")
    vdp = require_file(arguments.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    program = require_file(arguments.program, "staged regular-LOD fixture")
    symbols_path = require_file(arguments.symbols, "staged regular-LOD symbols")
    installed_program = require_file(DEFAULT_PROGRAM, "installed regular-LOD fixture")
    assembled_program = require_file(
        ASSEMBLED_PROGRAM, "tracked assembled regular-LOD fixture"
    )
    if sha256(installed_program) != sha256(assembled_program):
        raise SystemExit(
            "Installed regular-LOD fixture does not match its tracked assembly"
        )
    symbols = parse_symbols(symbols_path)
    proxy_source = require_file(
        input_trace.PROXY_SOURCE, "input trace proxy source"
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
        tempfile.TemporaryDirectory(prefix="regular-staged-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="regular-staged-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="regular-staged-fifo-") as fifo_name,
    ):
        sd_root = Path(sd_name)
        stage_fixture(sd_root, program)
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
                    "program": str(program),
                    "program_sha256": sha256(program),
                    "symbols": str(symbols_path),
                    "symbols_sha256": sha256(symbols_path),
                    "environment": {
                        "SDL_VIDEODRIVER": "dummy",
                        "SDL_AUDIODRIVER": "dummy",
                        "FAB_INPUT_REAL_VDP": str(vdp),
                        "FAB_INPUT_FIFO": "<temporary named pipe>",
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
                contents = wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: COLD_RENDER_MARKER in value,
                    "unchanged staged cold endpoint",
                )
                if not arguments.cold_only:
                    input_trace.write_command(
                        control_fd, f"down 0x{W_SCANCODE:04x}"
                    )
                    contents = wait_for_log(
                        log_path,
                        process,
                        deadline,
                        four_wraps_observed,
                        "four adjacent north-origin changes",
                    )
                    input_trace.write_command(
                        control_fd, f"up 0x{W_SCANCODE:04x}"
                    )
                    contents = wait_for_log(
                        log_path,
                        process,
                        deadline,
                        transition_stream_complete,
                        "stationary staged convergence at origin (80,129)",
                    )
                    if not arguments.crossings_only:
                        input_trace.write_command(
                            control_fd,
                            f"tap 0x{RADIUS_FOUR_SCANCODE:04x} 4",
                        )
                        contents = wait_for_log(
                            log_path,
                            process,
                            deadline,
                            radius_restart_complete,
                            "radius-four cold restart at origin (80,129)",
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
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    try:
        cold = validate_cold_endpoint(contents)
        if arguments.cold_only:
            input_evidence = None
            camera = None
            stream = None
            radius_input = None
            radius_stream = None
            final_state = None
        else:
            start = cold_end_offset(contents)
            input_evidence = validate_input(contents)
            camera = validate_camera(contents, start)
            if arguments.crossings_only:
                stream = validate_transition_stream(contents, start)
                radius_input = None
                radius_stream = None
                final_state = decode_and_validate_snapshot(
                    contents, symbols, stream
                )
            else:
                restart = radius_restart_offset(contents)
                stream = validate_transition_stream(contents, start, restart)
                radius_input = validate_radius_input(contents)
                pre_restart_camera = last_camera_position_before(contents, restart)
                radius_stream = validate_radius_restart_stream(
                    contents,
                    restart,
                    list(stream["final_active_ids"]),
                )
                final_state = decode_and_validate_snapshot(
                    contents,
                    symbols,
                    radius_stream,
                    expected_radius=RESTART_RADIUS,
                    expected_unified_slots=0,
                    expected_camera_position=pre_restart_camera,
                    require_exact_residency=True,
                )
                radius_stream["camera_before"] = pre_restart_camera
                radius_stream["camera_after"] = final_state["camera"]["position"]
                radius_stream["origin_preserved"] = (
                    final_state["manager"]["origin"] == list(FINAL_ORIGIN)
                )
    except EvidenceError as error:
        raise SystemExit(f"staged north qualification failed: {error}") from error
    if process.returncode != 0:
        raise SystemExit(f"emulator shutdown returned {process.returncode}")

    report = {
        "schema": SCHEMA,
        "mode": (
            "cold-only"
            if arguments.cold_only
            else "four-crossing"
            if arguments.crossings_only
            else "four-crossing-radius-four-cold-restart"
        ),
        "program": {"path": str(program), "sha256": sha256(program)},
        "symbols": {"path": str(symbols_path), "sha256": sha256(symbols_path)},
        "vdp": {"path": str(vdp), "sha256": sha256(vdp)},
        "proxy": {"sha256": sha256(proxy), "exports": sorted(exports)},
        "cold": cold,
        "input": input_evidence,
        "camera": camera,
        "transition_stream": stream,
        "radius_input": radius_input,
        "radius_restart_stream": radius_stream,
        "final_state": final_state,
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
        "qualified": True,
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if arguments.cold_only:
        print(f"Headless staged regular-LOD cold endpoint passed: {report_path}")
        print("cold seq=226; 227 publications; exact active OIDs 1..227")
    elif arguments.crossings_only:
        print(f"Headless staged regular-LOD four-crossing trace passed: {report_path}")
        print(
            "four north rebases; 130 enters/130 retires; no active command50; "
            "final exact 227-owner endpoint at (80,129)"
        )
    else:
        print(f"Headless staged regular-LOD restart trace passed: {report_path}")
        print(
            "four north rebases; atomic r5 handoffs; complete render-idle "
            "shutdown; inactive-only r4 refill; exact 196-owner endpoint at "
            "(80,129)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
