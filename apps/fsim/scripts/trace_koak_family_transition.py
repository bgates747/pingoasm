#!/usr/bin/env python3
"""Fly west from KOAK 28L through one nested-family LOD handoff."""

from __future__ import annotations

import argparse
from collections import Counter
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

import capture_koak_family_lod as family_capture
import trace_koak_input as input_trace
import trace_koak_takeoff as takeoff_trace


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "fixtures/koak-flight-family-lod/src"
TARGET = ROOT / "fixtures/koak-flight-family-lod/tgt"
FIXTURE = ROOT / "build/p3dm/bay-area-koak-family-proof"
PROGRAM = FIXTURE / "P3DLOD.BIN"
PLAN = TARGET / "family-plan.json"
BITMAP_ID = 257
STATE_LENGTH = takeoff_trace.STATE_LENGTH
OBJECT_LENGTH = takeoff_trace.OBJECT_LENGTH
ANSI_RE = takeoff_trace.ANSI_RE
MEMORY_RE = takeoff_trace.MEMORY_RE
SYMBOL_RE = takeoff_trace.SYMBOL_RE
ACTIVE_RE = family_capture.OBJECT_ACTIVE_RE
RENDER_RE = takeoff_trace.RENDER_RE
AIRCRAFT_OBJECT_ID = family_capture.AIRCRAFT_OBJECT_ID
OBJECT_POSE_RE = re.compile(
    r"PINGO_POSE object_translation oid=(\d+) "
    r"raw_x=(-?\d+) raw_y=(-?\d+) raw_z=(-?\d+)"
)
CAMERA_POSE_RE = re.compile(
    r"PINGO_POSE camera_translation "
    r"raw_x=(-?\d+) raw_y=(-?\d+) raw_z=(-?\d+)"
)
WIDE_POSE_RE = re.compile(
    r"PINGO_WIDE object_translation=ok oid=(\d+) "
    r"raw_x=(-?\d+) raw_y=(-?\d+) raw_z=(-?\d+)"
)
REQUIRED_POSE_DIAGNOSTIC_MARKERS = (
    b"PINGO_POSE object_translation oid=%u",
    b"PINGO_POSE camera_translation raw_x=%d",
    b"PINGO_WIDE object_translation=ok oid=%u",
)
FIXED_WEST_REBASE_RAW = (0, 0, -8192)
MAX_FRAME_MOTION_RAW = 128
COARSE_CELL_RAW = 8192
COARSE_CENTER_BIAS_RAW = 4096
TERRAIN_Y_RAW = 9728


def parse_sequence_list(value: str) -> tuple[int, ...]:
    try:
        sequences = tuple(int(item.strip(), 10) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "sequences must be comma-separated non-negative integers"
        ) from error
    if not sequences or any(sequence < 0 for sequence in sequences):
        raise argparse.ArgumentTypeError("sequences must be non-negative")
    if len(set(sequences)) != len(sequences):
        raise argparse.ArgumentTypeError("sequences must not repeat")
    return tuple(sorted(sequences))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=input_trace.DEFAULT_VDP,
        help="diagnostic native VDP module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trigger-sequence", type=int, default=40)
    parser.add_argument("--final-sequence", type=int, default=1600)
    parser.add_argument(
        "--boundary-sequences",
        type=parse_sequence_list,
        default=tuple(range(1188, 1201)),
        help="render frames around the expected crossing to retain",
    )
    parser.add_argument("--pitch-delay-vblanks", type=int, default=380)
    parser.add_argument("--pull-vblanks", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=360.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_pose_diagnostics(path: Path) -> None:
    image = path.read_bytes()
    missing = [
        marker.decode("ascii")
        for marker in REQUIRED_POSE_DIAGNOSTIC_MARKERS
        if marker not in image
    ]
    if missing:
        raise SystemExit(
            "VDP module lacks required pose diagnostic records "
            f"{missing}; rebuild it with DIAGNOSTICS=1: {path}"
        )


def export_exact_symbols(
    stage: Path, program: Path
) -> tuple[dict[str, int], Path]:
    """Reassemble an include-closed copy and bind symbols to the exact binary."""

    fixture_root = stage / "fixtures"
    staged_fixture = fixture_root / "koak-flight-family-lod"
    shutil.copytree(SOURCE, staged_fixture / "src")
    shutil.copytree(TARGET, staged_fixture / "tgt")
    for name in (
        "berkeley-flight-fdm",
        "koak-flight-streamed",
        "p3dm-loader-probe",
        "nested-agnb-loader-probe",
        "_common",
    ):
        shutil.copytree(ROOT / "fixtures" / name, fixture_root / name)
    shutil.copytree(ROOT / "build/aircraft", stage / "build/aircraft")

    staged_binary = stage / "P3DLOD.BIN"
    subprocess.run(
        ["ez80asm", "-s", "koak-flight-family-lod.asm", str(staged_binary)],
        cwd=staged_fixture / "src",
        check=True,
    )
    if sha256(staged_binary) != sha256(program):
        raise SystemExit(
            "Symbol-export assembly differs from the exact family fixture"
        )

    symbol_path = staged_fixture / "src/koak-flight-family-lod.symbols"
    symbols: dict[str, int] = {}
    for line in symbol_path.read_text(encoding="ascii").splitlines():
        match = SYMBOL_RE.fullmatch(line)
        if not match:
            continue
        name, address_text = match.groups()
        address = int(address_text, 16)
        previous = symbols.setdefault(name, address)
        if previous != address:
            raise SystemExit(
                f"Assembler exported conflicting values for {name}: "
                f"0x{previous:x} and 0x{address:x}"
            )
    required = {
        "flight_state",
        "flight_state_size",
        "object_state",
        "p3d_object_size",
        "streaming_coarse_x",
        "streaming_coarse_y",
        "family_plan_cursor",
        "family_error_hold",
        "family_swap_complete",
        "streaming_last_error",
        "family_plan_total_count",
        "submit_current_render",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise SystemExit(f"Symbol export omitted required family state: {missing}")
    if symbols["flight_state_size"] != STATE_LENGTH:
        raise SystemExit("Unexpected packed flight-state length")
    if symbols["p3d_object_size"] != OBJECT_LENGTH:
        raise SystemExit("Unexpected packed object-state length")
    if symbols["streaming_coarse_y"] != symbols["streaming_coarse_x"] + 1:
        raise SystemExit("Coarse-cell bytes are no longer adjacent")
    return symbols, symbol_path


def wait_for_log(
    log_path: Path,
    predicate,
    process: subprocess.Popen[bytes],
    deadline: float,
    description: str,
) -> str:
    while time.monotonic() < deadline:
        contents = log_path.read_text(encoding="utf-8", errors="replace")
        failures = input_trace.find_failures(contents)
        failures.extend(family_capture.find_log_failures(contents))
        if failures:
            raise SystemExit(
                f"Family trace failed ({', '.join(sorted(set(failures)))}); "
                f"see {log_path}"
            )
        if predicate(contents):
            return contents
        if process.poll() is not None:
            raise SystemExit(
                f"Emulator exited early with {process.returncode}; see {log_path}"
            )
        time.sleep(0.02)
    raise SystemExit(f"Timed out waiting for {description}; see {log_path}")


def write_debugger(process: subprocess.Popen[bytes], command: str) -> None:
    if process.stdin is None:
        raise SystemExit("Debugger stdin is unavailable")
    process.stdin.write((command.rstrip("\n") + "\n").encode("ascii"))
    process.stdin.flush()


def debugger_snapshot(
    process: subprocess.Popen[bytes],
    log_path: Path,
    symbols: dict[str, int],
    deadline: float,
) -> str:
    """Stop at a completed render-idle boundary and read exact family state."""

    before = log_path.read_text(encoding="utf-8", errors="replace")
    pause_count = ANSI_RE.sub("", before).count("CPU paused")
    os.kill(process.pid, signal.SIGINT)
    wait_for_log(
        log_path,
        lambda text: ANSI_RE.sub("", text).count("CPU paused") > pause_count,
        process,
        deadline,
        "debugger pause",
    )
    write_debugger(process, f"break 0x{symbols['submit_current_render']:x}")
    write_debugger(process, "continue")
    wait_for_log(
        log_path,
        lambda text: ANSI_RE.sub("", text).count("CPU paused") > pause_count + 1,
        process,
        deadline,
        "render-idle state boundary",
    )

    spans = (
        (symbols["flight_state"], STATE_LENGTH),
        (symbols["object_state"], OBJECT_LENGTH),
        (symbols["streaming_coarse_x"], 2),
        (symbols["family_plan_cursor"], 1),
        (symbols["family_error_hold"], 1),
        (symbols["family_swap_complete"], 1),
        (symbols["streaming_last_error"], 1),
    )
    for address, length in spans:
        write_debugger(process, f"memory 0x{address:x} {length}")
    expected_line = f"{spans[-1][0]:06x}:"
    wait_for_log(
        log_path,
        lambda text: expected_line in ANSI_RE.sub("", text),
        process,
        deadline,
        "debugger family-state snapshot",
    )
    write_debugger(process, "exit")
    try:
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise SystemExit("Debugger did not shut the emulator down") from error
    if process.returncode != 0:
        raise SystemExit(
            f"Debugger shutdown returned {process.returncode}; see {log_path}"
        )
    return log_path.read_text(encoding="utf-8", errors="replace")


def activity_events(contents: str) -> list[tuple[int, int]]:
    return [
        (int(match.group(1)), int(match.group(2)))
        for match in ACTIVE_RE.finditer(contents)
    ]


def transition_pattern(plan: dict[str, object]) -> tuple[tuple[int, int], ...]:
    swap = plan["swap"]
    assert isinstance(swap, dict)
    deactivations = tuple(
        int(slot)
        for key in (
            "deactivate_distant",
            "deactivate_transition",
            "deactivate_near",
        )
        for slot in swap[key]
    )
    activations = tuple(
        int(slot)
        for key in (
            "activate_near",
            "activate_transition",
            "activate_distant",
        )
        for slot in swap[key]
    )
    return tuple((slot, 0) for slot in deactivations) + tuple(
        (slot, 1) for slot in activations
    )


def find_exact_transaction(
    events: list[tuple[int, int]], pattern: tuple[tuple[int, int], ...]
) -> int:
    terrain = [event for event in events if 1 <= event[0] <= 37]
    matches = [
        index
        for index in range(len(terrain) - len(pattern) + 1)
        if tuple(terrain[index : index + len(pattern)]) == pattern
    ]
    if len(matches) != 1:
        raise SystemExit(
            "Expected one exact contiguous family activation transaction, "
            f"found {len(matches)}"
        )
    return matches[0]


def transaction_render_bracket(
    contents: str, pattern: tuple[tuple[int, int], ...]
) -> tuple[int, int]:
    """Return the last completed render before and first one after the swap."""

    terrain_matches = [
        match
        for match in ACTIVE_RE.finditer(contents)
        if 1 <= int(match.group(1)) <= 37
    ]
    events = [
        (int(match.group(1)), int(match.group(2))) for match in terrain_matches
    ]
    index = find_exact_transaction(events, pattern)
    first_position = terrain_matches[index].start()
    last_position = terrain_matches[index + len(pattern) - 1].end()
    interleaved_renders = [
        int(match.group(1))
        for match in RENDER_RE.finditer(contents)
        if first_position < match.start() < last_position
    ]
    interleaved_publications = [
        int(match.group(2))
        for match in family_capture.MESH_REPLACE_RE.finditer(contents)
        if first_position < match.start() < last_position
    ]
    interleaved_activity = [
        (int(match.group(1)), int(match.group(2)))
        for match in ACTIVE_RE.finditer(contents)
        if first_position < match.start() < last_position
        and not (1 <= int(match.group(1)) <= 37)
    ]
    if interleaved_renders or interleaved_publications or interleaved_activity:
        raise SystemExit(
            "Family activation transaction was interleaved: "
            f"renders={interleaved_renders}, publications={interleaved_publications}"
            f", other_activity={interleaved_activity}"
        )
    renders = [
        (match.start(), int(match.group(1)))
        for match in RENDER_RE.finditer(contents)
    ]
    before = [sequence for position, sequence in renders if position < first_position]
    after = [sequence for position, sequence in renders if position > last_position]
    if not before or not after:
        raise SystemExit("Could not bracket the family transaction with renders")
    return before[-1], after[0]


def pose_for_render(contents: str, sequence: int) -> dict[str, object]:
    """Return the sole aircraft/camera update submitted for one render."""

    renders = list(RENDER_RE.finditer(contents))
    matching_indices = [
        index
        for index, match in enumerate(renders)
        if int(match.group(1)) == sequence
    ]
    if len(matching_indices) != 1:
        raise SystemExit(
            f"Expected one render record for pose sequence {sequence}, "
            f"found {len(matching_indices)}"
        )
    render_index = matching_indices[0]
    if render_index == 0:
        raise SystemExit(
            f"Pose sequence {sequence} has no preceding render boundary"
        )
    window_start = renders[render_index - 1].end()
    window_end = renders[render_index].start()
    window = contents[window_start:window_end]
    aircraft = [
        (
            window_start + match.start(),
            [int(match.group(axis)) for axis in (2, 3, 4)],
        )
        for match in OBJECT_POSE_RE.finditer(window)
        if int(match.group(1)) == AIRCRAFT_OBJECT_ID
    ]
    camera = [
        (
            window_start + match.start(),
            [int(match.group(axis)) for axis in (1, 2, 3)],
        )
        for match in CAMERA_POSE_RE.finditer(window)
    ]
    if len(aircraft) != 1 or len(camera) != 1:
        raise SystemExit(
            f"Render {sequence} did not contain exactly one aircraft and "
            f"camera pose update: aircraft={len(aircraft)}, camera={len(camera)}"
        )
    if aircraft[0][0] >= camera[0][0]:
        raise SystemExit(
            f"Render {sequence} camera pose did not follow its aircraft pose"
        )
    relative = [
        camera[0][1][axis] - aircraft[0][1][axis] for axis in range(3)
    ]
    return {
        "aircraft_raw": aircraft[0][1],
        "camera_raw": camera[0][1],
        "camera_minus_aircraft_raw": relative,
        "log_offsets": {
            "previous_render_end": renders[render_index - 1].end(),
            "aircraft": aircraft[0][0],
            "camera": camera[0][0],
            "render_start": renders[render_index].start(),
        },
    }


def object_activity_before_render(
    contents: str, object_id: int, sequence: int
) -> int:
    render_matches = [
        match
        for match in RENDER_RE.finditer(contents)
        if int(match.group(1)) == sequence
    ]
    if len(render_matches) != 1:
        raise SystemExit(
            f"Expected one render record for activity sequence {sequence}, "
            f"found {len(render_matches)}"
        )
    states = [
        int(match.group(2))
        for match in ACTIVE_RE.finditer(contents, 0, render_matches[0].start())
        if int(match.group(1)) == object_id
    ]
    if not states:
        raise SystemExit(
            f"Object {object_id} has no activity state before render {sequence}"
        )
    return states[-1]


def validate_pose_rebase(
    contents: str,
    render_bracket: tuple[int, int],
    pattern: tuple[tuple[int, int], ...] | None = None,
) -> dict[str, object]:
    """Bind the family handoff to a coherent aircraft/camera cell rebase."""

    before_sequence, after_sequence = render_bracket
    if after_sequence != before_sequence + 1:
        raise SystemExit(
            "Family transition renders are not consecutive: "
            f"{render_bracket}"
        )
    before = pose_for_render(contents, before_sequence)
    after = pose_for_render(contents, after_sequence)
    aircraft_activity = {
        str(sequence): object_activity_before_render(
            contents, AIRCRAFT_OBJECT_ID, sequence
        )
        for sequence in render_bracket
    }
    if set(aircraft_activity.values()) != {1}:
        raise SystemExit(
            "Aircraft was not active on both family-transition renders: "
            f"{aircraft_activity}"
        )
    if pattern is not None:
        terrain_matches = [
            match
            for match in ACTIVE_RE.finditer(contents)
            if 1 <= int(match.group(1)) <= 37
        ]
        events = [
            (int(match.group(1)), int(match.group(2)))
            for match in terrain_matches
        ]
        transaction_index = find_exact_transaction(events, pattern)
        transaction_start = terrain_matches[transaction_index].start()
        transaction_end = terrain_matches[
            transaction_index + len(pattern) - 1
        ].end()
        if before["log_offsets"]["camera"] >= transaction_start:
            raise SystemExit("Pre-transition pose overlaps the family transaction")
        if after["log_offsets"]["aircraft"] <= transaction_end:
            raise SystemExit(
                "Post-transition pose was published before the family transaction ended"
            )
    if (
        before["camera_minus_aircraft_raw"]
        != after["camera_minus_aircraft_raw"]
    ):
        raise SystemExit(
            "Aircraft/camera chase offset changed across the family rebase: "
            f"before={before['camera_minus_aircraft_raw']}, "
            f"after={after['camera_minus_aircraft_raw']}"
        )
    aircraft_delta = [
        after["aircraft_raw"][axis] - before["aircraft_raw"][axis]
        for axis in range(3)
    ]
    camera_delta = [
        after["camera_raw"][axis] - before["camera_raw"][axis]
        for axis in range(3)
    ]
    if aircraft_delta != camera_delta:
        raise SystemExit(
            "Aircraft and camera received different rebase translations: "
            f"aircraft={aircraft_delta}, camera={camera_delta}"
        )
    frame_motion = [
        aircraft_delta[axis] - FIXED_WEST_REBASE_RAW[axis]
        for axis in range(3)
    ]
    if max(abs(component) for component in frame_motion) > MAX_FRAME_MOTION_RAW:
        raise SystemExit(
            "Aircraft/camera pose delta is not one west terrain-cell wrap "
            f"plus plausible frame motion: delta={aircraft_delta}, "
            f"motion={frame_motion}"
        )
    return {
        "render_sequences": [before_sequence, after_sequence],
        "before": before,
        "after": after,
        "expected_cell_translation_raw": list(FIXED_WEST_REBASE_RAW),
        "common_translation_delta_raw": aircraft_delta,
        "frame_motion_after_rebase_raw": frame_motion,
        "aircraft_active_by_render": aircraft_activity,
        "chase_offset_preserved": True,
    }


def validate_terrain_reposition(
    contents: str,
    render_bracket: tuple[int, int],
    pattern: tuple[tuple[int, int], ...],
    plan: dict[str, object],
) -> dict[str, object]:
    """Prove every resident slot was placed from one post-wrap origin."""

    renders = [
        match
        for match in RENDER_RE.finditer(contents)
        if int(match.group(1)) in render_bracket
    ]
    if len(renders) != 2 or [int(match.group(1)) for match in renders] != list(
        render_bracket
    ):
        raise SystemExit(
            f"Could not locate unique ordered terrain bracket {render_bracket}"
        )
    terrain_activity = [
        match
        for match in ACTIVE_RE.finditer(contents)
        if 1 <= int(match.group(1)) <= 37
    ]
    activity_events = [
        (int(match.group(1)), int(match.group(2)))
        for match in terrain_activity
    ]
    transaction_index = find_exact_transaction(activity_events, pattern)
    transaction_start = terrain_activity[transaction_index].start()
    window_start = renders[0].end()
    if transaction_start >= renders[1].start():
        raise SystemExit("Terrain transaction is outside its render bracket")
    records = [
        {
            "log_offset": match.start(),
            "slot": int(match.group(1)),
            "raw": [int(match.group(axis)) for axis in (2, 3, 4)],
        }
        for match in WIDE_POSE_RE.finditer(
            contents, window_start, transaction_start
        )
    ]
    loads = plan["loads"]
    assert isinstance(loads, list)
    plan_slots = [int(entry["slot"]) for entry in loads]
    observed_slots = [int(record["slot"]) for record in records]
    if observed_slots != plan_slots:
        raise SystemExit(
            "Post-wrap terrain placement order/identity changed: "
            f"expected={plan_slots}, observed={observed_slots}"
        )

    entries = {int(entry["slot"]): entry for entry in loads}
    east_origins: set[int] = set()
    north_origins: set[int] = set()
    wrong_heights: dict[int, int] = {}
    for record in records:
        slot = int(record["slot"])
        raw = record["raw"]
        assert isinstance(raw, list)
        center = entries[slot]["center_counts"]
        assert isinstance(center, list) and len(center) == 2
        # Retained KOAK axes deliberately have opposite signs: Pingo X is
        # north-relative while positive Pingo Z is west.
        east_origins.add(int(raw[2]) + int(center[0]))
        north_origins.add(int(center[1]) - int(raw[0]))
        if int(raw[1]) != TERRAIN_Y_RAW:
            wrong_heights[slot] = int(raw[1])
    if len(east_origins) != 1 or len(north_origins) != 1 or wrong_heights:
        raise SystemExit(
            "Terrain slots do not share one coarse-cell placement origin: "
            f"east={sorted(east_origins)}, north={sorted(north_origins)}, "
            f"heights={wrong_heights}"
        )
    east_origin = next(iter(east_origins))
    north_origin = next(iter(north_origins))
    for axis, origin in (("east", east_origin), ("north", north_origin)):
        if (origin - COARSE_CENTER_BIAS_RAW) % COARSE_CELL_RAW:
            raise SystemExit(
                f"Terrain {axis} origin is not a coarse-cell centre: {origin}"
            )
    coarse = [
        (east_origin - COARSE_CENTER_BIAS_RAW) // COARSE_CELL_RAW,
        (north_origin - COARSE_CENTER_BIAS_RAW) // COARSE_CELL_RAW,
    ]
    if coarse[0] >= 92:
        raise SystemExit(
            f"Terrain placements were not recomputed west of the boundary: {coarse}"
        )
    return {
        "record_count": len(records),
        "slot_order": observed_slots,
        "coarse_cell": coarse,
        "coarse_center_raw": [east_origin, north_origin],
        "terrain_y_raw": TERRAIN_Y_RAW,
        "records": records,
    }


def expected_final_slots(plan: dict[str, object]) -> set[int]:
    loads = plan["loads"]
    assert isinstance(loads, list)
    active = {
        int(entry["slot"])
        for entry in loads
        if bool(entry["activate_after_load"])
    }
    for slot, value in transition_pattern(plan):
        if value:
            active.add(slot)
        else:
            active.remove(slot)
    return active


def expected_terrain_histories(
    plan: dict[str, object]
) -> dict[int, list[int]]:
    histories = {slot: [0] for slot in range(1, 38)}
    loads = plan["loads"]
    assert isinstance(loads, list)
    for entry in loads:
        if bool(entry["activate_after_load"]):
            histories[int(entry["slot"])].append(1)
    for slot, active in transition_pattern(plan):
        histories[slot].append(active)
    return histories


def terrain_activity_histories(
    events: list[tuple[int, int]]
) -> dict[int, list[int]]:
    histories = {slot: [] for slot in range(1, 38)}
    for object_id, active in events:
        if object_id in histories:
            histories[object_id].append(active)
    return histories


def publication_evidence(contents: str) -> dict[str, object]:
    publications = [
        {
            "mesh_id": int(match.group(2)),
            "bytes": int(match.group(3)),
            "vertices": int(match.group(4)),
            "indices": int(match.group(5)),
            "publication_us": int(match.group(8)),
        }
        for match in family_capture.MESH_REPLACE_RE.finditer(contents)
    ]
    expected = {*range(1, 38), 101, 102}
    counts = Counter(int(item["mesh_id"]) for item in publications)
    wrong_multiplicity = {
        mesh_id: counts.get(mesh_id, 0)
        for mesh_id in sorted(expected)
        if counts.get(mesh_id, 0) != 1
    }
    unexpected = sorted(set(counts) - expected)
    if wrong_multiplicity or unexpected:
        raise SystemExit(
            "Mesh publication identity/multiplicity changed: "
            f"wrong={wrong_multiplicity}, unexpected={unexpected}"
        )
    return {
        "count": len(publications),
        "mesh_ids": sorted(counts),
        "maximum_publication_us": max(
            int(item["publication_us"]) for item in publications
        ),
        "records": publications,
    }


def replay_terrain_activity(events: list[tuple[int, int]]) -> set[int]:
    state: dict[int, int] = {}
    for object_id, active in events:
        if 1 <= object_id <= 37:
            state[object_id] = active
    return {object_id for object_id, active in state.items() if active}


def decode_family_state(
    memory: dict[int, int], symbols: dict[str, int]
) -> dict[str, int]:
    def byte(name: str) -> int:
        return takeoff_trace.read_span(memory, symbols[name], 1)[0]

    return {
        "plan_cursor": byte("family_plan_cursor"),
        "plan_total": symbols["family_plan_total_count"],
        "error_hold": byte("family_error_hold"),
        "swap_complete": byte("family_swap_complete"),
        "last_error": byte("streaming_last_error"),
    }


def validate_transition(
    state: dict[str, object],
    family_state: dict[str, int],
    events: list[tuple[int, int]],
    plan: dict[str, object],
) -> dict[str, object]:
    pattern = transition_pattern(plan)
    transaction_index = find_exact_transaction(events, pattern)
    actual_slots = replay_terrain_activity(events)
    expected_slots = expected_final_slots(plan)
    actual_histories = terrain_activity_histories(events)
    expected_histories = expected_terrain_histories(plan)
    if actual_histories != expected_histories:
        changed = {
            slot: {
                "expected": expected_histories[slot],
                "actual": actual_histories[slot],
            }
            for slot in range(1, 38)
            if actual_histories[slot] != expected_histories[slot]
        }
        raise SystemExit(f"Terrain activation history changed: {changed}")
    if actual_slots != expected_slots:
        raise SystemExit(
            "Final active terrain slots disagree with the next-family plan: "
            f"expected {sorted(expected_slots)}, got {sorted(actual_slots)}"
        )
    if len(actual_slots) != 24:
        raise SystemExit(f"Transition ended with {len(actual_slots)} terrain slots")
    if family_state["plan_cursor"] != family_state["plan_total"]:
        raise SystemExit(f"Family preload did not arm: {family_state}")
    if (
        family_state["error_hold"]
        or family_state["last_error"]
        or family_state["swap_complete"] != 1
    ):
        raise SystemExit(f"Family runtime ended in an invalid state: {family_state}")
    coarse = state["coarse_cell"]
    assert isinstance(coarse, list)
    if int(coarse[0]) >= 92:
        raise SystemExit(f"Aircraft did not cross the west boundary: {coarse}")
    if bool(state["arithmetic_failure"]):
        raise SystemExit("Flight model reported an arithmetic failure")
    displacement = state["displacement_m"]
    assert isinstance(displacement, list)
    # Starting at local Z=2181 counts, entering coarse X=91 requires 1915
    # counts to the first edge plus two complete 8192-count cells.
    if float(displacement[1]) < 1_143.6875:
        raise SystemExit(f"Westward displacement is too small: {displacement}")
    return {
        "transaction_terrain_event_index": transaction_index,
        "transaction_command_count": len(pattern),
        "final_active_terrain_slots": sorted(actual_slots),
    }


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if arguments.trigger_sequence < 30:
        raise SystemExit("--trigger-sequence must allow all 37 preload records")
    if arguments.final_sequence <= arguments.trigger_sequence:
        raise SystemExit("--final-sequence must follow --trigger-sequence")
    if any(
        sequence <= arguments.trigger_sequence
        or sequence >= arguments.final_sequence
        for sequence in arguments.boundary_sequences
    ):
        raise SystemExit(
            "--boundary-sequences must lie strictly between trigger and final"
        )
    if arguments.pitch_delay_vblanks <= 0 or arguments.pull_vblanks <= 0:
        raise SystemExit("pitch timing must be positive")

    emulator = input_trace.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = input_trace.require_file(input_trace.MOS_BINARY, "MOS image")
    real_vdp = input_trace.require_file(arguments.vdp_module, "diagnostic VDP")
    family_capture.require_diagnostic_vdp(real_vdp)
    require_pose_diagnostics(real_vdp)
    program = input_trace.require_file(PROGRAM, "family KOAK fixture")
    plan_path = input_trace.require_file(PLAN, "generated family plan")
    proxy_source = input_trace.require_file(
        input_trace.PROXY_SOURCE, "input proxy source"
    )
    plan = json.loads(plan_path.read_text())
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)

    proxy = output / "vdp_input_trace_proxy.so"
    exports = input_trace.build_proxy(proxy_source, proxy)
    log_path = output / "emulator.log"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /flight\r\n"
        b"load P3DLOD.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    dump_sequences = tuple(
        sorted(
            {
                0,
                arguments.trigger_sequence,
                *arguments.boundary_sequences,
                arguments.final_sequence,
            }
        )
    )
    dump_selectors = ",".join(
        f"{BITMAP_ID}:{sequence}" for sequence in dump_sequences
    )
    trigger_marker = (
        f"PINGO_DUMP seq={arguments.trigger_sequence} "
        f"bmid={BITMAP_ID} status=ok"
    )
    final_marker = (
        f"PINGO_DUMP seq={arguments.final_sequence} "
        f"bmid={BITMAP_ID} status=ok"
    )
    swap_marker = "PINGO_STREAM object_active=ok oid=37 active=1"
    deadline = time.monotonic() + arguments.timeout
    process: subprocess.Popen[bytes] | None = None
    shutdown_method = "not-started"
    contents = ""

    with (
        tempfile.TemporaryDirectory(prefix="kft-symbol-") as symbol_name,
        tempfile.TemporaryDirectory(prefix="kft-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="kft-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="kft-fifo-") as fifo_name,
    ):
        symbols, symbol_path = export_exact_symbols(Path(symbol_name), program)
        sd_root = Path(sd_name)
        shutil.copytree(FIXTURE, sd_root / "flight")
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
            + "\n"
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
                wait_for_log(
                    log_path,
                    lambda text: trigger_marker in text,
                    process,
                    deadline,
                    f"armed render sequence {arguments.trigger_sequence}",
                )
                takeoff_trace.write_command_batch(
                    control_fd,
                    [
                        f"tap 0x{input_trace.SET2_CODES['V']:04x} 4",
                        f"down 0x{input_trace.SET2_CODES['W']:04x}",
                        (
                            "tapafter "
                            f"0x{input_trace.SET2_CODES['DOWN']:04x} "
                            f"{arguments.pitch_delay_vblanks} "
                            f"{arguments.pull_vblanks}"
                        ),
                    ],
                )
                wait_for_log(
                    log_path,
                    lambda text: final_marker in text and swap_marker in text,
                    process,
                    deadline,
                    f"post-transition render sequence {arguments.final_sequence}",
                )
                input_trace.write_command(
                    control_fd, f"up 0x{input_trace.SET2_CODES['W']:04x}"
                )
                wait_for_log(
                    log_path,
                    lambda text: "action=up scancode=0x001d" in text,
                    process,
                    deadline,
                    "W release",
                )
                contents = debugger_snapshot(process, log_path, symbols, deadline)
                shutdown_method = "debugger-memory-exit"
        finally:
            os.close(control_fd)
            if process is not None and process.poll() is None:
                shutdown_method = input_trace.stop_process(process)

        symbols_sha = sha256(symbol_path)

    assert process is not None
    failures = input_trace.find_failures(contents)
    failures.extend(family_capture.find_log_failures(contents))
    if failures:
        raise SystemExit(f"Final family trace contains failures: {sorted(set(failures))}")
    memory = takeoff_trace.parse_memory(contents)
    state = takeoff_trace.decode_state(memory, symbols)
    family_state = decode_family_state(memory, symbols)
    input_records = input_trace.input_records(contents)
    input_timing = takeoff_trace.validate_takeoff(
        state,
        input_records,
        argparse.Namespace(
            pitch_delay_vblanks=arguments.pitch_delay_vblanks,
            pull_vblanks=arguments.pull_vblanks,
            counter_vblanks=0,
        ),
    )
    if any(record["scancode"] == 0x0007 for record in input_records):
        raise SystemExit("Natural-flight trace unexpectedly used the F12 test key")
    events = activity_events(contents)
    publications = publication_evidence(contents)
    transition = validate_transition(state, family_state, events, plan)
    render_bracket = transaction_render_bracket(
        contents, transition_pattern(plan)
    )
    transition["render_bracket"] = list(render_bracket)
    transition["render_bracket_captured"] = all(
        sequence in dump_sequences for sequence in render_bracket
    )
    if not transition["render_bracket_captured"]:
        raise SystemExit(
            "Boundary capture selection omitted the actual family-transition "
            f"renders {render_bracket}"
        )
    transition["pose_rebase"] = validate_pose_rebase(
        contents, render_bracket, transition_pattern(plan)
    )
    transition["terrain_reposition"] = validate_terrain_reposition(
        contents, render_bracket, transition_pattern(plan), plan
    )

    frames = []
    for sequence in dump_sequences:
        raw = input_trace.require_file(
            output / f"pingo-{BITMAP_ID}-{sequence}.rgba2",
            f"RGBA2222 render sequence {sequence}",
        )
        depth = input_trace.require_file(
            output / f"pingo-{BITMAP_ID}-{sequence}.z32le",
            f"depth render sequence {sequence}",
        )
        ppm = output / f"pingo-{BITMAP_ID}-{sequence}.ppm"
        input_trace.write_ppm(raw, ppm)
        analysis = family_capture.analyze_frame(raw, depth)
        analysis.update(
            {
                "sequence": sequence,
                "rgba2_sha256": sha256(raw),
                "depth_sha256": sha256(depth),
                "ppm_sha256": sha256(ppm),
            }
        )
        frames.append(analysis)
    principal_hashes = {
        frame["rgba2_sha256"]
        for frame in frames
        if frame["sequence"]
        in (0, arguments.trigger_sequence, arguments.final_sequence)
    }
    if len(principal_hashes) != 3:
        raise SystemExit("Initial, armed, and transitioned frames are not distinct")

    render_sequences = [int(value) for value in RENDER_RE.findall(contents)]
    report = {
        "schema": "pingo-terrain-koak-family-transition-trace-v2",
        "program": {"path": str(program), "sha256": sha256(program)},
        "plan": {"path": str(plan_path), "sha256": sha256(plan_path)},
        "real_vdp": {"path": str(real_vdp), "sha256": sha256(real_vdp)},
        "proxy": {
            "path": str(proxy),
            "sha256": sha256(proxy),
            "source_sha256": sha256(proxy_source),
            "exports": sorted(exports),
        },
        "symbol_export": {
            "sha256": symbols_sha,
            "exact_binary_match": True,
            "addresses": {
                name: symbols[name]
                for name in (
                    "flight_state",
                    "object_state",
                    "streaming_coarse_x",
                    "family_plan_cursor",
                    "family_error_hold",
                    "family_swap_complete",
                    "streaming_last_error",
                )
            },
        },
        "control_schedule": {
            "trigger_sequence": arguments.trigger_sequence,
            "final_sequence": arguments.final_sequence,
            "boundary_sequences": list(arguments.boundary_sequences),
            "pitch_delay_vblanks": arguments.pitch_delay_vblanks,
            "pull_vblanks": arguments.pull_vblanks,
            "observed_deltas": input_timing,
        },
        "events": input_records,
        "state": state,
        "family_state": family_state,
        "transition": transition,
        "mesh_publications": publications,
        "frames": frames,
        "render_sequence_range": [min(render_sequences), max(render_sequences)],
        "transition_qualified": True,
        "shutdown": shutdown_method,
        "emulator_exit_status": process.returncode,
        "emulator_log": {"path": str(log_path), "sha256": sha256(log_path)},
    }
    report_path = output / "family-transition-trace-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Headless KOAK family transition passed: {report_path}")
    print(
        "Crossed",
        f"coarse={state['coarse_cell']}",
        f"displacement_m={state['displacement_m']}",
        f"active_terrain={len(transition['final_active_terrain_slots'])}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
