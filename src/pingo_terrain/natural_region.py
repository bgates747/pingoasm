"""Adaptive full-region sample selection for the natural-mesh experiment.

The module is deliberately independent of Blender.  It chooses a bounded set
of DEM samples, extracts provisional water-transition constraints from a
regular analysis grid, and records why every retained point exists.  Blender's
compiled constrained-Delaunay implementation consumes the resulting plan.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


PointM = tuple[int, int]
SegmentM = tuple[PointM, PointM]

SOURCE_LOGICAL_SEED = 1 << 0
SOURCE_DEM_RESIDUAL = 1 << 1
SOURCE_DEM_CURVATURE = 1 << 2
SOURCE_WATER_NEIGHBOR = 1 << 3
SOURCE_WATER_CONSTRAINT = 1 << 4
SOURCE_CORPUS_EDGE = 1 << 5


@dataclass(frozen=True, slots=True)
class AdaptiveRegionProfile:
    analysis_step_m: int = 128
    middle_stride: int = 2
    coarse_stride: int = 4
    middle_residual_m: float = 4.0
    coarse_residual_m: float = 10.0
    curvature_residual_m: float = 7.0
    corpus_edge_stride: int = 4
    water_category: int = 11

    def validate(self) -> None:
        if self.analysis_step_m <= 0 or self.analysis_step_m % 2:
            raise ValueError("analysis step must be a positive even number")
        if self.middle_stride < 1 or self.coarse_stride <= self.middle_stride:
            raise ValueError("adaptive strides must be increasing positive integers")
        if self.coarse_stride % self.middle_stride:
            raise ValueError("coarse stride must be divisible by middle stride")
        if self.corpus_edge_stride < 1:
            raise ValueError("corpus edge stride must be positive")
        if min(
            self.middle_residual_m,
            self.coarse_residual_m,
            self.curvature_residual_m,
        ) < 0.0:
            raise ValueError("adaptive error thresholds cannot be negative")


@dataclass(frozen=True, slots=True)
class AdaptiveRegionPlan:
    origin_m: PointM
    columns: int
    rows: int
    profile: AdaptiveRegionProfile
    points: tuple[PointM, ...]
    point_source_flags: tuple[int, ...]
    water_segments: tuple[SegmentM, ...]
    selection_histogram: tuple[tuple[str, int], ...]


def _canonical_segment(first: PointM, second: PointM) -> SegmentM:
    if first == second:
        raise ValueError("constraint segment cannot have zero length")
    return tuple(sorted((first, second)))


def _grid_value(values: Sequence[float] | Sequence[int], columns: int, i: int, j: int):
    return values[j * columns + i]


def _interpolated_height(
    heights: Sequence[float],
    columns: int,
    rows: int,
    i: int,
    j: int,
    stride: int,
) -> float:
    i0 = (i // stride) * stride
    j0 = (j // stride) * stride
    i1 = min(columns - 1, i0 + stride)
    j1 = min(rows - 1, j0 + stride)
    if i0 == i1 and j0 == j1:
        return float(_grid_value(heights, columns, i, j))
    if i0 == i1:
        fy = (j - j0) / (j1 - j0)
        return (
            float(_grid_value(heights, columns, i0, j0)) * (1.0 - fy)
            + float(_grid_value(heights, columns, i0, j1)) * fy
        )
    if j0 == j1:
        fx = (i - i0) / (i1 - i0)
        return (
            float(_grid_value(heights, columns, i0, j0)) * (1.0 - fx)
            + float(_grid_value(heights, columns, i1, j0)) * fx
        )
    fx = (i - i0) / (i1 - i0)
    fy = (j - j0) / (j1 - j0)
    south = (
        float(_grid_value(heights, columns, i0, j0)) * (1.0 - fx)
        + float(_grid_value(heights, columns, i1, j0)) * fx
    )
    north = (
        float(_grid_value(heights, columns, i0, j1)) * (1.0 - fx)
        + float(_grid_value(heights, columns, i1, j1)) * fx
    )
    return south * (1.0 - fy) + north * fy


# Edge numbers are south, east, north, west.  Ambiguous diagonal-water cases
# preserve four-connectivity by enclosing each water corner independently.
_MARCHING_SEGMENTS: dict[int, tuple[tuple[int, int], ...]] = {
    0: (),
    1: ((3, 0),),
    2: ((0, 1),),
    3: ((3, 1),),
    4: ((1, 2),),
    5: ((3, 0), (1, 2)),
    6: ((0, 2),),
    7: ((2, 3),),
    8: ((2, 3),),
    9: ((2, 0),),
    10: ((0, 1), (2, 3)),
    11: ((1, 2),),
    12: ((1, 3),),
    13: ((0, 1),),
    14: ((3, 0),),
    15: (),
}


def marching_water_segments(
    *,
    origin_m: PointM,
    columns: int,
    rows: int,
    step_m: int,
    categories: Sequence[int],
    water_category: int = 11,
) -> tuple[SegmentM, ...]:
    """Extract deterministic half-grid water constraints over the analysis grid."""

    if columns < 2 or rows < 2:
        raise ValueError("marching grid requires at least two rows and columns")
    if len(categories) != columns * rows:
        raise ValueError("category count does not match marching grid")
    if step_m <= 0 or step_m % 2:
        raise ValueError("marching step must be a positive even number")
    half = step_m // 2
    segments: set[SegmentM] = set()
    for j in range(rows - 1):
        south = origin_m[1] + j * step_m
        for i in range(columns - 1):
            west = origin_m[0] + i * step_m
            southwest = int(_grid_value(categories, columns, i, j)) == water_category
            southeast = int(_grid_value(categories, columns, i + 1, j)) == water_category
            northeast = int(_grid_value(categories, columns, i + 1, j + 1)) == water_category
            northwest = int(_grid_value(categories, columns, i, j + 1)) == water_category
            case = (
                int(southwest)
                | (int(southeast) << 1)
                | (int(northeast) << 2)
                | (int(northwest) << 3)
            )
            edge_points = (
                (west + half, south),
                (west + step_m, south + half),
                (west + half, south + step_m),
                (west, south + half),
            )
            for first_edge, second_edge in _MARCHING_SEGMENTS[case]:
                segments.add(
                    _canonical_segment(
                        edge_points[first_edge], edge_points[second_edge]
                    )
                )
    return tuple(sorted(segments))


def build_adaptive_region_plan(
    *,
    origin_m: PointM,
    columns: int,
    rows: int,
    heights_m: Sequence[float],
    categories: Sequence[int],
    logical_seed_points_m: Iterable[PointM],
    profile: AdaptiveRegionProfile = AdaptiveRegionProfile(),
) -> AdaptiveRegionPlan:
    """Select natural-mesh inputs and provisional protected water edges."""

    profile.validate()
    expected = columns * rows
    if columns < 2 or rows < 2 or len(heights_m) != expected:
        raise ValueError("height count does not match adaptive grid")
    if len(categories) != expected:
        raise ValueError("category count does not match adaptive grid")
    if any(not math.isfinite(float(value)) for value in heights_m):
        raise ValueError("adaptive grid contains a non-finite height")

    step = profile.analysis_step_m
    source_flags: dict[PointM, int] = {}

    def retain(point: PointM, flag: int) -> None:
        source_flags[point] = source_flags.get(point, 0) | flag

    east_limit = origin_m[0] + (columns - 1) * step
    north_limit = origin_m[1] + (rows - 1) * step
    seed_points: set[PointM] = set()
    for raw_point in logical_seed_points_m:
        point = int(raw_point[0]), int(raw_point[1])
        if point[0] != raw_point[0] or point[1] != raw_point[1]:
            raise ValueError(f"logical seed is not an integral metre point: {raw_point}")
        if not (
            origin_m[0] <= point[0] <= east_limit
            and origin_m[1] <= point[1] <= north_limit
        ):
            raise ValueError(f"logical seed is outside the analysis grid: {point}")
        if point in seed_points:
            raise ValueError(f"duplicate logical seed point: {point}")
        seed_points.add(point)
        retain(point, SOURCE_LOGICAL_SEED)

    for j in range(rows):
        north = origin_m[1] + j * step
        for i in range(columns):
            east = origin_m[0] + i * step
            point = east, north
            horizontal_edge_sample = j in (0, rows - 1) and (
                i % profile.corpus_edge_stride == 0 or i == columns - 1
            )
            vertical_edge_sample = i in (0, columns - 1) and (
                j % profile.corpus_edge_stride == 0 or j == rows - 1
            )
            if horizontal_edge_sample or vertical_edge_sample:
                retain(point, SOURCE_CORPUS_EDGE)

            value = float(_grid_value(heights_m, columns, i, j))
            if i % profile.middle_stride == 0 and j % profile.middle_stride == 0:
                residual = abs(
                    value
                    - _interpolated_height(
                        heights_m,
                        columns,
                        rows,
                        i,
                        j,
                        profile.coarse_stride,
                    )
                )
                if residual > profile.coarse_residual_m:
                    retain(point, SOURCE_DEM_RESIDUAL)

            residual = abs(
                value
                - _interpolated_height(
                    heights_m,
                    columns,
                    rows,
                    i,
                    j,
                    profile.middle_stride,
                )
            )
            if residual > profile.middle_residual_m:
                retain(point, SOURCE_DEM_RESIDUAL)

            if 0 < i < columns - 1 and 0 < j < rows - 1:
                dxx = (
                    float(_grid_value(heights_m, columns, i - 1, j))
                    + float(_grid_value(heights_m, columns, i + 1, j))
                    - 2.0 * value
                )
                dyy = (
                    float(_grid_value(heights_m, columns, i, j - 1))
                    + float(_grid_value(heights_m, columns, i, j + 1))
                    - 2.0 * value
                )
                dxy = 0.25 * (
                    float(_grid_value(heights_m, columns, i + 1, j + 1))
                    - float(_grid_value(heights_m, columns, i - 1, j + 1))
                    - float(_grid_value(heights_m, columns, i + 1, j - 1))
                    + float(_grid_value(heights_m, columns, i - 1, j - 1))
                )
                # Frobenius norm of the discrete Hessian.  Unlike the
                # Laplacian alone, this retains mixed-curvature saddles.
                curvature = math.sqrt(dxx * dxx + dyy * dyy + 2.0 * dxy * dxy)
                if curvature > profile.curvature_residual_m:
                    retain(point, SOURCE_DEM_CURVATURE)

            water = int(_grid_value(categories, columns, i, j)) == profile.water_category
            for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor_i, neighbor_j = i + di, j + dj
                if not (0 <= neighbor_i < columns and 0 <= neighbor_j < rows):
                    continue
                neighbor_water = (
                    int(
                        _grid_value(
                            categories, columns, neighbor_i, neighbor_j
                        )
                    )
                    == profile.water_category
                )
                if neighbor_water != water:
                    retain(point, SOURCE_WATER_NEIGHBOR)
                    break

    water_segments = marching_water_segments(
        origin_m=origin_m,
        columns=columns,
        rows=rows,
        step_m=step,
        categories=categories,
        water_category=profile.water_category,
    )
    for first, second in water_segments:
        retain(first, SOURCE_WATER_CONSTRAINT)
        retain(second, SOURCE_WATER_CONSTRAINT)

    points = tuple(sorted(source_flags))
    flags = tuple(source_flags[point] for point in points)
    named_flags = (
        ("logical_seed", SOURCE_LOGICAL_SEED),
        ("dem_residual", SOURCE_DEM_RESIDUAL),
        ("dem_curvature", SOURCE_DEM_CURVATURE),
        ("water_neighbor", SOURCE_WATER_NEIGHBOR),
        ("water_constraint", SOURCE_WATER_CONSTRAINT),
        ("corpus_edge", SOURCE_CORPUS_EDGE),
    )
    histogram = tuple(
        (name, sum(bool(value & flag) for value in flags))
        for name, flag in named_flags
    )
    return AdaptiveRegionPlan(
        origin_m=origin_m,
        columns=columns,
        rows=rows,
        profile=profile,
        points=points,
        point_source_flags=flags,
        water_segments=water_segments,
        selection_histogram=histogram,
    )
