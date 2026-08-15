#!/usr/bin/env python3
"""Qualify one live regular-LOD C-policy handoff in every hex direction.

Each input chord starts from a fresh cold Marina process.  The tracer releases
the chord immediately after the first observed floating-origin rebase, reads
the resulting origin from the debugger, and only then binds the run to one of
the six host transition recipes.  This deliberately tests the input-to-world
mapping instead of assuming which chord selects which axial neighbor.

The default is the installed DUAL_STRICT sibling.  An explicitly built
C_GUARDED sibling can be supplied with ``--program``, ``--symbols`` and
``--expected-policy-mode c-guarded`` for the same matrix.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Sequence

import capture_koak_flight as capture
import capture_terrain_manager_survey as survey
import trace_koak_input as input_trace
import trace_regular_lod_staged_north_transitions as staged
from pingo_terrain.hex_terrain import HEX_TERRAIN_Y_COUNT, hex_center_m
from pingo_terrain.p3dm import parse_container
from pingo_terrain.regional_terrain import (
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
)
from pingo_terrain.regular_lod_runtime import (
    CoarsePlanEntry,
    TRANSITION_DIRECTION_NAMES,
    TRANSITION_DIRECTION_STEPS,
    build_terrain_owner_plan,
    schedule_terrain_transition,
)


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
DEFAULT_PROGRAM = FIXTURE / "P3DRGLC.BIN"
DEFAULT_POLICY_MODULE = FIXTURE / staged.POLICY_MODULE_NAME
DEFAULT_SYMBOLS = (
    ROOT
    / "fixtures/terrain-manager-regular-lod-c-policy-survey/tgt/"
    "terrain-manager-regular-lod-c-policy-survey.symbols"
)
REPORT_NAME = "regular-lod-c-policy-six-directions.json"
DIRECTION_REPORT_NAME = "direction.json"
SCHEMA = "pingo-terrain-regular-lod-c-policy-six-directions-v1"
DIRECTION_SCHEMA = "pingo-terrain-regular-lod-c-policy-direction-v1"
POST_CONVERGENCE_RENDERS = 3
REBASE_LARGE_DELTA = 2_000
REBASE_COMPONENT_TOLERANCE = 512

POLICY_MODES = {
    "dual-strict": staged.POLICY_MODE_DUAL_STRICT,
    "c-guarded": staged.POLICY_MODE_C_GUARDED,
}


@dataclass(frozen=True, slots=True)
class InputChord:
    name: str
    keys: tuple[str, ...]
    precenter_with_s: bool = False

    @property
    def scancodes(self) -> tuple[int, ...]:
        return tuple(input_trace.SET2_CODES[key] for key in self.keys)


# These are physical input witnesses, not assumed world-direction labels.
INPUT_CHORDS = (
    InputChord("w", ("W",)),
    InputChord("s", ("S",)),
    InputChord("w-d", ("W", "D"), True),
    InputChord("s-d", ("S", "D")),
    InputChord("w-a", ("W", "A"), True),
    InputChord("s-a", ("S", "A")),
)


class QualificationError(ValueError):
    """One direction violated the live C-policy handoff contract."""


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    parser.add_argument(
        "--policy-module", type=Path, default=DEFAULT_POLICY_MODULE
    )
    parser.add_argument(
        "--expected-policy-mode",
        choices=tuple(POLICY_MODES),
        default="dual-strict",
    )
    parser.add_argument(
        "--vdp-module", type=Path, default=survey.DEFAULT_VDP
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-per-direction", type=float, default=180.0)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _camera_rebase_delta(step: tuple[int, int]) -> tuple[int, int]:
    delta_q, delta_r = step
    origin_north_delta = 4_400 * delta_q + 8_800 * delta_r
    origin_east_delta = 7_680 * delta_q
    return -origin_north_delta, -origin_east_delta


def classify_rebase_delta(delta_x: int, delta_z: int) -> int:
    """Return the unique provider direction represented by a camera jump."""

    matches = [
        index
        for index, step in enumerate(TRANSITION_DIRECTION_STEPS)
        if abs(delta_x - _camera_rebase_delta(step)[0])
        <= REBASE_COMPONENT_TOLERANCE
        and abs(delta_z - _camera_rebase_delta(step)[1])
        <= REBASE_COMPONENT_TOLERANCE
    ]
    if len(matches) != 1:
        raise QualificationError(
            "camera rebase is not one unique axial neighbor: "
            f"delta={(delta_x, delta_z)!r}, matches={matches!r}"
        )
    return matches[0]


def camera_rebases(
    contents: str,
    start: int,
    initial_position: tuple[int, int, int] | None = None,
) -> list[dict[str, object]]:
    initial = (
        (
            staged.CAMERA_INITIAL_X,
            staged.CAMERA_INITIAL_Y,
            staged.CAMERA_INITIAL_Z,
        )
        if initial_position is None
        else initial_position
    )
    positions: list[tuple[int, int, int, int]] = [
        (start, *initial)
    ]
    positions.extend(
        (
            match.start(),
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        for match in staged.CAMERA_TRANSLATION_RE.finditer(contents, start)
    )
    rebases: list[dict[str, object]] = []
    for previous, current in zip(positions, positions[1:]):
        delta_x = current[1] - previous[1]
        delta_z = current[3] - previous[3]
        if (
            abs(delta_x) < REBASE_LARGE_DELTA
            and abs(delta_z) < REBASE_LARGE_DELTA
        ):
            continue
        direction = classify_rebase_delta(delta_x, delta_z)
        step = TRANSITION_DIRECTION_STEPS[direction]
        rebases.append(
            {
                "offset": current[0],
                "direction_index": direction,
                "direction_name": TRANSITION_DIRECTION_NAMES[direction],
                "step": list(step),
                "raw_before": list(previous[1:]),
                "raw_after": list(current[1:]),
                "raw_delta_xz": [delta_x, delta_z],
                "ideal_rebase_delta_xz": list(_camera_rebase_delta(step)),
            }
        )
    return rebases


def first_rebase_observed(contents: str, start: int) -> bool:
    return bool(camera_rebases(contents, start))


def transition_schedule(
    origin: tuple[int, int], direction_index: int
) -> tuple[object, list[tuple[int, int]]]:
    delta_q, delta_r = TRANSITION_DIRECTION_STEPS[direction_index]
    old = build_terrain_owner_plan(*origin, 5)
    new = build_terrain_owner_plan(
        origin[0] + delta_q, origin[1] + delta_r, 5
    )
    schedule = schedule_terrain_transition(old, new)
    shapes = [
        (len(step.group.retiring), len(step.group.entering))
        for step in schedule.steps
    ]
    return schedule, shapes


def input_released(contents: str, chord: InputChord) -> bool:
    records = [
        record
        for record in input_trace.input_records(contents)
        if int(record["scancode"]) in chord.scancodes
    ]
    return all(
        [record["action"] for record in records if int(record["scancode"]) == code]
        == ["down", "up"]
        for code in chord.scancodes
    )


def latest_camera_position(
    contents: str,
    start: int,
    initial_position: tuple[int, int, int] | None = None,
) -> tuple[int, int, int]:
    position = (
        (
            staged.CAMERA_INITIAL_X,
            staged.CAMERA_INITIAL_Y,
            staged.CAMERA_INITIAL_Z,
        )
        if initial_position is None
        else initial_position
    )
    for match in staged.CAMERA_TRANSLATION_RE.finditer(contents, start):
        position = tuple(int(match.group(axis)) for axis in range(1, 4))
    return position


def precenter_reached(contents: str, start: int) -> bool:
    if camera_rebases(contents, start):
        raise QualificationError("precentering crossed the starting hex")
    x, y, z = latest_camera_position(contents, start)
    if y != staged.CAMERA_INITIAL_Y or z != staged.CAMERA_INITIAL_Z:
        raise QualificationError(
            f"south precentering changed camera Y/Z: {(x, y, z)!r}"
        )
    return abs(x) <= 512


def precenter_release_observed(contents: str) -> bool:
    code = input_trace.SET2_CODES["S"]
    actions = [
        record["action"]
        for record in input_trace.input_records(contents)
        if record["scancode"] == code
    ]
    return actions == ["down", "up"]


def transition_complete(
    contents: str,
    start: int,
    chord: InputChord,
    shapes: Sequence[tuple[int, int]],
) -> bool:
    if not input_released(contents, chord):
        return False
    activity = list(capture.OBJECT_ACTIVE_RE.finditer(contents, start))
    entering = sum(int(match.group(2)) == 1 for match in activity)
    retiring = sum(int(match.group(2)) == 0 for match in activity)
    expected_entering = sum(item[1] for item in shapes)
    expected_retiring = sum(item[0] for item in shapes)
    if entering < expected_entering or retiring < expected_retiring:
        return False
    if not activity:
        return False
    renders_after = sum(
        match.start() > activity[-1].start()
        for match in staged.RENDER_RE.finditer(contents, start)
    )
    return renders_after >= POST_CONVERGENCE_RENDERS


def validate_input(contents: str, chord: InputChord) -> dict[str, object]:
    relevant_codes = {
        input_trace.SET2_CODES[key]
        for key in ("W", "S", "A", "D")
    }
    records = [
        record
        for record in input_trace.input_records(contents)
        if int(record["scancode"]) in relevant_codes
    ]
    expected = []
    if chord.precenter_with_s:
        expected.extend(
            (
                ("down", input_trace.SET2_CODES["S"]),
                ("up", input_trace.SET2_CODES["S"]),
            )
        )
    expected.extend(("down", code) for code in chord.scancodes)
    expected.extend(("up", code) for code in reversed(chord.scancodes))
    observed = [
        (str(record["action"]), int(record["scancode"]))
        for record in records
    ]
    if observed != expected:
        raise QualificationError(
            f"input chord {chord.name} changed: {observed!r} != {expected!r}"
        )
    if any(record["source"] != "fifo" for record in records):
        raise QualificationError(
            f"input chord {chord.name} did not use FIFO make/break"
        )
    return {
        "chord": chord.name,
        "keys": list(chord.keys),
        "precenter_with_s": chord.precenter_with_s,
        "scancodes": [f"0x{code:04x}" for code in chord.scancodes],
        "events": records,
    }


def validate_transition_stream(
    contents: str,
    start: int,
    shapes: Sequence[tuple[int, int]],
    expected_final_active_count: int,
) -> dict[str, object]:
    expected_entering = sum(item[1] for item in shapes)
    expected_retiring = sum(item[0] for item in shapes)
    activity = list(capture.OBJECT_ACTIVE_RE.finditer(contents, start))
    entering = [match for match in activity if int(match.group(2)) == 1]
    retiring = [match for match in activity if int(match.group(2)) == 0]
    if (len(entering), len(retiring)) != (
        expected_entering,
        expected_retiring,
    ):
        raise QualificationError(
            "transition activity differs from the host schedule: "
            f"observed={(len(retiring), len(entering))}, "
            f"expected={(expected_retiring, expected_entering)}"
        )

    state = staged.activity_state_at(contents, start)
    posed: set[int] = set()
    replaced: set[int] = set()
    replacements: list[int] = []
    semantic: list[tuple[int, str, int]] = []
    semantic.extend(
        (match.start(), "replace", int(match.group(2)))
        for match in capture.MESH_REPLACE_RE.finditer(contents, start)
    )
    semantic.extend(
        (match.start(), "pose", int(match.group(1)))
        for match in survey.OBJECT_TRANSLATION_RE.finditer(contents, start)
    )
    semantic.extend(
        (match.start(), f"active-{match.group(2)}", int(match.group(1)))
        for match in activity
    )
    semantic.sort()

    for _, kind, object_id in semantic:
        if kind == "replace":
            if state.get(object_id) != 0:
                raise QualificationError(
                    f"command 50 replaced active OID {object_id}"
                )
            replacements.append(object_id)
            replaced.add(object_id)
            posed.discard(object_id)
        elif kind == "pose":
            posed.add(object_id)
        elif kind == "active-0":
            if state.get(object_id) != 1:
                raise QualificationError(
                    f"group retired non-active OID {object_id}"
                )
            state[object_id] = 0
            posed.discard(object_id)
        else:
            if state.get(object_id) != 0:
                raise QualificationError(
                    f"group activated non-inactive OID {object_id}"
                )
            if object_id not in replaced or object_id not in posed:
                raise QualificationError(
                    f"group activated OID {object_id} without staged replace/pose"
                )
            state[object_id] = 1
            replaced.discard(object_id)
            posed.discard(object_id)

    if len(replacements) != expected_entering:
        raise QualificationError(
            f"command 50 count changed: {len(replacements)} != {expected_entering}"
        )
    final_active = sorted(
        object_id for object_id, value in state.items() if value
    )
    if len(final_active) != expected_final_active_count:
        raise QualificationError(
            f"transition ended with {len(final_active)} active objects, "
            f"expected {expected_final_active_count}"
        )

    render_offsets = [
        match.start() for match in staged.RENDER_RE.finditer(contents, start)
    ]
    by_interval: dict[int, list[object]] = {}
    for match in activity:
        by_interval.setdefault(
            bisect_right(render_offsets, match.start()), []
        ).append(match)
    observed_shapes: list[tuple[int, int]] = []
    for interval in sorted(by_interval):
        records = by_interval[interval]
        values = [int(match.group(2)) for match in records]
        first_enter = values.index(1) if 1 in values else len(values)
        if any(value != 0 for value in values[:first_enter]) or any(
            value != 1 for value in values[first_enter:]
        ):
            raise QualificationError(
                f"group interval {interval} did not retire before enter"
            )
        observed_shapes.append((first_enter, len(values) - first_enter))
    if observed_shapes != list(shapes):
        raise QualificationError(
            f"atomic group shapes changed: {observed_shapes!r} != {list(shapes)!r}"
        )

    return {
        "command50_count": len(replacements),
        "command50_all_inactive": True,
        "retiring_count": len(retiring),
        "entering_count": len(entering),
        "group_count": len(shapes),
        "group_shapes": [list(item) for item in shapes],
        "retire_before_enter": True,
        "render_inside_group_commit": False,
        "final_active_ids": final_active,
    }


def active_slot_identities(
    contents: str, symbols: dict[str, int]
) -> dict[int, tuple[int, int, int]]:
    memory = staged.debugger.parse_memory(contents)
    q_values = staged.debugger.read_span(
        memory, symbols["terrain_manager_resident_q"], staged.SLOT_COUNT * 2
    )
    r_values = staged.debugger.read_span(
        memory, symbols["terrain_manager_resident_r"], staged.SLOT_COUNT * 2
    )
    lod_values = staged.debugger.read_span(
        memory, symbols["terrain_manager_resident_lod"], staged.SLOT_COUNT
    )
    flags = staged.debugger.read_span(
        memory, symbols["terrain_manager_resident_flags"], staged.SLOT_COUNT
    )
    active_bit = symbols["terrain_manager_flag_active"]
    return {
        slot + 1: (
            lod_values[slot],
            staged.signed_word(q_values, slot * 2),
            staged.signed_word(r_values, slot * 2),
        )
        for slot, flag in enumerate(flags)
        if flag & active_bit
    }


@lru_cache(maxsize=None)
def coarse_center_m(lod: int, anchor_q: int, anchor_row: int) -> tuple[int, int]:
    entry = CoarsePlanEntry(lod, anchor_q, anchor_row)
    path = FIXTURE / entry.node.relative_path
    if not path.is_file():
        raise QualificationError(f"coarse record is absent: {path}")
    tile = parse_container(path.read_bytes())
    if (
        tile.meta.lod,
        tile.meta.tile_x,
        tile.meta.tile_y,
    ) != (lod, anchor_q, anchor_row):
        raise QualificationError(
            f"coarse P3DM identity changed: {path}"
        )
    return (
        REGIONAL_ORIGIN_EAST_M + tile.meta.center_east_m,
        REGIONAL_ORIGIN_NORTH_M + tile.meta.center_north_m,
    )


def expected_owner_transform(
    identity: tuple[int, int, int], origin: tuple[int, int]
) -> tuple[int, int, int]:
    lod, q, r_or_row = identity
    if lod == 0:
        center_east, center_north = hex_center_m(q, r_or_row)
    else:
        center_east, center_north = coarse_center_m(lod, q, r_or_row)
    origin_east, origin_north = hex_center_m(*origin)
    return (
        (center_north - origin_north) * 16,
        HEX_TERRAIN_Y_COUNT,
        (center_east - origin_east) * 16,
    )


def validate_final_transforms(
    contents: str,
    start: int,
    symbols: dict[str, int],
    origin: tuple[int, int],
) -> dict[str, object]:
    identities = active_slot_identities(contents, symbols)
    last_pose: dict[int, tuple[int, tuple[int, int, int]]] = {}
    for match in survey.OBJECT_TRANSLATION_RE.finditer(contents):
        last_pose[int(match.group(1))] = (
            match.start(),
            tuple(int(match.group(axis)) for axis in range(2, 5)),
        )
    records: list[dict[str, object]] = []
    for object_id in sorted(identities):
        identity = identities[object_id]
        pose = last_pose.get(object_id)
        if pose is None or pose[0] < start:
            raise QualificationError(
                f"active OID {object_id} lacks a post-cold command-52 transform"
            )
        expected = expected_owner_transform(identity, origin)
        if pose[1] != expected:
            raise QualificationError(
                f"OID {object_id} transform changed: {pose[1]} != {expected} "
                f"for owner {identity}"
            )
        records.append(
            {
                "object_id": object_id,
                "slot": object_id - 1,
                "lod": identity[0],
                "q": identity[1],
                "r_or_offset_row": identity[2],
                "translation": list(pose[1]),
            }
        )
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )
    return {
        "active_owner_slot_transform_count": len(records),
        "active_owner_slot_map_exact": True,
        "active_transforms_exact": True,
        "records_sha256": hashlib.sha256(encoded).hexdigest(),
        "records": records,
    }


def _write_input(control_fd: int, action: str, codes: Sequence[int]) -> None:
    selected = codes if action == "down" else tuple(reversed(codes))
    for code in selected:
        input_trace.write_command(control_fd, f"{action} 0x{code:04x}")


def deterministic_direction_summary(
    report: dict[str, object]
) -> dict[str, object]:
    """Strip debugger offsets, host-vblank timing and log hashes from a run."""

    input_evidence = report["input"]
    neighbor = report["observed_neighbor"]
    schedule = report["host_schedule"]
    stream = report["transition_stream"]
    final_state = report["final_state"]
    transforms = report["final_owner_slot_transforms"]
    assert isinstance(input_evidence, dict)
    assert isinstance(neighbor, dict)
    assert isinstance(schedule, dict)
    assert isinstance(stream, dict)
    assert isinstance(final_state, dict)
    assert isinstance(transforms, dict)
    policy = final_state["policy"]
    manager = final_state["manager"]
    provider = final_state["provider"]
    assert isinstance(policy, dict)
    assert isinstance(manager, dict)
    assert isinstance(provider, dict)
    return {
        "input": {
            "chord": input_evidence["chord"],
            "keys": input_evidence["keys"],
            "precenter_with_s": input_evidence["precenter_with_s"],
            "scancodes": input_evidence["scancodes"],
        },
        "neighbor": {
            "direction_index": neighbor["direction_index"],
            "direction_name": neighbor["direction_name"],
            "step": neighbor["step"],
            "origin": neighbor["origin"],
            "host_neighbor_valid": neighbor["host_neighbor_valid"],
        },
        "host_schedule": schedule,
        "stream": {
            name: stream[name]
            for name in (
                "command50_count",
                "command50_all_inactive",
                "retiring_count",
                "entering_count",
                "group_count",
                "group_shapes",
                "retire_before_enter",
                "render_inside_group_commit",
            )
        },
        "manager": {
            name: manager[name]
            for name in (
                "state",
                "ring",
                "desired_count",
                "active_count",
                "converged",
                "last_operation",
                "last_error",
                "origin",
                "proposed_origin",
                "origin_dirty",
                "staged_count",
            )
        },
        "provider": provider,
        "policy": {
            name: policy[name]
            for name in (
                "mode",
                "module_status",
                "qualification_failure",
                "selector_calls",
                "selector_matches",
                "selector_counter_contract",
            )
        },
        "final_owner_slot_transforms": {
            name: transforms[name]
            for name in (
                "active_owner_slot_transform_count",
                "active_owner_slot_map_exact",
                "active_transforms_exact",
                "records_sha256",
            )
        },
        "fault_markers": report["fault_markers"],
        "emulator_exit_status": report["emulator_exit_status"],
        "qualified": report["qualified"],
    }


def run_direction(
    chord: InputChord,
    output: Path,
    *,
    emulator: Path,
    mos: Path,
    vdp: Path,
    proxy: Path,
    program: Path,
    symbols_path: Path,
    symbols: dict[str, int],
    policy_module: Path,
    expected_policy_mode: int,
    timeout: float,
) -> dict[str, object]:
    output.mkdir()
    log_path = output / "emulator.log"
    autoexec = (
        b"SET KEYBOARD 1\r\n"
        b"cd /survey\r\n"
        b"load P3DRGL.BIN\r\n"
        b"run\r\n"
    )
    (output / "autoexec.txt").write_bytes(autoexec)
    process: subprocess.Popen[bytes] | None = None
    shutdown = "not-started"
    deadline = time.monotonic() + timeout
    contents = ""

    with (
        tempfile.TemporaryDirectory(prefix=f"regular-six-{chord.name}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"regular-six-{chord.name}-run-") as run_name,
        tempfile.TemporaryDirectory(prefix=f"regular-six-{chord.name}-fifo-") as fifo_name,
    ):
        sd_root = Path(sd_name)
        staged.stage_fixture(sd_root, program, policy_module)
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
                    "argv": [
                        "<fab>",
                        "--renderer",
                        "sw",
                        "--firmware",
                        "console8",
                        "--mos",
                        str(mos),
                        "--vdp",
                        str(proxy),
                        "--sdcard",
                        "<fresh-temporary-sd>",
                        "--verbose",
                        "--debugger",
                        "-z",
                        "-u",
                    ],
                    "input_chord": chord.name,
                    "program_sha256": sha256(program),
                    "symbols_sha256": sha256(symbols_path),
                    "policy_module_sha256": sha256(policy_module),
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
                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: staged.COLD_RENDER_MARKER in value,
                    f"{chord.name} cold endpoint",
                )
                start = staged.cold_end_offset(contents)
                if chord.precenter_with_s:
                    _write_input(
                        control_fd,
                        "down",
                        (input_trace.SET2_CODES["S"],),
                    )
                    contents = staged.wait_for_log(
                        log_path,
                        process,
                        deadline,
                        lambda value: precenter_reached(value, start),
                        f"{chord.name} input-driven starting-cell precenter",
                    )
                    _write_input(
                        control_fd,
                        "up",
                        (input_trace.SET2_CODES["S"],),
                    )
                    contents = staged.wait_for_log(
                        log_path,
                        process,
                        deadline,
                        precenter_release_observed,
                        f"{chord.name} precenter key release",
                    )
                _write_input(control_fd, "down", chord.scancodes)
                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: first_rebase_observed(value, start),
                    f"{chord.name} first adjacent rebase",
                )
                rebases = camera_rebases(contents, start)
                if len(rebases) != 1:
                    raise QualificationError(
                        f"{chord.name} crossed {len(rebases)} origins before release"
                    )
                _write_input(control_fd, "up", chord.scancodes)
                direction_index = int(rebases[0]["direction_index"])
                schedule, shapes = transition_schedule(
                    staged.START_ORIGIN, direction_index
                )
                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: transition_complete(
                        value, start, chord, shapes
                    ),
                    f"{chord.name} one-cell staged convergence",
                )
                contents = staged.snapshot_at_next_idle_render(
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
        cold = staged.validate_cold_endpoint(contents)
        start = staged.cold_end_offset(contents)
        input_evidence = validate_input(contents, chord)
        rebases = camera_rebases(contents, start)
        if len(rebases) != 1:
            raise QualificationError(
                f"{chord.name} final trace has {len(rebases)} rebases"
            )
        direction_index = int(rebases[0]["direction_index"])
        delta_q, delta_r = TRANSITION_DIRECTION_STEPS[direction_index]
        final_origin = (
            staged.START_ORIGIN[0] + delta_q,
            staged.START_ORIGIN[1] + delta_r,
        )
        schedule, shapes = transition_schedule(
            staged.START_ORIGIN, direction_index
        )
        stream = validate_transition_stream(
            contents, start, shapes, len(schedule.new_plan.owners)
        )
        expected_camera = staged.last_camera_position_before(
            contents, len(contents)
        )
        final_state = staged.decode_and_validate_snapshot(
            contents,
            symbols,
            stream,
            expected_origin=final_origin,
            expected_unified_slots=1,
            expected_camera_position=expected_camera,
            expected_camera_fixed_axes={1: staged.CAMERA_INITIAL_Y},
        )
        policy = staged.validate_policy_state(
            final_state["policy"],
            expected_available=True,
            expected_group_calls=len(shapes),
            expected_status=staged.POLICY_STATUS_READY,
        )
        if policy is None or int(policy["mode"]) != expected_policy_mode:
            raise QualificationError(
                f"{chord.name} policy mode changed: "
                f"{None if policy is None else policy['mode']} "
                f"!= {expected_policy_mode}"
            )
        final_state["policy"] = policy
        transforms = validate_final_transforms(
            contents, start, symbols, final_origin
        )
        failures = sorted(
            set(
                capture.find_log_failures(contents)
                + input_trace.find_failures(contents)
            )
        )
        if failures:
            raise QualificationError(
                f"{chord.name} emitted fault markers: {failures}"
            )
    except (QualificationError, staged.EvidenceError) as error:
        raise SystemExit(
            f"six-direction qualification failed for {chord.name}: {error}"
        ) from error
    if process.returncode != 0:
        raise SystemExit(
            f"{chord.name} emulator shutdown returned {process.returncode}"
        )

    report = {
        "schema": DIRECTION_SCHEMA,
        "input": input_evidence,
        "observed_neighbor": {
            **rebases[0],
            "origin": list(final_origin),
            "host_neighbor_valid": True,
        },
        "host_schedule": {
            "direction_index": direction_index,
            "direction_name": TRANSITION_DIRECTION_NAMES[direction_index],
            "step": [delta_q, delta_r],
            "group_count": len(shapes),
            "retiring_count": sum(item[0] for item in shapes),
            "entering_count": sum(item[1] for item in shapes),
            "group_shapes": [list(item) for item in shapes],
            "preserved_owner_count": len(schedule.preserved),
        },
        "cold": cold,
        "transition_stream": stream,
        "final_state": final_state,
        "final_owner_slot_transforms": transforms,
        "fault_markers": [],
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
        "qualified": True,
    }
    (output / DIRECTION_REPORT_NAME).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    if args.timeout_per_direction <= 0:
        raise SystemExit("--timeout-per-direction must be positive")
    emulator = staged.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = staged.require_file(input_trace.MOS_BINARY, "MOS image")
    vdp = staged.require_file(args.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    program = staged.require_file(args.program, "C-policy sibling fixture")
    symbols_path = staged.require_file(args.symbols, "C-policy sibling symbols")
    policy_module = staged.require_file(
        args.policy_module, "fixed regular-policy module"
    )
    symbols = staged.parse_symbols(symbols_path)
    if not staged.POLICY_SYMBOLS.issubset(symbols):
        raise SystemExit("C-policy sibling symbols omit the policy ABI")
    expected_policy_mode = POLICY_MODES[args.expected_policy_mode]
    if symbols["terrain_manager_regular_policy_mode"] != expected_policy_mode:
        raise SystemExit(
            "symbol policy mode differs from --expected-policy-mode: "
            f"{symbols['terrain_manager_regular_policy_mode']} != "
            f"{expected_policy_mode}"
        )

    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    proxy_source = staged.require_file(
        input_trace.PROXY_SOURCE, "input trace proxy source"
    )
    proxy = output / "vdp_input_trace_proxy.so"
    proxy_exports = input_trace.build_proxy(proxy_source, proxy)

    direction_reports: list[dict[str, object]] = []
    for chord in INPUT_CHORDS:
        print(f"QUALIFY_DIRECTION chord={chord.name}", flush=True)
        direction_reports.append(
            run_direction(
                chord,
                output / chord.name,
                emulator=emulator,
                mos=mos,
                vdp=vdp,
                proxy=proxy,
                program=program,
                symbols_path=symbols_path,
                symbols=symbols,
                policy_module=policy_module,
                expected_policy_mode=expected_policy_mode,
                timeout=args.timeout_per_direction,
            )
        )

    observed = [
        tuple(report["observed_neighbor"]["step"])
        for report in direction_reports
    ]
    if len(set(observed)) != len(TRANSITION_DIRECTION_STEPS) or set(observed) != set(
        TRANSITION_DIRECTION_STEPS
    ):
        raise SystemExit(
            "input matrix did not cover each hex neighbor exactly once: "
            f"{observed!r}"
        )

    deterministic_directions = [
        deterministic_direction_summary(item) for item in direction_reports
    ]
    deterministic_payload = json.dumps(
        deterministic_directions, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    report = {
        "schema": SCHEMA,
        "policy_mode": args.expected_policy_mode,
        "policy_mode_value": expected_policy_mode,
        "fresh_process_per_direction": True,
        "program": {"path": str(program), "sha256": sha256(program)},
        "symbols": {"path": str(symbols_path), "sha256": sha256(symbols_path)},
        "policy_module": {
            "path": str(policy_module),
            "sha256": sha256(policy_module),
        },
        "emulator": {"path": str(emulator), "sha256": sha256(emulator)},
        "mos": {"path": str(mos), "sha256": sha256(mos)},
        "vdp": {"path": str(vdp), "sha256": sha256(vdp)},
        "proxy": {"sha256": sha256(proxy), "exports": sorted(proxy_exports)},
        "expected_neighbor_steps": [list(item) for item in TRANSITION_DIRECTION_STEPS],
        "observed_neighbor_steps": [list(item) for item in observed],
        "all_six_neighbors_exactly_once": True,
        "directions": deterministic_directions,
        "direction_evidence": [
            {
                "chord": chord.name,
                "report": f"{chord.name}/{DIRECTION_REPORT_NAME}",
                "log": f"{chord.name}/emulator.log",
            }
            for chord in INPUT_CHORDS
        ],
        "deterministic_matrix_sha256": hashlib.sha256(
            deterministic_payload
        ).hexdigest(),
        "deterministic_summary_excludes_host_timing_and_debugger_offsets": True,
        "qualified": True,
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Headless regular-LOD C-policy six-direction matrix passed: {report_path}")
    print(
        "six fresh processes; READY policy; zero faults; exact selector "
        "counters, atomic groups, owner maps and command-52 transforms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
