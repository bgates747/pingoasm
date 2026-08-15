"""Deterministic categorical contours and canonical constraint crossings.

This module deliberately contains no Blender dependency.  It turns a pinned
categorical raster component into one closed source contour, provides the
small controlled smoothing used by the Lake Anza experiment, and reconciles a
feature loop with exact integer terrain-cell boundary segments.  Blender's
compiled constrained-Delaunay implementation consumes the resulting vertices
and edges; it is not allowed to invent cell-crossing identities independently.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
import math
from typing import Iterable, Sequence

from .regional_raster import RasterMosaic


Point = tuple[float, float]
CountPoint = tuple[int, int]
CountSegment = tuple[CountPoint, CountPoint]


@dataclass(frozen=True, slots=True)
class RasterComponent:
    """One four-connected categorical component on a raster's global grid."""

    category: int
    cells: frozenset[tuple[int, int]]
    centers: tuple[Point, ...]
    boundary: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class ReconciledConstraints:
    """A feature loop and terrain segments split at identical exact points."""

    feature_loop: tuple[CountPoint, ...]
    terrain_segments: tuple[CountSegment, ...]
    crossing_points: tuple[CountPoint, ...]


def signed_area(points: Sequence[tuple[float, float] | CountPoint]) -> float:
    """Return a closed polygon's signed area; positive means counter-clockwise."""

    if len(points) < 3:
        return 0.0
    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, points[1:] + points[:1], strict=True)
    )


def polygon_centroid(points: Sequence[Point]) -> Point:
    """Return the area centroid of one nondegenerate simple polygon."""

    twice_area = 2.0 * signed_area(points)
    if twice_area == 0.0:
        raise ValueError("polygon has zero area")
    east_sum = north_sum = 0.0
    for first, second in zip(points, points[1:] + points[:1], strict=True):
        cross = first[0] * second[1] - second[0] * first[1]
        east_sum += (first[0] + second[0]) * cross
        north_sum += (first[1] + second[1]) * cross
    scale = 3.0 * twice_area
    return east_sum / scale, north_sum / scale


def _grid_key(raster: RasterMosaic, x: float, y: float) -> tuple[int, int]:
    return (
        round((x - raster.west) / raster.pixel_size_x - 0.5),
        round((raster.north - y) / raster.pixel_size_y - 0.5),
    )


def _grid_center(raster: RasterMosaic, key: tuple[int, int]) -> Point:
    column, row = key
    return (
        raster.west + (column + 0.5) * raster.pixel_size_x,
        raster.north - (row + 0.5) * raster.pixel_size_y,
    )


def _component_boundary(
    raster: RasterMosaic, cells: frozenset[tuple[int, int]]
) -> tuple[Point, ...]:
    """Trace the exterior of a four-connected union of raster rectangles."""

    edge_counts: Counter[tuple[Point, Point]] = Counter()
    oriented: dict[tuple[Point, Point], tuple[Point, Point]] = {}
    for column, row in sorted(cells):
        west = raster.west + column * raster.pixel_size_x
        east = west + raster.pixel_size_x
        north = raster.north - row * raster.pixel_size_y
        south = north - raster.pixel_size_y
        # Counter-clockwise around one source pixel.
        corners = ((west, south), (east, south), (east, north), (west, north))
        for first, second in zip(corners, corners[1:] + corners[:1], strict=True):
            key = tuple(sorted((first, second)))
            edge_counts[key] += 1
            oriented[key] = first, second

    boundary_edges = tuple(
        oriented[key] for key in sorted(edge_counts) if edge_counts[key] == 1
    )
    outgoing: dict[Point, list[Point]] = defaultdict(list)
    for first, second in boundary_edges:
        outgoing[first].append(second)
    if any(len(values) != 1 for values in outgoing.values()):
        raise ValueError("categorical boundary is not a set of simple loops")

    unused = set(boundary_edges)
    loops: list[tuple[Point, ...]] = []
    while unused:
        first_edge = min(unused)
        start, current = first_edge
        loop = [start]
        unused.remove(first_edge)
        while current != start:
            loop.append(current)
            following = outgoing[current][0]
            edge = current, following
            if edge not in unused:
                raise ValueError("categorical boundary loop is open or self-touching")
            unused.remove(edge)
            current = following
        loops.append(tuple(loop))

    if not loops:
        raise ValueError("categorical component has no boundary")
    exterior = max(loops, key=lambda loop: abs(signed_area(loop)))
    if signed_area(exterior) < 0.0:
        exterior = tuple(reversed(exterior))
    return exterior


def extract_raster_component(
    raster: RasterMosaic,
    *,
    category: int,
    reference: Point,
    bounds: tuple[float, float, float, float],
) -> RasterComponent:
    """Extract the category component nearest ``reference`` within ``bounds``.

    Connectivity is four-neighbor connectivity.  That avoids joining two
    water bodies that merely touch at one raster corner.
    """

    west, south, east, north = bounds
    candidates: dict[tuple[int, int], Point] = {}
    for x, y, value, _nodata in raster.cells_in_bbox(west, south, east, north):
        if value == category:
            candidates[_grid_key(raster, x, y)] = (x, y)
    if not candidates:
        raise ValueError(f"no category {category} cells in requested bounds")

    seed = min(
        candidates,
        key=lambda key: (
            (candidates[key][0] - reference[0]) ** 2
            + (candidates[key][1] - reference[1]) ** 2,
            key,
        ),
    )
    component = {seed}
    pending = deque((seed,))
    while pending:
        column, row = pending.popleft()
        for neighbor in (
            (column - 1, row),
            (column + 1, row),
            (column, row - 1),
            (column, row + 1),
        ):
            if neighbor in candidates and neighbor not in component:
                component.add(neighbor)
                pending.append(neighbor)
    frozen = frozenset(component)
    return RasterComponent(
        category=category,
        cells=frozen,
        centers=tuple(_grid_center(raster, key) for key in sorted(frozen)),
        boundary=_component_boundary(raster, frozen),
    )


def chaikin_closed(points: Sequence[Point], *, iterations: int = 2) -> tuple[Point, ...]:
    """Corner-cut one closed loop without inventing geographic control points."""

    if iterations < 0:
        raise ValueError("Chaikin iteration count cannot be negative")
    result = tuple(points)
    if len(result) < 3:
        raise ValueError("closed smoothing requires at least three points")
    for _ in range(iterations):
        refined: list[Point] = []
        for first, second in zip(result, result[1:] + result[:1], strict=True):
            refined.extend(
                (
                    (
                        0.75 * first[0] + 0.25 * second[0],
                        0.75 * first[1] + 0.25 * second[1],
                    ),
                    (
                        0.25 * first[0] + 0.75 * second[0],
                        0.25 * first[1] + 0.75 * second[1],
                    ),
                )
            )
        result = tuple(refined)
    return result


def cyclic_corner_smooth(points: Sequence[Point], *, iterations: int = 1) -> tuple[Point, ...]:
    """Apply a fixed cyclic 1-2-1 filter while retaining contour cardinality.

    Unlike subdivision, this creates no additional control vertices.  One pass
    rounds a 30-metre raster staircase without pretending that the source
    supports detail below its pixel scale.
    """

    if iterations < 0:
        raise ValueError("corner-smoothing iteration count cannot be negative")
    result = tuple(points)
    if len(result) < 3:
        raise ValueError("closed smoothing requires at least three points")
    for _ in range(iterations):
        result = tuple(
            (
                (result[index - 1][0] + 2.0 * point[0] + result[(index + 1) % len(result)][0])
                / 4.0,
                (result[index - 1][1] + 2.0 * point[1] + result[(index + 1) % len(result)][1])
                / 4.0,
            )
            for index, point in enumerate(result)
        )
    return result


def quantize_loop(points: Sequence[Point], *, counts_per_metre: int) -> tuple[CountPoint, ...]:
    """Quantize a loop and remove only consecutive collisions."""

    if counts_per_metre <= 0:
        raise ValueError("counts_per_metre must be positive")
    result: list[CountPoint] = []
    for point in points:
        encoded = (
            round(point[0] * counts_per_metre),
            round(point[1] * counts_per_metre),
        )
        if not result or result[-1] != encoded:
            result.append(encoded)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    if len(result) < 3 or signed_area(result) == 0.0:
        raise ValueError("quantization collapsed the feature loop")
    if signed_area(result) < 0.0:
        result.reverse()
    return tuple(result)


def _cross(first: CountPoint, second: CountPoint) -> int:
    return first[0] * second[1] - first[1] * second[0]


def _subtract(first: CountPoint, second: CountPoint) -> CountPoint:
    return first[0] - second[0], first[1] - second[1]


def _canonical_segment(segment: CountSegment) -> CountSegment:
    return tuple(sorted(segment))


def _snap_to_segment(
    segment: CountSegment, parameter: Fraction
) -> tuple[CountPoint, Fraction]:
    """Snap a rational position to the segment's finest exact integer step."""

    first, second = segment
    delta = second[0] - first[0], second[1] - first[1]
    divisions = math.gcd(abs(delta[0]), abs(delta[1]))
    if divisions == 0:
        raise ValueError("cannot snap to a zero-length segment")
    step = delta[0] // divisions, delta[1] // divisions
    ordinal = min(divisions, max(0, round(parameter * divisions)))
    return (
        (first[0] + ordinal * step[0], first[1] + ordinal * step[1]),
        Fraction(ordinal, divisions),
    )


def reconcile_feature_crossings(
    feature_loop: Sequence[CountPoint],
    terrain_segments: Iterable[CountSegment],
) -> ReconciledConstraints:
    """Split feature and cell edges at common canonical crossing points.

    The feature is intentionally allowed to extend beyond a target cell.  This
    routine reconciles it against all target cell cuts *before* triangulation,
    so the later overbuild-and-clip operation gives both owners the identical
    crossing key.
    """

    feature = tuple(feature_loop)
    if len(feature) < 3:
        raise ValueError("feature loop requires at least three points")
    terrain = tuple(sorted({_canonical_segment(segment) for segment in terrain_segments}))
    feature_splits: dict[int, list[tuple[Fraction, CountPoint]]] = defaultdict(list)
    terrain_splits: dict[int, list[tuple[Fraction, CountPoint]]] = defaultdict(list)
    crossings: set[CountPoint] = set()

    for feature_index, (feature_first, feature_second) in enumerate(
        zip(feature, feature[1:] + feature[:1], strict=True)
    ):
        feature_delta = _subtract(feature_second, feature_first)
        for terrain_index, terrain_segment in enumerate(terrain):
            terrain_first, terrain_second = terrain_segment
            terrain_delta = _subtract(terrain_second, terrain_first)
            denominator = _cross(feature_delta, terrain_delta)
            if denominator == 0:
                continue
            offset = _subtract(terrain_first, feature_first)
            feature_parameter = Fraction(_cross(offset, terrain_delta), denominator)
            terrain_parameter = Fraction(_cross(offset, feature_delta), denominator)
            if not (
                Fraction(0) <= feature_parameter <= Fraction(1)
                and Fraction(0) <= terrain_parameter <= Fraction(1)
            ):
                continue
            point, snapped_parameter = _snap_to_segment(
                terrain_segment, terrain_parameter
            )
            # Order on the feature's original segment.  Projection remains
            # deterministic even though snapping moves the point very slightly.
            feature_length_squared = (
                feature_delta[0] ** 2 + feature_delta[1] ** 2
            )
            projected_parameter = Fraction(
                (point[0] - feature_first[0]) * feature_delta[0]
                + (point[1] - feature_first[1]) * feature_delta[1],
                feature_length_squared,
            )
            projected_parameter = min(Fraction(1), max(Fraction(0), projected_parameter))
            feature_splits[feature_index].append((projected_parameter, point))
            terrain_splits[terrain_index].append((snapped_parameter, point))
            crossings.add(point)

    expanded_feature: list[CountPoint] = []
    for index, first in enumerate(feature):
        values = [(Fraction(0), first), *feature_splits.get(index, ())]
        for _parameter, point in sorted(set(values)):
            if not expanded_feature or expanded_feature[-1] != point:
                expanded_feature.append(point)
    if len(expanded_feature) > 1 and expanded_feature[0] == expanded_feature[-1]:
        expanded_feature.pop()

    expanded_terrain: set[CountSegment] = set()
    for index, (first, second) in enumerate(terrain):
        values = [
            (Fraction(0), first),
            *terrain_splits.get(index, ()),
            (Fraction(1), second),
        ]
        ordered: list[CountPoint] = []
        for _parameter, point in sorted(set(values)):
            if not ordered or ordered[-1] != point:
                ordered.append(point)
        for start, end in zip(ordered, ordered[1:]):
            if start != end:
                expanded_terrain.add(_canonical_segment((start, end)))

    return ReconciledConstraints(
        feature_loop=tuple(expanded_feature),
        terrain_segments=tuple(sorted(expanded_terrain)),
        crossing_points=tuple(sorted(crossings)),
    )


def point_on_segment(point: CountPoint, segment: CountSegment) -> bool:
    first, second = segment
    if _cross(_subtract(point, first), _subtract(second, first)) != 0:
        return False
    return (
        min(first[0], second[0]) <= point[0] <= max(first[0], second[0])
        and min(first[1], second[1]) <= point[1] <= max(first[1], second[1])
    )


def point_in_polygon(point: CountPoint, polygon: Sequence[CountPoint]) -> bool:
    """Return true for points inside or on the boundary of a simple polygon."""

    inside = False
    for first, second in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if point_on_segment(point, (first, second)):
            return True
        if (first[1] > point[1]) == (second[1] > point[1]):
            continue
        intersection_x = first[0] + Fraction(
            (point[1] - first[1]) * (second[0] - first[0]),
            second[1] - first[1],
        )
        if intersection_x > point[0]:
            inside = not inside
    return inside
