#!/usr/bin/env python3
"""Build a quick shaded Blender view from the acquired Berkeley 3DEP DEM."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import subprocess
import sys
from collections import Counter

import bpy
from mathutils import Vector


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pingo_terrain.tiff_dem import read_float32_dem  # noqa: E402
from pingo_terrain.tiff_category import read_category_raster  # noqa: E402
from pingo_terrain.materials import NLCD_MATERIALS  # noqa: E402


DEFAULT_INPUT = (
    PROJECT_ROOT
    / "data/downloads/berkeley-ca/usgs-3dep-10m-utm10n.tif"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "build/visualization/berkeley-terrain.blend"
TRIANGULAR_OUTPUT = (
    PROJECT_ROOT / "build/visualization/berkeley-terrain-triangular.blend"
)
DEFAULT_LANDCOVER = (
    PROJECT_ROOT
    / "data/downloads/berkeley-ca/usgs-annual-nlcd-2025-epsg5070.tif"
)

def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-step", type=int, default=4)
    parser.add_argument("--display-scale", type=float, default=0.01)
    parser.add_argument("--landcover", type=Path, default=DEFAULT_LANDCOVER)
    parser.add_argument(
        "--topology",
        choices=("relief-grid", "triangular-lattice"),
        default="relief-grid",
    )
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(args)


def sampled_axis(length: int, step: int) -> list[int]:
    samples = list(range(0, length, step))
    if samples[-1] != length - 1:
        samples.append(length - 1)
    return samples


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def bilinear_elevation(dem, source_x: float, source_y: float, fallback: float) -> float:
    x0 = max(0, min(dem.width - 1, math.floor(source_x)))
    y0 = max(0, min(dem.height - 1, math.floor(source_y)))
    x1 = min(dem.width - 1, x0 + 1)
    y1 = min(dem.height - 1, y0 + 1)
    tx = source_x - x0
    ty = source_y - y0
    samples = (
        dem.value(x0, y0),
        dem.value(x1, y0),
        dem.value(x0, y1),
        dem.value(x1, y1),
    )
    if any(not math.isfinite(value) or value == dem.nodata for value in samples):
        return fallback
    north = samples[0] * (1.0 - tx) + samples[1] * tx
    south = samples[2] * (1.0 - tx) + samples[3] * tx
    return north * (1.0 - ty) + south * ty


def project_utm10_to_albers(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    source = "".join(f"{x:.3f} {y:.3f}\n" for x, y in points)
    result = subprocess.run(
        ["cs2cs", "EPSG:32610", "EPSG:5070"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    projected = []
    for line in result.stdout.splitlines():
        fields = line.split()
        projected.append((float(fields[0]), float(fields[1])))
    if len(projected) != len(points):
        raise RuntimeError("cs2cs returned the wrong number of projected points")
    return projected


def predominant_category(raster, triangle) -> int:
    pixels: list[int] = []
    columns = [int((x - raster.origin_x) / raster.pixel_size_x) for x, _ in triangle]
    rows = [int((raster.origin_y - y) / raster.pixel_size_y) for _, y in triangle]

    def inside(px: float, py: float) -> bool:
        (ax, ay), (bx, by), (cx, cy) = triangle
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denominator) < 1e-9:
            return False
        a = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
        b = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
        c = 1.0 - a - b
        return min(a, b, c) >= -1e-9

    for row in range(max(0, min(rows) - 1), min(raster.height, max(rows) + 2)):
        y = raster.origin_y - (row + 0.5) * raster.pixel_size_y
        for column in range(max(0, min(columns) - 1), min(raster.width, max(columns) + 2)):
            x = raster.origin_x + (column + 0.5) * raster.pixel_size_x
            if inside(x, y):
                pixels.append(raster.values[row * raster.width + column])
    if not pixels:
        x = sum(point[0] for point in triangle) / 3.0
        y = sum(point[1] for point in triangle) / 3.0
        return raster.value_at_projected(x, y) or 0
    counts = Counter(pixels)
    largest = max(counts.values())
    return min(category for category, count in counts.items() if count == largest)


def build_material(
    minimum: float, maximum: float, display_scale: float
) -> bpy.types.Material:
    material = bpy.data.materials.new("Berkeley elevation and relief")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    geometry = nodes.new("ShaderNodeNewGeometry")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeValToRGB")

    relief = maximum - minimum
    water_position = max(0.0, min(1.0, (0.0 - minimum) / relief))
    color_ramp = ramp.color_ramp
    color_ramp.interpolation = "CONSTANT"
    elements = color_ramp.elements
    elements.remove(elements[1])
    elements[0].position = 0.0
    elements[0].color = (0.015, 0.055, 0.16, 1.0)
    stops = (
        (min(1.0, water_position + 0.002), (0.055, 0.18, 0.055, 1.0)),
        (0.12, (0.10, 0.28, 0.07, 1.0)),
        (0.35, (0.22, 0.38, 0.10, 1.0)),
        (0.62, (0.40, 0.34, 0.14, 1.0)),
        (0.82, (0.50, 0.39, 0.22, 1.0)),
        (1.0, (0.68, 0.62, 0.48, 1.0)),
    )
    for position, color in stops:
        element = elements.new(max(position, elements[-1].position + 0.0001))
        element.color = color

    links.new(geometry.outputs["Position"], separate.inputs["Vector"])
    links.new(separate.outputs["Z"], ramp.inputs["Fac"])
    ramp.inputs["Fac"].default_value = 0.0
    links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    shader.inputs["Roughness"].default_value = 0.82

    # Map the shifted terrain Z range into the ColorRamp's 0..1 input.
    map_range = nodes.new("ShaderNodeMapRange")
    map_range.inputs["From Min"].default_value = -relief * display_scale / 2.0
    map_range.inputs["From Max"].default_value = relief * display_scale / 2.0
    map_range.inputs["To Min"].default_value = 0.0
    map_range.inputs["To Max"].default_value = 1.0
    links.remove(separate.outputs["Z"].links[0])
    links.new(separate.outputs["Z"], map_range.inputs["Value"])
    links.new(map_range.outputs["Result"], ramp.inputs["Fac"])
    return material


def main() -> None:
    args = arguments()
    if args.topology == "triangular-lattice" and args.output == DEFAULT_OUTPUT:
        args.output = TRIANGULAR_OUTPUT
    if args.sample_step < 1:
        raise SystemExit("--sample-step must be positive")
    if args.display_scale <= 0.0:
        raise SystemExit("--display-scale must be positive")
    dem = read_float32_dem(args.input)
    if dem.pixel_size_x is None or dem.pixel_size_y is None:
        raise SystemExit("DEM has no GeoTIFF pixel scale")

    if dem.origin_x is None or dem.origin_y is None:
        raise SystemExit("DEM has no GeoTIFF model tiepoint")
    landcover = read_category_raster(args.landcover)
    valid = [
        value
        for value in dem.values
        if math.isfinite(value) and value != dem.nodata
    ]
    minimum = min(valid)
    maximum = max(valid)
    elevation_midpoint = (minimum + maximum) / 2.0
    half_width = (dem.width - 1) * dem.pixel_size_x / 2.0
    half_height = (dem.height - 1) * dem.pixel_size_y / 2.0

    vertices: list[tuple[float, float, float]] = []
    projected_sources: list[tuple[float, float]] = []
    sampled_elevations: list[float] = []
    faces: list[tuple[int, int, int, int]] = []
    if args.topology == "relief-grid":
        xs = sampled_axis(dem.width, args.sample_step)
        ys = sampled_axis(dem.height, args.sample_step)
        sample_points = [(float(x), float(y)) for y in ys for x in xs]
        columns = len(xs)
        rows = len(ys)
        lattice_spacing_m = args.sample_step * dem.pixel_size_x
        perimeter_margin_m = 0.0
    else:
        control_spacing_m = args.sample_step * dem.pixel_size_x
        lattice_spacing_m = control_spacing_m * math.sqrt(2.0 / math.sqrt(3.0))
        row_spacing_m = lattice_spacing_m * math.sqrt(3.0) / 2.0
        width_m = (dem.width - 1) * dem.pixel_size_x
        height_m = (dem.height - 1) * dem.pixel_size_y
        columns = math.floor((width_m - lattice_spacing_m / 2.0) / lattice_spacing_m) + 1
        rows = math.floor(height_m / row_spacing_m) + 1
        used_width_m = (columns - 0.5) * lattice_spacing_m
        used_height_m = (rows - 1) * row_spacing_m
        west_margin_m = (width_m - used_width_m) / 2.0
        north_margin_m = (height_m - used_height_m) / 2.0
        perimeter_margin_m = max(west_margin_m, north_margin_m)
        sample_points = []
        for row in range(rows):
            offset_m = lattice_spacing_m / 2.0 if row & 1 else 0.0
            source_y = (north_margin_m + row * row_spacing_m) / dem.pixel_size_y
            for column in range(columns):
                source_x = (
                    west_margin_m + offset_m + column * lattice_spacing_m
                ) / dem.pixel_size_x
                sample_points.append((source_x, source_y))

    for source_x, source_y in sample_points:
        value = bilinear_elevation(dem, source_x, source_y, minimum)
        easting = source_x * dem.pixel_size_x - half_width
        northing = half_height - source_y * dem.pixel_size_y
        sampled_elevations.append(value)
        projected_sources.append(
            (
                dem.origin_x + (source_x + 0.5) * dem.pixel_size_x,
                dem.origin_y - (source_y + 0.5) * dem.pixel_size_y,
            )
        )
        vertices.append(
            (
                easting * args.display_scale,
                northing * args.display_scale,
                (value - elevation_midpoint) * args.display_scale,
            )
        )

    for row in range(rows - 1):
        for column in range(columns - 1):
            northwest = row * columns + column
            northeast = northwest + 1
            southwest = northwest + columns
            southeast = southwest + 1
            if args.topology == "relief-grid":
                # Pick the shorter 3D diagonal. Equal-relief ties alternate to
                # avoid a systematic directional bias while remaining stable.
                nw_se = abs(
                    sampled_elevations[northwest]
                    - sampled_elevations[southeast]
                )
                ne_sw = abs(
                    sampled_elevations[northeast]
                    - sampled_elevations[southwest]
                )
                if nw_se < ne_sw or (
                    nw_se == ne_sw and (row + column) % 2 == 0
                ):
                    faces.extend(
                        (
                            (northwest, southwest, southeast),
                            (northwest, southeast, northeast),
                        )
                    )
                else:
                    faces.extend(
                        (
                            (northwest, southwest, northeast),
                            (northeast, southwest, southeast),
                        )
                    )
            elif row & 1:
                faces.extend(
                    (
                        (northwest, southwest, southeast),
                        (northwest, southeast, northeast),
                    )
                )
            else:
                faces.extend(
                    (
                        (northwest, southwest, northeast),
                        (northeast, southwest, southeast),
                    )
                )

    albers_vertices = project_utm10_to_albers(projected_sources)
    categories = [
        predominant_category(landcover, [albers_vertices[index] for index in face])
        for face in faces
    ]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new(f"Berkeley 3DEP terrain — {args.topology}")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    terrain = bpy.data.objects.new(
        f"Berkeley terrain — {args.topology} — 1:100 display scale", mesh
    )
    bpy.context.collection.objects.link(terrain)
    used_categories = sorted(set(categories))
    material_slot = {}
    for slot, category in enumerate(used_categories):
        name, (red, green, blue) = NLCD_MATERIALS.get(
            category, NLCD_MATERIALS[0]
        )
        material = bpy.data.materials.new(f"NLCD {category}: {name}")
        material.diffuse_color = (red / 255.0, green / 255.0, blue / 255.0, 1.0)
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = material.diffuse_color
        shader.inputs["Roughness"].default_value = 0.82
        terrain.data.materials.append(material)
        material_slot[category] = slot
    for polygon, category in zip(mesh.polygons, categories, strict=True):
        polygon.material_index = material_slot[category]
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    sun_data = bpy.data.lights.new("Northwest sun", type="SUN")
    sun_data.energy = 3.0
    sun_data.angle = math.radians(18.0)
    sun = bpy.data.objects.new("Northwest sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(28), 0.0, math.radians(-35))

    world = bpy.data.worlds.new("Berkeley daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.055,
        0.075,
        0.11,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5
    bpy.context.scene.world = world

    camera_data = bpy.data.cameras.new("Berkeley overview camera")
    camera = bpy.data.objects.new("Berkeley overview camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = Vector((-76.0, -82.0, 64.0))
    camera_data.lens = 52.0
    look_at(camera, Vector((6.0, 3.0, 0.0)))
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(args.output.with_suffix(".png"))
    scene.display.shading.light = "STUDIO"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.color_type = "MATERIAL"

    scene["source_dem"] = str(args.input)
    scene["source_width"] = dem.width
    scene["source_height"] = dem.height
    scene["sample_step"] = args.sample_step
    scene["mesh_columns"] = columns
    scene["mesh_rows"] = rows
    scene["topology"] = args.topology
    scene["horizontal_lattice_spacing_m"] = lattice_spacing_m
    scene["maximum_perimeter_margin_m"] = perimeter_margin_m
    scene["minimum_elevation_navd88_m"] = minimum
    scene["maximum_elevation_navd88_m"] = maximum
    scene["vertical_exaggeration"] = 1.0
    scene["display_scale"] = args.display_scale
    scene["display_origin"] = "terrain bounding-box center"
    scene["triangulation"] = (
        "shorter 3D diagonal; parity tie-break"
        if args.topology == "relief-grid"
        else "regular triangular lattice; alternating half-row offset"
    )
    scene["landcover"] = str(args.landcover)
    scene["face_color"] = "predominant NLCD class mapped to restrained natural RGB"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print(
        "BERKELEY_TERRAIN",
        f"source={dem.width}x{dem.height}",
        f"mesh={columns}x{rows}",
        f"topology={args.topology}",
        f"vertices={len(vertices)}",
        f"faces={len(faces)}",
        f"spacing={lattice_spacing_m:.3f}m",
        f"perimeter_margin<={perimeter_margin_m:.3f}m",
        f"nlcd_classes={len(set(categories))}",
        f"elevation={minimum:.3f}..{maximum:.3f}m_NAVD88",
        f"display_scale={args.display_scale:g}",
        f"output={args.output}",
    )


if __name__ == "__main__":
    main()
