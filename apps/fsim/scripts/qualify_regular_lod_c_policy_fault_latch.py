#!/usr/bin/env python3
"""Live-qualify the C_GUARDED bad-result latch in a scratch-only fixture.

The diagnostic image derives from the clipped western regional-edge witness.
It changes neither the accepted fixture nor the canonical sibling.  Its copied
policy client overwrites exactly the first returned C selector byte with the
reserved INVALID value, then counts the first candidate-failure fallback and
all later latch-directed assembly fallbacks in the otherwise-unused
``regular_policy_selector_matches`` bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Sequence

import build_regular_lod_c_policy_survey as builder
import capture_koak_flight as capture
import capture_terrain_manager_survey as survey
import qualify_regular_lod_c_policy_regional_edge as edge
import qualify_regular_lod_c_policy_six_directions as six
import trace_koak_input as input_trace
import trace_regular_lod_staged_north_transitions as staged


ROOT = Path(__file__).resolve().parent.parent
REPORT_NAME = "regular-lod-c-policy-fault-latch.json"
LIVE_REPORT_NAME = "fault-latch-live.json"
BUILD_RECEIPT_NAME = "BUILD.json"
SCHEMA = "pingo-terrain-regular-lod-c-policy-fault-latch-v1"
LIVE_SCHEMA = "pingo-terrain-regular-lod-c-policy-fault-latch-live-v1"
BUILD_SCHEMA = "pingo-terrain-regular-lod-c-policy-fault-latch-build-v1"
FAULT_SOURCE_NAME = "fault-latch-profile.asm"
FAULT_CLIENT_NAME = "fault-latch-policy-client.inc"
FAULT_MODE_NAME = "fault-latch-policy-mode-c-guarded.inc"
POLICY_MODE = "c-guarded"
POLICY_MODE_VALUE = staged.POLICY_MODE_C_GUARDED
INVALID_RESULT = builder.module_builder.INVALID

CALL_INJECTION_ANCHOR = """regular_policy_select_c_guarded:
    REGULAR_POLICY_C_GUARDED_LATCH_CHECK
    ld a,(regular_policy_module_status)
    cp regular_policy_module_status_ready
    jp nz,regular_transition_select_feasible_group_asm
    ld a,(regular_policy_descriptors_ready)
    or a
    jr z,regular_policy_candidate_failed_fallback
    call regular_policy_pack_pending_descriptors
    jr c,regular_policy_candidate_failed_fallback
    call regular_policy_call_c
    call regular_policy_revalidate_c_result
"""
CALL_INJECTION_REPLACEMENT = CALL_INJECTION_ANCHOR.replace(
    "    call regular_policy_revalidate_c_result\n",
    "    call regular_policy_fault_inject_invalid_once\n"
    "    call regular_policy_revalidate_c_result\n",
)
CANDIDATE_FALLBACK_ANCHOR = """regular_policy_candidate_failed_fallback:
    ld a,1
    ld (regular_policy_qualification_failure),a
    jp regular_transition_select_feasible_group_asm
"""
CANDIDATE_FALLBACK_REPLACEMENT = CANDIDATE_FALLBACK_ANCHOR.replace(
    "    jp regular_transition_select_feasible_group_asm\n",
    "    jp regular_policy_fault_candidate_fallback\n",
)
DIAGNOSTIC_ROUTINES = """; Scratch-only C_GUARDED bad-result latch witness.
regular_policy_fault_inject_invalid_once:
    ld a,(regular_policy_fault_injected)
    or a
    ret nz
    inc a
    ld (regular_policy_fault_injected),a
    ld (regular_policy_selector_matches+2),a
    ld a,fsim_regular_policy_invalid
    ld (regular_policy_c_result),a
    ret

regular_policy_fault_candidate_fallback:
    ld hl,regular_policy_selector_matches+0
    inc (hl)
    jp regular_transition_select_feasible_group_asm

regular_policy_fault_latched_fallback:
    ld hl,regular_policy_selector_matches+1
    inc (hl)
    jp regular_transition_select_feasible_group_asm

regular_policy_fault_injected: db 0

"""
ROUTINE_INSERTION_ANCHOR = "regular_policy_filename:\n"
MODE_LATCH_ANCHOR = "        jp nz,regular_transition_select_feasible_group_asm\n"
MODE_LATCH_REPLACEMENT = "        jp nz,regular_policy_fault_latched_fallback\n"
FAULT_SYMBOLS = {
    "regular_policy_fault_inject_invalid_once",
    "regular_policy_fault_candidate_fallback",
    "regular_policy_fault_latched_fallback",
    "regular_policy_fault_injected",
    "regular_policy_c_result",
}


class FaultLatchQualificationError(ValueError):
    """The diagnostic transform or live latch witness violated its contract."""


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vdp-module", type=Path, default=survey.DEFAULT_VDP)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise FaultLatchQualificationError(
            f"{label} anchor count changed: {text.count(old)} != 1"
        )
    return text.replace(old, new, 1)


def fault_client_source() -> tuple[str, str]:
    """Return the canonical client and its exact scratch instrumentation."""

    base = builder.CLIENT.read_text(encoding="ascii")
    transformed = _replace_once(
        base,
        CALL_INJECTION_ANCHOR,
        CALL_INJECTION_REPLACEMENT,
        "C call injection",
    )
    transformed = _replace_once(
        transformed,
        CANDIDATE_FALLBACK_ANCHOR,
        CANDIDATE_FALLBACK_REPLACEMENT,
        "candidate fallback",
    )
    transformed = _replace_once(
        transformed,
        ROUTINE_INSERTION_ANCHOR,
        DIAGNOSTIC_ROUTINES + ROUTINE_INSERTION_ANCHOR,
        "diagnostic routine insertion",
    )
    return base, transformed


def fault_mode_source() -> tuple[str, str]:
    """Redirect only the already-latched C_GUARDED branch to its counter."""

    path = builder.SOURCE_DIRECTORY / str(
        builder.MODE_PROFILES[POLICY_MODE]["include"]
    )
    base = path.read_text(encoding="ascii")
    transformed = _replace_once(
        base,
        MODE_LATCH_ANCHOR,
        MODE_LATCH_REPLACEMENT,
        "latched fallback",
    )
    return base, transformed


def diagnostic_counter_bytes(packed: int) -> dict[str, int]:
    raw = packed.to_bytes(3, "little")
    return {
        "candidate_failure_fallbacks": raw[0],
        "latched_fallbacks": raw[1],
        "invalid_injections": raw[2],
    }


def validate_first_failure_snapshot(snapshot: dict[str, int]) -> dict[str, object]:
    expected = {
        "module_status": staged.POLICY_STATUS_READY,
        "qualification_failure": 1,
        "selector_calls": 1,
        "candidate_failure_fallbacks": 0,
        "latched_fallbacks": 0,
        "invalid_injections": 1,
        "c_result": INVALID_RESULT,
        "injected_flag": 1,
    }
    if snapshot != expected:
        raise FaultLatchQualificationError(
            f"first candidate-failure snapshot changed: {snapshot!r} != {expected!r}"
        )
    return {
        **snapshot,
        "breakpoint_at_candidate_fallback_before_counter_increment": True,
        "first_c_result_forced_invalid": True,
        "qualification_failure_already_latched": True,
    }


def validate_final_policy(
    policy: dict[str, object] | None, *, expected_selector_groups: int
) -> dict[str, object]:
    if policy is None:
        raise FaultLatchQualificationError("fault fixture omitted policy state")
    observed = {
        "mode": int(policy["mode"]),
        "module_status": int(policy["module_status"]),
        "qualification_failure": int(policy["qualification_failure"]),
        "selector_calls": int(policy["selector_calls"]),
    }
    expected = {
        "mode": POLICY_MODE_VALUE,
        "module_status": staged.POLICY_STATUS_READY,
        "qualification_failure": 1,
        "selector_calls": 1,
    }
    if observed != expected:
        raise FaultLatchQualificationError(
            f"final fault policy changed: {observed!r} != {expected!r}"
        )
    counters = diagnostic_counter_bytes(int(policy["selector_matches"]))
    expected_counters = {
        "candidate_failure_fallbacks": 1,
        "latched_fallbacks": expected_selector_groups - 1,
        "invalid_injections": 1,
    }
    if counters != expected_counters:
        raise FaultLatchQualificationError(
            f"fault latch counters changed: {counters!r} != {expected_counters!r}"
        )
    return {
        **observed,
        "diagnostic_counters": counters,
        "raw_selector_matches_field": int(policy["selector_matches"]),
        "first_group_used_candidate_failure_fallback": True,
        "all_subsequent_groups_used_latched_assembly_fallback": True,
        "accepted_assembly_fallback_calls": expected_selector_groups,
        "c_was_not_called_after_latch": True,
    }


def _replace_staged_symlink(path: Path, payload: str) -> None:
    if not path.is_symlink():
        raise FaultLatchQualificationError(
            f"scratch source dependency is not the expected symlink: {path}"
        )
    path.unlink()
    path.write_text(payload, encoding="ascii")


def build_fault_fixture(
    output: Path,
) -> tuple[Path, Path, Path, dict[str, object]]:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise FaultLatchQualificationError("ez80asm is not available on PATH")
    output.mkdir()
    builder.validate_source_copy()
    accepted_hash = builder.rebuild_accepted_control()
    module_receipt, module_image, module_import = builder.require_module(
        builder.DEFAULT_MODULE_OUTPUT.resolve(), build=False
    )
    base_source, transformed_source = edge.edge_profile_source(POLICY_MODE)
    base_client, transformed_client = fault_client_source()
    base_mode, transformed_mode = fault_mode_source()

    source_copy = output / FAULT_SOURCE_NAME
    client_copy = output / FAULT_CLIENT_NAME
    mode_copy = output / FAULT_MODE_NAME
    builder.atomic_bytes(source_copy, transformed_source.encode("ascii"))
    builder.atomic_bytes(client_copy, transformed_client.encode("ascii"))
    builder.atomic_bytes(mode_copy, transformed_mode.encode("ascii"))

    program = output / f"{builder.PROGRAM_STEM}.bin"
    listing = output / f"{builder.PROGRAM_STEM}.lst"
    symbols_path = output / f"{builder.PROGRAM_STEM}.symbols"
    with tempfile.TemporaryDirectory(
        dir="/tmp", prefix="rlc-fault-latch-build-"
    ) as temporary:
        source = builder.stage_source_mirror(Path(temporary), POLICY_MODE)
        source.write_text(transformed_source, encoding="ascii")
        _replace_staged_symlink(
            source.parent / builder.CLIENT.name, transformed_client
        )
        mode_name = str(builder.MODE_PROFILES[POLICY_MODE]["include"])
        _replace_staged_symlink(source.parent / mode_name, transformed_mode)
        audit = builder.run(
            (
                sys.executable,
                ROOT / "scripts/audit_adl_width.py",
                "--follow-includes",
                "--show-review",
                "--fail-review",
                source,
            ),
            cwd=source.parent,
        ).strip()
        generated_program = source.with_suffix(".BIN")
        generated_listing = source.with_suffix(".lst")
        generated_symbols = source.with_suffix(".symbols")
        builder.run(
            (
                assembler,
                "-l",
                "-s",
                source.name,
                generated_program.name,
                "-c",
            ),
            cwd=source.parent,
        )
        for generated, destination in (
            (generated_program, program),
            (generated_listing, listing),
            (generated_symbols, symbols_path),
        ):
            if not generated.is_file():
                raise FaultLatchQualificationError(
                    f"fault-latch assembly omitted artifact: {generated.name}"
                )
            builder.atomic_bytes(destination, generated.read_bytes())

    symbols = builder.parse_symbols(symbols_path)
    missing = sorted(FAULT_SYMBOLS - symbols.keys())
    if missing:
        raise FaultLatchQualificationError(
            f"fault-latch symbols are incomplete: {missing}"
        )
    contract = edge.edge_host_contract()
    expected_constants = {
        "manager_survey_start_q": edge.EDGE_ORIGIN[0],
        "manager_survey_start_r": edge.EDGE_ORIGIN[1],
        "camera_initial_x": edge.EDGE_CAMERA[0],
        "camera_initial_y": edge.EDGE_CAMERA[1],
        "camera_initial_z": edge.EDGE_CAMERA[2],
        "terrain_manager_regular_policy_mode": POLICY_MODE_VALUE,
    }
    observed_constants = {
        name: symbols.get(name) for name in expected_constants
    }
    if observed_constants != expected_constants:
        raise FaultLatchQualificationError(
            f"fault-latch symbol constants changed: {observed_constants!r}"
        )
    resource_paths = tuple(
        builder.DEFAULT_RUNTIME_OUTPUT / name
        for name in builder.accepted_builder.RESOURCE_NAMES
    )
    memory = builder.validate_memory_map(
        program, symbols_path, module_receipt["module"], resource_paths
    )
    artifacts = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in (
            source_copy,
            client_copy,
            mode_copy,
            program,
            listing,
            symbols_path,
        )
    }
    canonical_sibling = builder.DEFAULT_ARTIFACT_OUTPUT / (
        f"{builder.PROGRAM_STEM}.bin"
    )
    canonical_artifacts = {
        "accepted_program": {
            "path": str(
                builder.ROOT
                / "fixtures/terrain-manager-regular-lod-survey/tgt/"
                "terrain-manager-regular-lod-survey.bin"
            ),
            "sha256": accepted_hash,
        },
        "policy_module": {
            "path": str(module_image),
            "sha256": sha256(module_image),
        },
    }
    if canonical_sibling.is_file():
        canonical_artifacts["sibling_program"] = {
            "path": str(canonical_sibling),
            "sha256": sha256(canonical_sibling),
        }
    receipt: dict[str, object] = {
        "schema": BUILD_SCHEMA,
        "status": "scratch-statically-qualified",
        "installed": False,
        "policy_mode": POLICY_MODE,
        "policy_mode_value": POLICY_MODE_VALUE,
        "exact_edge_source_transform": [
            {"from": old, "to": new} for old, new in edge.SOURCE_TRANSFORMS
        ],
        "source_hashes": {
            "base_profile": hashlib.sha256(base_source.encode("ascii")).hexdigest(),
            "fault_profile": hashlib.sha256(
                transformed_source.encode("ascii")
            ).hexdigest(),
            "base_client": hashlib.sha256(base_client.encode("ascii")).hexdigest(),
            "fault_client": hashlib.sha256(
                transformed_client.encode("ascii")
            ).hexdigest(),
            "base_mode": hashlib.sha256(base_mode.encode("ascii")).hexdigest(),
            "fault_mode": hashlib.sha256(
                transformed_mode.encode("ascii")
            ).hexdigest(),
        },
        "fault_contract": {
            "injected_result": INVALID_RESULT,
            "injection_limit": 1,
            "first_candidate_fallback_counter_byte": 0,
            "later_latched_fallback_counter_byte": 1,
            "invalid_injection_counter_byte": 2,
            "expected_selector_groups": contract["recipe"]["raw_group_count"],
        },
        "symbols_exact": observed_constants,
        "fault_symbols": {name: symbols[name] for name in sorted(FAULT_SYMBOLS)},
        "accepted_control_sha256": accepted_hash,
        "canonical_artifacts_read_only": canonical_artifacts,
        "module_import": {
            "path": str(module_import),
            "sha256": sha256(module_import),
        },
        "host_contract": contract,
        "memory_map": memory,
        "artifacts": artifacts,
        "adl_width_audit": audit,
    }
    builder.atomic_json(output / BUILD_RECEIPT_NAME, receipt)
    return program, symbols_path, module_image, receipt


def _wait_for_debugger_pause(
    log_path: Path,
    process: subprocess.Popen[bytes],
    deadline: float,
    pause_count: int,
    description: str,
    *,
    pc: int | None = None,
    cursor: int = 0,
) -> str:
    def paused(contents: str) -> bool:
        plain = staged.debugger.ANSI_RE.sub("", contents)
        if plain.count("CPU paused") <= pause_count:
            return False
        return pc is None or f"* {pc:06x}:" in plain[cursor:]

    return staged.wait_for_log(
        log_path, process, deadline, paused, description
    )


def _read_first_failure_snapshot(
    process: subprocess.Popen[bytes],
    log_path: Path,
    symbols: dict[str, int],
    deadline: float,
) -> dict[str, int]:
    spans = (
        (symbols["regular_policy_module_status"], 1),
        (symbols["regular_policy_qualification_failure"], 1),
        (symbols["regular_policy_selector_calls"], 3),
        (symbols["regular_policy_selector_matches"], 3),
        (symbols["regular_policy_c_result"], 1),
        (symbols["regular_policy_fault_injected"], 1),
    )
    cursor = len(
        staged.debugger.ANSI_RE.sub(
            "", log_path.read_text(encoding="utf-8", errors="replace")
        )
    )
    for address, length in spans:
        staged.debugger.write_debugger(process, f"memory 0x{address:x} {length}")
    final_address = spans[-1][0]

    def memory_complete(contents: str) -> bool:
        plain = staged.debugger.ANSI_RE.sub("", contents)
        suffix = plain[cursor:]
        marker = suffix.rfind(f"{final_address:06x}:")
        return marker >= 0 and suffix.find(">>", marker + 7) >= 0

    contents = staged.wait_for_log(
        log_path,
        process,
        deadline,
        memory_complete,
        "first invalid-result latch memory",
    )
    memory = staged.debugger.parse_memory(contents[cursor:])
    diagnostic = staged.debugger.read_span(
        memory, symbols["regular_policy_selector_matches"], 3
    )
    return {
        "module_status": staged.debugger.read_span(
            memory, symbols["regular_policy_module_status"], 1
        )[0],
        "qualification_failure": staged.debugger.read_span(
            memory, symbols["regular_policy_qualification_failure"], 1
        )[0],
        "selector_calls": int.from_bytes(
            staged.debugger.read_span(
                memory, symbols["regular_policy_selector_calls"], 3
            ),
            "little",
        ),
        "candidate_failure_fallbacks": diagnostic[0],
        "latched_fallbacks": diagnostic[1],
        "invalid_injections": diagnostic[2],
        "c_result": staged.debugger.read_span(
            memory, symbols["regular_policy_c_result"], 1
        )[0],
        "injected_flag": staged.debugger.read_span(
            memory, symbols["regular_policy_fault_injected"], 1
        )[0],
    }


def run_fault_live(
    output: Path,
    *,
    program: Path,
    symbols_path: Path,
    policy_module: Path,
    emulator: Path,
    mos: Path,
    vdp: Path,
    proxy: Path,
    timeout: float,
) -> dict[str, object]:
    output.mkdir()
    symbols = staged.parse_symbols(symbols_path)
    missing = sorted(FAULT_SYMBOLS - symbols.keys())
    if missing:
        raise FaultLatchQualificationError(
            f"live fault symbols are incomplete: {missing}"
        )
    contract = edge.edge_host_contract()
    recipe = contract["recipe"]
    transition = contract["transition"]
    assert isinstance(recipe, dict)
    assert isinstance(transition, dict)
    shapes = [tuple(item) for item in recipe["group_shapes"]]
    expected_selector_groups = int(recipe["raw_group_count"])
    breakpoint = symbols["regular_policy_fault_candidate_fallback"]
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
    first_failure: dict[str, object] | None = None
    deadline = time.monotonic() + timeout

    with (
        tempfile.TemporaryDirectory(prefix="regular-fault-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="regular-fault-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="regular-fault-fifo-") as fifo_name,
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
        builder.atomic_json(
            output / "command.json",
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
                "program_sha256": sha256(program),
                "symbols_sha256": sha256(symbols_path),
                "policy_module_sha256": sha256(policy_module),
                "input_chord": edge.EDGE_CHORD.name,
                "breakpoint": breakpoint,
            },
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
                    lambda value: edge.cold_marker(contract) in value,
                    "fault-latch clipped cold endpoint",
                )
                start = edge.cold_end_offset(contents, contract)

                plain = staged.debugger.ANSI_RE.sub("", contents)
                pause_count = plain.count("CPU paused")
                os.kill(process.pid, signal.SIGINT)
                _wait_for_debugger_pause(
                    log_path,
                    process,
                    deadline,
                    pause_count,
                    "fault-latch debugger setup pause",
                )
                staged.debugger.write_debugger(
                    process, f"break 0x{breakpoint:x}"
                )
                breakpoint_cursor = len(
                    staged.debugger.ANSI_RE.sub(
                        "",
                        log_path.read_text(encoding="utf-8", errors="replace"),
                    )
                )
                staged.debugger.write_debugger(process, "continue")
                six._write_input(control_fd, "down", edge.EDGE_CHORD.scancodes)
                _wait_for_debugger_pause(
                    log_path,
                    process,
                    deadline,
                    pause_count + 1,
                    "first invalid-result candidate fallback",
                    pc=breakpoint,
                    cursor=breakpoint_cursor,
                )
                first_failure = validate_first_failure_snapshot(
                    _read_first_failure_snapshot(
                        process, log_path, symbols, deadline
                    )
                )
                six._write_input(control_fd, "up", edge.EDGE_CHORD.scancodes)
                staged.debugger.write_debugger(
                    process, f"delete 0x{breakpoint:x}"
                )
                staged.debugger.write_debugger(process, "continue")

                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: bool(
                        six.camera_rebases(value, start, edge.EDGE_CAMERA)
                    ),
                    "fault-latch q=0 to q=1 rebase",
                )
                rebases = six.camera_rebases(contents, start, edge.EDGE_CAMERA)
                if len(rebases) != 1:
                    raise FaultLatchQualificationError(
                        f"fault chord crossed {len(rebases)} origins"
                    )
                if int(rebases[0]["direction_index"]) != edge.EDGE_DIRECTION_INDEX:
                    raise FaultLatchQualificationError(
                        "fault chord selected the wrong regional-edge neighbor"
                    )
                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: six.transition_complete(
                        value, start, edge.EDGE_CHORD, shapes
                    ),
                    "fault-latch staged assembly-fallback convergence",
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
    assert first_failure is not None
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    try:
        cold = edge.validate_cold_endpoint(contents, contract)
        start = edge.cold_end_offset(contents, contract)
        input_evidence = six.validate_input(contents, edge.EDGE_CHORD)
        rebases = six.camera_rebases(contents, start, edge.EDGE_CAMERA)
        if len(rebases) != 1 or tuple(rebases[0]["step"]) != edge.EDGE_STEP:
            raise FaultLatchQualificationError(
                f"fault-latch final rebase changed: {rebases!r}"
            )
        stream = six.validate_transition_stream(
            contents,
            start,
            shapes,
            int(transition["final_owner_count"]),
        )
        expected_camera = list(
            six.latest_camera_position(contents, start, edge.EDGE_CAMERA)
        )
        final_state = staged.decode_and_validate_snapshot(
            contents,
            symbols,
            stream,
            expected_origin=edge.EDGE_FINAL_ORIGIN,
            expected_unified_slots=1,
            expected_camera_position=expected_camera,
            expected_camera_fixed_axes={1: edge.EDGE_CAMERA[1]},
            expected_scan_desired_count=int(
                transition["final_scan_desired_count"]
            ),
        )
        final_state["policy"] = validate_final_policy(
            final_state["policy"],
            expected_selector_groups=expected_selector_groups,
        )
        transforms = six.validate_final_transforms(
            contents, start, symbols, edge.EDGE_FINAL_ORIGIN
        )
        failures = sorted(
            set(
                capture.find_log_failures(contents)
                + input_trace.find_failures(contents)
            )
        )
        if failures:
            raise FaultLatchQualificationError(
                f"fault-latch trace emitted fault markers: {failures}"
            )
    except (
        FaultLatchQualificationError,
        edge.EdgeQualificationError,
        six.QualificationError,
        staged.EvidenceError,
    ) as error:
        raise SystemExit(f"fault-latch qualification failed: {error}") from error
    if process.returncode != 0:
        raise SystemExit(
            f"fault-latch emulator shutdown returned {process.returncode}"
        )

    report: dict[str, object] = {
        "schema": LIVE_SCHEMA,
        "input": input_evidence,
        "observed_neighbor": {
            **rebases[0],
            "origin": list(edge.EDGE_FINAL_ORIGIN),
            "host_neighbor_valid": True,
        },
        "host_schedule": {
            "selector_group_count": expected_selector_groups,
            "committed_group_count": len(shapes),
            "group_shapes": [list(item) for item in shapes],
            "final_owner_count": int(transition["final_owner_count"]),
        },
        "first_candidate_failure": first_failure,
        "transition_stream": stream,
        "final_state": final_state,
        "final_owner_slot_transforms": transforms,
        "fault_markers": [],
        "shutdown": shutdown,
        "emulator_exit_status": process.returncode,
        "log_sha256": sha256(log_path),
        "qualified": True,
    }
    builder.atomic_json(output / LIVE_REPORT_NAME, report)
    return report


def deterministic_summary(report: dict[str, object]) -> dict[str, object]:
    neighbor = report["observed_neighbor"]
    stream = report["transition_stream"]
    final_state = report["final_state"]
    transforms = report["final_owner_slot_transforms"]
    assert isinstance(neighbor, dict)
    assert isinstance(stream, dict)
    assert isinstance(final_state, dict)
    assert isinstance(transforms, dict)
    policy = final_state["policy"]
    manager = final_state["manager"]
    assert isinstance(policy, dict)
    assert isinstance(manager, dict)
    return {
        "neighbor": {
            key: neighbor[key]
            for key in (
                "direction_index",
                "direction_name",
                "step",
                "origin",
                "host_neighbor_valid",
            )
        },
        "host_schedule": report["host_schedule"],
        "first_candidate_failure": report["first_candidate_failure"],
        "fallback_latch": policy,
        "stream": {
            key: stream[key]
            for key in (
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
            key: manager[key]
            for key in (
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
        "final_owner_slot_transforms": {
            key: transforms[key]
            for key in (
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


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    emulator = staged.require_file(input_trace.FAB_BINARY, "Fab executable")
    mos = staged.require_file(input_trace.MOS_BINARY, "MOS image")
    vdp = staged.require_file(args.vdp_module, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    program, symbols_path, policy_module, build_receipt = build_fault_fixture(
        output / "fixture"
    )
    proxy_source = staged.require_file(
        input_trace.PROXY_SOURCE, "input trace proxy source"
    )
    proxy = output / "vdp_input_trace_proxy.so"
    proxy_exports = input_trace.build_proxy(proxy_source, proxy)
    live = run_fault_live(
        output / "live",
        program=program,
        symbols_path=symbols_path,
        policy_module=policy_module,
        emulator=emulator,
        mos=mos,
        vdp=vdp,
        proxy=proxy,
        timeout=args.timeout,
    )
    stable = deterministic_summary(live)
    stable_payload = json.dumps(
        stable, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    report = {
        "schema": SCHEMA,
        "policy_mode": POLICY_MODE,
        "policy_mode_value": POLICY_MODE_VALUE,
        "installed": False,
        "scratch_only": True,
        "build_receipt": {
            "path": f"fixture/{BUILD_RECEIPT_NAME}",
            "sha256": sha256(output / "fixture" / BUILD_RECEIPT_NAME),
        },
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
        "host_contract": edge.edge_host_contract(),
        "fault_contract": build_receipt["fault_contract"],
        "live": stable,
        "full_live_evidence": f"live/{LIVE_REPORT_NAME}",
        "deterministic_live_sha256": hashlib.sha256(stable_payload).hexdigest(),
        "deterministic_summary_excludes_host_timing_debugger_offsets_and_log_hash": True,
        "qualified": True,
    }
    report_path = output / REPORT_NAME
    builder.atomic_json(report_path, report)
    print(f"Headless regular-LOD C-policy fault-latch trace passed: {report_path}")
    print(
        "one INVALID injection; first candidate fallback plus 25 latched assembly "
        "fallbacks; exact clipped endpoint and atomic inactive-only publication"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        FaultLatchQualificationError,
        builder.CPolicyFixtureBuildError,
        edge.EdgeQualificationError,
    ) as error:
        raise SystemExit(str(error)) from error
