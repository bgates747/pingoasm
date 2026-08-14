#!/usr/bin/env python3
"""Build the seven-cell Lake Anza control/feature-aware Blender comparison.

The control decodes the exact accepted N=5 P3DM cells.  The candidate extracts
Lake Anza from the pinned NLCD raster, smooths that categorical boundary,
overbuilds a radius-two terrain context, constrains both the lake and every
radius-one hex cut in one Delaunay solve, and finally clips/partitions the
result back into seven independently owned cells.  Both objects use the exact
existing Berkeley terrain material vocabulary.

Run through Blender so ``bpy`` and ``mathutils.geometry.delaunay_2d_cdt`` are
available::

    blender --background --python scripts/build_lake_anza_blender.py -- \
      --render-preview
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SOURCE_MANIFEST = ROOT / "data/manifests/bay-area-2026-08-02.json"
CONTROL_CORPUS = ROOT / "build/p3dm/bay-area-hex-full-l0"
DEFAULT_OUTPUT = (
    ROOT / "build/visualization/lake-anza-control-vs-feature-aware.blend"
)
ARTIFACT_SCHEMA = "pingo-terrain-lake-anza-comparison-v1"

# East Bay Regional Park District's Lake Anza point, projected to the pinned
# WGS 84 / UTM zone 10N terrain CRS.  It selects the categorical component;
# the seven-cell disk is centered on that component's source-derived centroid.
# The lake geometry itself comes only from pinned NLCD and 3DEP rasters.
LAKE_ANZA_REFERENCE_UTM = (565_624.8155, 4_194_649.6279)
LAKE_ANZA_CELL = (92, 125)
WATER_CATEGORY = 11
DISPLAY_SCALE = 0.01
DISPLAY_SEPARATION_M = 1_650.0
SMOOTHING_ITERATIONS = 1

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPTS))

import build_regional_blender as regional_blender  # noqa: E402
import build_regional_hex_terrain as hex_builder  # noqa: E402
import build_regional_terrain as rectangular  # noqa: E402

from pingo_terrain.feature_terrain import (  # noqa: E402
    CountPoint,
    cyclic_corner_smooth,
    extract_raster_component,
    point_in_polygon,
    point_on_segment,
    polygon_centroid,
    quantize_loop,
    reconcile_feature_crossings,
    signed_area,
)
from pingo_terrain.geotiff import sha256_file  # noqa: E402
from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HEX_TERRAIN_Y_COUNT,
    HexCell,
    disk_offsets,
    hex_distance,
    hex_topology,
    locate_hex_cell,
)
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS  # noqa: E402
from pingo_terrain.p3dm import parse_container  # noqa: E402
from pingo_terrain.regional_raster import RasterMosaic  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    REGIONAL_VERTICAL_ORIGIN_M,
    predominant_category,
)


NLCD_TO_MATERIAL = {
    material.nlcd_category: material.material_id
    for material in BERKELEY_TERRAIN_MATERIALS
}


@dataclass(slots=True)
class ComparisonMesh:
    """One flat-shaded review mesh in absolute source coordinates."""

    vertices: list[tuple[int, int, float]]
    faces: list[tuple[int, int, int]]
    material_ids: list[int]
    cell_ids: list[int]
    q_values: list[int]
    r_values: list[int]


@dataclass(slots=True)
class CandidateEvidence:
    raw_boundary_utm: tuple[tuple[float, float], ...]
    smoothed_boundary_counts: tuple[CountPoint, ...]
    reconciled_boundary_counts: tuple[CountPoint, ...]
    crossing_points: tuple[CountPoint, ...]
    source_water_cells: int
    source_water_area_m2: float
    source_water_elevations_m: tuple[float, ...]
    water_surface_elevation_m: float
    context_cells: int
    prefiltered_lattice_points: int
    cdt_vertices: int
    cdt_faces: int
    discarded_context_faces: int
    minimum_triangle_angle_degrees: float
    mandatory_constraint_segments: int
    seam_report: dict


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST)
    parser.add_argument("--control-corpus", type=Path, default=CONTROL_CORPUS)
    parser.add_argument("--render-preview", action="store_true")
    parser.add_argument("--skip-source-hash", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    if argv is None:
        argv = (
            sys.argv[sys.argv.index("--") + 1 :]
            if "--" in sys.argv
            else sys.argv[1:]
        )
    return parser.parse_args(argv)


def selected_cells(radius: int = 1) -> tuple[HexCell, ...]:
    center = HexCell(*LAKE_ANZA_CELL)
    return tuple(
        HexCell(center.q + dq, center.r + dr) for dq, dr in disk_offsets(radius)
    )


def plan_summary() -> dict:
    cells = selected_cells()
    context = selected_cells(2)
    reference_cell = locate_hex_cell(*LAKE_ANZA_REFERENCE_UTM)
    return {
        "artifact_schema": ARTIFACT_SCHEMA,
        "lake_anza_reference_utm_m": list(LAKE_ANZA_REFERENCE_UTM),
        "lake_anza_reference_cell": [reference_cell.q, reference_cell.r],
        "center_cell": {"q": cells[0].q, "r": cells[0].r, "id": cells[0].cell_id},
        "target_cells": [
            {"q": cell.q, "r": cell.r, "id": cell.cell_id} for cell in cells
        ],
        "target_cell_count": len(cells),
        "overbuild_context_cell_count": len(context),
        "method": "radius-two overbuild; canonical radius-one clip and partition",
        "palette": [
            {
                "material_id": item.material_id,
                "nlcd_category": item.nlcd_category,
                "name": item.name,
                "rgb": list(item.rgb),
            }
            for item in BERKELEY_TERRAIN_MATERIALS
        ],
    }


def project_points(
    points: Iterable[tuple[float, float]], source_crs: str, target_crs: str
) -> tuple[tuple[float, float], ...]:
    """Project one bounded deterministic batch through the pinned PROJ CLI."""

    selected = tuple(points)
    if not selected:
        return ()
    source = "".join(f"{x:.9f} {y:.9f}\n" for x, y in selected)
    completed = subprocess.run(
        ["cs2cs", "-f", "%.9f", source_crs, target_crs],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    result: list[tuple[float, float]] = []
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] == "*" or fields[1] == "*":
            raise ValueError(f"cs2cs rejected comparison coordinate: {line}")
        result.append((float(fields[0]), float(fields[1])))
    if len(result) != len(selected):
        raise RuntimeError("cs2cs did not return every comparison coordinate")
    return tuple(result)


def _surface_from_control_cell(cell: HexCell, corpus: Path) -> ComparisonMesh:
    path = corpus / hex_builder.record_path(cell)
    tile = parse_container(path.read_bytes())
    if tile.meta.tile_x != cell.q or tile.meta.tile_y != cell.r:
        raise ValueError(f"control cell identity mismatch in {path}")
    topology = hex_topology(cell.q, cell.r)
    vertex_count = len(topology.keys)
    triangle_count = len(topology.faces)
    if len(tile.positions) < vertex_count:
        raise ValueError(f"control cell has too few vertices: {path}")

    center_east = REGIONAL_ORIGIN_EAST_M + tile.meta.center_east_m
    center_north = REGIONAL_ORIGIN_NORTH_M + tile.meta.center_north_m
    vertices: list[tuple[int, int, float]] = []
    for pingo_north, pingo_y, pingo_west in tile.positions[:vertex_count]:
        east_count = round((center_east - pingo_west / 32.0) * COUNTS_PER_METRE)
        north_count = round((center_north + pingo_north / 32.0) * COUNTS_PER_METRE)
        elevation = REGIONAL_VERTICAL_ORIGIN_M + pingo_y / 32.0
        vertices.append((east_count, north_count, elevation))
    expected_keys = tuple((east, north) for east, north in topology.keys)
    actual_keys = tuple((east, north) for east, north, _height in vertices)
    if actual_keys != expected_keys:
        raise ValueError(f"decoded control positions disagree with topology: {path}")

    faces: list[tuple[int, int, int]] = []
    material_ids: list[int] = []
    for face_index in range(triangle_count):
        start = face_index * 3
        face = tuple(tile.position_indices[start : start + 3])
        # Pingo's north/up/west basis maps to clockwise east/north vertices.
        faces.append((face[0], face[2], face[1]))
        selector = tile.uv_indices[start : start + 3]
        if len(set(selector)) != 1:
            raise ValueError(f"control face spans several material selectors: {path}")
        material_ids.append(selector[0])
    return ComparisonMesh(
        vertices=vertices,
        faces=faces,
        material_ids=material_ids,
        cell_ids=[cell.cell_id] * triangle_count,
        q_values=[cell.q] * triangle_count,
        r_values=[cell.r] * triangle_count,
    )


def build_control(corpus: Path) -> ComparisonMesh:
    """Decode and combine exactly seven accepted runtime surfaces."""

    result = ComparisonMesh([], [], [], [], [], [])
    for cell in selected_cells():
        cell_mesh = _surface_from_control_cell(cell, corpus)
        base = len(result.vertices)
        result.vertices.extend(cell_mesh.vertices)
        result.faces.extend(
            (first + base, second + base, third + base)
            for first, second, third in cell_mesh.faces
        )
        result.material_ids.extend(cell_mesh.material_ids)
        result.cell_ids.extend(cell_mesh.cell_ids)
        result.q_values.extend(cell_mesh.q_values)
        result.r_values.extend(cell_mesh.r_values)
    expected_histogram = {
        0: 21,
        1: 302,
        2: 171,
        3: 6,
        7: 356,
        8: 20,
        9: 161,
        10: 11,
        13: 2,
    }
    if (
        len(result.vertices) != 637
        or len(result.faces) != 1_050
        or Counter(result.material_ids) != expected_histogram
    ):
        raise ValueError("Lake Anza control no longer matches the accepted P3DM corpus")
    return result


def _unique_target_boundary_segments(cells: Iterable[HexCell]) -> tuple[tuple[CountPoint, CountPoint], ...]:
    segments: set[tuple[CountPoint, CountPoint]] = set()
    for cell in cells:
        topology = hex_topology(cell.q, cell.r)
        for start, end, _owner in topology.boundary_edges:
            segments.add(tuple(sorted((topology.keys[start], topology.keys[end]))))
    return tuple(sorted(segments))


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _distance_to_segment_counts(
    point: CountPoint, first: CountPoint, second: CountPoint
) -> float:
    delta_x = second[0] - first[0]
    delta_y = second[1] - first[1]
    denominator = delta_x * delta_x + delta_y * delta_y
    if denominator == 0:
        return math.hypot(point[0] - first[0], point[1] - first[1])
    parameter = min(
        1.0,
        max(
            0.0,
            (
                (point[0] - first[0]) * delta_x
                + (point[1] - first[1]) * delta_y
            )
            / denominator,
        ),
    )
    return math.hypot(
        point[0] - (first[0] + parameter * delta_x),
        point[1] - (first[1] + parameter * delta_y),
    )


def _minimum_angle_degrees(
    face: Sequence[int], coordinates: Sequence[CountPoint]
) -> float:
    points = [coordinates[index] for index in face]
    angles: list[float] = []
    for index, point in enumerate(points):
        first = (
            points[index - 1][0] - point[0],
            points[index - 1][1] - point[1],
        )
        second = (
            points[(index + 1) % 3][0] - point[0],
            points[(index + 1) % 3][1] - point[1],
        )
        denominator = math.hypot(*first) * math.hypot(*second)
        if denominator == 0.0:
            return 0.0
        cosine = min(
            1.0,
            max(-1.0, (first[0] * second[0] + first[1] * second[1]) / denominator),
        )
        angles.append(math.degrees(math.acos(cosine)))
    return min(angles)


def _find_lake_component(
    nlcd: RasterMosaic, target_cells: tuple[HexCell, ...]
):
    all_points = tuple(
        point
        for cell in selected_cells(2)
        for point in hex_topology(cell.q, cell.r).points
    )
    projected = project_points(all_points, "EPSG:32610", "EPSG:5070")
    west = min(point[0] for point in projected) - nlcd.pixel_size_x
    south = min(point[1] for point in projected) - nlcd.pixel_size_y
    east = max(point[0] for point in projected) + nlcd.pixel_size_x
    north = max(point[1] for point in projected) + nlcd.pixel_size_y
    reference = project_points(
        (LAKE_ANZA_REFERENCE_UTM,), "EPSG:32610", "EPSG:5070"
    )[0]
    return extract_raster_component(
        nlcd,
        category=WATER_CATEGORY,
        reference=reference,
        bounds=(west, south, east, north),
    )


def _candidate_materials(
    vertices: Sequence[tuple[int, int, float]],
    faces: Sequence[tuple[int, int, int]],
    lake_loop: Sequence[CountPoint],
    nlcd: RasterMosaic,
) -> list[int]:
    utm_points = tuple(
        (east / COUNTS_PER_METRE, north / COUNTS_PER_METRE)
        for east, north, _height in vertices
    )
    projected = project_points(utm_points, "EPSG:32610", "EPSG:5070")
    materials: list[int] = []

    def nearest_non_water_category(x: float, y: float) -> int:
        witnesses: list[tuple[float, int, int, int]] = []
        for row in range(-4, 5):
            for column in range(-4, 5):
                sample = nlcd.sample_nearest(
                    x + column * nlcd.pixel_size_x,
                    y + row * nlcd.pixel_size_y,
                    clamp=True,
                )
                if (
                    sample.value is None
                    or int(sample.value) == WATER_CATEGORY
                    or int(sample.value) not in NLCD_TO_MATERIAL
                ):
                    continue
                witnesses.append(
                    (
                        (column * nlcd.pixel_size_x) ** 2
                        + (row * nlcd.pixel_size_y) ** 2,
                        row,
                        column,
                        int(sample.value),
                    )
                )
        if not witnesses:
            raise ValueError("no non-water NLCD witness near constrained shoreline")
        return min(witnesses)[3]

    for face in faces:
        centroid_count = (
            Fraction(sum(vertices[index][0] for index in face), 3),
            Fraction(sum(vertices[index][1] for index in face), 3),
        )
        inside_lake = point_in_polygon(centroid_count, lake_loop)
        if inside_lake:
            materials.append(NLCD_TO_MATERIAL[WATER_CATEGORY])
            continue
        triangle = tuple(projected[index] for index in face)
        west = min(point[0] for point in triangle)
        south = min(point[1] for point in triangle)
        east = max(point[0] for point in triangle)
        north = max(point[1] for point in triangle)

        def centroid_lookup(x: float, y: float) -> int | None:
            sample = nlcd.sample_nearest(x, y, clamp=True)
            return None if sample.value is None else int(sample.value)

        category, _saw_nodata = predominant_category(
            triangle,
            (
                witness
                for witness in nlcd.cells_in_bbox(west, south, east, north)
                if witness[2] != WATER_CATEGORY
            ),
            centroid_lookup=centroid_lookup,
        )
        projected_centroid = (
            sum(projected[index][0] for index in face) / 3.0,
            sum(projected[index][1] for index in face) / 3.0,
        )
        if category == WATER_CATEGORY or category not in NLCD_TO_MATERIAL:
            category = nearest_non_water_category(*projected_centroid)
        if category not in NLCD_TO_MATERIAL:
            average_elevation = sum(vertices[index][2] for index in face) / 3.0
            category = WATER_CATEGORY if average_elevation <= 3.0 else 24
        material_id = NLCD_TO_MATERIAL[category]
        if material_id == NLCD_TO_MATERIAL[WATER_CATEGORY]:
            raise ValueError("water material escaped the constrained lake boundary")
        materials.append(material_id)
    return materials


def _cell_for_face(
    face: Sequence[int], coordinates: Sequence[CountPoint], cells: Sequence[HexCell]
) -> HexCell | None:
    centroid = (
        round(sum(coordinates[index][0] for index in face) / len(face)),
        round(sum(coordinates[index][1] for index in face) / len(face)),
    )
    try:
        located = locate_hex_cell(
            centroid[0] / COUNTS_PER_METRE,
            centroid[1] / COUNTS_PER_METRE,
        )
    except ValueError:
        return None
    return located if located in cells else None


def _seam_vertices(
    mesh: ComparisonMesh, cell: HexCell, neighbor: HexCell
) -> dict[CountPoint, set[int]]:
    first_corners = set(
        tuple(sorted((topology.keys[start], topology.keys[end])))
        for topology in (hex_topology(cell.q, cell.r),)
        for start, end, _owner in topology.boundary_edges
    )
    second_corners = set(
        tuple(sorted((topology.keys[start], topology.keys[end])))
        for topology in (hex_topology(neighbor.q, neighbor.r),)
        for start, end, _owner in topology.boundary_edges
    )
    common_segments = first_corners & second_corners
    if not common_segments:
        return {}
    face_indices = [
        index for index, cell_id in enumerate(mesh.cell_ids) if cell_id == cell.cell_id
    ]
    used_vertices = {
        vertex for face_index in face_indices for vertex in mesh.faces[face_index]
    }
    points: dict[CountPoint, set[int]] = defaultdict(set)
    for vertex in used_vertices:
        point = mesh.vertices[vertex][:2]
        if any(point_on_segment(point, segment) for segment in common_segments):
            points[point].add(round(mesh.vertices[vertex][2] * COUNTS_PER_METRE))
    return dict(points)


def validate_candidate_seams(mesh: ComparisonMesh) -> dict:
    cells = selected_cells()
    pairs = []
    for index, cell in enumerate(cells):
        for neighbor in cells[index + 1 :]:
            if hex_distance((cell.q, cell.r), (neighbor.q, neighbor.r)) != 1:
                continue
            first = _seam_vertices(mesh, cell, neighbor)
            second = _seam_vertices(mesh, neighbor, cell)
            if first.keys() != second.keys() or len(first) < 2:
                raise ValueError(
                    f"candidate seam mismatch {cell.q},{cell.r} / "
                    f"{neighbor.q},{neighbor.r}: {len(first)} != {len(second)}"
                )
            if any(first[key] != second[key] or len(first[key]) != 1 for key in first):
                raise ValueError(
                    f"candidate seam elevation mismatch {cell.q},{cell.r} / "
                    f"{neighbor.q},{neighbor.r}"
                )
            pairs.append(
                {
                    "first": [cell.q, cell.r],
                    "second": [neighbor.q, neighbor.r],
                    "vertices": len(first),
                    "maximum_encoded_delta": 0,
                }
            )
    return {"adjacent_pairs": len(pairs), "pairs": pairs, "passed": True}


def build_candidate(dem: RasterMosaic, nlcd: RasterMosaic) -> tuple[ComparisonMesh, CandidateEvidence]:
    """Overbuild, constrain, and partition the feature-aware seven-cell mesh."""

    try:
        from mathutils import Vector
        from mathutils.geometry import delaunay_2d_cdt
    except ImportError as error:  # pragma: no cover - Blender integration
        raise SystemExit("run this build through Blender so mathutils is available") from error

    target_cells = selected_cells()
    context_cells = selected_cells(2)
    component = _find_lake_component(nlcd, target_cells)
    raw_boundary_utm = project_points(
        component.boundary, "EPSG:5070", "EPSG:32610"
    )
    component_center = polygon_centroid(raw_boundary_utm)
    if locate_hex_cell(*component_center) != target_cells[0]:
        raise ValueError("source-derived Lake Anza centroid moved outside center cell")
    smoothed = cyclic_corner_smooth(
        raw_boundary_utm, iterations=SMOOTHING_ITERATIONS
    )
    smoothed_counts = quantize_loop(smoothed, counts_per_metre=COUNTS_PER_METRE)
    target_segments = _unique_target_boundary_segments(target_cells)
    reconciled = reconcile_feature_crossings(smoothed_counts, target_segments)

    water_centers_utm = project_points(
        component.centers, "EPSG:5070", "EPSG:32610"
    )
    water_elevations: list[float] = []
    for east, north in water_centers_utm:
        sample = dem.sample_bilinear(east, north)
        if sample.value is None:
            raise ValueError("DEM nodata at Lake Anza source-water witness")
        water_elevations.append(float(sample.value))
    water_surface = _median(water_elevations)

    mandatory_points: set[CountPoint] = set(reconciled.feature_loop)
    for segment in reconciled.terrain_segments:
        mandatory_points.update(segment)
    feature_segments = tuple(
        zip(
            reconciled.feature_loop,
            reconciled.feature_loop[1:] + reconciled.feature_loop[:1],
            strict=True,
        )
    )
    all_points: set[CountPoint] = set(mandatory_points)
    prefiltered_lattice_points = 0
    for cell in context_cells:
        for point in hex_topology(cell.q, cell.r).keys:
            if point in mandatory_points:
                all_points.add(point)
                continue
            distance = min(
                _distance_to_segment_counts(point, first, second)
                for first, second in feature_segments
            )
            if distance < 6.0 * COUNTS_PER_METRE:
                prefiltered_lattice_points += 1
            else:
                all_points.add(point)
    ordered_points = sorted(all_points)
    point_index = {point: index for index, point in enumerate(ordered_points)}
    constraint_segments = {
        tuple(sorted((point_index[first], point_index[second])))
        for first, second in reconciled.terrain_segments
    }
    for first, second in zip(
        reconciled.feature_loop,
        reconciled.feature_loop[1:] + reconciled.feature_loop[:1],
        strict=True,
    ):
        constraint_segments.add(tuple(sorted((point_index[first], point_index[second]))))

    anchor = target_cells[0].center_m
    vectors = [
        Vector(
            (
                east / COUNTS_PER_METRE - anchor[0],
                north / COUNTS_PER_METRE - anchor[1],
            )
        )
        for east, north in ordered_points
    ]
    result = delaunay_2d_cdt(
        vectors,
        sorted(constraint_segments),
        [],
        0,
        1.0e-6,
        False,
    )
    output_vectors, _output_edges, output_faces = result[:3]
    output_counts: list[CountPoint] = [
        (
            round((point.x + anchor[0]) * COUNTS_PER_METRE),
            round((point.y + anchor[1]) * COUNTS_PER_METRE),
        )
        for point in output_vectors
    ]
    if len(set(output_counts)) != len(output_counts):
        raise ValueError("CDT vertices collide after 1/16-metre quantization")

    output_edge_keys = {
        tuple(sorted((output_counts[first], output_counts[second])))
        for face in output_faces
        for first, second in zip(face, face[1:] + face[:1], strict=True)
    }
    mandatory_segments = set(reconciled.terrain_segments)
    mandatory_segments.update(
        tuple(sorted((first, second))) for first, second in feature_segments
    )
    missing_constraints = mandatory_segments - output_edge_keys
    if missing_constraints:
        raise ValueError(
            f"CDT omitted {len(missing_constraints)} mandatory constraint segments"
        )

    kept: list[tuple[tuple[int, int, int], HexCell]] = []
    discarded = 0
    minimum_angle = 180.0
    for raw_face in output_faces:
        if len(raw_face) != 3:
            raise ValueError("constrained Delaunay output contains a non-triangle")
        face = tuple(raw_face)
        area = signed_area(tuple(output_counts[index] for index in face))
        if area == 0.0:
            raise ValueError("constrained Delaunay output collapsed after quantization")
        if area < 0.0:
            face = face[0], face[2], face[1]
        owner = _cell_for_face(face, output_counts, target_cells)
        if owner is None:
            discarded += 1
        else:
            minimum_angle = min(
                minimum_angle, _minimum_angle_degrees(face, output_counts)
            )
            kept.append((face, owner))
    if minimum_angle < 5.0:
        raise ValueError(
            f"candidate minimum triangle angle {minimum_angle:.6f} is below 5 degrees"
        )

    # Partition into independently owned cells.  Vertices are deliberately
    # duplicated across owners only after the one global crossing solution.
    mesh = ComparisonMesh([], [], [], [], [], [])
    for cell in target_cells:
        cell_faces = [face for face, owner in kept if owner == cell]
        used = sorted({index for face in cell_faces for index in face})
        local = {source: index + len(mesh.vertices) for index, source in enumerate(used)}
        for source in used:
            east_count, north_count = output_counts[source]
            sample = dem.sample_bilinear(
                east_count / COUNTS_PER_METRE,
                north_count / COUNTS_PER_METRE,
            )
            if sample.value is None:
                raise ValueError("DEM nodata at candidate vertex")
            elevation = (
                water_surface
                if point_in_polygon((east_count, north_count), reconciled.feature_loop)
                else float(sample.value)
            )
            mesh.vertices.append((east_count, north_count, elevation))
        mesh.faces.extend(tuple(local[index] for index in face) for face in cell_faces)
        mesh.cell_ids.extend([cell.cell_id] * len(cell_faces))
        mesh.q_values.extend([cell.q] * len(cell_faces))
        mesh.r_values.extend([cell.r] * len(cell_faces))

    mesh.material_ids = _candidate_materials(
        mesh.vertices, mesh.faces, reconciled.feature_loop, nlcd
    )
    seam_report = validate_candidate_seams(mesh)
    evidence = CandidateEvidence(
        raw_boundary_utm=raw_boundary_utm,
        smoothed_boundary_counts=smoothed_counts,
        reconciled_boundary_counts=reconciled.feature_loop,
        crossing_points=reconciled.crossing_points,
        source_water_cells=len(component.cells),
        source_water_area_m2=(
            len(component.cells) * nlcd.pixel_size_x * nlcd.pixel_size_y
        ),
        source_water_elevations_m=tuple(water_elevations),
        water_surface_elevation_m=water_surface,
        context_cells=len(context_cells),
        prefiltered_lattice_points=prefiltered_lattice_points,
        cdt_vertices=len(output_vectors),
        cdt_faces=len(output_faces),
        discarded_context_faces=discarded,
        minimum_triangle_angle_degrees=minimum_angle,
        mandatory_constraint_segments=len(mandatory_segments),
        seam_report=seam_report,
    )
    return mesh, evidence


def _add_int_attribute(mesh, name: str, domain: str, values: Iterable[int]) -> None:
    payload = array("i", values)
    attribute = mesh.attributes.new(name=name, type="INT", domain=domain)
    attribute.data.foreach_set("value", payload)


def _create_materials(bpy) -> tuple:
    materials = []
    for spec in BERKELEY_TERRAIN_MATERIALS:
        red, green, blue = spec.rgb
        material = bpy.data.materials.new(
            f"Terrain {spec.material_id:02d} — NLCD {spec.nlcd_category}: {spec.name}"
        )
        color = red / 255.0, green / 255.0, blue / 255.0, 1.0
        material.diffuse_color = color
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = 0.88
        material["terrain_material_id"] = spec.material_id
        material["nlcd_category"] = spec.nlcd_category
        material["source_rgb8"] = list(spec.rgb)
        materials.append(material)
    return tuple(materials)


def _create_mesh_object(
    bpy,
    *,
    name: str,
    product: ComparisonMesh,
    materials: Sequence,
    display_origin: tuple[float, float],
    display_offset_x_m: float,
    collection,
    method: str,
):
    vertices = [
        (
            (east / COUNTS_PER_METRE - display_origin[0] + display_offset_x_m)
            * DISPLAY_SCALE,
            (north / COUNTS_PER_METRE - display_origin[1]) * DISPLAY_SCALE,
            elevation * DISPLAY_SCALE,
        )
        for east, north, elevation in product.vertices
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), product.faces)
    mesh.update(calc_edges=True)
    for material in materials:
        mesh.materials.append(material)
    mesh.polygons.foreach_set("material_index", array("i", product.material_ids))
    _add_int_attribute(mesh, "hex_cell_id", "FACE", product.cell_ids)
    _add_int_attribute(mesh, "hex_q", "FACE", product.q_values)
    _add_int_attribute(mesh, "hex_r", "FACE", product.r_values)
    _add_int_attribute(mesh, "terrain_material_id", "FACE", product.material_ids)
    _add_int_attribute(
        mesh, "utm_easting_count", "POINT", (value[0] for value in product.vertices)
    )
    _add_int_attribute(
        mesh, "utm_northing_count", "POINT", (value[1] for value in product.vertices)
    )
    elevation_attribute = mesh.attributes.new(
        name="elevation_navd88_m", type="FLOAT", domain="POINT"
    )
    elevation_attribute.data.foreach_set(
        "value", array("f", (value[2] for value in product.vertices))
    )
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["artifact_role"] = method
    obj["target_hex_cells"] = 7
    obj["flat_shading"] = True
    return obj


def _add_label(bpy, collection, text: str, x: float, y: float, z: float) -> None:
    curve = bpy.data.curves.new(f"{text} label", type="FONT")
    curve.body = text
    curve.align_x = "CENTER"
    curve.size = 0.75
    curve.extrude = 0.012
    obj = bpy.data.objects.new(f"Label — {text}", curve)
    obj.location = (x, y, z)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    collection.objects.link(obj)


def _mesh_summary(product: ComparisonMesh) -> dict:
    histogram = Counter(product.material_ids)
    digest = hashlib.sha256()
    for east, north, elevation in product.vertices:
        digest.update(struct.pack("<iif", east, north, elevation))
    for face, material, cell_id in zip(
        product.faces, product.material_ids, product.cell_ids, strict=True
    ):
        digest.update(struct.pack("<3IHI", *face, material, cell_id))
    return {
        "vertices": len(product.vertices),
        "faces": len(product.faces),
        "cells": len(set(product.cell_ids)),
        "material_face_histogram": {
            str(key): histogram[key] for key in sorted(histogram)
        },
        "water_faces": histogram[NLCD_TO_MATERIAL[WATER_CATEGORY]],
        "canonical_geometry_sha256": digest.hexdigest(),
        "elevation_m": [
            min(value[2] for value in product.vertices),
            max(value[2] for value in product.vertices),
        ],
    }


def build_scene(
    arguments: argparse.Namespace,
    control: ComparisonMesh,
    candidate: ComparisonMesh,
    evidence: CandidateEvidence,
    *,
    source_manifest_path: Path,
    source_manifest_sha256: str,
) -> dict:
    try:
        import bpy
        from mathutils import Vector
    except ImportError as error:  # pragma: no cover - Blender integration
        raise SystemExit("run this build through Blender so bpy is available") from error

    bpy.ops.wm.read_factory_settings(use_empty=True)
    control_collection = bpy.data.collections.new("CONTROL — accepted regular N=5")
    candidate_collection = bpy.data.collections.new(
        "CANDIDATE — feature-aware overbuild and clip"
    )
    bpy.context.scene.collection.children.link(control_collection)
    bpy.context.scene.collection.children.link(candidate_collection)
    materials = _create_materials(bpy)
    display_origin = selected_cells()[0].center_m
    control_offset = -DISPLAY_SEPARATION_M / 2.0
    candidate_offset = DISPLAY_SEPARATION_M / 2.0
    _create_mesh_object(
        bpy,
        name="Lake Anza — CONTROL — 7 accepted regular hex cells",
        product=control,
        materials=materials,
        display_origin=display_origin,
        display_offset_x_m=control_offset,
        collection=control_collection,
        method="exact accepted N=5 P3DM surfaces; seven independently encoded cells",
    )
    _create_mesh_object(
        bpy,
        name="Lake Anza — CANDIDATE — 7 feature-aware hex cells",
        product=candidate,
        materials=materials,
        display_origin=display_origin,
        display_offset_x_m=candidate_offset,
        collection=candidate_collection,
        method="radius-two overbuild; constrained lake and hex cuts; radius-one partition",
    )

    max_elevation = max(
        max(value[2] for value in control.vertices),
        max(value[2] for value in candidate.vertices),
    )
    label_y = 8.6
    label_z = max_elevation * DISPLAY_SCALE + 0.8
    _add_label(
        bpy,
        control_collection,
        "CONTROL — REGULAR N=5",
        control_offset * DISPLAY_SCALE,
        label_y,
        label_z,
    )
    _add_label(
        bpy,
        candidate_collection,
        "FEATURE-AWARE — OVERBUILD / CLIP",
        candidate_offset * DISPLAY_SCALE,
        label_y,
        label_z,
    )

    sun_data = bpy.data.lights.new("Lake Anza review sun", type="SUN")
    sun_data.energy = 2.5
    sun_data.angle = math.radians(12.0)
    sun = bpy.data.objects.new("Lake Anza review sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.location = Vector((-25.0, -30.0, 42.0))
    sun.rotation_euler = (Vector((0.0, 0.0, 2.5)) - sun.location).to_track_quat(
        "-Z", "Y"
    ).to_euler()

    world = bpy.data.worlds.new("Lake Anza review daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.055,
        0.075,
        0.11,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55

    camera_data = bpy.data.cameras.new("Lake Anza comparison camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 31.0
    camera_data.clip_end = 500.0
    camera = bpy.data.objects.new("Lake Anza comparison camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = Vector((0.0, -31.0, 34.0))
    camera.rotation_euler = (
        Vector((0.0, 0.5, 2.7)) - camera.location
    ).to_track_quat("-Z", "Y").to_euler()

    scene = bpy.context.scene
    scene.camera = camera
    scene.world = world
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(arguments.output.with_suffix(".png"))
    scene.display.shading.light = "STUDIO"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.color_type = "MATERIAL"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0 / DISPLAY_SCALE

    metadata = {
        **plan_summary(),
        "source_manifest": str(source_manifest_path),
        "source_manifest_sha256": source_manifest_sha256,
        "control_corpus": str(arguments.control_corpus.resolve()),
        "control": _mesh_summary(control),
        "candidate": _mesh_summary(candidate),
        "feature": {
            "name": "Lake Anza",
            "source": "pinned NLCD category 11 component nearest review reference",
            "source_water_cells": evidence.source_water_cells,
            "source_water_area_m2": evidence.source_water_area_m2,
            "raw_boundary_vertices": len(evidence.raw_boundary_utm),
            "smoothed_boundary_vertices": len(evidence.smoothed_boundary_counts),
            "reconciled_boundary_vertices": len(evidence.reconciled_boundary_counts),
            "hex_crossings": [list(point) for point in evidence.crossing_points],
            "source_centroid_utm_m": list(polygon_centroid(evidence.raw_boundary_utm)),
            "smoothing": (
                f"closed cyclic 1-2-1 corner filter, "
                f"{SMOOTHING_ITERATIONS} iteration"
            ),
            "water_elevation_m": {
                "minimum": min(evidence.source_water_elevations_m),
                "median_and_candidate_surface": evidence.water_surface_elevation_m,
                "mean": sum(evidence.source_water_elevations_m)
                / len(evidence.source_water_elevations_m),
                "maximum": max(evidence.source_water_elevations_m),
            },
        },
        "overbuild": {
            "context_cells": evidence.context_cells,
            "cdt_vertices": evidence.cdt_vertices,
            "cdt_faces": evidence.cdt_faces,
            "prefiltered_lattice_points": evidence.prefiltered_lattice_points,
            "discarded_context_faces": evidence.discarded_context_faces,
            "retained_target_faces": len(candidate.faces),
            "minimum_triangle_angle_degrees": (
                evidence.minimum_triangle_angle_degrees
            ),
            "mandatory_constraint_segments": (
                evidence.mandatory_constraint_segments
            ),
        },
        "candidate_seams": evidence.seam_report,
        "display": {
            "scale": DISPLAY_SCALE,
            "separation_source_m": DISPLAY_SEPARATION_M,
            "terrain_coordinates": "unaltered UTM/count attributes; display offset only",
        },
        "build_script_sha256": sha256_file(Path(__file__)),
        "feature_module_sha256": sha256_file(
            ROOT / "src/pingo_terrain/feature_terrain.py"
        ),
    }
    scene["artifact_schema"] = ARTIFACT_SCHEMA
    scene["review_metadata_json"] = json.dumps(
        metadata, sort_keys=True, separators=(",", ":")
    )
    scene["source_manifest_sha256"] = source_manifest_sha256
    scene["lake_anza_center_cell"] = f"{LAKE_ANZA_CELL[0]},{LAKE_ANZA_CELL[1]}"
    scene["candidate_seams_passed"] = evidence.seam_report["passed"]

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(arguments.output), check_existing=False, compress=True
    )
    if arguments.render_preview:
        bpy.ops.render.render(write_still=True)
    return metadata


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
    preview = output.with_suffix(".png")
    if preview.is_file():
        payload["preview"] = {
            "path": str(preview),
            "bytes": preview.stat().st_size,
            "sha256": sha256_file(preview),
        }
    receipt.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    plan = plan_summary()
    print("LAKE_ANZA_PLAN", json.dumps(plan, sort_keys=True), flush=True)
    if arguments.plan_only:
        return 0

    source_manifest_path = arguments.source_manifest.expanduser().resolve()
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = json.loads(source_manifest_bytes)
    if not arguments.skip_source_hash:
        regional_blender.verify_sources(ROOT, source_manifest)
    datasets = {dataset["id"]: dataset for dataset in source_manifest["datasets"]}
    dem = RasterMosaic(ROOT, datasets[rectangular.DEM_DATASET_ID])
    nlcd = RasterMosaic(
        ROOT, datasets[rectangular.NLCD_DATASET_ID], cache_blocks_per_tile=12
    )
    control = build_control(arguments.control_corpus.expanduser().resolve())
    candidate, evidence = build_candidate(dem, nlcd)
    metadata = build_scene(
        arguments,
        control,
        candidate,
        evidence,
        source_manifest_path=source_manifest_path,
        source_manifest_sha256=hashlib.sha256(source_manifest_bytes).hexdigest(),
    )
    receipt = write_receipt(arguments.output, metadata)
    print(
        "LAKE_ANZA_COMPARISON",
        f"control={len(control.vertices)}v/{len(control.faces)}f",
        f"candidate={len(candidate.vertices)}v/{len(candidate.faces)}f",
        f"water={evidence.source_water_cells}px/"
        f"{evidence.source_water_area_m2:.0f}m2",
        f"crossings={len(evidence.crossing_points)}",
        f"output={arguments.output}",
        f"receipt={receipt}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
