#!/usr/bin/env python3
"""Extract the complete accepted natural master into compact portable source.

Run this script through Blender::

    blender --background --python scripts/export_natural_runtime_corpus_blender.py

The output is the v2 fixed-record bridge documented by
``pingo_terrain.natural_corpus_source``.  It preserves every master vertex and
face once, grouped by dense logical cell ID without constructing the enormous
list-of-dictionaries representation used by the bounded v1 proof.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import export_natural_runtime_subset_blender as bounded  # noqa: E402
from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HEX_CELL_COUNT,
    cell_from_id,
)
from pingo_terrain.natural_corpus_source import (  # noqa: E402
    COMPONENTS_PATH,
    COMPONENT_RECORD,
    FACES_PATH,
    FACE_RECORD,
    SOURCE_SCHEMA,
    VERTICES_PATH,
    VERTEX_RECORD,
    canonical_bytes,
    semantic_payload,
    sha256_bytes,
    sha256_file,
)


DEFAULT_OUTPUT = ROOT / "build/source/bay-area-natural-post-partition-v2"
EXPECTED_VERTICES = 497_767
EXPECTED_FACES = 992_477
EXPECTED_MINIMUM_FACES = 1
EXPECTED_MAXIMUM_FACES = 76
EXPECTED_COMPONENT_VERTEX_INSTANCES = 842_903
EXPECTED_PARTITION_EDGES = 294_948
EXPECTED_CORPUS_EDGES = 3_105
EXPECTED_PHYSICAL_PAIRS = 128_259


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=bounded.SOURCE_BLEND)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def _foreach_float(attribute, size: int) -> array:
    values = array("f", [0.0]) * size
    attribute.data.foreach_get("value", values)
    return values


def _foreach_polygon_vertices(mesh) -> tuple[array, array]:
    loop_starts = array("i", [0]) * len(mesh.polygons)
    loop_totals = array("i", [0]) * len(mesh.polygons)
    loop_vertices = array("i", [0]) * len(mesh.loops)
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    if any(total != 3 for total in loop_totals):
        raise SystemExit("natural master contains a non-triangular polygon")
    return loop_starts, loop_vertices


def _validate_scene(bpy, source_path: Path):
    scene = bpy.context.scene
    witness = (
        scene.get("artifact_schema"),
        scene.get("topology_and_ownership_sha256"),
        scene.get("partition_checks_passed"),
    )
    expected = (
        bounded.SOURCE_ARTIFACT_SCHEMA,
        bounded.SOURCE_TOPOLOGY_SHA256,
        True,
    )
    if witness != expected:
        raise SystemExit(f"natural review scene contract changed: {witness} != {expected}")
    try:
        metadata = json.loads(scene["review_metadata_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit("natural review metadata is absent or malformed") from error
    mesh_metadata = metadata.get("mesh", {})
    expected_metadata = (
        EXPECTED_VERTICES,
        EXPECTED_FACES,
        EXPECTED_PARTITION_EDGES,
        EXPECTED_CORPUS_EDGES,
        EXPECTED_PHYSICAL_PAIRS,
        bounded.SOURCE_TOPOLOGY_SHA256,
    )
    observed_metadata = (
        mesh_metadata.get("retained_vertices"),
        mesh_metadata.get("retained_faces"),
        mesh_metadata.get("partition", {}).get("partition_edges"),
        mesh_metadata.get("partition", {}).get("corpus_edges"),
        mesh_metadata.get("partition", {}).get("physical_adjacencies"),
        mesh_metadata.get("topology_and_ownership_sha256"),
    )
    if observed_metadata != expected_metadata:
        raise SystemExit(
            f"natural review metadata changed: {observed_metadata} != {expected_metadata}"
        )
    terrain = bpy.data.objects.get(bounded.TERRAIN_OBJECT_NAME)
    if terrain is None or terrain.type != "MESH" or not terrain.get(
        "partition_checks_passed"
    ):
        raise SystemExit("accepted natural master object is missing or unqualified")
    mesh = terrain.data
    if (len(mesh.vertices), len(mesh.polygons)) != (
        EXPECTED_VERTICES,
        EXPECTED_FACES,
    ):
        raise SystemExit("accepted natural master vertex/face count changed")
    return scene, metadata, mesh


def _section_record(path: Path, record_count: int, record_struct: struct.Struct) -> dict:
    expected_bytes = record_count * record_struct.size
    if path.stat().st_size != expected_bytes:
        raise SystemExit(
            f"natural source section has {path.stat().st_size} bytes, "
            f"expected {expected_bytes}: {path}"
        )
    return {
        "path": path.name,
        "format": record_struct.format,
        "record_bytes": record_struct.size,
        "records": record_count,
        "bytes": expected_bytes,
        "sha256": sha256_file(path),
    }


def extract(bpy, source_path: Path, output: Path) -> dict:
    scene, metadata, mesh = _validate_scene(bpy, source_path)
    if output.exists():
        raise SystemExit(
            f"refusing to replace an existing natural source bridge: {output}"
        )
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        raise SystemExit(f"remove or inspect the prior incomplete extraction: {temporary}")
    temporary.mkdir(parents=True)

    east = bounded._foreach_int(
        bounded._require_attribute(
            mesh, "utm_easting_count", domain="POINT", data_type="INT"
        ),
        EXPECTED_VERTICES,
    )
    north = bounded._foreach_int(
        bounded._require_attribute(
            mesh, "utm_northing_count", domain="POINT", data_type="INT"
        ),
        EXPECTED_VERTICES,
    )
    elevation = _foreach_float(
        bounded._require_attribute(
            mesh, "elevation_navd88_m", domain="POINT", data_type="FLOAT"
        ),
        EXPECTED_VERTICES,
    )
    vertex_payload = bytearray(EXPECTED_VERTICES * VERTEX_RECORD.size)
    for index, (east_count, north_count, elevation_m) in enumerate(
        zip(east, north, elevation, strict=True)
    ):
        if not math.isfinite(elevation_m):
            raise SystemExit(f"natural master vertex {index} elevation is not finite")
        elevation_bits = struct.unpack("<I", struct.pack("<f", elevation_m))[0]
        VERTEX_RECORD.pack_into(
            vertex_payload,
            index * VERTEX_RECORD.size,
            int(east_count),
            int(north_count),
            round(float(elevation_m) * COUNTS_PER_METRE),
            elevation_bits,
        )
    vertices_path = temporary / VERTICES_PATH
    vertices_path.write_bytes(vertex_payload)
    del vertex_payload, east, north, elevation

    owner = bounded._foreach_int(
        bounded._require_attribute(
            mesh, "hex_cell_id", domain="FACE", data_type="INT"
        ),
        EXPECTED_FACES,
    )
    q_values = bounded._foreach_int(
        bounded._require_attribute(mesh, "hex_q", domain="FACE", data_type="INT"),
        EXPECTED_FACES,
    )
    r_values = bounded._foreach_int(
        bounded._require_attribute(mesh, "hex_r", domain="FACE", data_type="INT"),
        EXPECTED_FACES,
    )
    materials = bounded._foreach_int(
        bounded._require_attribute(
            mesh, "terrain_material_id", domain="FACE", data_type="INT"
        ),
        EXPECTED_FACES,
    )
    loop_starts, loop_vertices = _foreach_polygon_vertices(mesh)

    cell_q = array("h", (cell_from_id(index).q for index in range(HEX_CELL_COUNT)))
    cell_r = array("h", (cell_from_id(index).r for index in range(HEX_CELL_COUNT)))
    counts = array("I", [0]) * HEX_CELL_COUNT
    material_histogram: Counter[int] = Counter()
    for face_index, cell_id in enumerate(owner):
        if not 0 <= cell_id < HEX_CELL_COUNT:
            raise SystemExit(f"natural face {face_index} has invalid owner {cell_id}")
        if (q_values[face_index], r_values[face_index]) != (
            cell_q[cell_id],
            cell_r[cell_id],
        ):
            raise SystemExit(f"natural face {face_index} owner q/r attributes disagree")
        material = materials[face_index]
        if not 0 <= material < 15:
            raise SystemExit(f"natural face {face_index} has material {material}")
        counts[cell_id] += 1
        material_histogram[material] += 1
    if min(counts) != EXPECTED_MINIMUM_FACES or max(counts) != EXPECTED_MAXIMUM_FACES:
        raise SystemExit(
            f"natural component face range changed: {min(counts)}..{max(counts)}"
        )

    offsets = array("I", [0]) * HEX_CELL_COUNT
    running = 0
    for cell_id, count in enumerate(counts):
        offsets[cell_id] = running
        running += count
    if running != EXPECTED_FACES:
        raise SystemExit(f"natural component counts total {running}, not {EXPECTED_FACES}")
    cursors = array("I", offsets)
    face_payload = bytearray(EXPECTED_FACES * FACE_RECORD.size)
    for face_index, cell_id in enumerate(owner):
        loop_start = loop_starts[face_index]
        first, second, third = loop_vertices[loop_start : loop_start + 3]
        destination = cursors[cell_id]
        FACE_RECORD.pack_into(
            face_payload,
            destination * FACE_RECORD.size,
            face_index,
            first,
            second,
            third,
            materials[face_index],
        )
        cursors[cell_id] += 1
    faces_path = temporary / FACES_PATH
    faces_path.write_bytes(face_payload)

    component_payload = bytearray(HEX_CELL_COUNT * COMPONENT_RECORD.size)
    component_vertex_instances = 0
    for cell_id, (start, count) in enumerate(zip(offsets, counts, strict=True)):
        COMPONENT_RECORD.pack_into(
            component_payload, cell_id * COMPONENT_RECORD.size, start, count
        )
        master_vertices: set[int] = set()
        previous_face = -1
        for ordinal in range(start, start + count):
            master_face, first, second, third, _material = FACE_RECORD.unpack_from(
                face_payload, ordinal * FACE_RECORD.size
            )
            if master_face <= previous_face:
                raise SystemExit(f"natural component {cell_id} face order is unstable")
            previous_face = master_face
            master_vertices.update((first, second, third))
        component_vertex_instances += len(master_vertices)
    if component_vertex_instances != EXPECTED_COMPONENT_VERTEX_INSTANCES:
        raise SystemExit(
            "natural component vertex instances changed: "
            f"{component_vertex_instances} != {EXPECTED_COMPONENT_VERTEX_INSTANCES}"
        )
    components_path = temporary / COMPONENTS_PATH
    components_path.write_bytes(component_payload)

    partition_values = bounded._foreach_bool(
        bounded._require_attribute(
            mesh,
            "physical_partition_boundary",
            domain="EDGE",
            data_type="BOOLEAN",
        ),
        len(mesh.edges),
    )
    corpus_values = bounded._foreach_bool(
        bounded._require_attribute(
            mesh, "corpus_boundary", domain="EDGE", data_type="BOOLEAN"
        ),
        len(mesh.edges),
    )
    if (sum(partition_values), sum(corpus_values)) != (
        EXPECTED_PARTITION_EDGES,
        EXPECTED_CORPUS_EDGES,
    ):
        raise SystemExit("natural master partition/corpus edge ledger changed")

    sections = {
        "vertices": _section_record(vertices_path, EXPECTED_VERTICES, VERTEX_RECORD),
        "components": _section_record(
            components_path, HEX_CELL_COUNT, COMPONENT_RECORD
        ),
        "faces": _section_record(faces_path, EXPECTED_FACES, FACE_RECORD),
    }
    document = {
        "schema": SOURCE_SCHEMA,
        "source": {
            "blend_path": str(source_path.relative_to(ROOT)),
            "blend_sha256": bounded.SOURCE_BLEND_SHA256,
            "artifact_schema": bounded.SOURCE_ARTIFACT_SCHEMA,
            "topology_and_ownership_sha256": bounded.SOURCE_TOPOLOGY_SHA256,
            "source_manifest_sha256": scene.get("source_manifest_sha256"),
            "object_name": bounded.TERRAIN_OBJECT_NAME,
        },
        "coordinate_contract": {
            "horizontal": "integer UTM zone 10N counts",
            "elevation": "round(float32 NAVD88 metres * 16) once globally",
            "counts_per_metre": COUNTS_PER_METRE,
            "display_mesh_coordinates_used": False,
        },
        "format_contract": {
            "byte_order": "little-endian",
            "component_identity": "dense cell ID equals COMPONENTS.bin ordinal",
            "face_owner": "implicit dense component ordinal",
            "face_order": "ascending master face index within each owner",
            "vertex_order": "master vertex index",
        },
        "selection": {
            "name": "bay-area-full-region",
            "component_order": "dense cell IDs 0..50182",
            "component_count": HEX_CELL_COUNT,
            "minimum_cell_id": 0,
            "maximum_cell_id": HEX_CELL_COUNT - 1,
        },
        "statistics": {
            "components": HEX_CELL_COUNT,
            "master_vertices": EXPECTED_VERTICES,
            "master_faces": EXPECTED_FACES,
            "component_vertex_instances": component_vertex_instances,
            "minimum_faces_per_component": min(counts),
            "maximum_faces_per_component": max(counts),
            "material_histogram": {
                str(material): count
                for material, count in sorted(material_histogram.items())
            },
        },
        "seam_evidence": {
            "selected_selected_master_edges": EXPECTED_PARTITION_EDGES,
            "selected_subset_outer_edges": EXPECTED_CORPUS_EDGES,
            "component_boundary_edge_incidences": (
                EXPECTED_PARTITION_EDGES * 2 + EXPECTED_CORPUS_EDGES
            ),
            "physical_component_pairs": EXPECTED_PHYSICAL_PAIRS,
        },
        "sections": sections,
        "generator": {
            "path": str(Path(__file__).resolve().relative_to(ROOT)),
            "sha256": sha256_file(Path(__file__).resolve()),
            "blender_version": bpy.app.version_string,
            "review_metadata_sha256": hashlib.sha256(
                canonical_bytes(metadata)
            ).hexdigest(),
        },
    }
    document["semantic_sha256"] = sha256_bytes(
        canonical_bytes(semantic_payload(document))
    )
    manifest = temporary / "SOURCE.json"
    manifest.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.rename(output)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"accepted natural Blender artifact is missing: {source}")
    actual_blend_sha = bounded.sha256_file(source)
    if actual_blend_sha != bounded.SOURCE_BLEND_SHA256:
        raise SystemExit(
            f"natural Blender artifact hash changed: "
            f"{actual_blend_sha} != {bounded.SOURCE_BLEND_SHA256}"
        )
    try:
        import bpy
    except ImportError as error:  # pragma: no cover - Blender integration
        raise SystemExit("run this extractor through Blender") from error
    loaded = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if loaded != source:
        bpy.ops.wm.open_mainfile(filepath=str(source))
    document = extract(bpy, source, output)
    print(
        "NATURAL_RUNTIME_CORPUS_SOURCE",
        f"components={document['selection']['component_count']}",
        f"vertices={document['statistics']['master_vertices']}",
        f"faces={document['statistics']['master_faces']}",
        f"semantic_sha256={document['semantic_sha256']}",
        f"output={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

