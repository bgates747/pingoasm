#!/usr/bin/env python3
"""Build the full Marina near/distance-LOD Blender review artifact.

The scene is reconstructed from the exact P3DM records used by the runtime
experiment.  It combines the complete natural L0 disk at logical rings 0..5
with the regular one-centre/six-triangle distance chunks at rings 6..30.
Distance-chunk skirts live in their own collection so the honest surface join
and the runtime fail-soft coverage can be inspected independently.

Run through Blender::

    blender --background --python scripts/build_distance_lod_review_blender.py

The accepted natural master, its derived three-class review, the accepted
regular overview, and both generated P3DM corpora are read-only inputs.  This
script refuses to replace an existing output unless ``--force`` is explicit.
"""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.distance_lod import (  # noqa: E402
    FAR_RING,
    MODEL_HALF_EXTENT_M,
    NEAR_RING,
    OBJECT_SCALE_Q8_8,
    START_CELL,
    axial_distance,
)
from pingo_terrain.hex_terrain import (  # noqa: E402
    HEX_TERRAIN_Y_COUNT,
    HexCell,
    disk_offsets,
    hex_center_m,
)
from pingo_terrain.materials import (  # noqa: E402
    AGON_SOLID_TERRAIN_MATERIALS,
    BERKELEY_TERRAIN_MATERIALS,
)
from pingo_terrain.p3dm import P3DMTile, parse_container  # noqa: E402


DISTANCE_ROOT = ROOT / "build/p3dm/bay-area-distance-lod-control"
DISTANCE_PLAN = DISTANCE_ROOT / "DISTANCE.json"
NATURAL_ROOT = ROOT / "build/p3dm/bay-area-natural-full-l0"
NATURAL_WORLD = NATURAL_ROOT / "WORLD.json"
NATURAL_MASTER = ROOT / "build/visualization/bay-area-natural-post-partition.blend"
NATURAL_RUNTIME_REVIEW = (
    ROOT / "build/visualization/bay-area-natural-three-class-runtime-review.blend"
)
REGULAR_OVERVIEW = ROOT / "build/visualization/bay-area-hex-overview.blend"
DEFAULT_OUTPUT = (
    ROOT
    / "build/visualization/bay-area-marina-r5-r30-hybrid-lod-review.blend"
)

RECEIPT_SCHEMA = "pingo-terrain-marina-r5-r30-hybrid-lod-review-v1"
DISPLAY_SCALE = 0.001
RUNTIME_METRES_PER_PINGO_UNIT = 8.0
CAMERA_POSITION_COUNTS = (4_275, 8_000, 466)
CAMERA_PITCH = -1_820
CAMERA_YAW = 8_192
PINGO_TURN = 32_768
PINGO_VERTICAL_FOV_RADIANS = 0.6
PINGO_NEAR_UNITS = 1
PINGO_FAR_UNITS = 65_535
EXPECTED_NATURAL_BLEND_SHA256 = (
    "fd4dde2a9f366797808ef9bd395f0966386a8286aeca87b0c73c9ed4f1f64d02"
)
EXPECTED_NATURAL_TOPOLOGY_SHA256 = (
    "c7695f333e25812909fd2667614cb7213fee9de864dda417167181af128e5cca"
)
EXPECTED_REGULAR_BLEND_SHA256 = (
    "3cc3d95e1b41655594eb1002ad6de61a3bac7d102a964f6f3e1c9983150f12ea"
)
EXPECTED_NATURAL_REVIEW_SCHEMA = "pingo-terrain-natural-three-class-review-v1"
PALETTE_INDEX_BY_CLASS = (20, 7, 21)
RGB_BY_CLASS = ((0, 85, 255), (170, 170, 170), (0, 170, 85))


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance-plan", type=Path, default=DISTANCE_PLAN)
    parser.add_argument("--natural-world", type=Path, default=NATURAL_WORLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_file(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"{description} is missing: {resolved}")
    return resolved


def _load_json(path: Path, description: str) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"{description} is unreadable: {path}") from error
    if not isinstance(document, dict):
        raise SystemExit(f"{description} root must be a JSON object")
    return document


def _binary32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _runtime_position_metres(
    raw: tuple[int, int, int],
    translation_counts: tuple[int, int, int],
    scale_q8_8: int,
) -> tuple[float, float, float]:
    """Reproduce Pingo's binary32 local-scale plus command-52 placement."""

    position_factor = _binary32(1.0 / 32_767.0)
    translation_factor = _binary32(256.0 / 32_767.0)
    scale = _binary32(
        _binary32(float(scale_q8_8)) * _binary32(1.0 / 256.0)
    )
    result: list[float] = []
    for position_word, translation_count in zip(
        raw, translation_counts, strict=True
    ):
        position = _binary32(
            _binary32(float(position_word)) * position_factor
        )
        translation = _binary32(
            _binary32(float(translation_count)) * translation_factor
        )
        world = _binary32(_binary32(position * scale) + translation)
        result.append(world * RUNTIME_METRES_PER_PINGO_UNIT)
    return result[0], result[1], result[2]


def _blender_position(
    raw: tuple[int, int, int],
    translation_counts: tuple[int, int, int],
    scale_q8_8: int,
) -> tuple[float, float, float]:
    pingo_x, pingo_y, pingo_z = _runtime_position_metres(
        raw, translation_counts, scale_q8_8
    )
    return (
        -pingo_z * DISPLAY_SCALE,
        pingo_x * DISPLAY_SCALE,
        pingo_y * DISPLAY_SCALE,
    )


def runtime_class(material_id: int) -> int:
    if material_id == 0:
        return 0
    if 1 <= material_id <= 4:
        return 1
    if 5 <= material_id < len(BERKELEY_TERRAIN_MATERIALS):
        return 2
    raise ValueError(f"terrain material ID is outside 0..14: {material_id}")


def _make_materials(bpy) -> tuple:
    materials = []
    names = ("water", "developed", "other land")
    for class_id, (name, rgb, palette) in enumerate(
        zip(names, RGB_BY_CLASS, PALETTE_INDEX_BY_CLASS, strict=True)
    ):
        material = bpy.data.materials.new(
            f"Runtime {name} — Agon palette {palette}"
        )
        color = tuple(channel / 255.0 for channel in rgb) + (1.0,)
        material.diffuse_color = color
        material.use_nodes = True
        shader = material.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = 0.88
        material["runtime_class"] = class_id
        material["agon_palette_index"] = palette
        material["runtime_rgb8"] = list(rgb)
        material["exact_native_agon_base"] = True
        materials.append(material)
    return tuple(materials)


def _compact_faces(
    tile: P3DMTile,
    start_triangle: int,
    triangle_count: int,
) -> tuple[tuple[int, ...], tuple[tuple[int, int, int], ...], tuple[int, ...]]:
    start = start_triangle * 3
    stop = (start_triangle + triangle_count) * 3
    raw_indices = tile.position_indices[start:stop]
    if len(raw_indices) != triangle_count * 3:
        raise ValueError("P3DM triangle range exceeds the decoded index stream")
    used = tuple(sorted(set(raw_indices)))
    local = {source: index for index, source in enumerate(used)}
    faces = tuple(
        tuple(local[index] for index in raw_indices[offset : offset + 3])
        for offset in range(0, len(raw_indices), 3)
    )
    material_ids = tuple(
        tile.uv_indices[start + offset]
        for offset in range(0, len(raw_indices), 3)
    )
    return used, faces, material_ids


def _make_mesh_object(
    bpy,
    *,
    name: str,
    tile: P3DMTile,
    translation_counts: tuple[int, int, int],
    scale_q8_8: int,
    start_triangle: int,
    triangle_count: int,
    collection,
    materials: Sequence,
    properties: dict[str, object],
):
    used, faces, source_materials = _compact_faces(
        tile, start_triangle, triangle_count
    )
    vertices = tuple(
        _blender_position(tile.positions[index], translation_counts, scale_q8_8)
        for index in used
    )
    mesh = bpy.data.meshes.new(f"{name} mesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.update(calc_edges=True)
    for material in materials:
        mesh.materials.append(material)
    presentation = array("i", (runtime_class(item) for item in source_materials))
    mesh.polygons.foreach_set("material_index", presentation)
    semantic_attribute = mesh.attributes.new(
        name="terrain_material_id", type="INT", domain="FACE"
    )
    semantic_attribute.data.foreach_set("value", array("i", source_materials))
    class_attribute = mesh.attributes.new(
        name="runtime_material_class", type="INT", domain="FACE"
    )
    class_attribute.data.foreach_set("value", presentation)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["runtime_reconstruction"] = (
        "binary32 position/32767 * Q8.8 scale plus command-52 count * 256/32767"
    )
    for key, value in properties.items():
        obj[key] = value
    return obj


def _natural_translation(cell: HexCell) -> tuple[int, int, int]:
    origin_east, origin_north = hex_center_m(*START_CELL)
    center_east, center_north = cell.center_m
    return (
        (center_north - origin_north) * 16,
        HEX_TERRAIN_Y_COUNT,
        -(center_east - origin_east) * 16,
    )


def _verify_palette_contract() -> list[dict[str, object]]:
    mapping = []
    expected = ((0, 85, 255),) + ((170, 170, 170),) * 4 + ((0, 170, 85),) * 10
    actual = tuple(material.rgb for material in AGON_SOLID_TERRAIN_MATERIALS)
    if actual != expected:
        raise SystemExit(f"three-class Agon palette changed: {actual!r}")
    for source, runtime in zip(
        BERKELEY_TERRAIN_MATERIALS,
        AGON_SOLID_TERRAIN_MATERIALS,
        strict=True,
    ):
        class_id = runtime_class(source.material_id)
        mapping.append(
            {
                "material_id": source.material_id,
                "nlcd_category": source.nlcd_category,
                "name": source.name,
                "runtime_class": class_id,
                "agon_palette_index": PALETTE_INDEX_BY_CLASS[class_id],
                "rgb8": list(runtime.rgb),
            }
        )
    return mapping


def _camera(bpy, collection):
    from mathutils import Vector

    x_count, y_count, z_count = CAMERA_POSITION_COUNTS
    location = Vector(
        (
            -z_count / 16.0 * DISPLAY_SCALE,
            x_count / 16.0 * DISPLAY_SCALE,
            y_count / 16.0 * DISPLAY_SCALE,
        )
    )
    pitch = CAMERA_PITCH * 2.0 * math.pi / PINGO_TURN
    direction = Vector((0.0, -math.cos(pitch), math.sin(pitch)))
    data = bpy.data.cameras.new("Exact Berkeley Marina runtime camera")
    data.sensor_fit = "VERTICAL"
    data.lens = data.sensor_height / (
        2.0 * math.tan(PINGO_VERTICAL_FOV_RADIANS / 2.0)
    )
    data.clip_start = (
        PINGO_NEAR_UNITS * RUNTIME_METRES_PER_PINGO_UNIT * DISPLAY_SCALE
    )
    data.clip_end = (
        PINGO_FAR_UNITS * RUNTIME_METRES_PER_PINGO_UNIT * DISPLAY_SCALE
    )
    camera = bpy.data.objects.new("CAMERA — Marina 500m south/down", data)
    collection.objects.link(camera)
    camera.location = location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera["origin_cell"] = list(START_CELL)
    camera["position_counts"] = list(CAMERA_POSITION_COUNTS)
    camera["position_utm_m"] = [560_354.875, 4_191_369.1875, 500.0]
    camera["pingo_pitch"] = CAMERA_PITCH
    camera["pingo_yaw"] = CAMERA_YAW
    camera["vertical_fov_radians"] = PINGO_VERTICAL_FOV_RADIANS
    camera["projection_near_units"] = PINGO_NEAR_UNITS
    camera["projection_far_units"] = PINGO_FAR_UNITS
    return camera


def _hash_witness(path: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build(bpy, args: argparse.Namespace) -> dict:
    distance_plan_path = _require_file(args.distance_plan, "distance-LOD plan")
    natural_world_path = _require_file(args.natural_world, "natural WORLD index")
    output = args.output.expanduser().resolve()
    preview = output.with_suffix(".png")
    receipt_path = output.with_suffix(".review.json")
    existing = tuple(path for path in (output, preview, receipt_path) if path.exists())
    if existing and not args.force:
        raise SystemExit(
            "refusing to replace existing review output: "
            + ", ".join(map(str, existing))
        )

    for source in (NATURAL_MASTER, NATURAL_RUNTIME_REVIEW, REGULAR_OVERVIEW):
        _require_file(source, "review source")
    if sha256_file(NATURAL_MASTER) != EXPECTED_NATURAL_BLEND_SHA256:
        raise SystemExit("accepted natural master hash changed")
    if sha256_file(REGULAR_OVERVIEW) != EXPECTED_REGULAR_BLEND_SHA256:
        raise SystemExit("accepted regular overview hash changed")
    natural_review_receipt = _load_json(
        NATURAL_RUNTIME_REVIEW.with_suffix(".json"),
        "natural three-class review receipt",
    )
    if (
        natural_review_receipt.get("schema") != EXPECTED_NATURAL_REVIEW_SCHEMA
        or natural_review_receipt.get("source", {}).get(
            "topology_and_ownership_sha256"
        )
        != EXPECTED_NATURAL_TOPOLOGY_SHA256
    ):
        raise SystemExit("natural three-class review contract changed")

    distance = _load_json(distance_plan_path, "distance-LOD plan")
    natural = _load_json(natural_world_path, "natural WORLD index")
    if distance.get("schema") != "pingo-terrain-distance-lod-control-v1":
        raise SystemExit("distance-LOD plan schema changed")
    if tuple(distance.get("origin_cell", ())) != START_CELL:
        raise SystemExit("distance-LOD origin changed")
    if distance.get("source", {}).get("sha256") != EXPECTED_REGULAR_BLEND_SHA256:
        raise SystemExit("distance-LOD source identity changed")
    natural_source = natural.get("source", {})
    if (
        natural.get("schema") != "pingo-terrain-natural-corpus-v2"
        or natural_source.get("blend_sha256") != EXPECTED_NATURAL_BLEND_SHA256
        or natural_source.get("topology_and_ownership_sha256")
        != EXPECTED_NATURAL_TOPOLOGY_SHA256
    ):
        raise SystemExit("natural runtime corpus identity changed")

    mapping = _verify_palette_contract()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    master = bpy.data.collections.new("MARINA R5/R30 HYBRID LOD REVIEW")
    near_collection = bpy.data.collections.new("LOD0 — natural rings 0..5")
    middle_collection = bpy.data.collections.new("LOD1 — regular rings 6..15")
    far_collection = bpy.data.collections.new("LOD2 — regular rings 16..30")
    skirt_collection = bpy.data.collections.new(
        "FAIL-SOFT — distance chunk skirts (toggle for honest surface)"
    )
    camera_collection = bpy.data.collections.new("CAMERAS")
    scene.collection.children.link(master)
    for collection in (
        near_collection,
        middle_collection,
        far_collection,
        skirt_collection,
        camera_collection,
    ):
        master.children.link(collection)
    materials = _make_materials(bpy)

    natural_records = {
        (record["q"], record["r"]): record for record in natural["records"]
    }
    selected_cells = tuple(
        HexCell(START_CELL[0] + dq, START_CELL[1] + dr)
        for dq, dr in disk_offsets(NEAR_RING)
    )
    near_triangles = 0
    near_vertices = 0
    for cell in selected_cells:
        record = natural_records.get((cell.q, cell.r))
        if record is None:
            raise SystemExit(f"natural WORLD omits near cell {cell.q},{cell.r}")
        path = NATURAL_ROOT / record["path"]
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise SystemExit(f"natural P3DM hash changed: {path}")
        tile = parse_container(payload)
        triangles = len(tile.position_indices) // 3
        if triangles != record["surface_triangles"] or record["skirt_triangles"]:
            raise SystemExit(f"natural near record shape changed: {path}")
        _make_mesh_object(
            bpy,
            name=f"NAT L0 q{cell.q:+04d} r{cell.r:+04d}",
            tile=tile,
            translation_counts=_natural_translation(cell),
            scale_q8_8=natural["normalization"]["object_scale_q8_8"],
            start_triangle=0,
            triangle_count=triangles,
            collection=near_collection,
            materials=materials,
            properties={
                "tier": 0,
                "logical_ring": axial_distance(cell.q, cell.r),
                "cell_id": cell.cell_id,
                "q": cell.q,
                "r": cell.r,
                "p3dm_path": record["path"],
                "p3dm_sha256": record["sha256"],
            },
        )
        near_triangles += triangles
        near_vertices += len(tile.positions)

    coarse_surface_triangles = 0
    coarse_skirt_triangles = 0
    coarse_vertices = 0
    selected_coarse_cells: set[tuple[int, int]] = set()
    tier_chunks = {1: 0, 2: 0}
    for record in distance["records"]:
        ordinal = int(record["ordinal"])
        path = DISTANCE_ROOT / record["path"]
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise SystemExit(f"distance P3DM hash changed: {path}")
        tile = parse_container(payload)
        surface = int(record["surface_triangles"])
        skirts = int(record["skirt_triangles"])
        if len(tile.position_indices) // 3 != surface + skirts:
            raise SystemExit(f"distance P3DM shape changed: {path}")
        tier = int(record["tier"])
        if tier not in (1, 2) or tile.meta.lod != tier:
            raise SystemExit(f"distance tier changed: {path}")
        tier_collection = middle_collection if tier == 1 else far_collection
        translation = tuple(int(value) for value in record["translation_counts"])
        common = {
            "tier": tier,
            "chunk_ordinal": ordinal,
            "bucket_q": int(record["bucket_q"]),
            "bucket_r": int(record["bucket_r"]),
            "source_cells_json": json.dumps(record["cells"], separators=(",", ":")),
            "p3dm_path": record["path"],
            "p3dm_sha256": record["sha256"],
        }
        _make_mesh_object(
            bpy,
            name=f"DST L{tier} chunk {ordinal:03d} surface",
            tile=tile,
            translation_counts=translation,  # type: ignore[arg-type]
            scale_q8_8=OBJECT_SCALE_Q8_8,
            start_triangle=0,
            triangle_count=surface,
            collection=tier_collection,
            materials=materials,
            properties={**common, "surface": True, "fail_soft_skirt": False},
        )
        if skirts:
            _make_mesh_object(
                bpy,
                name=f"DST L{tier} chunk {ordinal:03d} skirt",
                tile=tile,
                translation_counts=translation,  # type: ignore[arg-type]
                scale_q8_8=OBJECT_SCALE_Q8_8,
                start_triangle=surface,
                triangle_count=skirts,
                collection=skirt_collection,
                materials=materials,
                properties={**common, "surface": False, "fail_soft_skirt": True},
            )
        for q, r in record["cells"]:
            cell = (int(q), int(r))
            if cell in selected_coarse_cells:
                raise SystemExit(f"distance cell is repeated: {cell}")
            distance_from_origin = axial_distance(*cell)
            expected_tier = 1 if distance_from_origin <= 15 else 2
            if not NEAR_RING < distance_from_origin <= FAR_RING or tier != expected_tier:
                raise SystemExit(f"distance cell has wrong tier/ring: {cell}")
            selected_coarse_cells.add(cell)
        coarse_surface_triangles += surface
        coarse_skirt_triangles += skirts
        coarse_vertices += len(tile.positions)
        tier_chunks[tier] += 1

    expected_coarse_cells = (
        1 + 3 * FAR_RING * (FAR_RING + 1)
        - (1 + 3 * NEAR_RING * (NEAR_RING + 1))
    )
    geometry_witness = (
        len(selected_cells),
        near_triangles,
        len(selected_coarse_cells),
        coarse_surface_triangles,
        coarse_skirt_triangles,
        len(distance["records"]),
    )
    expected_geometry = (91, 968, expected_coarse_cells, 16_200, 7_624, 92)
    if geometry_witness != expected_geometry:
        raise SystemExit(
            f"hybrid review geometry changed: {geometry_witness} != {expected_geometry}"
        )

    camera = _camera(bpy, camera_collection)
    scene.camera = camera
    world = bpy.data.worlds.new("Marina hybrid LOD daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.055,
        0.075,
        0.11,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55
    scene.world = world
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(preview)
    scene.render.film_transparent = False
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.background_type = "WORLD"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0 / DISPLAY_SCALE

    hazards = [
        "natural ring-five ownership follows irregular physical master edges while the coarse ring begins on ideal logical hex cells; the mixed-tier join is intentionally nonconforming",
        "six-triangle coarse boundary profiles are not the fine natural boundary polylines and may expose T-junctions, gaps, overlaps, or abrupt normal changes",
        "1,792 m independently normalized distance chunks quantize common source vertices separately; decoded chunk seams are not the accepted exact same-LOD seam construction",
        "distance chunk skirts are fail-soft coverage only and do not prove a mathematical mixed-LOD seam",
        "the 65,535-unit far plane greatly exceeds the roughly 17 km ring-30 corpus and reduces depth separation",
        "coarse face normals and illumination may expose the tier boundary despite identical three-color base materials",
    ]
    scene_metadata = {
        "schema": RECEIPT_SCHEMA,
        "artifact_role": "decoded runtime-faithful static visual review; not mixed-LOD acceptance",
        "origin": {
            "cell": list(START_CELL),
            "center_utm_m": list(hex_center_m(*START_CELL)),
        },
        "camera": {
            "position_counts": list(CAMERA_POSITION_COUNTS),
            "position_utm_m": [560_354.875, 4_191_369.1875, 500.0],
            "pitch": CAMERA_PITCH,
            "yaw": CAMERA_YAW,
            "vertical_fov_radians": PINGO_VERTICAL_FOV_RADIANS,
            "projection_units": [PINGO_NEAR_UNITS, PINGO_FAR_UNITS],
        },
        "geometry": {
            "near_cells": len(selected_cells),
            "near_component_vertices": near_vertices,
            "near_surface_triangles": near_triangles,
            "coarse_cells": len(selected_coarse_cells),
            "coarse_chunks": len(distance["records"]),
            "middle_chunks": tier_chunks[1],
            "far_chunks": tier_chunks[2],
            "coarse_component_vertices_including_skirt_vertices": coarse_vertices,
            "coarse_surface_triangles": coarse_surface_triangles,
            "coarse_skirt_triangles": coarse_skirt_triangles,
            "combined_surface_triangles": near_triangles + coarse_surface_triangles,
            "combined_runtime_triangles": (
                near_triangles + coarse_surface_triangles + coarse_skirt_triangles
            ),
            "distance_model_half_extent_m": MODEL_HALF_EXTENT_M,
            "distance_object_scale_q8_8": OBJECT_SCALE_Q8_8,
        },
        "presentation": {
            "display_scale": DISPLAY_SCALE,
            "materials": mapping,
            "distance_skirts_separate_collection": True,
            "distance_skirts_visible_in_preview": True,
        },
        "runtime_reconstruction": {
            "binary32_model": True,
            "pingo_axes": "x=north, y=up, z=west",
            "metres_per_pingo_unit": RUNTIME_METRES_PER_PINGO_UNIT,
            "formula": "float32(raw/32767 * scale_q8_8/256 + translation_count*256/32767) * 8m",
        },
        "hazards": hazards,
    }
    scene["artifact_schema"] = RECEIPT_SCHEMA
    scene["artifact_role"] = scene_metadata["artifact_role"]
    scene["origin_q"] = START_CELL[0]
    scene["origin_r"] = START_CELL[1]
    scene["near_cells"] = len(selected_cells)
    scene["coarse_cells"] = len(selected_coarse_cells)
    scene["coarse_chunks"] = len(distance["records"])
    scene["surface_triangles"] = near_triangles + coarse_surface_triangles
    scene["skirt_triangles"] = coarse_skirt_triangles
    scene["review_metadata_json"] = json.dumps(
        scene_metadata, sort_keys=True, separators=(",", ":")
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(output), check_existing=False, compress=True
    )
    bpy.ops.render.render(write_still=True)
    receipt = {
        **scene_metadata,
        "sources": {
            "distance_plan": _hash_witness(distance_plan_path),
            "natural_world": _hash_witness(natural_world_path),
            "natural_master": _hash_witness(NATURAL_MASTER),
            "natural_three_class_review": _hash_witness(NATURAL_RUNTIME_REVIEW),
            "regular_overview": _hash_witness(REGULAR_OVERVIEW),
        },
        "outputs": {
            "blend": _hash_witness(output),
            "preview": _hash_witness(preview),
        },
        "inputs": {
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "materials_py_sha256": sha256_file(
                ROOT / "src/pingo_terrain/materials.py"
            ),
            "distance_lod_py_sha256": sha256_file(
                ROOT / "src/pingo_terrain/distance_lod.py"
            ),
            "blender_version": bpy.app.version_string,
        },
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    try:
        import bpy
    except ImportError as error:  # pragma: no cover - Blender owns this path
        raise SystemExit("run this review builder through Blender") from error
    receipt = build(bpy, args)
    geometry = receipt["geometry"]
    print(
        "DISTANCE_LOD_REVIEW",
        f"near_cells={geometry['near_cells']}",
        f"coarse_cells={geometry['coarse_cells']}",
        f"chunks={geometry['coarse_chunks']}",
        f"surface_triangles={geometry['combined_surface_triangles']}",
        f"skirt_triangles={geometry['coarse_skirt_triangles']}",
        f"output={receipt['outputs']['blend']['path']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
