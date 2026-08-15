#!/usr/bin/env python3
"""Build and live-qualify one clipped regular-LOD regional-edge handoff.

The scratch profile changes only the C-policy sibling's initial origin and
camera translation: ``(80,125)/(4275,8000,-466)`` becomes the centered western
boundary witness ``(0,117)/(0,8000,0)``.  It is assembled in an isolated source
mirror and never installed.  A held W+D chord then crosses the valid
``(0,117) -> (1,117)`` neighbor while both radius-five endpoint plans are
clipped by the corpus boundary.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Sequence

import build_regular_lod_c_policy_survey as builder
import capture_koak_flight as capture
import capture_terrain_manager_survey as survey
import qualify_regular_lod_c_policy_six_directions as six
import trace_koak_input as input_trace
import trace_regular_lod_staged_north_transitions as staged
from pingo_terrain.regular_lod import offset_row
from pingo_terrain.regular_lod_runtime import (
    PHASE_OFFSET_ROW_COUNT,
    PHASE_Q_COUNT,
    ProtectedSlotAllocator,
    TRANSITION_DIRECTION_NAMES,
    TRANSITION_DIRECTION_STEPS,
    build_runtime_plan,
    build_terrain_owner_plan,
    build_terrain_transition_recipe,
    resolve_transition_recipe_groups,
    schedule_terrain_transition,
    transition_recipe_ordinal_groups,
)


ROOT = Path(__file__).resolve().parent.parent
EDGE_ORIGIN = (0, 117)
EDGE_DIRECTION_INDEX = 2
EDGE_STEP = TRANSITION_DIRECTION_STEPS[EDGE_DIRECTION_INDEX]
EDGE_FINAL_ORIGIN = (
    EDGE_ORIGIN[0] + EDGE_STEP[0],
    EDGE_ORIGIN[1] + EDGE_STEP[1],
)
EDGE_CAMERA = (0, staged.CAMERA_INITIAL_Y, 0)
EDGE_CHORD = six.InputChord("w-d", ("W", "D"))
EDGE_SOURCE_NAME = "regional-edge-profile.asm"
EDGE_BUILD_RECEIPT = "BUILD.json"
EDGE_LIVE_REPORT = "regional-edge-live.json"
REPORT_NAME = "regular-lod-c-policy-regional-edge.json"
SCHEMA = "pingo-terrain-regular-lod-c-policy-regional-edge-v1"
BUILD_SCHEMA = "pingo-terrain-regular-lod-c-policy-regional-edge-build-v1"
LIVE_SCHEMA = "pingo-terrain-regular-lod-c-policy-regional-edge-live-v1"
SUPPORTED_MODES = {
    "dual-strict": staged.POLICY_MODE_DUAL_STRICT,
    "c-guarded": staged.POLICY_MODE_C_GUARDED,
}
SOURCE_TRANSFORMS = (
    ("manager_survey_start_q: equ 80", "manager_survey_start_q: equ 0"),
    ("manager_survey_start_r: equ 125", "manager_survey_start_r: equ 117"),
    ("camera_initial_x: equ 4275", "camera_initial_x: equ 0"),
    ("camera_initial_z: equ -466", "camera_initial_z: equ 0"),
)


class EdgeQualificationError(ValueError):
    """The scratch edge profile or live handoff violated its exact contract."""


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy-mode", choices=tuple(SUPPORTED_MODES), default="dual-strict"
    )
    parser.add_argument(
        "--vdp-module", type=Path, default=survey.DEFAULT_VDP
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def edge_profile_source(mode: str) -> tuple[str, str]:
    """Return the exact base profile and its four-literal edge transform."""

    if mode not in SUPPORTED_MODES:
        raise EdgeQualificationError(f"unsupported edge policy mode: {mode}")
    base = builder.profile_source(mode)
    transformed = base
    for old, new in SOURCE_TRANSFORMS:
        if transformed.count(old) != 1 or new in transformed:
            raise EdgeQualificationError(
                f"edge profile source literal changed: {old!r}"
            )
        transformed = transformed.replace(old, new, 1)
    if len(transformed.splitlines()) != len(base.splitlines()):
        raise EdgeQualificationError("edge transform changed source line count")
    return base, transformed


@lru_cache(maxsize=1)
def edge_host_contract() -> dict[str, object]:
    old = build_terrain_owner_plan(*EDGE_ORIGIN, 5)
    new = build_terrain_owner_plan(*EDGE_FINAL_ORIGIN, 5)
    old_source = build_terrain_owner_plan(
        *EDGE_ORIGIN, 5, clip_to_region=False
    )
    new_source = build_terrain_owner_plan(
        *EDGE_FINAL_ORIGIN, 5, clip_to_region=False
    )
    recipe = build_terrain_transition_recipe(
        EDGE_ORIGIN[0] % PHASE_Q_COUNT,
        offset_row(*EDGE_ORIGIN) % PHASE_OFFSET_ROW_COUNT,
        EDGE_DIRECTION_INDEX,
    )
    raw_groups = transition_recipe_ordinal_groups(recipe)
    resolved = resolve_transition_recipe_groups(recipe, *EDGE_ORIGIN)
    direct = schedule_terrain_transition(old, new)
    resolved_pairs = tuple(
        (group.retiring, group.entering) for group in resolved
    )
    direct_pairs = tuple(
        (step.group.retiring, step.group.entering) for step in direct.steps
    )
    if resolved_pairs != direct_pairs:
        raise EdgeQualificationError(
            "clipped source-ordinal recipe differs from direct host schedule"
        )

    old_present = set(old.owners)
    new_present = set(new.owners)
    filtered_shapes: list[tuple[int, int]] = []
    clipped_retiring_refs = 0
    clipped_entering_refs = 0
    for group in raw_groups:
        retiring_count = sum(
            old_source.owners[ordinal] in old_present
            for ordinal in group.retiring_ordinals
        )
        entering_count = sum(
            new_source.owners[ordinal] in new_present
            for ordinal in group.entering_ordinals
        )
        filtered_shapes.append((retiring_count, entering_count))
        clipped_retiring_refs += len(group.retiring_ordinals) - retiring_count
        clipped_entering_refs += len(group.entering_ordinals) - entering_count
    nonempty_shapes = [shape for shape in filtered_shapes if shape != (0, 0)]
    expected_shapes = [
        (len(step.group.retiring), len(step.group.entering))
        for step in direct.steps
    ]
    if nonempty_shapes != expected_shapes:
        raise EdgeQualificationError(
            "filtered ordinal shapes differ from the direct host schedule"
        )

    runtime = build_runtime_plan(
        ProtectedSlotAllocator(), *EDGE_ORIGIN, 5
    )
    cold_active_ids = sorted(
        [entry.slot + 1 for entry in runtime.near_entries]
        + [entry.slot + 1 for entry in runtime.coarse.entries]
    )
    if runtime.active_count != len(old.owners):
        raise EdgeQualificationError("edge runtime and owner-plan counts differ")

    return {
        "origin": list(EDGE_ORIGIN),
        "final_origin": list(EDGE_FINAL_ORIGIN),
        "direction_index": EDGE_DIRECTION_INDEX,
        "direction_name": TRANSITION_DIRECTION_NAMES[EDGE_DIRECTION_INDEX],
        "step": list(EDGE_STEP),
        "near_radius": 5,
        "old_endpoint": {
            "clipped_owner_count": len(old.owners),
            "unbounded_source_owner_count": len(old_source.owners),
            "clipped_source_ordinals": len(old_source.owners) - len(old.owners),
            "near_count": len(old.near_entries),
            "coarse_count": len(old.coarse_entries),
        },
        "new_endpoint": {
            "clipped_owner_count": len(new.owners),
            "unbounded_source_owner_count": len(new_source.owners),
            "clipped_source_ordinals": len(new_source.owners) - len(new.owners),
            "near_count": len(new.near_entries),
            "coarse_count": len(new.coarse_entries),
        },
        "recipe": {
            "index": recipe.index,
            "raw_group_count": len(raw_groups),
            "filtered_nonempty_group_count": len(nonempty_shapes),
            "filtered_empty_group_count": len(raw_groups) - len(nonempty_shapes),
            "raw_retiring_ordinal_references": sum(
                len(group.retiring_ordinals) for group in raw_groups
            ),
            "raw_entering_ordinal_references": sum(
                len(group.entering_ordinals) for group in raw_groups
            ),
            "clipped_retiring_ordinal_references": clipped_retiring_refs,
            "clipped_entering_ordinal_references": clipped_entering_refs,
            "filtered_shapes_including_empty": [
                list(shape) for shape in filtered_shapes
            ],
            "group_shapes": [list(shape) for shape in nonempty_shapes],
            "source_ordinal_clipping_exact": True,
            "resolved_schedule_equals_direct_host_schedule": True,
        },
        "transition": {
            "preserved_owner_count": len(direct.preserved),
            "retiring_count": sum(shape[0] for shape in nonempty_shapes),
            "entering_count": sum(shape[1] for shape in nonempty_shapes),
            "final_owner_count": len(new.owners),
            "final_scan_desired_count": 91 + len(new.coarse_entries),
        },
        "cold_active_ids": cold_active_ids,
    }


def build_edge_fixture(
    mode: str, output: Path
) -> tuple[Path, Path, Path, dict[str, object]]:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise EdgeQualificationError("ez80asm is not available on PATH")
    output.mkdir()
    builder.validate_source_copy()
    accepted_hash = builder.rebuild_accepted_control()
    module_receipt, module_image, module_import = builder.require_module(
        builder.DEFAULT_MODULE_OUTPUT.resolve(), build=False
    )
    base, transformed = edge_profile_source(mode)
    source_copy = output / EDGE_SOURCE_NAME
    builder.atomic_bytes(source_copy, transformed.encode("ascii"))

    program = output / f"{builder.PROGRAM_STEM}.bin"
    listing = output / f"{builder.PROGRAM_STEM}.lst"
    symbols_path = output / f"{builder.PROGRAM_STEM}.symbols"
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="rlc-edge-build-") as temporary:
        source = builder.stage_source_mirror(Path(temporary), mode)
        source.write_text(transformed, encoding="ascii")
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
                raise EdgeQualificationError(
                    f"edge assembly omitted artifact: {generated.name}"
                )
            builder.atomic_bytes(destination, generated.read_bytes())

    symbols = builder.parse_symbols(symbols_path)
    expected_constants = {
        "manager_survey_start_q": EDGE_ORIGIN[0],
        "manager_survey_start_r": EDGE_ORIGIN[1],
        "camera_initial_x": EDGE_CAMERA[0],
        "camera_initial_y": EDGE_CAMERA[1],
        "camera_initial_z": EDGE_CAMERA[2],
        "terrain_manager_regular_policy_mode": SUPPORTED_MODES[mode],
    }
    observed_constants = {
        name: symbols.get(name) for name in expected_constants
    }
    if observed_constants != expected_constants:
        raise EdgeQualificationError(
            f"edge symbol constants changed: {observed_constants!r}"
        )
    resource_paths = tuple(
        builder.DEFAULT_RUNTIME_OUTPUT / name
        for name in builder.accepted_builder.RESOURCE_NAMES
    )
    memory = builder.validate_memory_map(
        program, symbols_path, module_receipt["module"], resource_paths
    )
    artifacts = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in (source_copy, program, listing, symbols_path)
    }
    receipt: dict[str, object] = {
        "schema": BUILD_SCHEMA,
        "status": "scratch-statically-qualified",
        "installed": False,
        "policy_mode": mode,
        "policy_mode_value": SUPPORTED_MODES[mode],
        "base_profile": {
            "source": str(builder.SOURCE.relative_to(ROOT)),
            "profiled_sha256": hashlib.sha256(base.encode("ascii")).hexdigest(),
        },
        "exact_source_transform": [
            {"from": old, "to": new} for old, new in SOURCE_TRANSFORMS
        ],
        "transformed_source_sha256": hashlib.sha256(
            transformed.encode("ascii")
        ).hexdigest(),
        "symbols_exact": observed_constants,
        "accepted_control_sha256": accepted_hash,
        "module": {
            "path": str(module_image),
            "sha256": sha256(module_image),
            "import": str(module_import),
            "import_sha256": sha256(module_import),
        },
        "host_contract": edge_host_contract(),
        "memory_map": memory,
        "artifacts": artifacts,
        "adl_width_audit": audit,
    }
    builder.atomic_json(output / EDGE_BUILD_RECEIPT, receipt)
    return program, symbols_path, module_image, receipt


def cold_marker(contract: dict[str, object]) -> str:
    old_endpoint = contract["old_endpoint"]
    assert isinstance(old_endpoint, dict)
    sequence = int(old_endpoint["clipped_owner_count"]) - 1
    return f"PINGO_RENDER seq={sequence} "


def cold_end_offset(contents: str, contract: dict[str, object]) -> int:
    marker = cold_marker(contract)
    offset = contents.find(marker)
    if offset < 0:
        raise EdgeQualificationError("edge cold render marker is absent")
    return offset + len(marker)


def validate_cold_endpoint(
    contents: str, contract: dict[str, object]
) -> dict[str, object]:
    marker = cold_marker(contract)
    offsets = [
        offset
        for offset in range(len(contents))
        if contents.startswith(marker, offset)
    ]
    if len(offsets) != 1:
        raise EdgeQualificationError(
            f"expected one edge cold marker, got {len(offsets)}"
        )
    end = offsets[0] + len(marker)
    state = staged.activity_state_at(contents, end)
    if set(state) != set(range(1, staged.SLOT_COUNT + 1)):
        raise EdgeQualificationError(
            "edge cold stream did not establish all activity states"
        )
    active = sorted(object_id for object_id, value in state.items() if value)
    expected = list(contract["cold_active_ids"])
    if active != expected:
        raise EdgeQualificationError(
            f"edge cold active slots changed: {active!r} != {expected!r}"
        )
    replacements = list(capture.MESH_REPLACE_RE.finditer(contents, 0, end))
    replacement_ids = [int(match.group(2)) for match in replacements]
    if len(replacement_ids) != len(expected) or set(replacement_ids) != set(expected):
        raise EdgeQualificationError(
            "edge cold command-50 publications differ from the host slot map"
        )
    return {
        "sequence": len(expected) - 1,
        "active_count": len(active),
        "active_ids": active,
        "publication_count": len(replacements),
        "active_slot_map_exact": True,
    }


def run_edge_live(
    mode: str,
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
    contract = edge_host_contract()
    old_endpoint = contract["old_endpoint"]
    transition = contract["transition"]
    recipe = contract["recipe"]
    assert isinstance(old_endpoint, dict)
    assert isinstance(transition, dict)
    assert isinstance(recipe, dict)
    shapes = [tuple(item) for item in recipe["group_shapes"]]
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

    with (
        tempfile.TemporaryDirectory(prefix="regular-edge-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix="regular-edge-run-") as run_name,
        tempfile.TemporaryDirectory(prefix="regular-edge-fifo-") as fifo_name,
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
                    lambda value: cold_marker(contract) in value,
                    "clipped regional-edge cold endpoint",
                )
                start = cold_end_offset(contents, contract)
                six._write_input(control_fd, "down", EDGE_CHORD.scancodes)
                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: bool(
                        six.camera_rebases(value, start, EDGE_CAMERA)
                    ),
                    "q=0 to q=1 regional-edge rebase",
                )
                rebases = six.camera_rebases(contents, start, EDGE_CAMERA)
                if len(rebases) != 1:
                    raise EdgeQualificationError(
                        f"edge chord crossed {len(rebases)} origins before release"
                    )
                if int(rebases[0]["direction_index"]) != EDGE_DIRECTION_INDEX:
                    raise EdgeQualificationError(
                        f"edge chord selected {rebases[0]['direction_name']}, "
                        "expected northeast"
                    )
                six._write_input(control_fd, "up", EDGE_CHORD.scancodes)
                contents = staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: six.transition_complete(
                        value, start, EDGE_CHORD, shapes
                    ),
                    "clipped regional-edge staged convergence",
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
        cold = validate_cold_endpoint(contents, contract)
        start = cold_end_offset(contents, contract)
        input_evidence = six.validate_input(contents, EDGE_CHORD)
        rebases = six.camera_rebases(contents, start, EDGE_CAMERA)
        if len(rebases) != 1:
            raise EdgeQualificationError(
                f"edge final trace has {len(rebases)} rebases"
            )
        if tuple(rebases[0]["step"]) != EDGE_STEP:
            raise EdgeQualificationError(
                f"edge final origin step changed: {rebases[0]['step']}"
            )
        stream = six.validate_transition_stream(
            contents,
            start,
            shapes,
            int(transition["final_owner_count"]),
        )
        expected_camera = list(
            six.latest_camera_position(contents, start, EDGE_CAMERA)
        )
        final_state = staged.decode_and_validate_snapshot(
            contents,
            symbols,
            stream,
            expected_origin=EDGE_FINAL_ORIGIN,
            expected_unified_slots=1,
            expected_camera_position=expected_camera,
            expected_camera_fixed_axes={1: EDGE_CAMERA[1]},
            expected_scan_desired_count=int(
                transition["final_scan_desired_count"]
            ),
        )
        policy = staged.validate_policy_state(
            final_state["policy"],
            expected_available=True,
            expected_group_calls=int(recipe["raw_group_count"]),
            expected_status=staged.POLICY_STATUS_READY,
        )
        expected_mode = SUPPORTED_MODES[mode]
        if policy is None or int(policy["mode"]) != expected_mode:
            raise EdgeQualificationError(
                f"edge policy mode changed: "
                f"{None if policy is None else policy['mode']} != {expected_mode}"
            )
        final_state["policy"] = policy
        transforms = six.validate_final_transforms(
            contents, start, symbols, EDGE_FINAL_ORIGIN
        )
        failures = sorted(
            set(
                capture.find_log_failures(contents)
                + input_trace.find_failures(contents)
            )
        )
        if failures:
            raise EdgeQualificationError(
                f"edge trace emitted fault markers: {failures}"
            )
    except (EdgeQualificationError, six.QualificationError, staged.EvidenceError) as error:
        raise SystemExit(f"regional-edge qualification failed: {error}") from error
    if process.returncode != 0:
        raise SystemExit(
            f"regional-edge emulator shutdown returned {process.returncode}"
        )

    report: dict[str, object] = {
        "schema": LIVE_SCHEMA,
        "input": input_evidence,
        "observed_neighbor": {
            **rebases[0],
            "origin": list(EDGE_FINAL_ORIGIN),
            "host_neighbor_valid": True,
        },
        "host_schedule": {
            "direction_index": EDGE_DIRECTION_INDEX,
            "direction_name": TRANSITION_DIRECTION_NAMES[EDGE_DIRECTION_INDEX],
            "step": list(EDGE_STEP),
            "group_count": len(shapes),
            "selector_group_count": int(recipe["raw_group_count"]),
            "retiring_count": int(transition["retiring_count"]),
            "entering_count": int(transition["entering_count"]),
            "group_shapes": [list(item) for item in shapes],
            "preserved_owner_count": int(transition["preserved_owner_count"]),
            "source_ordinal_clipping_exact": True,
        },
        "source_ordinal_clipping": contract,
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
    builder.atomic_json(output / EDGE_LIVE_REPORT, report)
    return report


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
    program, symbols_path, policy_module, build_receipt = build_edge_fixture(
        args.policy_mode, output / "fixture"
    )
    proxy_source = staged.require_file(
        input_trace.PROXY_SOURCE, "input trace proxy source"
    )
    proxy = output / "vdp_input_trace_proxy.so"
    proxy_exports = input_trace.build_proxy(proxy_source, proxy)
    live = run_edge_live(
        args.policy_mode,
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
    deterministic_live = six.deterministic_direction_summary(live)
    deterministic_payload = json.dumps(
        deterministic_live, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    report = {
        "schema": SCHEMA,
        "policy_mode": args.policy_mode,
        "policy_mode_value": SUPPORTED_MODES[args.policy_mode],
        "installed": False,
        "exact_source_transform": build_receipt["exact_source_transform"],
        "transformed_source_sha256": build_receipt["transformed_source_sha256"],
        "build_receipt": {
            "path": f"fixture/{EDGE_BUILD_RECEIPT}",
            "sha256": sha256(output / "fixture" / EDGE_BUILD_RECEIPT),
        },
        "program": {"path": str(program), "sha256": sha256(program)},
        "symbols": {
            "path": str(symbols_path),
            "sha256": sha256(symbols_path),
        },
        "policy_module": {
            "path": str(policy_module),
            "sha256": sha256(policy_module),
        },
        "emulator": {"path": str(emulator), "sha256": sha256(emulator)},
        "mos": {"path": str(mos), "sha256": sha256(mos)},
        "vdp": {"path": str(vdp), "sha256": sha256(vdp)},
        "proxy": {"sha256": sha256(proxy), "exports": sorted(proxy_exports)},
        "host_contract": edge_host_contract(),
        "live": deterministic_live,
        "full_live_evidence": f"live/{EDGE_LIVE_REPORT}",
        "deterministic_live_sha256": hashlib.sha256(
            deterministic_payload
        ).hexdigest(),
        "deterministic_summary_excludes_host_timing_and_debugger_offsets": True,
        "qualified": True,
    }
    report_path = output / REPORT_NAME
    builder.atomic_json(report_path, report)
    print(f"Headless regular-LOD C-policy regional-edge trace passed: {report_path}")
    print(
        "q=0->1; both endpoints clipped; exact source ordinals, atomic groups, "
        "policy counters, owner slots and command-52 transforms"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EdgeQualificationError, builder.CPolicyFixtureBuildError) as error:
        raise SystemExit(str(error)) from error
