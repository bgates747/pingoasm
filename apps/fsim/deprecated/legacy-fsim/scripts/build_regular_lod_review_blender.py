#!/usr/bin/env python3
"""Build the mandatory decoded review of the full regular N=1 hierarchy.

The four complete hierarchy levels are decoded from their actual P3DM files,
not regenerated from Blender or GIS.  Each level has a separate full-region
surface and skirt collection.  The default overview shows L8; L4/L2/L1 and
all full-corpus skirts are toggleable.

A second, initially hidden witness collection reconstructs the exact Marina
runtime policy: N=5 L0 through ring five and the algorithmically selected
L8/L4/L2/L1 leaves outside it.  Witness skirts are separate but visible in
the Marina render so cracks are not silently hidden from review.
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
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import (  # noqa: E402
    HEX_TERRAIN_Y_COUNT,
    HexCell,
    disk_offsets,
    hex_center_m,
)
from pingo_terrain.p3dm import P3DMTile, parse_container  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
)
from pingo_terrain.regular_lod import (  # noqa: E402
    HIERARCHY_LEVELS,
    NEAR_RING_MAX,
    select_hierarchy_nodes,
    terrain_class,
)


CORPUS = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
WORLD = CORPUS / "WORLD.json"
N5_CORPUS = ROOT / "build/p3dm/bay-area-hex-full-l0"
N5_WORLD = N5_CORPUS / "WORLD.json"
DEFAULT_OUTPUT = (
    ROOT / "build/visualization/bay-area-full-regular-n1-hierarchy-review.blend"
)
CORPUS_SCHEMA = "pingo-terrain-regular-n1-hierarchy-v1"
RECEIPT_SCHEMA = "pingo-terrain-regular-n1-hierarchy-review-v1"
CORPUS_WORLD_SHA256 = (
    "382e7c7e9ec46ddb4d57bd51db706e441a37e52b7538d2af1b384fa9a053c04e"
)
N5_WORLD_SHA256 = (
    "43a41bced05f35eaf104e48c906b59e28f4b0ac254ec60fa2b35166b0e707a26"
)
MARINA_CELL = (80, 125)
MARINA_CAMERA_COUNTS = (4_275, 8_000, 466)
MARINA_PITCH = -1_820
MARINA_YAW = 8_192
PINGO_TURN = 32_768
VERTICAL_FOV_RADIANS = 0.6
NEAR_UNITS = 1
FAR_UNITS = 65_535
METRES_PER_PINGO_UNIT = 8.0
DISPLAY_SCALE = 0.001
PALETTE_INDEX_BY_CLASS = (20, 7, 21)
RGB_BY_CLASS = ((0, 85, 255), (170, 170, 170), (0, 170, 85))


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, description: str) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"{description} is unreadable: {path}") from error
    if not isinstance(document, dict):
        raise SystemExit(f"{description} root is not an object")
    return document


def _binary32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _runtime_metres(
    raw: tuple[int, int, int],
    translation_counts: tuple[int, int, int],
    scale_q8_8: int,
) -> tuple[float, float, float]:
    """Reproduce Pingo binary32 scale and command-52 translation."""

    position_factor = _binary32(1.0 / 32_767.0)
    translation_factor = _binary32(256.0 / 32_767.0)
    scale = _binary32(
        _binary32(float(scale_q8_8)) * _binary32(1.0 / 256.0)
    )
    result = []
    for word, translation in zip(raw, translation_counts, strict=True):
        position = _binary32(_binary32(float(word)) * position_factor)
        offset = _binary32(_binary32(float(translation)) * translation_factor)
        world = _binary32(_binary32(position * scale) + offset)
        result.append(world * METRES_PER_PINGO_UNIT)
    return result[0], result[1], result[2]


def _blender_vertex(
    raw: tuple[int, int, int],
    translation_counts: tuple[int, int, int],
    scale_q8_8: int,
) -> tuple[float, float, float]:
    pingo_x, pingo_y, pingo_z = _runtime_metres(
        raw, translation_counts, scale_q8_8
    )
    return (
        -pingo_z * DISPLAY_SCALE,
        pingo_x * DISPLAY_SCALE,
        pingo_y * DISPLAY_SCALE,
    )


def _translation_counts(center_east_m: int, center_north_m: int) -> tuple[int, int, int]:
    origin_east_m, origin_north_m = hex_center_m(*MARINA_CELL)
    return (
        round((center_north_m - origin_north_m) * 16),
        HEX_TERRAIN_Y_COUNT,
        round(-(center_east_m - origin_east_m) * 16),
    )


def _materials(bpy) -> tuple:
    result = []
    for class_id, (name, palette, rgb) in enumerate(
        zip(
            ("water", "developed", "other land"),
            PALETTE_INDEX_BY_CLASS,
            RGB_BY_CLASS,
            strict=True,
        )
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
        result.append(material)
    return tuple(result)


def _part(
    tile: P3DMTile,
    start_triangle: int,
    triangle_count: int,
    translation: tuple[int, int, int],
    scale_q8_8: int,
):
    start = start_triangle * 3
    stop = (start_triangle + triangle_count) * 3
    indices = tile.position_indices[start:stop]
    used = tuple(sorted(set(indices)))
    local = {source: index for index, source in enumerate(used)}
    vertices = tuple(
        _blender_vertex(tile.positions[index], translation, scale_q8_8)
        for index in used
    )
    faces = tuple(
        tuple(local[index] for index in indices[offset : offset + 3])
        for offset in range(0, len(indices), 3)
    )
    semantic = tuple(
        int(tile.uv_indices[start + offset])
        for offset in range(0, len(indices), 3)
    )
    classes = tuple(terrain_class(material) for material in semantic)
    return vertices, faces, semantic, classes


class MeshAccumulator:
    def __init__(self) -> None:
        self.vertices: list[tuple[float, float, float]] = []
        self.faces: list[tuple[int, int, int]] = []
        self.semantic = array("i")
        self.classes = array("i")
        self.ordinals = array("i")

    def append(
        self,
        vertices,
        faces,
        semantic,
        classes,
        ordinal: int,
    ) -> None:
        base = len(self.vertices)
        self.vertices.extend(vertices)
        self.faces.extend(
            tuple(base + index for index in face) for face in faces
        )
        self.semantic.extend(semantic)
        self.classes.extend(classes)
        self.ordinals.extend((ordinal,) * len(faces))


def _mesh_object(bpy, name: str, accumulator: MeshAccumulator, collection, materials):
    mesh = bpy.data.meshes.new(f"{name} mesh")
    mesh.from_pydata(accumulator.vertices, (), accumulator.faces)
    mesh.update(calc_edges=True)
    for material in materials:
        mesh.materials.append(material)
    mesh.polygons.foreach_set("material_index", accumulator.classes)
    for attribute_name, values in (
        ("terrain_material_id", accumulator.semantic),
        ("runtime_material_class", accumulator.classes),
        ("hierarchy_record_ordinal", accumulator.ordinals),
    ):
        attribute = mesh.attributes.new(
            name=attribute_name, type="INT", domain="FACE"
        )
        attribute.data.foreach_set("value", values)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["flat_shaded"] = True
    return obj


def _decode_record(
    corpus: Path,
    record: dict,
    *,
    verify_hash: bool = True,
) -> P3DMTile:
    path = corpus / record["path"]
    payload = path.read_bytes()
    if verify_hash and (
        len(payload) != record["bytes"]
        or hashlib.sha256(payload).hexdigest() != record["sha256"]
    ):
        raise SystemExit(f"hierarchy record hash changed: {path}")
    tile = parse_container(payload)
    if (
        tile.meta.lod,
        tile.meta.tile_x,
        tile.meta.tile_y,
        tile.meta.model_half_extent_m,
    ) != (
        record["lod"],
        record["anchor_q"],
        record["anchor_offset_row"],
        record["model_half_extent_m"],
    ):
        raise SystemExit(f"hierarchy descriptor changed: {path}")
    return tile


def _full_layers(bpy, corpus: Path, world: dict, master, materials):
    surfaces_root = bpy.data.collections.new("FULL REGION — decoded N1 surfaces")
    skirts_root = bpy.data.collections.new("FULL REGION — fail-soft node skirts")
    master.children.link(surfaces_root)
    master.children.link(skirts_root)
    records_by_level = {level.name: [] for level in HIERARCHY_LEVELS}
    for record in world["records"]:
        records_by_level[record["level"]].append(record)
    results = {}
    for level_index, level in enumerate(HIERARCHY_LEVELS):
        surface_collection = bpy.data.collections.new(
            f"{level.name} — complete surface"
        )
        skirt_collection = bpy.data.collections.new(
            f"{level.name} — complete skirts"
        )
        surfaces_root.children.link(surface_collection)
        skirts_root.children.link(skirt_collection)
        surface = MeshAccumulator()
        skirts = MeshAccumulator()
        for completed, record in enumerate(records_by_level[level.name], 1):
            tile = _decode_record(corpus, record)
            translation = _translation_counts(*record["center_utm_m"])
            scale = record["object_scale_q8_8"]
            surface_part = _part(
                tile, 0, record["surface_triangles"], translation, scale
            )
            surface.append(*surface_part, record["ordinal"])
            skirt_part = _part(
                tile,
                record["surface_triangles"],
                record["skirt_triangles"],
                translation,
                scale,
            )
            skirts.append(*skirt_part, record["ordinal"])
            if completed % 5_000 == 0 or completed == len(records_by_level[level.name]):
                print(
                    f"REGULAR_REVIEW_DECODE level={level.name} "
                    f"records={completed}/{len(records_by_level[level.name])}",
                    flush=True,
                )
        surface_object = _mesh_object(
            bpy,
            f"{level.name} FULL SURFACE — decoded runtime records",
            surface,
            surface_collection,
            materials,
        )
        skirt_object = _mesh_object(
            bpy,
            f"{level.name} FULL SKIRTS — fail-soft only",
            skirts,
            skirt_collection,
            materials,
        )
        surface_object["level"] = level.name
        surface_object["lod"] = level.lod
        surface_object["model_half_extent_m"] = level.model_half_extent_m
        skirt_object["fail_soft_only"] = True
        visible = level_index == 0
        surface_collection.hide_viewport = not visible
        surface_collection.hide_render = not visible
        skirt_collection.hide_viewport = True
        skirt_collection.hide_render = True
        results[level.name] = {
            "surface_object": surface_object,
            "skirt_object": skirt_object,
            "surface_collection": surface_collection,
            "skirt_collection": skirt_collection,
            "records": len(records_by_level[level.name]),
            "surface_vertices": len(surface.vertices),
            "surface_triangles": len(surface.faces),
            "skirt_vertices": len(skirts.vertices),
            "skirt_triangles": len(skirts.faces),
        }
    return surfaces_root, skirts_root, results


def _n5_near_records() -> tuple[dict, dict[tuple[int, int], dict]]:
    if sha256_file(N5_WORLD) != N5_WORLD_SHA256:
        raise SystemExit("accepted N=5 WORLD hash changed")
    world = _load_json(N5_WORLD, "accepted N=5 WORLD")
    records = {(item["q"], item["r"]): item for item in world["records"]}
    return world, records


def _witness(bpy, corpus: Path, world: dict, master, materials):
    witness = bpy.data.collections.new(
        "MARINA ACTIVE PROFILE — N5 ring5 plus N1 hierarchy ring30"
    )
    surfaces = bpy.data.collections.new("MARINA — active surfaces")
    skirts = bpy.data.collections.new("MARINA — active fail-soft skirts")
    master.children.link(witness)
    witness.children.link(surfaces)
    witness.children.link(skirts)
    n5_surface = MeshAccumulator()
    n5_skirts = MeshAccumulator()
    _n5_world, n5_records = _n5_near_records()
    near_cells = tuple(
        HexCell(MARINA_CELL[0] + dq, MARINA_CELL[1] + dr)
        for dq, dr in disk_offsets(NEAR_RING_MAX)
    )
    for ordinal, cell in enumerate(near_cells):
        record = n5_records[(cell.q, cell.r)]
        path = N5_CORPUS / record["path"]
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise SystemExit(f"N=5 witness hash changed: {path}")
        tile = parse_container(payload)
        center = (
            tile.meta.center_east_m + REGIONAL_ORIGIN_EAST_M,
            tile.meta.center_north_m + REGIONAL_ORIGIN_NORTH_M,
        )
        translation = _translation_counts(*center)
        scale = 32_768
        n5_surface.append(
            *_part(tile, 0, record["surface_triangles"], translation, scale),
            ordinal,
        )
        n5_skirts.append(
            *_part(
                tile,
                record["surface_triangles"],
                record["skirt_triangles"],
                translation,
                scale,
            ),
            ordinal,
        )
    _mesh_object(
        bpy,
        "MARINA N5 L0 SURFACE — rings 0..5",
        n5_surface,
        surfaces,
        materials,
    )
    n5_skirt_object = _mesh_object(
        bpy,
        "MARINA N5 L0 SKIRTS — fail-soft",
        n5_skirts,
        skirts,
        materials,
    )
    n5_skirt_object["fail_soft_only"] = True

    records = {
        (item["lod"], item["anchor_q"], item["anchor_offset_row"]): item
        for item in world["records"]
    }
    plan = select_hierarchy_nodes(*MARINA_CELL, NEAR_RING_MAX)
    hierarchy_surface = {level.name: MeshAccumulator() for level in HIERARCHY_LEVELS}
    hierarchy_skirts = {level.name: MeshAccumulator() for level in HIERARCHY_LEVELS}
    plan_counts = {level.name: 0 for level in HIERARCHY_LEVELS}
    for ordinal, node in enumerate(plan):
        record = records[node.identity]
        tile = _decode_record(corpus, record, verify_hash=False)
        translation = _translation_counts(*record["center_utm_m"])
        scale = record["object_scale_q8_8"]
        hierarchy_surface[node.level.name].append(
            *_part(tile, 0, record["surface_triangles"], translation, scale),
            ordinal,
        )
        hierarchy_skirts[node.level.name].append(
            *_part(
                tile,
                record["surface_triangles"],
                record["skirt_triangles"],
                translation,
                scale,
            ),
            ordinal,
        )
        plan_counts[node.level.name] += 1
    for level in HIERARCHY_LEVELS:
        if not plan_counts[level.name]:
            continue
        _mesh_object(
            bpy,
            f"MARINA {level.name} ACTIVE SURFACES",
            hierarchy_surface[level.name],
            surfaces,
            materials,
        )
        skirt_object = _mesh_object(
            bpy,
            f"MARINA {level.name} ACTIVE SKIRTS — fail-soft",
            hierarchy_skirts[level.name],
            skirts,
            materials,
        )
        skirt_object["fail_soft_only"] = True
    witness.hide_viewport = True
    witness.hide_render = True
    return witness, surfaces, skirts, {
        "origin_cell": list(MARINA_CELL),
        "fine_cells": len(near_cells),
        "coarse_nodes": len(plan),
        "total_objects": len(near_cells) + len(plan),
        "level_counts": plan_counts,
        "fine_surface_triangles": len(n5_surface.faces),
        "fine_skirt_triangles": len(n5_skirts.faces),
        "coarse_surface_triangles": sum(
            len(item.faces) for item in hierarchy_surface.values()
        ),
        "coarse_skirt_triangles": sum(
            len(item.faces) for item in hierarchy_skirts.values()
        ),
    }


def _overview_camera(bpy, collection, bounds):
    from mathutils import Vector

    minimum, maximum = bounds
    center = (minimum + maximum) * 0.5
    span = max(maximum.x - minimum.x, maximum.y - minimum.y)
    data = bpy.data.cameras.new("Full Bay Area hierarchy overview camera")
    data.type = "ORTHO"
    data.ortho_scale = span * 1.18
    data.clip_end = 1_000.0
    camera = bpy.data.objects.new("CAMERA — full hierarchy overview", data)
    collection.objects.link(camera)
    camera.location = Vector((center.x, center.y - span * 0.75, span * 0.95))
    target = Vector((center.x, center.y, center.z))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    return camera


def _marina_camera(bpy, collection):
    from mathutils import Vector

    x_count, y_count, z_count = MARINA_CAMERA_COUNTS
    location = Vector(
        (
            -z_count / 16.0 * DISPLAY_SCALE,
            x_count / 16.0 * DISPLAY_SCALE,
            y_count / 16.0 * DISPLAY_SCALE,
        )
    )
    pitch = MARINA_PITCH * 2.0 * math.pi / PINGO_TURN
    direction = Vector((0.0, -math.cos(pitch), math.sin(pitch)))
    data = bpy.data.cameras.new("Exact Marina runtime camera")
    data.sensor_fit = "VERTICAL"
    data.lens = data.sensor_height / (
        2.0 * math.tan(VERTICAL_FOV_RADIANS / 2.0)
    )
    data.clip_start = NEAR_UNITS * METRES_PER_PINGO_UNIT * DISPLAY_SCALE
    data.clip_end = FAR_UNITS * METRES_PER_PINGO_UNIT * DISPLAY_SCALE
    camera = bpy.data.objects.new("CAMERA — Marina 500m south/down", data)
    collection.objects.link(camera)
    camera.location = location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera["position_counts"] = list(MARINA_CAMERA_COUNTS)
    camera["pitch"] = MARINA_PITCH
    camera["yaw"] = MARINA_YAW
    camera["vertical_fov_radians"] = VERTICAL_FOV_RADIANS
    return camera


def _bounds(obj):
    from mathutils import Vector

    vertices = obj.data.vertices
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    for vertex in vertices:
        coordinate = vertex.co
        minimum.x = min(minimum.x, coordinate.x)
        minimum.y = min(minimum.y, coordinate.y)
        minimum.z = min(minimum.z, coordinate.z)
        maximum.x = max(maximum.x, coordinate.x)
        maximum.y = max(maximum.y, coordinate.y)
        maximum.z = max(maximum.z, coordinate.z)
    return minimum, maximum


def _hash_witness(path: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build(bpy, args: argparse.Namespace) -> dict:
    corpus = args.corpus.expanduser().resolve()
    output = args.output.expanduser().resolve()
    overview_png = output.with_suffix(".png")
    marina_png = output.with_name(output.stem + "-marina.png")
    receipt_path = output.with_suffix(".review.json")
    existing = tuple(
        path
        for path in (output, overview_png, marina_png, receipt_path)
        if path.exists()
    )
    if existing and not args.force:
        raise SystemExit(
            "refusing to replace existing review: " + ", ".join(map(str, existing))
        )
    world_path = corpus / "WORLD.json"
    if sha256_file(world_path) != CORPUS_WORLD_SHA256:
        raise SystemExit("regular hierarchy WORLD hash changed")
    world = _load_json(world_path, "regular hierarchy WORLD")
    if (
        world.get("schema") != CORPUS_SCHEMA
        or world.get("statistics", {}).get("records") != 83_293
        or world.get("statistics", {}).get("container_bytes") != 57_521_020
    ):
        raise SystemExit("regular hierarchy WORLD contract changed")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    master = bpy.data.collections.new("FULL REGULAR N1 HIERARCHY REVIEW")
    camera_collection = bpy.data.collections.new("CAMERAS")
    scene.collection.children.link(master)
    master.children.link(camera_collection)
    materials = _materials(bpy)
    full_surfaces, full_skirts, layer_results = _full_layers(
        bpy, corpus, world, master, materials
    )
    witness, witness_surfaces, witness_skirts, witness_result = _witness(
        bpy, corpus, world, master, materials
    )
    overview = _overview_camera(
        bpy,
        camera_collection,
        _bounds(layer_results["L8"]["surface_object"]),
    )
    marina = _marina_camera(bpy, camera_collection)

    world_data = bpy.data.worlds.new("Regular hierarchy daylight")
    world_data.use_nodes = True
    world_data.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.055,
        0.075,
        0.11,
        1.0,
    )
    world_data.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55
    scene.world = world_data
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.background_type = "WORLD"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0 / DISPLAY_SCALE

    scene.camera = overview
    scene.render.filepath = str(overview_png)
    bpy.ops.render.render(write_still=True)
    full_surfaces.hide_render = True
    full_skirts.hide_render = True
    witness.hide_render = False
    witness_surfaces.hide_render = False
    witness_skirts.hide_render = False
    scene.camera = marina
    scene.render.filepath = str(marina_png)
    bpy.ops.render.render(write_still=True)
    witness.hide_render = True
    full_surfaces.hide_render = False
    layer_results["L8"]["surface_collection"].hide_render = False
    scene.camera = overview

    hazards = [
        "L8 and L4 use independently quantized guarded extents and may expose cross-node seams",
        "the N5/N1 boundary shares encoded endpoints but is topologically nonconforming at four intermediate N5 edge heights",
        "all skirts are fail-soft coverage, not mathematical transition geometry",
        "hierarchy leaves may overfetch only beyond ring 30; the neutral backdrop owns that presentation",
        "complete hierarchy layers are review alternatives and are never simultaneously active at runtime",
    ]
    metadata = {
        "schema": RECEIPT_SCHEMA,
        "artifact_role": (
            "decoded full-corpus hierarchy and exact Marina active-plan visual review"
        ),
        "presentation": {
            "materials": [
                {
                    "runtime_class": class_id,
                    "agon_palette_index": PALETTE_INDEX_BY_CLASS[class_id],
                    "rgb8": list(RGB_BY_CLASS[class_id]),
                }
                for class_id in range(3)
            ],
            "default_visible_full_level": "L8",
            "full_skirts_default_hidden": True,
            "marina_witness_default_hidden": True,
        },
        "full_layers": {
            level: {
                key: value
                for key, value in result.items()
                if isinstance(value, int)
            }
            for level, result in layer_results.items()
        },
        "marina_witness": witness_result,
        "camera": {
            "origin_cell": list(MARINA_CELL),
            "position_counts": list(MARINA_CAMERA_COUNTS),
            "pitch": MARINA_PITCH,
            "yaw": MARINA_YAW,
            "vertical_fov_radians": VERTICAL_FOV_RADIANS,
            "projection_units": [NEAR_UNITS, FAR_UNITS],
        },
        "runtime_reconstruction": {
            "binary32": True,
            "metres_per_pingo_unit": METRES_PER_PINGO_UNIT,
            "reference_origin_cell": list(MARINA_CELL),
            "formula": (
                "float32(raw/32767 * scale_q8_8/256 + "
                "translation_count*256/32767) * 8m"
            ),
        },
        "hazards": hazards,
    }
    scene["artifact_schema"] = RECEIPT_SCHEMA
    scene["artifact_role"] = metadata["artifact_role"]
    scene["hierarchy_records"] = 83_293
    scene["marina_active_objects"] = witness_result["total_objects"]
    scene["review_metadata_json"] = json.dumps(
        metadata, sort_keys=True, separators=(",", ":")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(output), check_existing=False, compress=True
    )
    receipt = {
        **metadata,
        "sources": {
            "hierarchy_world": _hash_witness(world_path),
            "accepted_n5_world": _hash_witness(N5_WORLD),
            "builder": _hash_witness(Path(__file__).resolve()),
        },
        "outputs": {
            "blend": _hash_witness(output),
            "overview_png": _hash_witness(overview_png),
            "marina_png": _hash_witness(marina_png),
        },
        "blender_version": bpy.app.version_string,
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    try:
        import bpy
    except ImportError as error:  # pragma: no cover
        raise SystemExit("run this review builder through Blender") from error
    receipt = build(bpy, args)
    print(
        "REGULAR_HIERARCHY_REVIEW",
        f"records={sum(x['records'] for x in receipt['full_layers'].values())}",
        f"marina_objects={receipt['marina_witness']['total_objects']}",
        f"output={receipt['outputs']['blend']['path']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
