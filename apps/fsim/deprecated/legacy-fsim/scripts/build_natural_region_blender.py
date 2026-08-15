#!/usr/bin/env python3
"""Build the full Bay Area natural-surface/post-partition Blender experiment.

This artifact deliberately reverses the accepted runtime build order.  One
adaptive constrained terrain surface is generated over the complete pinned
region first; only then is each finished triangle assigned to a roughly
hexagonal logical streaming address.  The result is a review artifact, not a
replacement P3DM corpus.

Run through Blender so its bundled ``bpy`` and constrained-Delaunay code are
available::

    blender --background --python scripts/build_natural_region_blender.py -- \
      --render-preview
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import heapq
import json
import math
from pathlib import Path
import resource
import struct
import sys
import time
from typing import Iterable, Iterator, Sequence


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SOURCE_MANIFEST = ROOT / "data/manifests/bay-area-2026-08-02.json"
DEFAULT_OUTPUT = (
    ROOT / "build/visualization/bay-area-natural-post-partition.blend"
)
ARTIFACT_SCHEMA = "pingo-terrain-natural-post-partition-review-v1"
DISPLAY_SCALE = 0.001
VERTICAL_EXAGGERATION = 1.0
PROJECT_BATCH = 50_000

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPTS))

import build_regional_blender as regional_blender  # noqa: E402

from pingo_terrain.geotiff import sha256_file  # noqa: E402
from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HEX_CELL_COUNT,
    HexCell,
    hex_distance,
    iter_cells,
    locate_hex_cell_counts,
)
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS  # noqa: E402
from pingo_terrain.natural_region import (  # noqa: E402
    AdaptiveRegionPlan,
    AdaptiveRegionProfile,
    SOURCE_LOGICAL_SEED,
    build_adaptive_region_plan,
)
from pingo_terrain.regional_raster import RasterMosaic  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_EPSG,
)


NLCD_TO_MATERIAL = {
    material.nlcd_category: material.material_id
    for material in BERKELEY_TERRAIN_MATERIALS
}
WATER_CATEGORY = 11
UNKNOWN_LAND_CATEGORY = 24
DEM_DATASET_ID = "usgs-3dep-10m-utm10n"
NLCD_DATASET_ID = "usgs-annual-nlcd-2025-epsg5070"
HEX_CORNER_OFFSETS_M: tuple[tuple[int, int], ...] = (
    (320, 0),
    (160, 275),
    (-160, 275),
    (-320, 0),
    (-160, -275),
    (160, -275),
)
AXIAL_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


@dataclass(frozen=True, slots=True)
class AnalysisGrid:
    origin_m: tuple[int, int]
    columns: int
    rows: int
    step_m: int
    corpus_bounds_m: tuple[int, int, int, int]

    @property
    def point_count(self) -> int:
        return self.columns * self.rows

    @property
    def bounds_m(self) -> tuple[int, int, int, int]:
        return (
            self.origin_m[0],
            self.origin_m[1],
            self.origin_m[0] + (self.columns - 1) * self.step_m,
            self.origin_m[1] + (self.rows - 1) * self.step_m,
        )


@dataclass(slots=True)
class AnalysisSamples:
    heights_m: array
    categories: array
    edge_padded_dem_points: int
    edge_padded_nlcd_points: int
    nodata_nlcd_points: int


@dataclass(slots=True)
class NaturalMesh:
    points_counts: list[tuple[int, int]]
    elevations_m: array
    point_source_flags: array
    faces: list[tuple[int, int, int]]
    face_cell_ids: array
    face_q: array
    face_r: array
    face_categories: array
    face_material_ids: array
    partition_edges: frozenset[tuple[int, int]]
    protected_water_edges: frozenset[tuple[int, int]]
    corpus_edges: frozenset[tuple[int, int]]
    evidence: dict


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--analysis-step-m", type=int, default=128)
    parser.add_argument("--middle-residual-m", type=float, default=4.0)
    parser.add_argument("--coarse-residual-m", type=float, default=10.0)
    parser.add_argument("--curvature-residual-m", type=float, default=7.0)
    parser.add_argument("--max-input-points", type=int, default=500_000)
    parser.add_argument("--display-scale", type=float, default=DISPLAY_SCALE)
    parser.add_argument(
        "--vertical-exaggeration", type=float, default=VERTICAL_EXAGGERATION
    )
    parser.add_argument("--skip-source-hash", action="store_true")
    parser.add_argument("--render-preview", action="store_true")
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="report the deterministic source grid without reading rasters",
    )
    if argv is None:
        argv = (
            sys.argv[sys.argv.index("--") + 1 :]
            if "--" in sys.argv
            else sys.argv[1:]
        )
    arguments = parser.parse_args(argv)
    if arguments.analysis_step_m <= 0 or arguments.analysis_step_m % 2:
        parser.error("--analysis-step-m must be a positive even number")
    if arguments.max_input_points < HEX_CELL_COUNT:
        parser.error(f"--max-input-points must be at least {HEX_CELL_COUNT}")
    if arguments.display_scale <= 0.0:
        parser.error("--display-scale must be positive")
    if arguments.vertical_exaggeration <= 0.0:
        parser.error("--vertical-exaggeration must be positive")
    return arguments


def profile_from_arguments(arguments: argparse.Namespace) -> AdaptiveRegionProfile:
    return AdaptiveRegionProfile(
        analysis_step_m=arguments.analysis_step_m,
        middle_residual_m=arguments.middle_residual_m,
        coarse_residual_m=arguments.coarse_residual_m,
        curvature_residual_m=arguments.curvature_residual_m,
    )


def analysis_grid(
    cells: Sequence[HexCell], profile: AdaptiveRegionProfile
) -> AnalysisGrid:
    if not cells:
        raise ValueError("natural-region analysis requires logical cells")
    west = min(cell.center_m[0] for cell in cells) + min(
        point[0] for point in HEX_CORNER_OFFSETS_M
    )
    south = min(cell.center_m[1] for cell in cells) + min(
        point[1] for point in HEX_CORNER_OFFSETS_M
    )
    east = max(cell.center_m[0] for cell in cells) + max(
        point[0] for point in HEX_CORNER_OFFSETS_M
    )
    north = max(cell.center_m[1] for cell in cells) + max(
        point[1] for point in HEX_CORNER_OFFSETS_M
    )
    step = profile.analysis_step_m
    aligned_west = west // step * step
    aligned_south = south // step * step
    aligned_east = -((-east) // step) * step
    aligned_north = -((-north) // step) * step
    return AnalysisGrid(
        origin_m=(aligned_west, aligned_south),
        columns=(aligned_east - aligned_west) // step + 1,
        rows=(aligned_north - aligned_south) // step + 1,
        step_m=step,
        corpus_bounds_m=(west, south, east, north),
    )


def plan_summary(
    cells: Sequence[HexCell], grid: AnalysisGrid, profile: AdaptiveRegionProfile
) -> dict:
    return {
        "artifact_schema": ARTIFACT_SCHEMA,
        "artifact_role": "full-region visual/structural experiment; not runtime payload",
        "logical_cells": len(cells),
        "logical_cell_id_range": [
            min(cell.cell_id for cell in cells),
            max(cell.cell_id for cell in cells),
        ],
        "method": "adaptive constrained master surface first; face ownership second",
        "analysis_profile": asdict(profile),
        "analysis_grid": {
            "origin_m": list(grid.origin_m),
            "columns": grid.columns,
            "rows": grid.rows,
            "points": grid.point_count,
            "bounds_m": list(grid.bounds_m),
            "corpus_bounds_m": list(grid.corpus_bounds_m),
        },
    }


def _chunks(values: Sequence, size: int) -> Iterator[Sequence]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _grid_point(grid: AnalysisGrid, index: int) -> tuple[int, int]:
    row, column = divmod(index, grid.columns)
    return (
        grid.origin_m[0] + column * grid.step_m,
        grid.origin_m[1] + row * grid.step_m,
    )


def sample_analysis_grid(
    grid: AnalysisGrid, dem: RasterMosaic, nlcd: RasterMosaic
) -> AnalysisSamples:
    """Read the fixed analysis lattice without materializing source rasters."""

    heights_m = array("f")
    categories = array("B")
    edge_padded_dem_points = 0
    edge_padded_nlcd_points = 0
    nodata_nlcd_points = 0
    for start in range(0, grid.point_count, PROJECT_BATCH):
        stop = min(grid.point_count, start + PROJECT_BATCH)
        points = [_grid_point(grid, index) for index in range(start, stop)]
        for east, north in points:
            sample = dem.sample_bilinear(east, north)
            if sample.value is None:
                raise ValueError(f"DEM nodata at analysis point E {east}, N {north}")
            heights_m.append(float(sample.value))
            edge_padded_dem_points += int(sample.edge_padded)
        projected = regional_blender.project_utm10_to_albers(points)
        for east, north in projected:
            sample = nlcd.sample_nearest(east, north, clamp=True)
            edge_padded_nlcd_points += int(sample.edge_padded)
            nodata_nlcd_points += int(sample.nodata)
            category = UNKNOWN_LAND_CATEGORY if sample.value is None else int(sample.value)
            if category not in NLCD_TO_MATERIAL:
                category = UNKNOWN_LAND_CATEGORY
            categories.append(category)
        print(
            f"NATURAL_ANALYSIS points={stop}/{grid.point_count}", flush=True
        )
    return AnalysisSamples(
        heights_m=heights_m,
        categories=categories,
        edge_padded_dem_points=edge_padded_dem_points,
        edge_padded_nlcd_points=edge_padded_nlcd_points,
        nodata_nlcd_points=nodata_nlcd_points,
    )


def _signed_twice_area(
    face: tuple[int, int, int], points: Sequence[tuple[int, int]]
) -> int:
    first, second, third = (points[index] for index in face)
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _minimum_angle_degrees(
    face: tuple[int, int, int], points: Sequence[tuple[int, int]]
) -> float:
    result = 180.0
    for pivot, first, second in (
        (face[0], face[1], face[2]),
        (face[1], face[2], face[0]),
        (face[2], face[0], face[1]),
    ):
        ax = points[first][0] - points[pivot][0]
        ay = points[first][1] - points[pivot][1]
        bx = points[second][0] - points[pivot][0]
        by = points[second][1] - points[pivot][1]
        denominator = math.hypot(ax, ay) * math.hypot(bx, by)
        if denominator == 0.0:
            return 0.0
        cosine = min(1.0, max(-1.0, (ax * bx + ay * by) / denominator))
        result = min(result, math.degrees(math.acos(cosine)))
    return result


def _validate_constraint_chains(
    *,
    constraints: Iterable[tuple[int, int]],
    output_edges: set[tuple[int, int]],
    points: Sequence[tuple[int, int]],
) -> tuple[dict, frozenset[tuple[int, int]]]:
    """Accept a protected segment only as one edge or one exact edge chain."""

    subdivided = 0
    maximum_pieces = 1
    failures: list[tuple[int, int]] = []
    protected_edges: set[tuple[int, int]] = set()
    selected = tuple(constraints)
    for first_index, second_index in selected:
        direct = tuple(sorted((first_index, second_index)))
        if direct in output_edges:
            protected_edges.add(direct)
            continue
        first, second = points[first_index], points[second_index]
        delta_x = second[0] - first[0]
        delta_y = second[1] - first[1]
        denominator = delta_x * delta_x + delta_y * delta_y
        candidates: list[tuple[int, int]] = []
        for index, point in enumerate(points):
            offset_x = point[0] - first[0]
            offset_y = point[1] - first[1]
            if delta_x * offset_y - delta_y * offset_x:
                continue
            parameter = offset_x * delta_x + offset_y * delta_y
            if 0 <= parameter <= denominator:
                candidates.append((parameter, index))
        candidates.sort()
        chain = [index for _parameter, index in candidates]
        if (
            not chain
            or chain[0] != first_index
            or chain[-1] != second_index
            or any(
                tuple(sorted((a, b))) not in output_edges
                for a, b in zip(chain, chain[1:])
            )
        ):
            failures.append(direct)
            continue
        subdivided += 1
        maximum_pieces = max(maximum_pieces, len(chain) - 1)
        protected_edges.update(
            tuple(sorted((first, second)))
            for first, second in zip(chain, chain[1:])
        )
    if failures:
        raise ValueError(
            f"CDT broke {len(failures)} protected water segments; "
            f"examples={failures[:10]}"
        )
    return (
        {
            "direct_segments": len(selected) - subdivided,
            "subdivided_segments": subdivided,
            "maximum_edge_chain_pieces": maximum_pieces,
            "passed": True,
        },
        frozenset(protected_edges),
    )


def _sample_output_elevations(
    points_counts: Sequence[tuple[int, int]], dem: RasterMosaic
) -> tuple[array, int]:
    elevations = array("f")
    edge_padded = 0
    for index, (east, north) in enumerate(points_counts, start=1):
        sample = dem.sample_bilinear(
            east / COUNTS_PER_METRE, north / COUNTS_PER_METRE
        )
        if sample.value is None:
            raise ValueError(f"DEM nodata at natural vertex {east},{north}")
        elevations.append(float(sample.value))
        edge_padded += int(sample.edge_padded)
        if index % PROJECT_BATCH == 0 or index == len(points_counts):
            print(
                f"NATURAL_ELEVATION points={index}/{len(points_counts)}", flush=True
            )
    return elevations, edge_padded


def _sample_face_materials(
    points_counts: Sequence[tuple[int, int]],
    faces: Sequence[tuple[int, int, int]],
    elevations_m: Sequence[float],
    nlcd: RasterMosaic,
) -> tuple[array, array, dict]:
    categories = array("i")
    materials = array("i")
    edge_padded = 0
    nodata = 0
    fallback = 0
    for start in range(0, len(faces), PROJECT_BATCH):
        batch = faces[start : start + PROJECT_BATCH]
        centroids = [
            (
                sum(points_counts[index][0] for index in face)
                / (3.0 * COUNTS_PER_METRE),
                sum(points_counts[index][1] for index in face)
                / (3.0 * COUNTS_PER_METRE),
            )
            for face in batch
        ]
        projected = regional_blender.project_utm10_to_albers(centroids)
        for face, (east, north) in zip(batch, projected, strict=True):
            sample = nlcd.sample_nearest(east, north, clamp=True)
            edge_padded += int(sample.edge_padded)
            nodata += int(sample.nodata)
            category = None if sample.value is None else int(sample.value)
            if category not in NLCD_TO_MATERIAL:
                mean_height = sum(elevations_m[index] for index in face) / 3.0
                category = WATER_CATEGORY if mean_height <= 3.0 else UNKNOWN_LAND_CATEGORY
                fallback += 1
            categories.append(category)
            materials.append(NLCD_TO_MATERIAL[category])
        stop = start + len(batch)
        print(f"NATURAL_MATERIAL faces={stop}/{len(faces)}", flush=True)
    return categories, materials, {
        "edge_padded_faces": edge_padded,
        "nodata_faces": nodata,
        "fallback_faces": fallback,
    }


def _expected_adjacencies(cells: Sequence[HexCell]) -> set[tuple[int, int]]:
    identities = {(cell.q, cell.r): cell.cell_id for cell in cells}
    result: set[tuple[int, int]] = set()
    for cell in cells:
        for dq, dr in AXIAL_DIRECTIONS:
            neighbor = identities.get((cell.q + dq, cell.r + dr))
            if neighbor is not None:
                result.add(tuple(sorted((cell.cell_id, neighbor))))
    return result


def _connected_graph_voronoi_owners(
    *,
    points: Sequence[tuple[int, int]],
    faces: Sequence[tuple[int, int, int]],
    cells: Sequence[HexCell],
    preferred_owners: Sequence[int],
) -> tuple[array, dict]:
    """Partition the completed surface by physical distance on its dual graph.

    Each logical cell locks one incident triangle as a source.  Multi-source
    expansion then assigns every other triangle.  The face's ideal centroid
    owner gets first refusal; physical distance breaks ties.  A face is
    finalized only from a face already finalized for the same source, so every
    output component is nonempty and connected by construction; no master face
    is cut.
    """

    face_count = len(faces)
    if not face_count:
        raise ValueError("cannot partition an empty natural surface")
    if len(preferred_owners) != face_count:
        raise ValueError("preferred-owner count does not match natural faces")
    centroid_east = array(
        "d", (sum(points[index][0] for index in face) / 3.0 for face in faces)
    )
    centroid_north = array(
        "d", (sum(points[index][1] for index in face) / 3.0 for face in faces)
    )
    neighbors = array("i", [-1]) * (3 * face_count)
    open_edges: dict[tuple[int, int], tuple[int, int]] = {}
    for face_index, face in enumerate(faces):
        for slot, (first, second) in enumerate(
            zip(face, face[1:] + face[:1], strict=True)
        ):
            edge = tuple(sorted((first, second)))
            previous = open_edges.pop(edge, None)
            if previous is None:
                open_edges[edge] = (face_index, slot)
                continue
            other_face, other_slot = previous
            neighbors[face_index * 3 + slot] = other_face
            neighbors[other_face * 3 + other_slot] = face_index

    point_index = {point: index for index, point in enumerate(points)}
    seed_vertex_to_owner: dict[int, int] = {}
    cell_by_id = {cell.cell_id: cell for cell in cells}
    for cell in cells:
        point = (
            cell.center_m[0] * COUNTS_PER_METRE,
            cell.center_m[1] * COUNTS_PER_METRE,
        )
        vertex = point_index.get(point)
        if vertex is None:
            raise ValueError(f"logical seed is absent from retained mesh: {cell}")
        seed_vertex_to_owner[vertex] = cell.cell_id
    candidates: dict[int, list[int]] = defaultdict(list)
    for face_index, face in enumerate(faces):
        for vertex in face:
            owner = seed_vertex_to_owner.get(vertex)
            if owner is not None:
                candidates[owner].append(face_index)
    missing_candidates = sorted(set(cell_by_id) - candidates.keys())
    if missing_candidates:
        raise ValueError(
            f"{len(missing_candidates)} logical seeds have no incident retained face"
        )

    source_face_by_owner: dict[int, int] = {}
    claimed_faces: set[int] = set()
    source_owner_by_face: dict[int, int] = {}
    # Constrained-first ordering avoids spending a scarce shared face before a
    # logical seed with fewer choices has selected its source.
    for owner in sorted(candidates, key=lambda value: (len(set(candidates[value])), value)):
        cell = cell_by_id[owner]
        center = (
            cell.center_m[0] * COUNTS_PER_METRE,
            cell.center_m[1] * COUNTS_PER_METRE,
        )
        ordered = sorted(
            set(candidates[owner]),
            key=lambda face_index: (
                (centroid_east[face_index] - center[0]) ** 2
                + (centroid_north[face_index] - center[1]) ** 2,
                face_index,
            ),
        )
        source = None
        for face_index in ordered:
            if face_index in claimed_faces:
                continue
            adjacent_source_owners = {
                source_owner_by_face[neighbor]
                for offset in range(3)
                if (neighbor := neighbors[face_index * 3 + offset])
                in source_owner_by_face
            }
            if any(
                hex_distance(
                    (cell.q, cell.r),
                    (
                        cell_by_id[neighbor_owner].q,
                        cell_by_id[neighbor_owner].r,
                    ),
                )
                != 1
                for neighbor_owner in adjacent_source_owners
            ):
                continue
            source = face_index
            break
        if source is None:
            raise ValueError(
                f"logical seed cannot claim a unique adjacency-safe source face: {cell}"
            )
        source_face_by_owner[owner] = source
        claimed_faces.add(source)
        source_owner_by_face[source] = owner

    owners = array("i", [-1]) * face_count
    finalized = bytearray(face_count)
    locked_owner = {face: owner for owner, face in source_face_by_owner.items()}
    queue: list[tuple[int, float, int, int]] = []
    for owner, face_index in source_face_by_owner.items():
        owners[face_index] = owner
        finalized[face_index] = 1

    def enqueue_frontier(owner: int, face_index: int) -> None:
        cell = cell_by_id[owner]
        center_east = cell.center_m[0] * COUNTS_PER_METRE
        center_north = cell.center_m[1] * COUNTS_PER_METRE
        for offset in range(3):
            neighbor = neighbors[face_index * 3 + offset]
            if neighbor < 0 or finalized[neighbor]:
                continue
            lock = locked_owner.get(neighbor)
            if lock is not None and lock != owner:
                continue
            preferred = cell_by_id[preferred_owners[neighbor]]
            preference_distance = hex_distance(
                (cell.q, cell.r), (preferred.q, preferred.r)
            )
            physical_distance_squared = (
                centroid_east[neighbor] - center_east
            ) ** 2 + (centroid_north[neighbor] - center_north) ** 2
            heapq.heappush(
                queue,
                (
                    preference_distance,
                    physical_distance_squared,
                    owner,
                    neighbor,
                ),
            )

    for owner, face_index in source_face_by_owner.items():
        enqueue_frontier(owner, face_index)

    finalized_count = len(source_face_by_owner)
    adjacency_rejections = 0
    extent_rejections = 0
    extent_limit_squared = (1024 * COUNTS_PER_METRE) ** 2
    while queue:
        _preference, _physical_distance, owner, face_index = heapq.heappop(queue)
        if finalized[face_index]:
            continue
        cell = cell_by_id[owner]
        adjacent_owners = {
            owners[neighbor]
            for offset in range(3)
            if (neighbor := neighbors[face_index * 3 + offset]) >= 0
            and finalized[neighbor]
            and owners[neighbor] != owner
        }
        if any(
            hex_distance(
                (cell.q, cell.r),
                (cell_by_id[neighbor_owner].q, cell_by_id[neighbor_owner].r),
            )
            != 1
            for neighbor_owner in adjacent_owners
        ):
            adjacency_rejections += 1
            continue
        center_east = cell.center_m[0] * COUNTS_PER_METRE
        center_north = cell.center_m[1] * COUNTS_PER_METRE
        if any(
            (points[vertex][0] - center_east) ** 2
            + (points[vertex][1] - center_north) ** 2
            >= extent_limit_squared
            for vertex in faces[face_index]
        ):
            extent_rejections += 1
            continue
        finalized[face_index] = 1
        owners[face_index] = owner
        finalized_count += 1
        enqueue_frontier(owner, face_index)
        if finalized_count % 100_000 == 0:
            print(
                f"NATURAL_PARTITION faces={finalized_count}/{face_count}", flush=True
            )
    strict_finalized_count = finalized_count
    repair_components = 0
    repaired_faces = 0
    repair_noncanonical_contacts = 0
    seen_unassigned = bytearray(face_count)
    for start in range(face_count):
        if owners[start] >= 0 or seen_unassigned[start]:
            continue
        component: list[int] = []
        adjacent_owners: set[int] = set()
        stack = [start]
        seen_unassigned[start] = 1
        while stack:
            face_index = stack.pop()
            component.append(face_index)
            for offset in range(3):
                neighbor = neighbors[face_index * 3 + offset]
                if neighbor < 0:
                    continue
                if owners[neighbor] >= 0:
                    adjacent_owners.add(owners[neighbor])
                elif not seen_unassigned[neighbor]:
                    seen_unassigned[neighbor] = 1
                    stack.append(neighbor)
        # A component with no assigned neighbor is one of the permitted outer
        # clip islands.  It cannot be attached without inventing surface.
        if not adjacent_owners:
            continue
        candidates: list[tuple[int, int, float, int]] = []
        for candidate_owner in adjacent_owners:
            candidate_cell = cell_by_id[candidate_owner]
            center_east = candidate_cell.center_m[0] * COUNTS_PER_METRE
            center_north = candidate_cell.center_m[1] * COUNTS_PER_METRE
            if any(
                (points[vertex][0] - center_east) ** 2
                + (points[vertex][1] - center_north) ** 2
                >= extent_limit_squared
                for face_index in component
                for vertex in faces[face_index]
            ):
                continue
            noncanonical = sum(
                hex_distance(
                    (candidate_cell.q, candidate_cell.r),
                    (cell_by_id[other].q, cell_by_id[other].r),
                )
                != 1
                for other in adjacent_owners
                if other != candidate_owner
            )
            preference = sum(
                hex_distance(
                    (candidate_cell.q, candidate_cell.r),
                    (
                        cell_by_id[preferred_owners[face_index]].q,
                        cell_by_id[preferred_owners[face_index]].r,
                    ),
                )
                for face_index in component
            )
            physical = sum(
                (centroid_east[face_index] - center_east) ** 2
                + (centroid_north[face_index] - center_north) ** 2
                for face_index in component
            )
            candidates.append(
                (noncanonical, preference, physical, candidate_owner)
            )
        if not candidates:
            continue
        noncanonical, _preference, _physical, selected_owner = min(candidates)
        for face_index in component:
            owners[face_index] = selected_owner
            finalized[face_index] = 1
        repair_components += 1
        repaired_faces += len(component)
        repair_noncanonical_contacts += noncanonical
        finalized_count += len(component)

    unreachable = [
        face_index
        for face_index, owner in enumerate(owners)
        if owner < 0
    ]
    return owners, {
        "method": (
            "locked-seed connected dual-graph flood; ideal centroid owner first, "
            "then direct physical distance"
        ),
        "source_faces": len(source_face_by_owner),
        "faces_reached": finalized_count,
        "strict_flood_faces_reached": strict_finalized_count,
        "repair_components": repair_components,
        "repaired_faces": repaired_faces,
        "repair_noncanonical_contact_count": repair_noncanonical_contacts,
        "unseeded_disconnected_outer_faces": len(unreachable),
        "unseeded_disconnected_outer_face_examples": unreachable[:20],
        "outer_open_edges": len(open_edges),
        "noncanonical_adjacency_candidates_rejected": adjacency_rejections,
        "over_1024m_extent_candidates_rejected": extent_rejections,
        "distance_units": "squared projected 1/16-metre counts from logical seed",
    }


def _partition_evidence(
    *,
    points: Sequence[tuple[int, int]],
    faces: Sequence[tuple[int, int, int]],
    owners: Sequence[int],
    cells: Sequence[HexCell],
) -> tuple[frozenset[tuple[int, int]], frozenset[tuple[int, int]], dict]:
    """Validate one-face ownership, connectivity, and the physical edge graph."""

    parent = list(range(len(faces)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    edge_face: dict[tuple[int, int], int] = {}
    partition_edges: set[tuple[int, int]] = set()
    corpus_edges: set[tuple[int, int]] = set()
    adjacency: set[tuple[int, int]] = set()
    for face_index, face in enumerate(faces):
        for first, second in zip(face, face[1:] + face[:1], strict=True):
            edge = tuple(sorted((first, second)))
            previous = edge_face.get(edge)
            if previous is None:
                edge_face[edge] = face_index
                continue
            if previous < 0:
                raise ValueError(f"non-manifold natural mesh edge: {edge}")
            edge_face[edge] = -previous - 1
            if owners[previous] == owners[face_index]:
                union(previous, face_index)
            else:
                partition_edges.add(edge)
                adjacency.add(tuple(sorted((owners[previous], owners[face_index]))))
    for edge, marker in edge_face.items():
        if marker >= 0:
            corpus_edges.add(edge)

    face_histogram = Counter(owners)
    present = set(face_histogram)
    expected_ids = {cell.cell_id for cell in cells}
    empty = sorted(expected_ids - present)
    owner_roots: dict[int, set[int]] = defaultdict(set)
    for face_index, owner in enumerate(owners):
        owner_roots[owner].add(find(face_index))
    disconnected = {
        owner: len(roots) for owner, roots in owner_roots.items() if len(roots) != 1
    }

    expected_adjacency = _expected_adjacencies(cells)
    non_neighbor = sorted(adjacency - expected_adjacency)
    missing_neighbor = sorted(expected_adjacency - adjacency)
    cell_by_id = {cell.cell_id: cell for cell in cells}
    maximum_extent_m = 0.0
    per_cell_extent: dict[int, float] = defaultdict(float)
    for face, owner in zip(faces, owners, strict=True):
        center = cell_by_id[owner].center_m
        for vertex in face:
            point = points[vertex]
            distance = math.hypot(
                point[0] / COUNTS_PER_METRE - center[0],
                point[1] / COUNTS_PER_METRE - center[1],
            )
            per_cell_extent[owner] = max(per_cell_extent[owner], distance)
            maximum_extent_m = max(maximum_extent_m, distance)

    counts = list(face_histogram.values())
    evidence = {
        "faces_owned_once": len(owners) == len(faces),
        "empty_cells": len(empty),
        "empty_cell_examples": empty[:20],
        "disconnected_cells": len(disconnected),
        "disconnected_cell_examples": dict(list(sorted(disconnected.items()))[:20]),
        "physical_adjacencies": len(adjacency),
        "expected_canonical_adjacencies": len(expected_adjacency),
        "non_neighbor_adjacencies": len(non_neighbor),
        "non_neighbor_examples": [list(pair) for pair in non_neighbor[:20]],
        "missing_neighbor_adjacencies": len(missing_neighbor),
        "missing_neighbor_examples": [list(pair) for pair in missing_neighbor[:20]],
        "partition_edges": len(partition_edges),
        "corpus_edges": len(corpus_edges),
        "faces_per_cell": {
            "minimum": min(counts) if counts else 0,
            "mean": sum(counts) / len(counts) if counts else 0.0,
            "maximum": max(counts) if counts else 0,
        },
        "maximum_component_vertex_extent_m": maximum_extent_m,
        "components_with_extent_over_1024m": sum(
            extent >= 1024.0 for extent in per_cell_extent.values()
        ),
    }
    evidence["review_partition_checks_passed"] = not any(
        (
            empty,
            disconnected,
            evidence["components_with_extent_over_1024m"],
        )
    )
    evidence["canonical_six_neighbor_graph_exact"] = not any(
        (non_neighbor, missing_neighbor)
    )
    return frozenset(partition_edges), frozenset(corpus_edges), evidence


def build_natural_mesh(
    *,
    plan: AdaptiveRegionPlan,
    cells: Sequence[HexCell],
    dem: RasterMosaic,
    nlcd: RasterMosaic,
    max_input_points: int,
) -> NaturalMesh:
    try:
        from mathutils import Vector
        from mathutils.geometry import delaunay_2d_cdt
    except ImportError as error:  # pragma: no cover - Blender integration
        raise SystemExit("run this build through Blender so mathutils is available") from error

    if len(plan.points) > max_input_points:
        raise ValueError(
            f"adaptive plan has {len(plan.points):,} points; hard cap is "
            f"{max_input_points:,}"
        )
    point_index = {point: index for index, point in enumerate(plan.points)}
    constraints = sorted(
        {
            tuple(sorted((point_index[first], point_index[second])))
            for first, second in plan.water_segments
        }
    )
    anchor = (
        (plan.points[0][0] + plan.points[-1][0]) / 2.0,
        (min(point[1] for point in plan.points) + max(point[1] for point in plan.points))
        / 2.0,
    )
    vectors = [
        Vector((east - anchor[0], north - anchor[1]))
        for east, north in plan.points
    ]
    print(
        f"NATURAL_CDT_INPUT points={len(vectors)} constraints={len(constraints)}",
        flush=True,
    )
    output_vectors, output_edges, output_faces = delaunay_2d_cdt(
        vectors, constraints, [], 0, 1.0e-6, False
    )[:3]
    output_counts = [
        (
            round((point.x + anchor[0]) * COUNTS_PER_METRE),
            round((point.y + anchor[1]) * COUNTS_PER_METRE),
        )
        for point in output_vectors
    ]
    if len(set(output_counts)) != len(output_counts):
        raise ValueError("CDT vertices collide after 1/16-metre quantization")
    output_edge_set = {
        tuple(sorted((int(edge[0]), int(edge[1])))) for edge in output_edges
    }
    output_by_count = {point: index for index, point in enumerate(output_counts)}
    mandatory_output_edges: set[tuple[int, int]] = set()
    for first, second in plan.water_segments:
        key = tuple(
            sorted(
                (
                    output_by_count[(first[0] * COUNTS_PER_METRE, first[1] * COUNTS_PER_METRE)],
                    output_by_count[(second[0] * COUNTS_PER_METRE, second[1] * COUNTS_PER_METRE)],
                )
            )
        )
        mandatory_output_edges.add(key)
    constraint_evidence, protected_output_edges = _validate_constraint_chains(
        constraints=mandatory_output_edges,
        output_edges=output_edge_set,
        points=output_counts,
    )

    retained: list[tuple[tuple[int, int, int], HexCell]] = []
    discarded_faces = 0
    minimum_angle = 180.0
    maximum_edge_m = 0.0
    for raw_face in output_faces:
        if len(raw_face) != 3:
            raise ValueError("natural CDT emitted a non-triangular face")
        face = tuple(int(index) for index in raw_face)
        signed_area = _signed_twice_area(face, output_counts)
        if signed_area == 0:
            raise ValueError("natural CDT face collapsed after count quantization")
        if signed_area < 0:
            face = face[0], face[2], face[1]
        centroid = (
            round(sum(output_counts[index][0] for index in face) / 3.0),
            round(sum(output_counts[index][1] for index in face) / 3.0),
        )
        try:
            owner = locate_hex_cell_counts(*centroid)
        except ValueError:
            discarded_faces += 1
            continue
        retained.append((face, owner))
        minimum_angle = min(minimum_angle, _minimum_angle_degrees(face, output_counts))
        for first, second in zip(face, face[1:] + face[:1], strict=True):
            maximum_edge_m = max(
                maximum_edge_m,
                math.dist(output_counts[first], output_counts[second])
                / COUNTS_PER_METRE,
            )
    centroid_prepartition = Counter(owner.cell_id for _face, owner in retained)
    used = sorted({index for face, _owner in retained for index in face})
    compact = {source: index for index, source in enumerate(used)}
    points_counts = [output_counts[index] for index in used]
    faces = [tuple(compact[index] for index in face) for face, _owner in retained]
    preferred_owners = array("i", (owner.cell_id for _face, owner in retained))
    owners, graph_partition = _connected_graph_voronoi_owners(
        points=points_counts,
        faces=faces,
        cells=cells,
        preferred_owners=preferred_owners,
    )
    if any(owner < 0 for owner in owners):
        retained_face_indices = [
            index for index, owner in enumerate(owners) if owner >= 0
        ]
        faces = [faces[index] for index in retained_face_indices]
        owners = array("i", (owners[index] for index in retained_face_indices))
        retained_vertices = sorted({vertex for face in faces for vertex in face})
        second_compact = {
            source: index for index, source in enumerate(retained_vertices)
        }
        points_counts = [points_counts[index] for index in retained_vertices]
        faces = [
            tuple(second_compact[index] for index in face) for face in faces
        ]
        compact = {
            output_index: second_compact[first_compact_index]
            for output_index, first_compact_index in compact.items()
            if first_compact_index in second_compact
        }
    cell_by_id = {cell.cell_id: cell for cell in cells}
    q_values = array("i", (cell_by_id[owner].q for owner in owners))
    r_values = array("i", (cell_by_id[owner].r for owner in owners))
    input_flags = {
        (point[0] * COUNTS_PER_METRE, point[1] * COUNTS_PER_METRE): flag
        for point, flag in zip(plan.points, plan.point_source_flags, strict=True)
    }
    point_flags = array("i", (input_flags.get(point, 0) for point in points_counts))
    if sum(bool(flag & SOURCE_LOGICAL_SEED) for flag in point_flags) != len(cells):
        raise ValueError("retained master surface lost one or more logical seed anchors")

    partition_edges, corpus_edges, partition = _partition_evidence(
        points=points_counts,
        faces=faces,
        owners=owners,
        cells=cells,
    )
    if partition["empty_cells"] or partition["disconnected_cells"]:
        raise ValueError(
            "post-partition surface has empty or disconnected logical owners: "
            f"{partition}"
        )
    elevations, output_edge_padded = _sample_output_elevations(points_counts, dem)
    categories, materials, material_sampling = _sample_face_materials(
        points_counts, faces, elevations, nlcd
    )

    protected_water_edges: set[tuple[int, int]] = set()
    for first, second in protected_output_edges:
        if first in compact and second in compact:
            protected_water_edges.add(
                tuple(sorted((compact[first], compact[second])))
            )

    digest = hashlib.sha256()
    for point in points_counts:
        digest.update(struct.pack("<2i", *point))
    for face, owner in zip(faces, owners, strict=True):
        digest.update(struct.pack("<3II", *face, owner))
    evidence = {
        "adaptive_input_points": len(plan.points),
        "adaptive_point_histogram": dict(plan.selection_histogram),
        "water_constraint_segments": len(plan.water_segments),
        "water_constraint_validation": constraint_evidence,
        "cdt_output_vertices": len(output_vectors),
        "cdt_output_faces": len(output_faces),
        "discarded_outer_faces": discarded_faces,
        "retained_vertices": len(points_counts),
        "retained_faces": len(faces),
        "minimum_triangle_angle_degrees": minimum_angle,
        "maximum_triangle_edge_m": maximum_edge_m,
        "centroid_labeling_control": {
            "empty_cells": len(cells) - len(centroid_prepartition),
            "faces_per_present_cell": {
                "minimum": min(centroid_prepartition.values()),
                "mean": sum(centroid_prepartition.values()) / len(centroid_prepartition),
                "maximum": max(centroid_prepartition.values()),
            },
        },
        "graph_partition": graph_partition,
        "topology_and_ownership_sha256": digest.hexdigest(),
        "edge_padded_output_elevation_points": output_edge_padded,
        "material_sampling": material_sampling,
        "partition": partition,
    }
    return NaturalMesh(
        points_counts=points_counts,
        elevations_m=elevations,
        point_source_flags=point_flags,
        faces=faces,
        face_cell_ids=owners,
        face_q=q_values,
        face_r=r_values,
        face_categories=categories,
        face_material_ids=materials,
        partition_edges=partition_edges,
        protected_water_edges=frozenset(protected_water_edges),
        corpus_edges=corpus_edges,
        evidence=evidence,
    )


def _add_int_attribute(mesh, name: str, domain: str, values: Iterable[int]) -> None:
    payload = values if isinstance(values, array) else array("i", values)
    attribute = mesh.attributes.new(name=name, type="INT", domain=domain)
    attribute.data.foreach_set("value", payload)


def _add_boolean_attribute(mesh, name: str, values: Iterable[int]) -> None:
    attribute = mesh.attributes.new(name=name, type="BOOLEAN", domain="EDGE")
    attribute.data.foreach_set("value", array("b", values))


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


def build_scene(
    arguments: argparse.Namespace,
    product: NaturalMesh,
    cells: Sequence[HexCell],
    *,
    source_manifest_path: Path,
    source_manifest: dict,
    source_manifest_sha256: str,
    analysis: dict,
    timings: dict,
) -> dict:
    try:
        import bpy
        from mathutils import Vector
    except ImportError as error:  # pragma: no cover - Blender integration
        raise SystemExit("run this build through Blender so bpy is available") from error

    bpy.ops.wm.read_factory_settings(use_empty=True)
    terrain_collection = bpy.data.collections.new("NATURAL MASTER TERRAIN")
    diagnostics = bpy.data.collections.new("DIAGNOSTICS — toggle visibility")
    bpy.context.scene.collection.children.link(terrain_collection)
    bpy.context.scene.collection.children.link(diagnostics)
    center_east = (
        analysis["analysis_grid"]["bounds_m"][0]
        + analysis["analysis_grid"]["bounds_m"][2]
    ) / 2.0
    center_north = (
        analysis["analysis_grid"]["bounds_m"][1]
        + analysis["analysis_grid"]["bounds_m"][3]
    ) / 2.0
    vertices = [
        (
            (east / COUNTS_PER_METRE - center_east) * arguments.display_scale,
            (north / COUNTS_PER_METRE - center_north) * arguments.display_scale,
            elevation
            * arguments.display_scale
            * arguments.vertical_exaggeration,
        )
        for (east, north), elevation in zip(
            product.points_counts, product.elevations_m, strict=True
        )
    ]
    mesh = bpy.data.meshes.new("Bay Area natural adaptive master surface")
    mesh.from_pydata(vertices, (), product.faces)
    mesh.update(calc_edges=True)
    terrain = bpy.data.objects.new(
        "Bay Area — NATURAL MASTER — post-partition face ownership", mesh
    )
    terrain_collection.objects.link(terrain)
    for material in _create_materials(bpy):
        mesh.materials.append(material)
    mesh.polygons.foreach_set("material_index", product.face_material_ids)
    _add_int_attribute(mesh, "hex_cell_id", "FACE", product.face_cell_ids)
    _add_int_attribute(mesh, "hex_q", "FACE", product.face_q)
    _add_int_attribute(mesh, "hex_r", "FACE", product.face_r)
    _add_int_attribute(mesh, "terrain_material_id", "FACE", product.face_material_ids)
    _add_int_attribute(mesh, "nlcd_category", "FACE", product.face_categories)
    _add_int_attribute(
        mesh,
        "utm_easting_count",
        "POINT",
        (point[0] for point in product.points_counts),
    )
    _add_int_attribute(
        mesh,
        "utm_northing_count",
        "POINT",
        (point[1] for point in product.points_counts),
    )
    _add_int_attribute(mesh, "adaptive_source_flags", "POINT", product.point_source_flags)
    elevation_attribute = mesh.attributes.new(
        name="elevation_navd88_m", type="FLOAT", domain="POINT"
    )
    elevation_attribute.data.foreach_set("value", product.elevations_m)
    _add_boolean_attribute(
        mesh,
        "physical_partition_boundary",
        (
            int(tuple(sorted(edge.vertices)) in product.partition_edges)
            for edge in mesh.edges
        ),
    )
    _add_boolean_attribute(
        mesh,
        "protected_water_edge",
        (
            int(tuple(sorted(edge.vertices)) in product.protected_water_edges)
            for edge in mesh.edges
        ),
    )
    _add_boolean_attribute(
        mesh,
        "corpus_boundary",
        (
            int(tuple(sorted(edge.vertices)) in product.corpus_edges)
            for edge in mesh.edges
        ),
    )
    terrain["artifact_role"] = "natural master surface; review only"
    terrain["build_order"] = "surface first; logical face ownership second"
    terrain["flat_shading"] = True
    terrain["logical_cells"] = len(cells)
    terrain["partition_checks_passed"] = product.evidence["partition"][
        "review_partition_checks_passed"
    ]

    boundary_mesh = bpy.data.meshes.new("Physical partition boundary diagnostics")
    boundary_mesh.from_pydata(vertices, sorted(product.partition_edges), ())
    boundary_mesh.update()
    boundary_object = bpy.data.objects.new(
        "DIAGNOSTIC — irregular physical partition edges", boundary_mesh
    )
    diagnostics.objects.link(boundary_object)
    boundary_object.display_type = "WIRE"
    boundary_object.hide_render = True
    boundary_object.hide_set(True)

    point_by_count = {
        point: index for index, point in enumerate(product.points_counts)
    }
    seed_indices = [
        point_by_count[(cell.center_m[0] * COUNTS_PER_METRE, cell.center_m[1] * COUNTS_PER_METRE)]
        for cell in cells
    ]
    seed_vertices = [vertices[index] for index in seed_indices]
    seed_mesh = bpy.data.meshes.new("Logical axial seed diagnostics")
    seed_mesh.from_pydata(seed_vertices, (), ())
    seed_mesh.update()
    _add_int_attribute(seed_mesh, "hex_cell_id", "POINT", (cell.cell_id for cell in cells))
    _add_int_attribute(seed_mesh, "hex_q", "POINT", (cell.q for cell in cells))
    _add_int_attribute(seed_mesh, "hex_r", "POINT", (cell.r for cell in cells))
    seed_object = bpy.data.objects.new("DIAGNOSTIC — 50,183 logical seeds", seed_mesh)
    diagnostics.objects.link(seed_object)
    seed_object.hide_render = True
    seed_object.hide_set(True)

    sun_data = bpy.data.lights.new("Natural terrain review sun", type="SUN")
    sun_data.energy = 2.5
    sun_data.angle = math.radians(12.0)
    sun = bpy.data.objects.new("Natural terrain review sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.location = Vector((-80.0, -95.0, 95.0))
    sun.rotation_euler = (
        Vector((0.0, 0.0, 0.0)) - sun.location
    ).to_track_quat("-Z", "Y").to_euler()

    world = bpy.data.worlds.new("Bay Area natural terrain daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.055,
        0.075,
        0.11,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55

    camera_data = bpy.data.cameras.new("Full natural Bay Area overview camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 185.0
    camera_data.clip_end = 1_000.0
    camera = bpy.data.objects.new("Full natural Bay Area overview camera", camera_data)
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

    metadata = {
        **analysis,
        "region_id": source_manifest["region_id"],
        "source_manifest": str(source_manifest_path),
        "source_manifest_sha256": source_manifest_sha256,
        "source_datasets": [
            {
                "id": dataset["id"],
                "crs": dataset["crs"],
                "tiles": len(dataset["tiles"]),
            }
            for dataset in source_manifest["datasets"]
        ],
        "projected_crs": f"EPSG:{REGIONAL_EPSG}",
        "mesh": product.evidence,
        "elevation_m": [min(product.elevations_m), max(product.elevations_m)],
        "material_face_histogram": {
            str(key): value
            for key, value in sorted(Counter(product.face_material_ids).items())
        },
        "nlcd_face_histogram": {
            str(key): value
            for key, value in sorted(Counter(product.face_categories).items())
        },
        "display": {
            "scale": arguments.display_scale,
            "vertical_exaggeration": arguments.vertical_exaggeration,
            "origin_utm_m": [center_east, center_north, 0.0],
        },
        "timings_seconds": timings,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "omitted_from_first_experiment": [
            "runtime P3DM component emission",
            "mixed-distance LOD transitions",
            "skirts and crack repair",
            "airport replacement meshes",
            "vector streams and roads",
            "DEM ridge constraints beyond numerical adaptive samples",
            "collision and hardware qualification",
            "outer-corpus edge repair",
        ],
        "material_vocabulary": [
            {
                "material_id": material.material_id,
                "nlcd_category": material.nlcd_category,
                "name": material.name,
                "rgb": list(material.rgb),
            }
            for material in BERKELEY_TERRAIN_MATERIALS
        ],
        "build_script_sha256": sha256_file(Path(__file__)),
        "selector_module_sha256": sha256_file(
            ROOT / "src/pingo_terrain/natural_region.py"
        ),
    }
    scene["artifact_schema"] = ARTIFACT_SCHEMA
    scene["artifact_role"] = metadata["artifact_role"]
    scene["source_manifest_sha256"] = source_manifest_sha256
    scene["logical_cells"] = len(cells)
    scene["natural_vertices"] = len(product.points_counts)
    scene["natural_faces"] = len(product.faces)
    scene["partition_checks_passed"] = product.evidence["partition"][
        "review_partition_checks_passed"
    ]
    scene["topology_and_ownership_sha256"] = product.evidence[
        "topology_and_ownership_sha256"
    ]
    scene["review_metadata_json"] = json.dumps(
        metadata, sort_keys=True, separators=(",", ":")
    )

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
    started = time.perf_counter()
    arguments = parse_arguments(argv)
    profile = profile_from_arguments(arguments)
    profile.validate()
    cells = tuple(iter_cells())
    grid = analysis_grid(cells, profile)
    analysis = plan_summary(cells, grid, profile)
    print("NATURAL_PLAN", json.dumps(analysis, sort_keys=True), flush=True)
    if arguments.plan_only:
        return 0

    source_manifest_path = arguments.source_manifest.expanduser().resolve()
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = json.loads(source_manifest_bytes)
    if not arguments.skip_source_hash:
        regional_blender.verify_sources(ROOT, source_manifest)
    datasets = {dataset["id"]: dataset for dataset in source_manifest["datasets"]}
    dem = RasterMosaic(ROOT, datasets[DEM_DATASET_ID])
    nlcd = RasterMosaic(ROOT, datasets[NLCD_DATASET_ID], cache_blocks_per_tile=12)

    sample_started = time.perf_counter()
    samples = sample_analysis_grid(grid, dem, nlcd)
    sample_finished = time.perf_counter()
    adaptive_plan = build_adaptive_region_plan(
        origin_m=grid.origin_m,
        columns=grid.columns,
        rows=grid.rows,
        heights_m=samples.heights_m,
        categories=samples.categories,
        logical_seed_points_m=(cell.center_m for cell in cells),
        profile=profile,
    )
    selection_finished = time.perf_counter()
    print(
        "NATURAL_SELECTION",
        f"points={len(adaptive_plan.points)}",
        f"water_segments={len(adaptive_plan.water_segments)}",
        f"histogram={dict(adaptive_plan.selection_histogram)}",
        flush=True,
    )
    product = build_natural_mesh(
        plan=adaptive_plan,
        cells=cells,
        dem=dem,
        nlcd=nlcd,
        max_input_points=arguments.max_input_points,
    )
    mesh_finished = time.perf_counter()
    analysis["analysis_sampling"] = {
        "edge_padded_dem_points": samples.edge_padded_dem_points,
        "edge_padded_nlcd_points": samples.edge_padded_nlcd_points,
        "nodata_nlcd_points": samples.nodata_nlcd_points,
    }
    timings = {
        "source_grid_sampling": sample_finished - sample_started,
        "adaptive_selection": selection_finished - sample_finished,
        "cdt_partition_and_output_sampling": mesh_finished - selection_finished,
    }
    metadata = build_scene(
        arguments,
        product,
        cells,
        source_manifest_path=source_manifest_path,
        source_manifest=source_manifest,
        source_manifest_sha256=hashlib.sha256(source_manifest_bytes).hexdigest(),
        analysis=analysis,
        timings=timings,
    )
    receipt = write_receipt(arguments.output, metadata)
    finished = time.perf_counter()
    print(
        "NATURAL_REGION",
        f"cells={len(cells)}",
        f"vertices={len(product.points_counts)}",
        f"faces={len(product.faces)}",
        f"partition_checks={product.evidence['partition']['review_partition_checks_passed']}",
        f"elapsed={finished - started:.3f}s",
        f"output={arguments.output}",
        f"receipt={receipt}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
