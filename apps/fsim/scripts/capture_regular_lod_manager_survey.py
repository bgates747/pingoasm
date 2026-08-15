#!/usr/bin/env python3
"""Silently qualify the 227-object Marina regular-hierarchy cold view."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re

import build_regular_lod_manager_survey as builder
import capture_terrain_manager_survey as survey


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
PROGRAM_NAME = "P3DRGL.BIN"
PROGRAM = FIXTURE / PROGRAM_NAME
MANIFEST = FIXTURE / "MANAGER.json"
WORLD = FIXTURE / "WORLD.json"
DEFAULT_RADIUS = 5
START_CELL = (80, 125)
SLOT_COUNT = 255
ACTIVE_COUNT = 227
SEQUENCES = (0, ACTIVE_COUNT - 1)
CAPTURE_SCHEMA = "pingo-terrain-regular-lod-manager-survey-capture-v1"
CAPTURE_REPORT_NAME = "regular-lod-manager-survey-capture.json"
RENDER_RE = re.compile(r"PINGO_RENDER seq=(\d+)[^\r\n]*")


@lru_cache(maxsize=1)
def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def initial_records() -> tuple[dict, ...]:
    records = tuple(_manifest().get("initial_view", {}).get("records", ()))
    if len(records) != ACTIVE_COUNT:
        raise SystemExit(
            f"regular-LOD manager receipt needs {ACTIVE_COUNT} initial records"
        )
    if tuple(record.get("order") for record in records) != tuple(range(ACTIVE_COUNT)):
        raise SystemExit("regular-LOD initial record order changed")
    if len({record.get("slot") for record in records}) != ACTIVE_COUNT:
        raise SystemExit("regular-LOD initial record slots are not injective")
    return records


def expected_cells(*_args, **_kwargs) -> dict[int, tuple[int, int, int]]:
    """Return exact command-52 transforms in cold publication order."""

    return {
        int(record["object_id"]): tuple(record["translation_counts"])
        for record in initial_records()
    }


def terrain_record_paths(*_args, **_kwargs) -> tuple[Path, ...]:
    return tuple(Path(record["path"]) for record in initial_records())


def expected_publication_shapes() -> dict[int, dict[str, int]]:
    fields = (
        "data_bytes",
        "vertices",
        "position_indices",
        "texture_coordinates",
        "texture_indices",
    )
    return {
        int(record["mesh_id"]): {
            field: int(record[field]) for field in fields
        }
        for record in initial_records()
    }


def validate_fixture_contract(
    fixture: Path,
    program: Path,
    manifest: Path,
    world: Path,
) -> dict[str, object]:
    document = _manifest()
    if document.get("schema") != builder.MANAGER_SCHEMA:
        raise SystemExit("regular-LOD manager schema changed")
    manager = document.get("manager", {})
    expected_manager = {
        "default_radius": 5,
        "maximum_radius": 5,
        "near_slots": 91,
        "coarse_slot_capacity": 164,
        "stable_slots": 255,
        "marina_near_counts": [1, 7, 19, 37, 61, 91],
        "marina_coarse_counts": [110, 117, 127, 125, 135, 136],
        "marina_desired_counts": [111, 124, 146, 162, 196, 227],
        "mesh_id_range": [1, 255],
        "object_id_range": [1, 255],
        "publication_budget_per_idle_pass": 1,
        "defer_stale_rebase": True,
        "fallback_position_fringe_cells": 1,
        "group_staging_enabled": True,
        "owner_domain": "unified detailed and coarse owners",
        "cold_slot_policy": "91 hashed detailed slots, then coarse slots",
        "post_handoff_slot_policy": "arbitrary authoritative owner-to-slot map",
        "transition_policy": "coverage-component atomic commit",
        "transition_radius": 5,
        "transition_recipe_count": 192,
        "transition_group_count": 4_176,
        "maximum_group_retiring": 14,
        "maximum_group_entering": 14,
        "maximum_group_commit_activity": 15,
        "minimum_group_staging_margin": 4,
        "radius_change_policy": "render-idle cold restart at current origin",
        "runtime_axis_adapter": {
            "source": "X=north,Y=up,Z=-east (reflected)",
            "published": "X=north,Y=up,Z=+east (right-handed)",
            "vertex_z_negated": True,
            "triangle_winding_reversed": True,
        },
        "projection_far_units": 65_535,
        "phase_q": 0,
        "phase_offset_row": 1,
    }
    for name, expected in expected_manager.items():
        if manager.get(name) != expected:
            raise SystemExit(
                f"regular-LOD manager {name}={manager.get(name)!r}, "
                f"expected {expected!r}"
            )
    binary = document.get("binary", {})
    if binary.get("sha256") != survey.sha256(program):
        raise SystemExit("regular-LOD manager binary checksum changed")
    hierarchy = document.get("hierarchy", {})
    if hierarchy.get("world_sha256") != survey.sha256(world):
        raise SystemExit("regular-LOD hierarchy WORLD checksum changed")
    transition = hierarchy.get("transition_include", {})
    expected_transition = {
        "path": "fixtures/terrain-manager-regular-lod-survey/tgt/regular-lod-transitions.inc",
        "bytes": 109_831,
        "sha256": "aa6a3d152370f59fc2cefceacc46766bfc3425cb012be927beb5a758788de749",
        "recipe_count": 192,
        "group_count": 4_176,
        "logical_table_bytes": 21_504,
        "logical_table_sha256": "34fd0c448e6b653d4ab25883eb283a328dc5825cd6232591866059cbd2b6a79d",
        "maximum_retiring": 14,
        "maximum_entering": 14,
        "maximum_commit_activity": 15,
        "minimum_staging_margin": 4,
        "audited_directed_bounded_transitions": 299_306,
    }
    for name, expected in expected_transition.items():
        if transition.get(name) != expected:
            raise SystemExit(
                f"regular-LOD transition {name}={transition.get(name)!r}, "
                f"expected {expected!r}"
            )
    if transition.get("sha256") != survey.sha256(builder.TRANSITION_INCLUDE):
        raise SystemExit("regular-LOD transition source include checksum changed")

    resources: dict[str, dict[str, object]] = {}
    for name in survey.RESOURCE_NAMES:
        path = survey.capture.require_file(fixture / name, f"regular resource {name}")
        actual = {"bytes": path.stat().st_size, "sha256": survey.sha256(path)}
        if document.get("resources", {}).get(name) != actual:
            raise SystemExit(f"regular-LOD resource checksum changed: {name}")
        resources[name] = actual

    validated_records: dict[str, dict[str, object]] = {}
    for record in initial_records():
        relative = Path(record["path"])
        path = survey.capture.require_file(
            fixture / relative, f"regular terrain record {relative}"
        )
        actual = {"bytes": path.stat().st_size, "sha256": survey.sha256(path)}
        expected = {"bytes": record["bytes"], "sha256": record["sha256"]}
        if actual != expected:
            raise SystemExit(f"regular-LOD record checksum changed: {relative}")
        validated_records[relative.as_posix()] = actual
    return {
        "program": {"bytes": program.stat().st_size, "sha256": survey.sha256(program)},
        "resources": resources,
        "terrain_records": validated_records,
        "active_records": ACTIVE_COUNT,
        "manager_slots": SLOT_COUNT,
    }


def configure_shared_capture() -> None:
    survey.FIXTURE = FIXTURE
    survey.DEFAULT_RADIUS = DEFAULT_RADIUS
    survey.SEQUENCES = SEQUENCES
    survey.START_CELL = START_CELL
    survey.SLOT_COUNT = SLOT_COUNT
    survey.PROGRAM_NAME = PROGRAM_NAME
    survey.PROGRAM = PROGRAM
    survey.MANIFEST = MANIFEST
    survey.WORLD = WORLD
    survey.MANIFEST_SCHEMA = builder.MANAGER_SCHEMA
    survey.CAPTURE_SCHEMA = CAPTURE_SCHEMA
    survey.CAPTURE_REPORT_NAME = CAPTURE_REPORT_NAME
    survey.CAPTURE_LABEL = "regular-LOD terrain manager survey"
    survey.expected_cells = expected_cells
    survey.terrain_record_paths = terrain_record_paths
    survey.expected_publication_shapes = expected_publication_shapes
    survey.validate_fixture_contract = validate_fixture_contract


def _final_render_counts(log: str) -> dict[str, int]:
    lines = [
        match.group(0)
        for match in RENDER_RE.finditer(log)
        if int(match.group(1)) == SEQUENCES[-1]
    ]
    if len(lines) != 1:
        raise SystemExit(f"expected one final regular-LOD render, got {len(lines)}")
    fields = {
        name: int(value)
        for name, value in re.findall(r"\b(far|ob|obt)=(\d+)", lines[0])
    }
    expected = {"far": 65_535, "ob": ACTIVE_COUNT, "obt": ACTIVE_COUNT}
    if fields != expected:
        raise SystemExit(f"regular-LOD final traversal changed: {fields} != {expected}")
    return fields


def main() -> int:
    configure_shared_capture()
    status = survey.main()
    output = survey.parse_arguments().output.expanduser().resolve()
    report_path = output / CAPTURE_REPORT_NAME
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["frames"][0]["population"] = "Marina-centre-only"
    report["frames"][-1]["population"] = "all-227-regular-hierarchy-objects"
    log = (output / "emulator.log").read_text(encoding="utf-8", errors="replace")
    if "PINGO_PROJECTION far_set=ok units=65535" not in log:
        raise SystemExit("regular-LOD capture omitted the 65535-unit far command")
    if "PINGO_SCENE active_overflow=1" in log:
        raise SystemExit("regular-LOD capture hit the retired scene-object limit")
    report["projection_far_units"] = 65_535
    report["final_traversal"] = _final_render_counts(log)
    report["active_object_capacity_overflow"] = False
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
