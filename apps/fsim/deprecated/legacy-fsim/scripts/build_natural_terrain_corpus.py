#!/usr/bin/env python3
"""Compile the complete natural master into loose regional P3DM records."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Iterator, Sequence


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_natural_terrain_manager_survey as fixture_builder  # noqa: E402
from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HEX_CELL_COUNT,
    HEX_MODEL_HALF_EXTENT_M,
    HEX_OBJECT_SCALE_Q8_8,
    HEX_TERRAIN_Y_COUNT,
    HexCell,
)
from pingo_terrain.natural_corpus_source import (  # noqa: E402
    NaturalCorpusSource,
    sha256_file,
)
from pingo_terrain.natural_runtime import (  # noqa: E402
    build_natural_runtime_component,
    validate_same_lod_seams,
)
from pingo_terrain.p3dm import (  # noqa: E402
    LayerKind,
    make_container,
    make_data,
    parse_container,
)
from pingo_terrain.regional_terrain import STAGING_BUFFER_ID  # noqa: E402


DEFAULT_SOURCE = (
    ROOT / "build/source/bay-area-natural-post-partition-v2/SOURCE.json"
)
DEFAULT_OUTPUT = ROOT / "build/p3dm/bay-area-natural-full-l0"
WORLD_SCHEMA = "pingo-terrain-natural-corpus-v2"
MANAGER_SCHEMA = "pingo-terrain-natural-manager-survey-v2"
RUNTIME_PROGRAM_NAME = "P3DNAT.BIN"
RUNTIME_MANIFEST_NAME = "MANAGER.json"
P3DM_FILE_LIMIT = 16_384

START_CELL = (80, 125)
START_CANONICAL = (4275, 8000, 466)
START_ROTATION = (-1820, 8192, 0)
DEFAULT_RADIUS = 5
MAXIMUM_RADIUS = 5
RADIUS_COUNTS = tuple(1 + 3 * radius * (radius + 1) for radius in range(6))
SLOT_COUNT = RADIUS_COUNTS[-1]
PROJECTION_FAR_UNITS = 65_535

EXPECTED_SOURCE_SEMANTIC_SHA256 = (
    "e9c8ad9059d17a6a3425fede36ea9c3935d8004b1cc50be9a40fe0c4ab5f4bf1"
)
EXPECTED_AGGREGATE = {
    "records": 50_183,
    "container_bytes": 25_251_544,
    "data_bytes": 20_178_854,
    "vertices": 842_903,
    "triangles": 992_477,
    "minimum_container_bytes": 196,
    "maximum_container_bytes": 1_384,
    "maximum_absolute_position_word": 30_720,
    "maximum_file_bytes": P3DM_FILE_LIMIT,
}
EXPECTED_SEAMS = {
    "components": 50_183,
    "boundary_edge_incidences": 593_001,
    "selected_selected_seam_edges": 294_948,
    "selected_subset_outer_edges": 3_105,
    "physical_component_pairs": 128_259,
    "boundary_reconstruction_instances": 1_186_002,
    "reconstruction_mismatches": 0,
    "multi_owner_boundary_vertices": 78_271,
    "maximum_boundary_vertex_owners": 7,
}


def arguments(argv: Sequence[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-assemble", action="store_true")
    return parser.parse_args(argv)


def record_path(cell: HexCell) -> Path:
    cell_id = cell.cell_id
    return Path("NAT/L0") / f"{cell_id >> 8:02X}" / f"{cell_id & 0xFF:02X}.AGN"


def _atomic_write(path: Path, payload: bytes) -> bool:
    """Publish one generated file atomically; return true when rewritten."""

    if path.is_file() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return True


def _atomic_json(path: Path, document: dict) -> None:
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, payload)


def _validate_source_identity(source: NaturalCorpusSource) -> None:
    document = source.document
    source_identity = document.get("source", {})
    witness = (
        document.get("semantic_sha256"),
        source_identity.get("blend_sha256"),
        source_identity.get("topology_and_ownership_sha256"),
        source.cell_count,
        source.vertex_count,
        source.face_count,
    )
    expected = (
        EXPECTED_SOURCE_SEMANTIC_SHA256,
        fixture_builder.SOURCE_BLEND_SHA256,
        fixture_builder.SOURCE_TOPOLOGY_SHA256,
        HEX_CELL_COUNT,
        497_767,
        992_477,
    )
    if witness != expected:
        raise SystemExit(f"complete natural source changed: {witness} != {expected}")


def build_corpus(source_path: Path, output: Path) -> dict:
    try:
        source = NaturalCorpusSource(source_path)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    _validate_source_identity(source)
    output.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    material_histogram: Counter[int] = Counter()
    aggregate = {
        "records": 0,
        "container_bytes": 0,
        "data_bytes": 0,
        "vertices": 0,
        "triangles": 0,
        "minimum_container_bytes": P3DM_FILE_LIMIT,
        "maximum_container_bytes": 0,
        "maximum_absolute_position_word": 0,
        "maximum_file_bytes": P3DM_FILE_LIMIT,
    }
    expected_paths: set[Path] = set()
    rewritten = 0

    def built_components() -> Iterator:
        nonlocal rewritten
        try:
            components = source.components()
            for ordinal, component in enumerate(components, start=1):
                built = build_natural_runtime_component(component)
                cell = component.cell
                relative = record_path(cell)
                expected_paths.add(relative)
                destination = output / relative
                container = make_container(built.tile)
                if len(container) > P3DM_FILE_LIMIT:
                    raise SystemExit(
                        f"natural P3DM record exceeds loader limit: {relative} "
                        f"({len(container)} > {P3DM_FILE_LIMIT})"
                    )
                parsed = parse_container(container)
                if parsed != built.tile:
                    raise SystemExit(f"natural P3DM round trip changed: {relative}")
                data = make_data(parsed)
                rewritten += int(_atomic_write(destination, container))
                triangles = len(parsed.position_indices) // 3
                maximum_word = max(
                    abs(axis) for position in parsed.positions for axis in position
                )
                aggregate["records"] += 1
                aggregate["container_bytes"] += len(container)
                aggregate["data_bytes"] += len(data)
                aggregate["vertices"] += len(parsed.positions)
                aggregate["triangles"] += triangles
                aggregate["minimum_container_bytes"] = min(
                    aggregate["minimum_container_bytes"], len(container)
                )
                aggregate["maximum_container_bytes"] = max(
                    aggregate["maximum_container_bytes"], len(container)
                )
                aggregate["maximum_absolute_position_word"] = max(
                    aggregate["maximum_absolute_position_word"], maximum_word
                )
                material_histogram.update(dict(built.material_histogram))
                records.append(
                    {
                        "cell_id": cell.cell_id,
                        "q": cell.q,
                        "r": cell.r,
                        "offset_row": cell.offset_row,
                        "lod": 0,
                        "path": relative.as_posix(),
                        "bytes": len(container),
                        "sha256": hashlib.sha256(container).hexdigest(),
                        "data_bytes": len(data),
                        "data_sha256": hashlib.sha256(data).hexdigest(),
                        "vertices": len(parsed.positions),
                        "surface_vertices": len(parsed.positions),
                        "triangles": triangles,
                        "surface_triangles": triangles,
                        "skirt_triangles": 0,
                        "minimum_elevation_count": built.minimum_elevation_count,
                        "maximum_elevation_count": built.maximum_elevation_count,
                        "minimum_elevation_dm": parsed.meta.minimum_elevation_dm,
                        "maximum_elevation_dm": parsed.meta.maximum_elevation_dm,
                        "material_histogram": {
                            str(material): count
                            for material, count in built.material_histogram
                        },
                        "component_boundary_edges": len(built.boundary_edges),
                    }
                )
                if ordinal % 5_000 == 0 or ordinal == HEX_CELL_COUNT:
                    print(
                        "NATURAL_TERRAIN_CORPUS_PROGRESS",
                        f"components={ordinal}/{HEX_CELL_COUNT}",
                        f"triangles={aggregate['triangles']}",
                        f"rewritten={rewritten}",
                        flush=True,
                    )
                yield built
        except ValueError as error:
            raise SystemExit(str(error)) from error

    seam_report = validate_same_lod_seams(built_components())
    if source.observed_statistics is None:
        raise AssertionError("complete natural source iterator did not finish")
    if aggregate != EXPECTED_AGGREGATE:
        raise SystemExit(
            f"complete natural P3DM aggregate changed: "
            f"{aggregate} != {EXPECTED_AGGREGATE}"
        )
    seam_witness = {key: seam_report[key] for key in EXPECTED_SEAMS}
    if seam_witness != EXPECTED_SEAMS:
        raise SystemExit(
            f"complete natural seam ledger changed: "
            f"{seam_witness} != {EXPECTED_SEAMS}"
        )
    if {
        str(material): count for material, count in sorted(material_histogram.items())
    } != source.document["statistics"]["material_histogram"]:
        raise SystemExit("complete natural P3DM material histogram changed")

    actual_paths = {
        path.relative_to(output)
        for path in (output / "NAT/L0").rglob("*.AGN")
        if path.is_file()
    }
    extras = actual_paths - expected_paths
    missing = expected_paths - actual_paths
    if extras or missing:
        raise SystemExit(
            f"complete natural loose-record set changed: "
            f"extras={sorted(extras)[:10]} missing={sorted(missing)[:10]}"
        )

    pattern_report = fixture_builder.build_patterns(output)
    build_inputs = (
        Path(__file__),
        ROOT / "src/pingo_terrain/natural_corpus_source.py",
        ROOT / "src/pingo_terrain/natural_runtime.py",
        ROOT / "src/pingo_terrain/p3dm.py",
        ROOT / "src/pingo_terrain/flat_patterns.py",
        ROOT / "src/pingo_terrain/materials.py",
        fixture_builder.ASSEMBLY_SOURCE,
        fixture_builder.SOURCE_DIRECTORY / "terrain-manager-hex-provider.inc",
        ROOT / "runtime/ez80/terrain-manager.inc",
    )
    signature = hashlib.sha256()
    signature.update(source.document["semantic_sha256"].encode("ascii"))
    for section in source.document["sections"].values():
        signature.update(section["sha256"].encode("ascii"))
    for path in build_inputs:
        signature.update(path.read_bytes())

    world = {
        "schema": WORLD_SCHEMA,
        "selection": source.document["selection"],
        "path_equation": "NAT/L0/{cell_id >> 8:02X}/{cell_id & 255:02X}.AGN",
        "source": {
            **source.document["source"],
            "portable_source_path": str(source_path),
            "portable_source_sha256": sha256_file(source_path),
            "semantic_sha256": source.document["semantic_sha256"],
            "sections": source.document["sections"],
        },
        "stage_buffer_id": STAGING_BUFFER_ID,
        "normalization": {
            "counts_per_metre": COUNTS_PER_METRE,
            "model_half_extent_m": HEX_MODEL_HALF_EXTENT_M,
            "object_scale_q8_8": HEX_OBJECT_SCALE_Q8_8,
            "object_translation_y_count": HEX_TERRAIN_Y_COUNT,
            "component_center": "ideal logical HexCell.center_m",
            "surface_only": True,
            "skirts": False,
        },
        "render_policy": {
            "layer_kind": int(LayerKind.TERRAIN),
            "shading": "flat-pattern",
            "illumination": "scene",
            "base_materials": "three exact opaque Agon RGBA2222 solids",
            "illumination_bands_may_dither": True,
        },
        "seams": {
            **seam_report,
            "master_source_evidence": source.document["seam_evidence"],
            "validation": (
                "exact ideal-world integer reconstruction across the complete "
                "master partition; global-origin binary32 span is diagnostic "
                "only because runtime rebasing uses a nearby active origin"
            ),
        },
        "patterns": pattern_report,
        "statistics": aggregate,
        "source_statistics": source.observed_statistics,
        "records": records,
        "build_signature": signature.hexdigest(),
    }
    _atomic_json(output / "WORLD.json", world)
    print(
        "NATURAL_TERRAIN_CORPUS_COMPLETE",
        f"components={aggregate['records']}",
        f"triangles={aggregate['triangles']}",
        f"container_bytes={aggregate['container_bytes']}",
        f"rewritten={rewritten}",
        flush=True,
    )
    return world


def install_program_and_manifest(output: Path, world: dict) -> dict:
    runtime_program = output / RUNTIME_PROGRAM_NAME
    shutil.copy2(fixture_builder.PROGRAM, runtime_program)
    report = {
        "schema": MANAGER_SCHEMA,
        "binary": {
            "fixture_path": str(fixture_builder.PROGRAM),
            "runtime_path": str(runtime_program),
            "bytes": runtime_program.stat().st_size,
            "sha256": sha256_file(runtime_program),
        },
        "corpus": {
            "world_path": str(output / "WORLD.json"),
            "world_sha256": sha256_file(output / "WORLD.json"),
            "records": world["statistics"]["records"],
            "container_bytes": world["statistics"]["container_bytes"],
            "semantic_source_sha256": world["source"]["semantic_sha256"],
        },
        "camera": {
            "axial_cell": list(START_CELL),
            "local_position_counts": list(START_CANONICAL),
            "rotation": list(START_ROTATION),
        },
        "manager": {
            "implementation": "runtime/ez80/terrain-manager.inc",
            "planning_topology": "provisional flat-top canonical axial hex",
            "physical_mesh_boundaries": "post-partition master edges",
            "provider_region": "complete 50,183-cell Bay Area corpus",
            "default_radius": DEFAULT_RADIUS,
            "maximum_radius": MAXIMUM_RADIUS,
            "radius_cell_counts": list(RADIUS_COUNTS),
            "stable_slots": SLOT_COUNT,
            "mesh_id_range": [1, SLOT_COUNT],
            "object_id_range": [1, SLOT_COUNT],
            "publication_budget_per_idle_pass": 1,
            "topology": "flat-top-axial-hex",
            "translation_command": 52,
            "projection_far_command": 53,
            "projection_far_units": PROJECTION_FAR_UNITS,
            "bounded_provider_clipping": False,
            "true_regional_bounds_enabled": True,
        },
        "resources": {
            name: world["patterns"]["resources"][name]
            for name in ("MATID.RG2", "PATLUT.BIN", "PATTERN.RG2")
        },
        "diagnostic_scope": {
            "qualifies": [
                "complete natural P3DM emission",
                "complete same-LOD integer seam ledger",
                "position-driven universal-manager publication",
                "scene illumination over three exact native base colors",
                "maximum accepted ring-five residency and projection far plane",
            ],
            "defers": [
                "explicit physical-adjacency containment",
                "mixed LOD and distant terrain generation",
                "collision",
                "airports",
                "physical hardware",
            ],
        },
    }
    _atomic_json(output / RUNTIME_MANIFEST_NAME, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    world = build_corpus(source, output)
    if args.skip_assemble:
        return 0
    fixture_builder.assemble()
    report = install_program_and_manifest(output, world)
    print(
        "NATURAL_TERRAIN_MANAGER",
        f"components={world['statistics']['records']}",
        f"triangles={world['statistics']['triangles']}",
        f"binary_bytes={report['binary']['bytes']}",
        f"binary_sha256={report['binary']['sha256']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
