#!/usr/bin/env python3
"""Extract a pinned natural-master subset into portable integer source data.

Run with Blender so the accepted review artifact can be read semantically::

    blender --background --python scripts/export_natural_runtime_subset_blender.py

The resulting ``SOURCE.json`` is not a mesh container.  It is a canonical
bridge between Blender and the ordinary-Python P3DM compiler: projected
coordinates and component ownership come from named mesh attributes, never
from the centered/scaled display coordinates used by the review scene.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HexCell,
    disk_offsets,
)


SOURCE_BLEND = ROOT / "build/visualization/bay-area-natural-post-partition.blend"
DEFAULT_OUTPUT = (
    ROOT / "build/p3dm/bay-area-natural-campanile-r5-l0/SOURCE.json"
)
SOURCE_BLEND_SHA256 = (
    "fd4dde2a9f366797808ef9bd395f0966386a8286aeca87b0c73c9ed4f1f64d02"
)
SOURCE_TOPOLOGY_SHA256 = (
    "c7695f333e25812909fd2667614cb7213fee9de864dda417167181af128e5cca"
)
SOURCE_ARTIFACT_SCHEMA = "pingo-terrain-natural-post-partition-review-v1"
OUTPUT_SCHEMA = "pingo-terrain-natural-runtime-source-v1"
TERRAIN_OBJECT_NAME = (
    "Bay Area — NATURAL MASTER — post-partition face ownership"
)
SELECTION_CENTER = (90, 121)
SELECTION_RADIUS = 5


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_BLEND)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def _require_attribute(mesh, name: str, *, domain: str, data_type: str):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        raise SystemExit(f"natural master omits required attribute {name!r}")
    witness = (attribute.domain, attribute.data_type)
    if witness != (domain, data_type):
        raise SystemExit(
            f"natural master attribute {name!r} changed: "
            f"{witness} != {(domain, data_type)}"
        )
    return attribute


def _foreach_int(attribute, size: int) -> array:
    values = array("i", [0]) * size
    attribute.data.foreach_get("value", values)
    return values


def _foreach_bool(attribute, size: int) -> array:
    values = array("b", [0]) * size
    attribute.data.foreach_get("value", values)
    return values


def _float32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _selected_cells() -> tuple[HexCell, ...]:
    q0, r0 = SELECTION_CENTER
    return tuple(
        HexCell(q0 + dq, r0 + dr)
        for dq, dr in disk_offsets(SELECTION_RADIUS)
    )


def _edge_key(first: int, second: int) -> tuple[int, int]:
    return (first, second) if first < second else (second, first)


def extract_document(bpy, source_path: Path) -> dict:
    """Read and validate the accepted object, returning canonical source JSON."""

    scene = bpy.context.scene
    scene_witness = (
        scene.get("artifact_schema"),
        scene.get("topology_and_ownership_sha256"),
        scene.get("partition_checks_passed"),
    )
    expected_scene = (
        SOURCE_ARTIFACT_SCHEMA,
        SOURCE_TOPOLOGY_SHA256,
        True,
    )
    if scene_witness != expected_scene:
        raise SystemExit(
            f"natural review scene contract changed: {scene_witness} != {expected_scene}"
        )
    try:
        review_metadata = json.loads(scene["review_metadata_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit("natural review scene metadata is absent or malformed") from error
    if (
        review_metadata.get("mesh", {}).get("topology_and_ownership_sha256")
        != SOURCE_TOPOLOGY_SHA256
    ):
        raise SystemExit("natural review metadata topology witness changed")

    terrain = bpy.data.objects.get(TERRAIN_OBJECT_NAME)
    if terrain is None or terrain.type != "MESH":
        raise SystemExit(f"accepted natural object is missing: {TERRAIN_OBJECT_NAME}")
    if not terrain.get("partition_checks_passed"):
        raise SystemExit("accepted natural object does not pass partition checks")
    mesh = terrain.data
    if any(len(polygon.vertices) != 3 for polygon in mesh.polygons):
        raise SystemExit("natural master contains a non-triangular polygon")

    east_attribute = _require_attribute(
        mesh, "utm_easting_count", domain="POINT", data_type="INT"
    )
    north_attribute = _require_attribute(
        mesh, "utm_northing_count", domain="POINT", data_type="INT"
    )
    elevation_attribute = _require_attribute(
        mesh, "elevation_navd88_m", domain="POINT", data_type="FLOAT"
    )
    owner_attribute = _require_attribute(
        mesh, "hex_cell_id", domain="FACE", data_type="INT"
    )
    q_attribute = _require_attribute(mesh, "hex_q", domain="FACE", data_type="INT")
    r_attribute = _require_attribute(mesh, "hex_r", domain="FACE", data_type="INT")
    material_attribute = _require_attribute(
        mesh, "terrain_material_id", domain="FACE", data_type="INT"
    )
    partition_attribute = _require_attribute(
        mesh,
        "physical_partition_boundary",
        domain="EDGE",
        data_type="BOOLEAN",
    )
    corpus_attribute = _require_attribute(
        mesh, "corpus_boundary", domain="EDGE", data_type="BOOLEAN"
    )

    cells = _selected_cells()
    selected_ids = {cell.cell_id for cell in cells}
    cell_by_id = {cell.cell_id: cell for cell in cells}
    owner_values = _foreach_int(owner_attribute, len(mesh.polygons))
    selected_face_indices = [
        index for index, owner in enumerate(owner_values) if owner in selected_ids
    ]
    if not selected_face_indices:
        raise SystemExit("natural runtime selection contains no faces")

    faces_by_owner: dict[int, list[tuple[int, tuple[int, int, int], int]]] = defaultdict(list)
    selected_vertex_indices: set[int] = set()
    for face_index in selected_face_indices:
        owner = owner_values[face_index]
        cell = cell_by_id[owner]
        q = int(q_attribute.data[face_index].value)
        r = int(r_attribute.data[face_index].value)
        material = int(material_attribute.data[face_index].value)
        if (q, r) != (cell.q, cell.r):
            raise SystemExit(
                f"face {face_index} owner attributes disagree: "
                f"{owner}/{q},{r} != {cell.cell_id}/{cell.q},{cell.r}"
            )
        vertices = tuple(int(index) for index in mesh.polygons[face_index].vertices)
        if len(vertices) != 3:
            raise AssertionError("triangular master polygon changed during extraction")
        faces_by_owner[owner].append((face_index, vertices, material))
        selected_vertex_indices.update(vertices)
    missing = sorted(selected_ids - set(faces_by_owner))
    if missing:
        raise SystemExit(f"natural runtime selection has empty owners: {missing}")

    # A component-local boundary occurs where exactly one selected face of that
    # owner uses a master edge.  Collapse same-owner interior edges first.
    component_boundary_occurrences: dict[tuple[int, int], list[int]] = defaultdict(list)
    for owner, records in faces_by_owner.items():
        owner_edge_counts: Counter[tuple[int, int]] = Counter()
        for _face_index, vertices, _material in records:
            owner_edge_counts.update(
                _edge_key(first, second)
                for first, second in zip(
                    vertices, vertices[1:] + vertices[:1], strict=True
                )
            )
        bad_counts = [edge for edge, count in owner_edge_counts.items() if count > 2]
        if bad_counts:
            raise SystemExit(f"component {owner} contains non-manifold edges")
        for edge, count in owner_edge_counts.items():
            if count == 1:
                component_boundary_occurrences[edge].append(owner)

    needed_edges = set(component_boundary_occurrences)
    raw_edge_vertices = array("i", [0]) * (len(mesh.edges) * 2)
    mesh.edges.foreach_get("vertices", raw_edge_vertices)
    partition_values = _foreach_bool(partition_attribute, len(mesh.edges))
    corpus_values = _foreach_bool(corpus_attribute, len(mesh.edges))
    edge_flags: dict[tuple[int, int], tuple[bool, bool]] = {}
    for edge_index in range(len(mesh.edges)):
        key = _edge_key(
            raw_edge_vertices[edge_index * 2],
            raw_edge_vertices[edge_index * 2 + 1],
        )
        if key in needed_edges:
            edge_flags[key] = (
                bool(partition_values[edge_index]),
                bool(corpus_values[edge_index]),
            )
    if set(edge_flags) != needed_edges:
        raise SystemExit("could not resolve every selected component-boundary edge")

    internal_edges = 0
    selected_to_outside = 0
    global_corpus_edges = 0
    physical_pairs: set[tuple[int, int]] = set()
    boundary_vertex_owners: dict[int, set[int]] = defaultdict(set)
    for edge, owners in component_boundary_occurrences.items():
        for owner in owners:
            boundary_vertex_owners[edge[0]].add(owner)
            boundary_vertex_owners[edge[1]].add(owner)
        is_partition, is_corpus = edge_flags[edge]
        if len(owners) == 2:
            if owners[0] == owners[1] or not is_partition or is_corpus:
                raise SystemExit(f"selected internal seam has bad master flags: {edge}")
            internal_edges += 1
            physical_pairs.add(tuple(sorted(owners)))
        elif len(owners) == 1 and is_partition and not is_corpus:
            selected_to_outside += 1
        elif len(owners) == 1 and is_corpus and not is_partition:
            global_corpus_edges += 1
        else:
            raise SystemExit(
                f"selected boundary edge has unsupported ownership/flags: "
                f"{edge}, owners={owners}, flags={(is_partition, is_corpus)}"
            )

    vertex_records: dict[int, tuple[int, int, int, int]] = {}
    for master_index in sorted(selected_vertex_indices):
        east = int(east_attribute.data[master_index].value)
        north = int(north_attribute.data[master_index].value)
        elevation_float32 = float(elevation_attribute.data[master_index].value)
        elevation_bits = _float32_bits(elevation_float32)
        elevation_count = round(elevation_float32 * COUNTS_PER_METRE)
        vertex_records[master_index] = (
            east,
            north,
            elevation_count,
            elevation_bits,
        )

    components: list[dict] = []
    for cell in cells:
        source_faces = sorted(faces_by_owner[cell.cell_id])
        master_indices = sorted(
            {index for _face_index, face, _material in source_faces for index in face}
        )
        local = {master: index for index, master in enumerate(master_indices)}
        components.append(
            {
                "cell_id": cell.cell_id,
                "q": cell.q,
                "r": cell.r,
                "vertices": [
                    {
                        "master_vertex_index": master,
                        "east_count": vertex_records[master][0],
                        "north_count": vertex_records[master][1],
                        "elevation_count": vertex_records[master][2],
                        "elevation_float32_bits": vertex_records[master][3],
                    }
                    for master in master_indices
                ],
                "faces": [
                    {
                        "master_face_index": face_index,
                        "vertices": [local[index] for index in face],
                        "material_id": material,
                    }
                    for face_index, face, material in source_faces
                ],
            }
        )

    selection = {
        "name": "campanile-r5",
        "center_q": SELECTION_CENTER[0],
        "center_r": SELECTION_CENTER[1],
        "radius": SELECTION_RADIUS,
        "component_count": len(cells),
        "cell_ids_in_manager_order": [cell.cell_id for cell in cells],
    }
    seam_evidence = {
        "selected_selected_master_edges": internal_edges,
        "selected_to_outside_master_edges": selected_to_outside,
        "selected_global_corpus_edges": global_corpus_edges,
        "physical_component_pairs": len(physical_pairs),
        "component_boundary_edge_incidences": sum(
            len(owners) for owners in component_boundary_occurrences.values()
        ),
        "multi_owner_boundary_vertices": sum(
            len(owners) >= 3 for owners in boundary_vertex_owners.values()
        ),
        "maximum_boundary_vertex_owners": max(
            map(len, boundary_vertex_owners.values()), default=0
        ),
    }
    semantic_payload = {
        "selection": selection,
        "components": components,
        "seam_evidence": seam_evidence,
    }
    semantic_sha256 = hashlib.sha256(canonical_bytes(semantic_payload)).hexdigest()
    return {
        "schema": OUTPUT_SCHEMA,
        "source": {
            "blend_path": str(source_path),
            "blend_sha256": SOURCE_BLEND_SHA256,
            "artifact_schema": SOURCE_ARTIFACT_SCHEMA,
            "topology_and_ownership_sha256": SOURCE_TOPOLOGY_SHA256,
            "source_manifest_sha256": scene.get("source_manifest_sha256"),
            "object_name": TERRAIN_OBJECT_NAME,
        },
        "coordinate_contract": {
            "horizontal": "integer UTM zone 10N counts",
            "elevation": "round(float32 NAVD88 metres * 16) once globally",
            "counts_per_metre": COUNTS_PER_METRE,
            "display_mesh_coordinates_used": False,
        },
        **semantic_payload,
        "statistics": {
            "master_faces": len(selected_face_indices),
            "unique_master_vertices": len(selected_vertex_indices),
            "component_vertex_instances": sum(
                len(component["vertices"]) for component in components
            ),
            "material_histogram": {
                str(material): count
                for material, count in sorted(
                    Counter(
                        face["material_id"]
                        for component in components
                        for face in component["faces"]
                    ).items()
                )
            },
        },
        "semantic_sha256": semantic_sha256,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"accepted natural Blender artifact is missing: {source}")
    actual_blend_sha = sha256_file(source)
    if actual_blend_sha != SOURCE_BLEND_SHA256:
        raise SystemExit(
            f"natural Blender artifact hash changed: "
            f"{actual_blend_sha} != {SOURCE_BLEND_SHA256}"
        )

    try:
        import bpy
    except ImportError as error:  # pragma: no cover - Blender integration
        raise SystemExit("run this extractor through Blender") from error
    loaded = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if loaded != source:
        bpy.ops.wm.open_mainfile(filepath=str(source))
    document = extract_document(bpy, source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "NATURAL_RUNTIME_SOURCE",
        f"components={document['selection']['component_count']}",
        f"vertices={document['statistics']['component_vertex_instances']}",
        f"faces={document['statistics']['master_faces']}",
        f"semantic_sha256={document['semantic_sha256']}",
        f"output={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
