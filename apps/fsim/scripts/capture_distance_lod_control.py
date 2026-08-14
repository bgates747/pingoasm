#!/usr/bin/env python3
"""Silently qualify all 183 objects in the Marina distance-LOD control."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import sys

import capture_terrain_manager_survey as survey


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-distance-lod-control"
NATURAL_FIXTURE = ROOT / "build/p3dm/bay-area-natural-full-l0"
PROGRAM_NAME = "P3DDST.BIN"
PROGRAM = FIXTURE / PROGRAM_NAME
MANIFEST = FIXTURE / "MANAGER.json"
DISTANCE = FIXTURE / "DISTANCE.json"
NATURAL_WORLD = NATURAL_FIXTURE / "WORLD.json"
DEFAULT_RADIUS = 5
START_CELL = (80, 125)
SLOT_COUNT = 183
NEAR_SLOT_COUNT = 91
SEQUENCES = (0, SLOT_COUNT - 1)

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import HexCell, disk_offsets  # noqa: E402
from pingo_terrain.p3dm import make_data, parse_container  # noqa: E402


@lru_cache(maxsize=1)
def _documents() -> tuple[dict, dict, dict]:
    return (
        json.loads(MANIFEST.read_text(encoding="utf-8")),
        json.loads(DISTANCE.read_text(encoding="utf-8")),
        json.loads(NATURAL_WORLD.read_text(encoding="utf-8")),
    )


def expected_cells(*_args, **_kwargs) -> dict[int, tuple[int, int, int]]:
    """Return exact command-52 translations in manager desired-set order."""

    result: dict[int, tuple[int, int, int]] = {}
    q0, r0 = START_CELL
    for dq, dr in disk_offsets(DEFAULT_RADIUS):
        q, r = q0 + dq, r0 + dr
        object_id = 1 + (5 * q + 11 * r) % NEAR_SLOT_COUNT
        if object_id in result:
            raise AssertionError(f"near terrain repeats object {object_id}")
        result[object_id] = (dq * 4400 + dr * 8800, 9728, -dq * 7680)
    distance = _documents()[1]
    for record in distance["records"]:
        object_id = 1 + NEAR_SLOT_COUNT + record["ordinal"]
        if object_id in result:
            raise AssertionError(f"distance terrain repeats object {object_id}")
        result[object_id] = tuple(record["translation_counts"])
    if len(result) != SLOT_COUNT:
        raise AssertionError(f"expected {SLOT_COUNT} objects, got {len(result)}")
    return result


def terrain_record_paths(*_args, **_kwargs) -> tuple[Path, ...]:
    q0, r0 = START_CELL
    near = []
    for dq, dr in disk_offsets(DEFAULT_RADIUS):
        cell_id = HexCell(q0 + dq, r0 + dr).cell_id
        near.append(
            Path("NAT/L0") / f"{cell_id >> 8:02X}" / f"{cell_id & 0xFF:02X}.AGN"
        )
    distance = _documents()[1]
    return tuple(near) + tuple(Path(record["path"]) for record in distance["records"])


def expected_publication_shapes() -> dict[int, dict[str, int]]:
    _, distance, natural = _documents()
    natural_by_id = {record["cell_id"]: record for record in natural["records"]}
    result: dict[int, dict[str, int]] = {}
    q0, r0 = START_CELL
    for dq, dr in disk_offsets(DEFAULT_RADIUS):
        q, r = q0 + dq, r0 + dr
        record = natural_by_id[HexCell(q, r).cell_id]
        object_id = 1 + (5 * q + 11 * r) % NEAR_SLOT_COUNT
        result[object_id] = {
            "data_bytes": record["data_bytes"],
            "vertices": record["vertices"],
            "position_indices": record["triangles"] * 3,
            "texture_coordinates": 16,
            "texture_indices": record["triangles"] * 3,
        }
    for record in distance["records"]:
        tile = parse_container((FIXTURE / record["path"]).read_bytes())
        object_id = 1 + NEAR_SLOT_COUNT + record["ordinal"]
        result[object_id] = {
            "data_bytes": len(make_data(tile)),
            "vertices": len(tile.positions),
            "position_indices": len(tile.position_indices),
            "texture_coordinates": len(tile.uvs),
            "texture_indices": len(tile.uv_indices),
        }
    return result


def validate_fixture_contract(
    fixture: Path, program: Path, manifest: Path, world: Path
) -> dict[str, object]:
    manager, distance, natural = _documents()
    if manager.get("schema") != "pingo-terrain-distance-lod-manager-v1":
        raise SystemExit("distance manager schema changed")
    contract = manager.get("manager", {})
    expected = {
        "near_slots": 91,
        "coarse_slots": 92,
        "stable_slots": 183,
        "radius_desired_counts": [93, 99, 111, 129, 153, 183],
        "mesh_id_range": [1, 183],
        "object_id_range": [1, 183],
        "publication_budget_per_idle_pass": 1,
        "projection_far_units": 65_535,
    }
    for name, value in expected.items():
        if contract.get(name) != value:
            raise SystemExit(
                f"distance manager {name}={contract.get(name)!r}, expected {value!r}"
            )
    if manager.get("binary", {}).get("sha256") != survey.sha256(program):
        raise SystemExit("distance manager binary checksum changed")
    resources: dict[str, dict[str, object]] = {}
    for name in survey.RESOURCE_NAMES:
        path = survey.capture.require_file(fixture / name, f"distance resource {name}")
        actual = {"bytes": path.stat().st_size, "sha256": survey.sha256(path)}
        if manager.get("resources", {}).get(name) != actual:
            raise SystemExit(f"distance resource checksum changed: {name}")
        resources[name] = actual

    distance_by_path = {record["path"]: record for record in distance["records"]}
    natural_by_path = {record["path"]: record for record in natural["records"]}
    records: dict[str, dict[str, object]] = {}
    for relative in terrain_record_paths():
        name = relative.as_posix()
        metadata = distance_by_path.get(name) or natural_by_path.get(name)
        if metadata is None:
            raise SystemExit(f"runtime record is absent from its index: {name}")
        path = survey.capture.require_file(fixture / relative, f"terrain record {name}")
        actual = {"bytes": path.stat().st_size, "sha256": survey.sha256(path)}
        if actual != {"bytes": metadata["bytes"], "sha256": metadata["sha256"]}:
            raise SystemExit(f"runtime terrain checksum changed: {name}")
        records[name] = actual
    return {
        "program": {"bytes": program.stat().st_size, "sha256": survey.sha256(program)},
        "resources": resources,
        "terrain_records": records,
        "near_records": 91,
        "coarse_records": 92,
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
    survey.WORLD = DISTANCE
    survey.MANIFEST_SCHEMA = "pingo-terrain-distance-lod-manager-v1"
    survey.CAPTURE_SCHEMA = "pingo-terrain-distance-lod-capture-v1"
    survey.CAPTURE_REPORT_NAME = "distance-lod-control-capture.json"
    survey.CAPTURE_LABEL = "distance LOD control"
    survey.expected_cells = expected_cells
    survey.terrain_record_paths = terrain_record_paths
    survey.expected_publication_shapes = expected_publication_shapes
    survey.validate_fixture_contract = validate_fixture_contract


def main() -> int:
    configure_shared_capture()
    status = survey.main()
    # The shared capture uses historical population prose; correct the durable
    # receipt while retaining its fully qualified evidence and raw log.
    output_argument = survey.parse_arguments().output.expanduser().resolve()
    report_path = output_argument / survey.CAPTURE_REPORT_NAME
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["frames"][0]["population"] = "near-centre-only"
    report["frames"][-1]["population"] = "all-183-near-and-distance-objects"
    log = (output_argument / "emulator.log").read_text(
        encoding="utf-8", errors="replace"
    )
    if "PINGO_PROJECTION far_set=ok units=65535" not in log:
        raise SystemExit("distance capture omitted the 65535-unit projection command")
    if "PINGO_SCENE active_overflow=1" in log:
        raise SystemExit("distance capture hit the retired 32-object scene limit")
    report["projection_far_units"] = 65_535
    report["active_object_capacity_overflow"] = False
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
