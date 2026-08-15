#!/usr/bin/env python3
"""Compile the bounded natural master subset and its manager-survey fixture."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = ROOT / "fixtures/terrain-manager-survey/src"
FIXTURE = ROOT / "fixtures/terrain-manager-natural-survey"
TARGET = FIXTURE / "tgt"
ASSEMBLY_SOURCE = SOURCE_DIRECTORY / "terrain-manager-natural-survey.asm"
PROGRAM = TARGET / "terrain-manager-natural-survey.bin"
LISTING = TARGET / "terrain-manager-natural-survey.lst"
SYMBOLS = TARGET / "terrain-manager-natural-survey.symbols"
RUNTIME_PROGRAM_NAME = "P3DNAT.BIN"
RUNTIME_MANIFEST_NAME = "MANAGER.json"
DEFAULT_CORPUS = ROOT / "build/p3dm/bay-area-natural-campanile-r5-l0"
DEFAULT_SOURCE = DEFAULT_CORPUS / "SOURCE.json"
SOURCE_SCHEMA = "pingo-terrain-natural-runtime-source-v1"
WORLD_SCHEMA = "pingo-terrain-natural-corpus-v1"
MANAGER_SCHEMA = "pingo-terrain-natural-manager-survey-v1"
EXPECTED_SOURCE_SEMANTIC_SHA256 = (
    "10758c3e4633e199af85c2829af3313923220db65267ec999e033d780227be88"
)
SOURCE_BLEND_SHA256 = (
    "fd4dde2a9f366797808ef9bd395f0966386a8286aeca87b0c73c9ed4f1f64d02"
)
SOURCE_TOPOLOGY_SHA256 = (
    "c7695f333e25812909fd2667614cb7213fee9de864dda417167181af128e5cca"
)
START_CELL = (90, 121)
START_CANONICAL = (3711, 3496, -1482)
SELECTION_RADIUS = 5
DEFAULT_RADIUS = 2
MAXIMUM_RADIUS = 5
RADIUS_COUNTS = tuple(1 + 3 * radius * (radius + 1) for radius in range(6))
SLOT_COUNT = RADIUS_COUNTS[-1]
P3DM_FILE_LIMIT = 16_384
RUNTIME_PATTERN_COUNT = 126
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"
FIXTURE_LOAD_CAPACITY = 0x070000

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.flat_patterns import (  # noqa: E402
    ILLUMINATION_BANDS,
    PATTERN_PIXELS,
    compile_patterns,
    pack_opaque_rgba2222,
)
from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HEX_MODEL_HALF_EXTENT_M,
    HEX_OBJECT_SCALE_Q8_8,
    HEX_TERRAIN_Y_COUNT,
    HexCell,
    disk_offsets,
)
from pingo_terrain.materials import (  # noqa: E402
    AGON_SOLID_TERRAIN_MATERIALS,
    BERKELEY_TERRAIN_MATERIALS,
)
from pingo_terrain.natural_runtime import (  # noqa: E402
    NaturalRuntimeComponent,
    build_natural_runtime_component,
    maximum_absolute_position_word,
    validate_same_lod_seams,
)
from pingo_terrain.p3dm import (  # noqa: E402
    LayerKind,
    make_container,
    make_data,
    parse_container,
)
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    STAGING_BUFFER_ID,
)


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--skip-assemble", action="store_true")
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def require_exact_int(value: object, description: str) -> int:
    if type(value) is not int:
        raise SystemExit(f"{description} must be an exact integer: {value!r}")
    return value


def expected_cells() -> tuple[HexCell, ...]:
    q0, r0 = START_CELL
    return tuple(
        HexCell(q0 + dq, r0 + dr)
        for dq, dr in disk_offsets(SELECTION_RADIUS)
    )


def record_path(cell: HexCell) -> Path:
    cell_id = cell.cell_id
    return Path("NAT/L0") / f"{cell_id >> 8:02X}" / f"{cell_id & 0xFF:02X}.AGN"


def require_source(path: Path) -> tuple[dict, tuple[NaturalRuntimeComponent, ...]]:
    if not path.is_file():
        raise SystemExit(
            "Extract the accepted Blender artifact first with "
            "scripts/export_natural_runtime_subset_blender.py"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"natural runtime source is unreadable: {path}") from error
    source = document.get("source", {})
    selection = document.get("selection", {})
    witness = (
        document.get("schema"),
        source.get("blend_sha256"),
        source.get("topology_and_ownership_sha256"),
        selection.get("center_q"),
        selection.get("center_r"),
        selection.get("radius"),
        selection.get("component_count"),
    )
    expected_witness = (
        SOURCE_SCHEMA,
        SOURCE_BLEND_SHA256,
        SOURCE_TOPOLOGY_SHA256,
        *START_CELL,
        SELECTION_RADIUS,
        SLOT_COUNT,
    )
    if witness != expected_witness:
        raise SystemExit(
            f"natural runtime source contract changed: {witness} != {expected_witness}"
        )
    semantic_payload = {
        "selection": selection,
        "components": document.get("components"),
        "seam_evidence": document.get("seam_evidence"),
    }
    semantic_sha = sha256_bytes(canonical_bytes(semantic_payload))
    if (
        semantic_sha != document.get("semantic_sha256")
        or semantic_sha != EXPECTED_SOURCE_SEMANTIC_SHA256
    ):
        raise SystemExit(
            f"natural runtime semantic source changed: {semantic_sha} != "
            f"{EXPECTED_SOURCE_SEMANTIC_SHA256}"
        )

    cells = expected_cells()
    if selection.get("cell_ids_in_manager_order") != [cell.cell_id for cell in cells]:
        raise SystemExit("natural source component order differs from manager ring order")
    raw_components = document.get("components")
    if not isinstance(raw_components, list) or len(raw_components) != SLOT_COUNT:
        raise SystemExit("natural source component list is incomplete")

    components: list[NaturalRuntimeComponent] = []
    master_vertices: dict[int, tuple[int, int, int, int]] = {}
    master_faces: set[int] = set()
    for ordinal, (cell, raw) in enumerate(zip(cells, raw_components, strict=True)):
        if not isinstance(raw, dict):
            raise SystemExit(f"natural component {ordinal} is not an object")
        identity = (
            raw.get("cell_id"),
            raw.get("q"),
            raw.get("r"),
        )
        if identity != (cell.cell_id, cell.q, cell.r):
            raise SystemExit(
                f"natural component {ordinal} identity changed: "
                f"{identity} != {(cell.cell_id, cell.q, cell.r)}"
            )
        raw_vertices = raw.get("vertices")
        raw_faces = raw.get("faces")
        if not isinstance(raw_vertices, list) or not isinstance(raw_faces, list):
            raise SystemExit(f"natural component {ordinal} arrays are malformed")

        vertices: list[tuple[int, int, int]] = []
        master_indices: list[int] = []
        for local_index, vertex in enumerate(raw_vertices):
            if not isinstance(vertex, dict):
                raise SystemExit(
                    f"natural component {ordinal} vertex {local_index} is malformed"
                )
            master_index = require_exact_int(
                vertex.get("master_vertex_index"), "master vertex index"
            )
            record = (
                require_exact_int(vertex.get("east_count"), "east count"),
                require_exact_int(vertex.get("north_count"), "north count"),
                require_exact_int(vertex.get("elevation_count"), "elevation count"),
                require_exact_int(
                    vertex.get("elevation_float32_bits"), "float32 elevation bits"
                ),
            )
            previous = master_vertices.setdefault(master_index, record)
            if previous != record:
                raise SystemExit(
                    f"master vertex {master_index} differs across components"
                )
            master_indices.append(master_index)
            vertices.append(record[:3])
        if master_indices != sorted(set(master_indices)):
            raise SystemExit(
                f"natural component {ordinal} vertices are not canonical master order"
            )

        faces: list[tuple[int, int, int]] = []
        materials: list[int] = []
        face_indices: list[int] = []
        for local_face, face in enumerate(raw_faces):
            if not isinstance(face, dict):
                raise SystemExit(
                    f"natural component {ordinal} face {local_face} is malformed"
                )
            master_face = require_exact_int(
                face.get("master_face_index"), "master face index"
            )
            if master_face in master_faces:
                raise SystemExit(f"master face {master_face} has several owners")
            master_faces.add(master_face)
            face_indices.append(master_face)
            indices = face.get("vertices")
            if not isinstance(indices, list) or len(indices) != 3:
                raise SystemExit(f"master face {master_face} is not triangular")
            faces.append(
                tuple(
                    require_exact_int(index, f"master face {master_face} index")
                    for index in indices
                )
            )
            materials.append(
                require_exact_int(face.get("material_id"), "terrain material ID")
            )
        if face_indices != sorted(face_indices):
            raise SystemExit(
                f"natural component {ordinal} faces are not canonical master order"
            )
        components.append(
            NaturalRuntimeComponent(
                cell=cell,
                vertices=tuple(vertices),
                faces=tuple(faces),
                materials=tuple(materials),
            )
        )

    statistics = document.get("statistics", {})
    extracted_counts = (
        len(master_faces),
        len(master_vertices),
        sum(len(component.vertices) for component in components),
    )
    expected_counts = (
        statistics.get("master_faces"),
        statistics.get("unique_master_vertices"),
        statistics.get("component_vertex_instances"),
    )
    if extracted_counts != expected_counts:
        raise SystemExit(
            f"natural source statistics disagree: {extracted_counts} != {expected_counts}"
        )
    return document, tuple(components)


def build_patterns(output: Path) -> dict:
    """Install an exact-native base profile in the fixed 126-pattern ABI."""

    compiled = compile_patterns(AGON_SOLID_TERRAIN_MATERIALS)
    if compiled.pattern_count > RUNTIME_PATTERN_COUNT:
        raise SystemExit(
            f"diagnostic profile needs {compiled.pattern_count} patterns, exceeding "
            f"the fixture ABI count {RUNTIME_PATTERN_COUNT}"
        )
    black_pattern = bytes((0xC0,)) * PATTERN_PIXELS
    patterns = compiled.patterns + black_pattern * (
        RUNTIME_PATTERN_COUNT - compiled.pattern_count
    )
    if len(patterns) != RUNTIME_PATTERN_COUNT * PATTERN_PIXELS:
        raise AssertionError("padded runtime pattern resource has the wrong size")
    if len(compiled.lookup) != len(AGON_SOLID_TERRAIN_MATERIALS) * ILLUMINATION_BANDS:
        raise AssertionError("diagnostic pattern lookup has the wrong size")

    mapping: list[dict] = []
    for source, diagnostic in zip(
        BERKELEY_TERRAIN_MATERIALS,
        AGON_SOLID_TERRAIN_MATERIALS,
        strict=True,
    ):
        levels = tuple(channel // 85 for channel in diagnostic.rgb)
        packed = pack_opaque_rgba2222(levels)
        lookup_offset = source.material_id * ILLUMINATION_BANDS + (
            ILLUMINATION_BANDS - 1
        )
        pattern_id = compiled.lookup[lookup_offset]
        base = patterns[
            pattern_id * PATTERN_PIXELS : (pattern_id + 1) * PATTERN_PIXELS
        ]
        if base != bytes((packed,)) * PATTERN_PIXELS:
            raise SystemExit(
                f"material {source.material_id} base pattern is not solid {packed:#04x}"
            )
        mapping.append(
            {
                "material_id": source.material_id,
                "nlcd_category": source.nlcd_category,
                "name": source.name,
                "authored_rgb8": list(source.rgb),
                "diagnostic_rgb8": list(diagnostic.rgb),
                "opaque_rgba2222": packed,
                "base_illumination_band": ILLUMINATION_BANDS - 1,
                "base_pattern_id": pattern_id,
                "base_pattern_unique_pixels": 1,
                "base_pattern_sha256": sha256_bytes(base),
            }
        )

    selector = bytes((0xC0,)) * 16
    resources = {
        "MATID.RG2": selector,
        "PATTERN.RG2": patterns,
        "PATLUT.BIN": compiled.lookup,
    }
    witnesses: dict[str, dict[str, object]] = {}
    for name, payload in resources.items():
        path = output / name
        path.write_bytes(payload)
        witnesses[name] = {
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
    metadata = {
        **compiled.metadata,
        "schema": "pingo-terrain-native-base-patterns-v1",
        "diagnostic_contract": {
            "authored_base_colors_are_exact_opaque_rgba2222": True,
            "base_patterns_are_solid": True,
            "scene_illumination_enabled": True,
            "darker_illumination_bands_may_dither": True,
            "mapping": mapping,
        },
        "runtime_library": {
            "compiled_unique_patterns": compiled.pattern_count,
            "bound_pattern_count": RUNTIME_PATTERN_COUNT,
            "padding_patterns": RUNTIME_PATTERN_COUNT - compiled.pattern_count,
            "padding_value": 0xC0,
            "resources": witnesses,
        },
    }
    metadata_path = output / "PATTERN.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    witnesses[metadata_path.name] = {
        "bytes": metadata_path.stat().st_size,
        "sha256": sha256_file(metadata_path),
    }
    return {
        "profile": metadata["schema"],
        "compiled_unique_patterns": compiled.pattern_count,
        "bound_pattern_count": RUNTIME_PATTERN_COUNT,
        "mapping": mapping,
        "resources": witnesses,
    }


def assemble() -> None:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise SystemExit("ez80asm is not available on PATH")
    TARGET.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_adl_width.py"),
            "--follow-includes",
            "--show-review",
            "--fail-review",
            str(ASSEMBLY_SOURCE),
        ],
        cwd=ROOT,
        check=True,
    )
    generated_program = SOURCE_DIRECTORY / "terrain-manager-natural-survey.bin"
    subprocess.run(
        [
            assembler,
            "-l",
            "-s",
            ASSEMBLY_SOURCE.name,
            generated_program.name,
            "-c",
        ],
        cwd=SOURCE_DIRECTORY,
        check=True,
    )
    generated_listing = SOURCE_DIRECTORY / "terrain-manager-natural-survey.lst"
    generated_symbols = SOURCE_DIRECTORY / "terrain-manager-natural-survey.symbols"
    if not generated_listing.is_file() or not generated_symbols.is_file():
        raise SystemExit("ez80asm omitted natural-survey listing/symbols")
    if not generated_program.is_file():
        raise SystemExit("ez80asm omitted the natural-survey binary")
    shutil.move(generated_program, PROGRAM)
    shutil.move(generated_listing, LISTING)
    shutil.move(generated_symbols, SYMBOLS)
    payload = PROGRAM.read_bytes()
    if len(payload) > FIXTURE_LOAD_CAPACITY:
        raise SystemExit("natural manager survey exceeds the fixture load window")
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise SystemExit("natural manager survey lost the common fixture entry")


def build_corpus(source_path: Path, output: Path) -> dict:
    document, components = require_source(source_path)
    output.mkdir(parents=True, exist_ok=True)
    built_components = tuple(
        build_natural_runtime_component(component) for component in components
    )
    seam_report = validate_same_lod_seams(built_components)
    source_seams = document["seam_evidence"]
    seam_witness = (
        seam_report["selected_selected_seam_edges"],
        seam_report["selected_subset_outer_edges"],
        seam_report["physical_component_pairs"],
        seam_report["boundary_edge_incidences"],
        seam_report["multi_owner_boundary_vertices"],
        seam_report["maximum_boundary_vertex_owners"],
    )
    expected_seam_witness = (
        source_seams["selected_selected_master_edges"],
        source_seams["selected_to_outside_master_edges"]
        + source_seams["selected_global_corpus_edges"],
        source_seams["physical_component_pairs"],
        source_seams["component_boundary_edge_incidences"],
        source_seams["multi_owner_boundary_vertices"],
        source_seams["maximum_boundary_vertex_owners"],
    )
    if seam_witness != expected_seam_witness:
        raise SystemExit(
            f"P3DM seam ledger changed: {seam_witness} != {expected_seam_witness}"
        )
    renderer_float_witness = (
        seam_report["renderer_float32_shared_vertices"],
        seam_report["renderer_float32_nonidentical_shared_vertices"],
        seam_report["renderer_float32_maximum_span_pingo_units"],
    )
    expected_renderer_float_witness = (
        389,
        144,
        3.0517578125e-05,
    )
    if renderer_float_witness != expected_renderer_float_witness:
        raise SystemExit(
            "natural renderer-path seam witness changed: "
            f"{renderer_float_witness} != {expected_renderer_float_witness}"
        )

    records: list[dict] = []
    for built in built_components:
        cell = built.source.cell
        relative = record_path(cell)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
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
        destination.write_bytes(container)
        records.append(
            {
                "cell_id": cell.cell_id,
                "q": cell.q,
                "r": cell.r,
                "offset_row": cell.offset_row,
                "lod": 0,
                "path": relative.as_posix(),
                "bytes": len(container),
                "sha256": sha256_bytes(container),
                "data_bytes": len(data),
                "data_sha256": sha256_bytes(data),
                "vertices": len(parsed.positions),
                "surface_vertices": len(parsed.positions),
                "triangles": len(parsed.position_indices) // 3,
                "surface_triangles": len(parsed.position_indices) // 3,
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

    aggregate = {
        "records": len(records),
        "container_bytes": sum(record["bytes"] for record in records),
        "data_bytes": sum(record["data_bytes"] for record in records),
        "vertices": sum(record["vertices"] for record in records),
        "triangles": sum(record["triangles"] for record in records),
        "minimum_container_bytes": min(record["bytes"] for record in records),
        "maximum_container_bytes": max(record["bytes"] for record in records),
        "maximum_absolute_position_word": maximum_absolute_position_word(
            built_components
        ),
        "maximum_file_bytes": P3DM_FILE_LIMIT,
    }
    expected_aggregate = {
        "records": 91,
        "container_bytes": 44_156,
        "data_bytes": 34_978,
        "vertices": 1_461,
        "triangles": 1_699,
        "minimum_container_bytes": 196,
        "maximum_container_bytes": 772,
        "maximum_absolute_position_word": 19_086,
        "maximum_file_bytes": P3DM_FILE_LIMIT,
    }
    if aggregate != expected_aggregate:
        raise SystemExit(
            f"natural runtime aggregate changed: {aggregate} != {expected_aggregate}"
        )

    pattern_report = build_patterns(output)
    build_inputs = (
        Path(__file__),
        ROOT / "src/pingo_terrain/natural_runtime.py",
        ROOT / "src/pingo_terrain/p3dm.py",
        ROOT / "src/pingo_terrain/flat_patterns.py",
        ROOT / "src/pingo_terrain/materials.py",
        ASSEMBLY_SOURCE,
        SOURCE_DIRECTORY / "terrain-manager-hex-provider.inc",
        ROOT / "runtime/ez80/terrain-manager.inc",
    )
    signature = hashlib.sha256()
    signature.update(source_path.read_bytes())
    for path in build_inputs:
        signature.update(path.read_bytes())

    world = {
        "schema": WORLD_SCHEMA,
        "selection": document["selection"],
        "path_equation": "NAT/L0/{cell_id >> 8:02X}/{cell_id & 255:02X}.AGN",
        "source": {
            **document["source"],
            "portable_source_path": str(source_path),
            "portable_source_sha256": sha256_file(source_path),
            "semantic_sha256": document["semantic_sha256"],
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
            "base_materials": "exact opaque Agon RGBA2222 solids",
            "illumination_bands_may_dither": True,
        },
        "seams": {
            **seam_report,
            "master_source_evidence": source_seams,
            "validation": (
                "exact ideal-world integer reconstruction plus measured "
                "binary32 renderer-path span; selected seam copies must be "
                "opposite; no runtime skirts"
            ),
        },
        "patterns": pattern_report,
        "statistics": aggregate,
        "records": records,
        "build_signature": signature.hexdigest(),
    }
    world_path = output / "WORLD.json"
    world_path.write_text(
        json.dumps(world, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return world


def install_program_and_manifest(output: Path, world: dict) -> dict:
    runtime_program = output / RUNTIME_PROGRAM_NAME
    shutil.copy2(PROGRAM, runtime_program)
    report = {
        "schema": MANAGER_SCHEMA,
        "binary": {
            "fixture_path": str(PROGRAM),
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
            "rotation": [0, 0, 0],
        },
        "manager": {
            "implementation": "runtime/ez80/terrain-manager.inc",
            "planning_topology": "flat-top canonical axial hex",
            "physical_mesh_boundaries": "post-partition master edges",
            "corpus_center": list(START_CELL),
            "corpus_radius": SELECTION_RADIUS,
            "default_radius": DEFAULT_RADIUS,
            "maximum_radius": MAXIMUM_RADIUS,
            "radius_cell_counts": list(RADIUS_COUNTS),
            "stable_slots": SLOT_COUNT,
            "mesh_id_range": [1, SLOT_COUNT],
            "object_id_range": [1, SLOT_COUNT],
            "publication_budget_per_idle_pass": 1,
            "topology": "flat-top-axial-hex",
            "translation_command": 52,
            "bounded_provider_clipping": True,
            "complete_default_ring_origin_radius": (
                SELECTION_RADIUS - DEFAULT_RADIUS
            ),
        },
        "resources": {
            name: world["patterns"]["resources"][name]
            for name in ("MATID.RG2", "PATLUT.BIN", "PATTERN.RG2")
        },
        "diagnostic_scope": {
            "qualifies": [
                "natural P3DM emission",
                "same-LOD integer seams and renderer float32 error bound",
                "universal manager publication and retirement",
                "scene illumination over exact native base colors",
            ],
            "defers": [
                "mixed LOD",
                "distant terrain",
                "collision",
                "airports",
                "full-region streaming",
            ],
        },
    }
    manifest = output / RUNTIME_MANIFEST_NAME
    manifest.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    world = build_corpus(source, output)
    if not args.skip_assemble:
        assemble()
        report = install_program_and_manifest(output, world)
        binary = report["binary"]
        print(
            "NATURAL_TERRAIN_MANAGER",
            f"components={world['statistics']['records']}",
            f"triangles={world['statistics']['triangles']}",
            f"container_bytes={world['statistics']['container_bytes']}",
            f"binary_bytes={binary['bytes']}",
            f"binary_sha256={binary['sha256']}",
            f"output={output}",
        )
    else:
        print(
            "NATURAL_TERRAIN_CORPUS",
            f"components={world['statistics']['records']}",
            f"triangles={world['statistics']['triangles']}",
            f"container_bytes={world['statistics']['container_bytes']}",
            f"output={output}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
