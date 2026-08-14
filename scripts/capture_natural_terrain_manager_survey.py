#!/usr/bin/env python3
"""Silently qualify the complete regional natural manager's initial disk."""

from __future__ import annotations

import json
from pathlib import Path

import capture_terrain_manager_survey as survey


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "build/p3dm/bay-area-natural-full-l0"
PROGRAM_NAME = "P3DNAT.BIN"
WORLD = FIXTURE / "WORLD.json"
START_CELL = (80, 125)
DEFAULT_RADIUS = 5
SEQUENCES = (0, 90)


def publication_shapes(document: dict) -> dict[int, dict[str, int]]:
    """Derive each variable natural P3DM shape from the qualified WORLD index."""

    indexed = {record["cell_id"]: record for record in document["records"]}
    result: dict[int, dict[str, int]] = {}
    q0, r0 = START_CELL
    for dq, dr in survey.disk_offsets(DEFAULT_RADIUS):
        cell = survey.HexCell(q0 + dq, r0 + dr)
        record = indexed[cell.cell_id]
        mesh_id = survey.MESH_ID_BASE + (5 * cell.q + 11 * cell.r) % survey.SLOT_COUNT
        shape = {
            "data_bytes": record["data_bytes"],
            "vertices": record["vertices"],
            "position_indices": record["triangles"] * 3,
            "texture_coordinates": 16,
            "texture_indices": record["triangles"] * 3,
        }
        if mesh_id in result:
            raise SystemExit(f"natural default disk repeats stable mesh {mesh_id}")
        result[mesh_id] = shape
    return result


def expected_publication_shapes() -> dict[int, dict[str, int]]:
    return publication_shapes(json.loads(WORLD.read_text(encoding="utf-8")))


def configure_shared_capture() -> None:
    """Bind the generic manager capture lifecycle to the natural fixture."""

    survey.FIXTURE = FIXTURE
    survey.DEFAULT_RADIUS = DEFAULT_RADIUS
    survey.SEQUENCES = SEQUENCES
    survey.START_CELL = START_CELL
    survey.PROGRAM_NAME = PROGRAM_NAME
    survey.PROGRAM = FIXTURE / PROGRAM_NAME
    survey.MANIFEST = FIXTURE / "MANAGER.json"
    survey.WORLD = WORLD
    survey.TERRAIN_RECORD_ROOT = "NAT"
    survey.MANIFEST_SCHEMA = "pingo-terrain-natural-manager-survey-v2"
    survey.CAPTURE_SCHEMA = "pingo-terrain-natural-manager-survey-capture-v2"
    survey.CAPTURE_REPORT_NAME = "natural-terrain-manager-survey-capture.json"
    survey.CAPTURE_LABEL = "natural terrain manager survey"
    survey.expected_publication_shapes = expected_publication_shapes


def main() -> int:
    configure_shared_capture()
    return survey.main()


if __name__ == "__main__":
    raise SystemExit(main())
