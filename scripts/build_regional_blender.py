#!/usr/bin/env python3
"""Build the required full-corpus Blender review scene for Bay Area terrain.

Run this script through Blender so its bundled ``bpy`` module is available::

    blender --background --python scripts/build_regional_blender.py -- \
      --output build/visualization/bay-area-hex-overview.blend

The scene is deliberately a review LOD, not a runtime terrain payload.  It
uses one centre vertex and six triangular faces per canonical streaming cell,
which preserves the complete cell extent and identity while keeping the whole
50,183-cell region responsive enough for interactive inspection.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_MANIFEST = PROJECT_ROOT / "data/manifests/bay-area-2026-08-02.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "build/visualization/bay-area-hex-overview.blend"
)
DEFAULT_DISPLAY_SCALE = 0.001
DEFAULT_VERTICAL_EXAGGERATION = 1.0
DEM_DATASET_ID = "usgs-3dep-10m-utm10n"
NLCD_DATASET_ID = "usgs-annual-nlcd-2025-epsg5070"
ARTIFACT_SCHEMA = "pingo-terrain-blender-review-v1"
PREVIEW_LOD_NAME = "one-centre-six-triangle-per-cell"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pingo_terrain.geotiff import sha256_file  # noqa: E402
from pingo_terrain.hex_terrain import (  # noqa: E402
    HEX_AREA_M2,
    HEX_BASIS_Q_EAST_M,
    HEX_BASIS_Q_NORTH_M,
    HEX_BASIS_R_EAST_M,
    HEX_BASIS_R_NORTH_M,
    HEX_CELL_COUNT,
    HEX_ORIGIN_EAST_M,
    HEX_ORIGIN_NORTH_M,
    HEX_SIDE_M,
    HEX_SIDE_STEPS,
    LATTICE_V_NORTH_M,
    HexCell,
    iter_cells,
)
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS  # noqa: E402
from pingo_terrain.regional_raster import RasterMosaic  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_EPSG,
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    WORLD_COLUMNS,
    WORLD_ROWS,
)


# Clockwise/counter-clockwise ambiguity is removed by spelling these in
# positive-Z Blender winding: east, northeast, northwest, west, southwest,
# southeast.  They are the N=5 boundary corners of the canonical lattice.
HEX_CORNER_OFFSETS_M: tuple[tuple[int, int], ...] = (
    (HEX_SIDE_M, 0),
    (HEX_SIDE_M // 2, HEX_SIDE_STEPS * LATTICE_V_NORTH_M),
    (-HEX_SIDE_M // 2, HEX_SIDE_STEPS * LATTICE_V_NORTH_M),
    (-HEX_SIDE_M, 0),
    (-HEX_SIDE_M // 2, -HEX_SIDE_STEPS * LATTICE_V_NORTH_M),
    (HEX_SIDE_M // 2, -HEX_SIDE_STEPS * LATTICE_V_NORTH_M),
)

NLCD_TO_MATERIAL = {
    material.nlcd_category: material.material_id
    for material in BERKELEY_TERRAIN_MATERIALS
}
WATER_CATEGORY = 11
UNKNOWN_LAND_CATEGORY = 24


@dataclass(slots=True)
class PreviewTopology:
    """One deterministic, deduplicated mesh for the complete review corpus."""

    cells: tuple[HexCell, ...]
    points_m: list[tuple[int, int]]
    faces: list[tuple[int, int, int]]
    face_cell_ids: array
    face_q: array
    face_r: array
    face_sectors: array
    boundary_edges: frozenset[tuple[int, int]]


@dataclass(slots=True)
class PreviewSamples:
    elevations_m: list[float]
    face_categories: array
    face_material_ids: array
    edge_padded_elevation_points: int
    edge_padded_material_faces: int
    nodata_material_faces: int
    fallback_material_faces: int


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=SOURCE_MANIFEST,
        help=f"pinned regional source manifest (default: {SOURCE_MANIFEST})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Blender output (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--display-scale",
        type=float,
        default=DEFAULT_DISPLAY_SCALE,
        help="Blender units per source metre (default: 0.001, or 1:1000)",
    )
    parser.add_argument(
        "--vertical-exaggeration",
        type=float,
        default=DEFAULT_VERTICAL_EXAGGERATION,
        help="vertical-only review multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--skip-source-hash",
        action="store_true",
        help="skip source checksums for an explicitly nondurable development build",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="report exact preview topology without loading rasters or Blender",
    )
    parser.add_argument(
        "--render-preview",
        action="store_true",
        help="also render a Workbench PNG beside the .blend",
    )
    if argv is None:
        argv = (
            sys.argv[sys.argv.index("--") + 1 :]
            if "--" in sys.argv
            else sys.argv[1:]
        )
    arguments = parser.parse_args(argv)
    if arguments.display_scale <= 0.0:
        parser.error("--display-scale must be positive")
    if arguments.vertical_exaggeration <= 0.0:
        parser.error("--vertical-exaggeration must be positive")
    return arguments


def _corners(center: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    return tuple(
        (center[0] + offset[0], center[1] + offset[1])
        for offset in HEX_CORNER_OFFSETS_M
    )


def build_preview_topology(
    cells: Iterable[HexCell] | None = None,
) -> PreviewTopology:
    """Build a shared-vertex N=1 preview without changing runtime topology."""

    selected = tuple(iter_cells() if cells is None else cells)
    point_keys: set[tuple[int, int]] = set()
    for cell in selected:
        point_keys.add(cell.center_m)
        point_keys.update(_corners(cell.center_m))

    # Raster locality is materially better when a full-region point set is
    # ordered south-to-north, then west-to-east.  The order is also stable.
    points_m = sorted(point_keys, key=lambda point: (point[1], point[0]))
    point_indices = {point: index for index, point in enumerate(points_m)}
    faces: list[tuple[int, int, int]] = []
    face_cell_ids = array("i")
    face_q = array("i")
    face_r = array("i")
    face_sectors = array("i")
    boundary_edges: set[tuple[int, int]] = set()

    for cell in selected:
        center_index = point_indices[cell.center_m]
        corners = _corners(cell.center_m)
        corner_indices = tuple(point_indices[point] for point in corners)
        for sector in range(6):
            following = (sector + 1) % 6
            faces.append(
                (center_index, corner_indices[sector], corner_indices[following])
            )
            face_cell_ids.append(cell.cell_id)
            face_q.append(cell.q)
            face_r.append(cell.r)
            face_sectors.append(sector)
            edge = tuple(
                sorted((corner_indices[sector], corner_indices[following]))
            )
            boundary_edges.add(edge)

    return PreviewTopology(
        cells=selected,
        points_m=points_m,
        faces=faces,
        face_cell_ids=face_cell_ids,
        face_q=face_q,
        face_r=face_r,
        face_sectors=face_sectors,
        boundary_edges=frozenset(boundary_edges),
    )


def topology_summary(topology: PreviewTopology) -> dict:
    eastings = [point[0] for point in topology.points_m]
    northings = [point[1] for point in topology.points_m]
    cell_ids = [cell.cell_id for cell in topology.cells]
    return {
        "artifact_schema": ARTIFACT_SCHEMA,
        "artifact_role": "full-corpus Blender review; not a runtime payload",
        "preview_lod": PREVIEW_LOD_NAME,
        "hex_cells": len(topology.cells),
        "cell_id_min": min(cell_ids) if cell_ids else None,
        "cell_id_max": max(cell_ids) if cell_ids else None,
        "vertices": len(topology.points_m),
        "faces": len(topology.faces),
        "hex_boundary_edges": len(topology.boundary_edges),
        "boundary_policy": "six straight plan-view sides per cell; no sawtooth approximation",
        "projected_bounds_m": (
            [min(eastings), min(northings), max(eastings), max(northings)]
            if eastings
            else None
        ),
    }


def verify_sources(root: Path, manifest: dict) -> None:
    """Fail closed on all pinned regional source sizes and hashes."""

    for dataset in manifest["datasets"]:
        for item in dataset["tiles"]:
            path = root / item["local_path"]
            actual_size = path.stat().st_size
            if actual_size != item["byte_size"]:
                raise ValueError(
                    f"source size changed for {path}: {actual_size}, "
                    f"expected {item['byte_size']}"
                )
            if sha256_file(path) != item["sha256"]:
                raise ValueError(f"source SHA-256 changed for {path}")


def project_utm10_to_albers(
    points: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Transform one bounded batch through the pinned system PROJ tool."""

    selected = tuple(points)
    if not selected:
        return []
    source = "".join(f"{east:.6f} {north:.6f}\n" for east, north in selected)
    completed = subprocess.run(
        ["cs2cs", "-f", "%.6f", "EPSG:32610", "EPSG:5070"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    projected: list[tuple[float, float]] = []
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] == "*" or fields[1] == "*":
            raise ValueError(f"cs2cs rejected preview coordinate: {line}")
        projected.append((float(fields[0]), float(fields[1])))
    if len(projected) != len(selected):
        raise RuntimeError(
            f"cs2cs returned {len(projected)} points for {len(selected)} inputs"
        )
    return projected


def sample_preview(
    topology: PreviewTopology,
    dem: RasterMosaic,
    nlcd: RasterMosaic,
) -> PreviewSamples:
    """Sample vertex heights and representative flat face materials."""

    elevations_m: list[float] = []
    edge_padded_elevation_points = 0
    for index, (east, north) in enumerate(topology.points_m, start=1):
        sample = dem.sample_bilinear(east, north)
        if sample.value is None:
            raise ValueError(f"DEM nodata at preview vertex E {east}, N {north}")
        elevations_m.append(float(sample.value))
        edge_padded_elevation_points += int(sample.edge_padded)
        if index % 25_000 == 0 or index == len(topology.points_m):
            print(
                f"REGIONAL_BLENDER_ELEVATION points={index}/{len(topology.points_m)}",
                flush=True,
            )

    centroids = (
        (
            sum(topology.points_m[index][0] for index in face) / 3.0,
            sum(topology.points_m[index][1] for index in face) / 3.0,
        )
        for face in topology.faces
    )
    projected_centroids = project_utm10_to_albers(centroids)
    face_categories = array("i")
    face_material_ids = array("i")
    edge_padded_material_faces = 0
    nodata_material_faces = 0
    fallback_material_faces = 0
    for face_index, ((east, north), face) in enumerate(
        zip(projected_centroids, topology.faces, strict=True), start=1
    ):
        sample = nlcd.sample_nearest(east, north, clamp=True)
        edge_padded_material_faces += int(sample.edge_padded)
        nodata_material_faces += int(sample.nodata)
        category = None if sample.value is None else int(sample.value)
        if category not in NLCD_TO_MATERIAL:
            average_elevation = sum(elevations_m[index] for index in face) / 3.0
            category = (
                WATER_CATEGORY
                if average_elevation <= 3.0
                else UNKNOWN_LAND_CATEGORY
            )
            fallback_material_faces += 1
        face_categories.append(category)
        face_material_ids.append(NLCD_TO_MATERIAL[category])
        if face_index % 50_000 == 0 or face_index == len(topology.faces):
            print(
                f"REGIONAL_BLENDER_MATERIAL faces={face_index}/{len(topology.faces)}",
                flush=True,
            )

    return PreviewSamples(
        elevations_m=elevations_m,
        face_categories=face_categories,
        face_material_ids=face_material_ids,
        edge_padded_elevation_points=edge_padded_elevation_points,
        edge_padded_material_faces=edge_padded_material_faces,
        nodata_material_faces=nodata_material_faces,
        fallback_material_faces=fallback_material_faces,
    )


def _add_int_attribute(mesh, name: str, domain: str, values: array) -> None:
    attribute = mesh.attributes.new(name=name, type="INT", domain=domain)
    attribute.data.foreach_set("value", values)


def build_blender_scene(
    arguments: argparse.Namespace,
    topology: PreviewTopology,
    samples: PreviewSamples,
    *,
    source_manifest_path: Path,
    source_manifest: dict,
    source_manifest_sha256: str,
) -> dict:
    """Populate and save the Blender scene; imported lazily for host tests."""

    try:
        import bpy
        from mathutils import Vector
    except ImportError as error:  # pragma: no cover - exercised by Blender
        raise SystemExit("run this build through Blender so bpy is available") from error

    bpy.ops.wm.read_factory_settings(use_empty=True)
    center_east = REGIONAL_ORIGIN_EAST_M + WORLD_COLUMNS * 512 / 2.0
    center_north = REGIONAL_ORIGIN_NORTH_M + WORLD_ROWS * 512 / 2.0
    vertices = [
        (
            (east - center_east) * arguments.display_scale,
            (north - center_north) * arguments.display_scale,
            elevation
            * arguments.display_scale
            * arguments.vertical_exaggeration,
        )
        for (east, north), elevation in zip(
            topology.points_m, samples.elevations_m, strict=True
        )
    ]

    mesh = bpy.data.meshes.new("Bay Area hex terrain review LOD")
    mesh.from_pydata(vertices, (), topology.faces)
    mesh.update(calc_edges=True)
    terrain = bpy.data.objects.new("Bay Area — complete hex terrain corpus", mesh)
    bpy.context.collection.objects.link(terrain)

    for material_spec in BERKELEY_TERRAIN_MATERIALS:
        red, green, blue = material_spec.rgb
        material = bpy.data.materials.new(
            f"Terrain {material_spec.material_id:02d} — "
            f"NLCD {material_spec.nlcd_category}: {material_spec.name}"
        )
        color = (red / 255.0, green / 255.0, blue / 255.0, 1.0)
        material.diffuse_color = color
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = 0.88
        material["terrain_material_id"] = material_spec.material_id
        material["nlcd_category"] = material_spec.nlcd_category
        material["source_rgb8"] = list(material_spec.rgb)
        mesh.materials.append(material)
    mesh.polygons.foreach_set("material_index", samples.face_material_ids)

    _add_int_attribute(mesh, "hex_cell_id", "FACE", topology.face_cell_ids)
    _add_int_attribute(mesh, "hex_q", "FACE", topology.face_q)
    _add_int_attribute(mesh, "hex_r", "FACE", topology.face_r)
    _add_int_attribute(mesh, "hex_preview_sector", "FACE", topology.face_sectors)
    _add_int_attribute(mesh, "terrain_material_id", "FACE", samples.face_material_ids)
    _add_int_attribute(mesh, "nlcd_category", "FACE", samples.face_categories)
    _add_int_attribute(
        mesh,
        "utm_easting_m",
        "POINT",
        array("i", (point[0] for point in topology.points_m)),
    )
    _add_int_attribute(
        mesh,
        "utm_northing_m",
        "POINT",
        array("i", (point[1] for point in topology.points_m)),
    )
    elevation_attribute = mesh.attributes.new(
        name="elevation_navd88_m", type="FLOAT", domain="POINT"
    )
    elevation_attribute.data.foreach_set("value", samples.elevations_m)
    boundary_flags = array(
        "b",
        (
            int(tuple(sorted(edge.vertices)) in topology.boundary_edges)
            for edge in mesh.edges
        ),
    )
    boundary_attribute = mesh.attributes.new(
        name="hex_cell_boundary", type="BOOLEAN", domain="EDGE"
    )
    boundary_attribute.data.foreach_set("value", boundary_flags)

    terrain["artifact_role"] = "complete regional review mesh; not runtime data"
    terrain["preview_lod"] = PREVIEW_LOD_NAME
    terrain["face_identity"] = "hex_cell_id, hex_q, hex_r, hex_preview_sector"
    terrain["point_provenance"] = (
        "utm_easting_m, utm_northing_m, elevation_navd88_m"
    )
    terrain["edge_identity"] = "hex_cell_boundary"
    terrain["flat_shading"] = True

    sun_data = bpy.data.lights.new("Regional review sun", type="SUN")
    sun_data.energy = 2.5
    sun_data.angle = math.radians(12.0)
    sun = bpy.data.objects.new("Regional review sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.location = Vector((-80.0, -95.0, 95.0))
    sun.rotation_euler = (
        Vector((0.0, 0.0, 0.0)) - sun.location
    ).to_track_quat("-Z", "Y").to_euler()

    world = bpy.data.worlds.new("Bay Area review daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.055,
        0.075,
        0.11,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55

    camera_data = bpy.data.cameras.new("Full Bay Area overview camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 185.0
    camera_data.clip_end = 1_000.0
    camera = bpy.data.objects.new("Full Bay Area overview camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = Vector((0.0, -155.0, 175.0))
    camera.rotation_euler = (
        Vector((0.0, 0.0, 0.25)) - camera.location
    ).to_track_quat("-Z", "Y").to_euler()

    scene = bpy.context.scene
    scene.camera = camera
    scene.world = world
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(arguments.output.with_suffix(".png"))
    scene.display.shading.light = "STUDIO"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.color_type = "MATERIAL"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0 / arguments.display_scale

    summary = topology_summary(topology)
    material_histogram = Counter(samples.face_material_ids)
    category_histogram = Counter(samples.face_categories)
    source_label = (
        source_manifest_path.relative_to(PROJECT_ROOT).as_posix()
        if source_manifest_path.is_relative_to(PROJECT_ROOT)
        else str(source_manifest_path)
    )
    build_script_sha256 = sha256_file(Path(__file__))
    hex_module_sha256 = sha256_file(
        PROJECT_ROOT / "src/pingo_terrain/hex_terrain.py"
    )
    scene_metadata = {
        **summary,
        "region_id": source_manifest["region_id"],
        "source_manifest": source_label,
        "source_manifest_sha256": source_manifest_sha256,
        "source_datasets": [
            {
                "id": dataset["id"],
                "crs": dataset["crs"],
                "tiles": len(dataset["tiles"]),
            }
            for dataset in source_manifest["datasets"]
        ],
        "source_elevation": DEM_DATASET_ID,
        "source_landcover": NLCD_DATASET_ID,
        "source_vertical_datum": next(
            dataset["vertical_datum"]
            for dataset in source_manifest["datasets"]
            if dataset["id"] == DEM_DATASET_ID
        ),
        "projected_crs": f"EPSG:{REGIONAL_EPSG}",
        "hex_profile": {
            "origin_center_east_m": HEX_ORIGIN_EAST_M,
            "origin_center_north_m": HEX_ORIGIN_NORTH_M,
            "basis_q_m": [HEX_BASIS_Q_EAST_M, HEX_BASIS_Q_NORTH_M],
            "basis_r_m": [HEX_BASIS_R_EAST_M, HEX_BASIS_R_NORTH_M],
            "side_m": HEX_SIDE_M,
            "area_m2": HEX_AREA_M2,
            "cell_id_range": [0, HEX_CELL_COUNT - 1],
            "boundary_policy": "six straight plan-view sides; runtime subdivisions remain collinear",
        },
        "preview_sampling": {
            "topology": PREVIEW_LOD_NAME,
            "runtime_topology": "canonical N=5 triangular lattice; not embedded",
            "elevation": "bilinear 3DEP sample at every preview vertex",
            "material": "nearest NLCD category at each preview-face centroid",
            "flat_shaded": True,
            "edge_padded_elevation_points": samples.edge_padded_elevation_points,
            "edge_padded_material_faces": samples.edge_padded_material_faces,
            "nodata_material_faces": samples.nodata_material_faces,
            "fallback_material_faces": samples.fallback_material_faces,
        },
        "minimum_elevation_navd88_m": min(samples.elevations_m),
        "maximum_elevation_navd88_m": max(samples.elevations_m),
        "material_face_histogram": {
            str(key): material_histogram[key] for key in sorted(material_histogram)
        },
        "nlcd_face_histogram": {
            str(key): category_histogram[key] for key in sorted(category_histogram)
        },
        "display_scale": arguments.display_scale,
        "vertical_exaggeration": arguments.vertical_exaggeration,
        "display_origin_utm_m": [center_east, center_north, 0.0],
        "build_script_sha256": build_script_sha256,
        "hex_module_sha256": hex_module_sha256,
        "material_vocabulary": [
            {
                "material_id": material.material_id,
                "nlcd_category": material.nlcd_category,
                "name": material.name,
                "rgb": list(material.rgb),
            }
            for material in BERKELEY_TERRAIN_MATERIALS
        ],
    }
    scene["artifact_schema"] = ARTIFACT_SCHEMA
    scene["artifact_role"] = scene_metadata["artifact_role"]
    scene["region_id"] = scene_metadata["region_id"]
    scene["source_manifest"] = source_label
    scene["source_manifest_sha256"] = source_manifest_sha256
    scene["projected_crs"] = scene_metadata["projected_crs"]
    scene["hex_cells"] = summary["hex_cells"]
    scene["cell_id_min"] = summary["cell_id_min"]
    scene["cell_id_max"] = summary["cell_id_max"]
    scene["preview_vertices"] = summary["vertices"]
    scene["preview_faces"] = summary["faces"]
    scene["preview_lod"] = PREVIEW_LOD_NAME
    scene["display_scale"] = arguments.display_scale
    scene["vertical_exaggeration"] = arguments.vertical_exaggeration
    scene["build_script_sha256"] = build_script_sha256
    scene["hex_module_sha256"] = hex_module_sha256
    scene["review_metadata_json"] = json.dumps(
        scene_metadata, sort_keys=True, separators=(",", ":")
    )

    if bpy.context.screen is not None:
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
                area.spaces.active.shading.type = "SOLID"
                area.spaces.active.shading.color_type = "MATERIAL"

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(arguments.output), check_existing=False, compress=True
    )
    if arguments.render_preview:
        bpy.ops.render.render(write_still=True)
    return scene_metadata


def write_receipt(output: Path, metadata: dict) -> Path:
    receipt = output.with_suffix(".review.json")
    payload = {
        **metadata,
        "blend": {
            "path": str(output),
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
        },
    }
    receipt.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    topology = build_preview_topology()
    summary = topology_summary(topology)
    print("REGIONAL_BLENDER_PLAN", json.dumps(summary, sort_keys=True), flush=True)
    if arguments.plan_only:
        return 0

    source_manifest_path = arguments.source_manifest.expanduser().resolve()
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = json.loads(source_manifest_bytes)
    if not arguments.skip_source_hash:
        verify_sources(PROJECT_ROOT, source_manifest)
    datasets = {dataset["id"]: dataset for dataset in source_manifest["datasets"]}
    dem = RasterMosaic(PROJECT_ROOT, datasets[DEM_DATASET_ID])
    nlcd = RasterMosaic(
        PROJECT_ROOT, datasets[NLCD_DATASET_ID], cache_blocks_per_tile=12
    )
    samples = sample_preview(topology, dem, nlcd)
    metadata = build_blender_scene(
        arguments,
        topology,
        samples,
        source_manifest_path=source_manifest_path,
        source_manifest=source_manifest,
        source_manifest_sha256=hashlib.sha256(source_manifest_bytes).hexdigest(),
    )
    receipt = write_receipt(arguments.output, metadata)
    print(
        "REGIONAL_BLENDER",
        f"cells={len(topology.cells)}",
        f"vertices={len(topology.points_m)}",
        f"faces={len(topology.faces)}",
        f"elevation={min(samples.elevations_m):.3f}.."
        f"{max(samples.elevations_m):.3f}m_NAVD88",
        f"display_scale={arguments.display_scale:g}",
        f"output={arguments.output}",
        f"receipt={receipt}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
