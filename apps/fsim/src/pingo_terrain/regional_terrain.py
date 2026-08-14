"""Deterministic triangular-lattice terrain normalization for Pingo."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Callable, Iterable

from .materials import BERKELEY_TERRAIN_MATERIALS
from .p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    P3DMMeta,
    P3DMTile,
    ShadingMode,
)


REGIONAL_EPSG = 32610
REGIONAL_ORIGIN_EAST_M = 521_728
REGIONAL_ORIGIN_NORTH_M = 4_100_096
CHUNK_WIDTH_M = 512
WORLD_COLUMNS = 201
WORLD_ROWS = 252
REGIONAL_VERTICAL_ORIGIN_M = 608.0
MODEL_HALF_EXTENT_M = 768
BASE_SQUARE_EQUIVALENT_SPACING_M = 64.0
BASE_TRIANGULAR_SPACING_M = BASE_SQUARE_EQUIVALENT_SPACING_M * math.sqrt(
    2.0 / math.sqrt(3.0)
)
SKIRT_DEPTH_M = 64.0
SKIRT_FLOOR_ELEVATION_M = REGIONAL_VERTICAL_ORIGIN_M - MODEL_HALF_EXTENT_M
STAGING_BUFFER_ID = 0x7400


@dataclass(frozen=True, slots=True)
class LodSpec:
    lod: int
    spacing_m: float


LODS: tuple[LodSpec, ...] = tuple(
    LodSpec(lod, BASE_TRIANGULAR_SPACING_M * (2**lod)) for lod in range(3)
)


@dataclass(frozen=True, slots=True)
class WorldGrid:
    origin_east_m: int = REGIONAL_ORIGIN_EAST_M
    origin_north_m: int = REGIONAL_ORIGIN_NORTH_M
    chunk_width_m: int = CHUNK_WIDTH_M
    columns: int = WORLD_COLUMNS
    rows: int = WORLD_ROWS

    @property
    def east_m(self) -> int:
        return self.origin_east_m + self.columns * self.chunk_width_m

    @property
    def north_m(self) -> int:
        return self.origin_north_m + self.rows * self.chunk_width_m

    def tile_id(self, tile_x: int, tile_y: int) -> int:
        self.validate_tile(tile_x, tile_y)
        return tile_y * self.columns + tile_x

    def validate_tile(self, tile_x: int, tile_y: int) -> None:
        if not (0 <= tile_x < self.columns and 0 <= tile_y < self.rows):
            raise ValueError(f"terrain tile is outside world grid: {tile_x},{tile_y}")

    def tile_bounds(self, tile_x: int, tile_y: int) -> tuple[float, float, float, float]:
        self.validate_tile(tile_x, tile_y)
        west = self.origin_east_m + tile_x * self.chunk_width_m
        south = self.origin_north_m + tile_y * self.chunk_width_m
        return west, south, west + self.chunk_width_m, south + self.chunk_width_m


@dataclass(frozen=True, slots=True)
class TriangleTopology:
    """One tile's share of a continuous global triangular lattice."""

    # Keys are canonical projected micrometres, not local vertex indices. This
    # makes independently clipped neighbors compare exactly at shared edges.
    keys: tuple[tuple[int, int], ...]
    points: tuple[tuple[float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    boundary_edges: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True, slots=True)
class BuiltTerrainTile:
    tile: P3DMTile
    surface_vertex_count: int
    surface_triangle_count: int
    skirt_triangle_count: int
    surface_minimum_elevation_m: float
    surface_maximum_elevation_m: float
    mesh_minimum_elevation_m: float
    clamped_skirt_vertices: int
    material_histogram: tuple[tuple[int, int], ...]


def lod_spec(lod: int) -> LodSpec:
    try:
        return LODS[lod]
    except IndexError as error:
        raise ValueError(f"unsupported terrain LOD: {lod}") from error


def lattice_point(grid: WorldGrid, spec: LodSpec, gy: int, gx: int) -> tuple[float, float]:
    row_spacing = spec.spacing_m * math.sqrt(3.0) / 2.0
    offset = spec.spacing_m / 2.0 if gy & 1 else 0.0
    return (
        grid.origin_east_m + gx * spec.spacing_m + offset,
        grid.origin_north_m + gy * row_spacing,
    )


def _canonical_point(point: tuple[float, float]) -> tuple[float, float]:
    return round(point[0], 6), round(point[1], 6)


def _point_key(point: tuple[float, float]) -> tuple[int, int]:
    return round(point[0] * 1_000_000), round(point[1] * 1_000_000)


def _clip_polygon(
    polygon: tuple[tuple[float, float], ...],
    *,
    axis: int,
    boundary: float,
    keep_greater: bool,
) -> tuple[tuple[float, float], ...]:
    """Clip one convex polygon against an axis-aligned half plane."""

    if not polygon:
        return ()

    def inside(point: tuple[float, float]) -> bool:
        return point[axis] >= boundary if keep_greater else point[axis] <= boundary

    def intersection(
        first: tuple[float, float], second: tuple[float, float]
    ) -> tuple[float, float]:
        delta = second[axis] - first[axis]
        if abs(delta) < 1e-15:
            # A parallel segment cannot truly cross; this branch only absorbs
            # floating equality at an already admitted boundary vertex.
            result = list(first)
            result[axis] = boundary
            return _canonical_point((result[0], result[1]))
        fraction = (boundary - first[axis]) / delta
        other_axis = 1 - axis
        result = [0.0, 0.0]
        result[axis] = boundary
        result[other_axis] = first[other_axis] + fraction * (
            second[other_axis] - first[other_axis]
        )
        return _canonical_point((result[0], result[1]))

    output: list[tuple[float, float]] = []
    previous = polygon[-1]
    previous_inside = inside(previous)
    for current in polygon:
        current_inside = inside(current)
        if current_inside != previous_inside:
            output.append(intersection(previous, current))
        if current_inside:
            output.append(_canonical_point(current))
        previous, previous_inside = current, current_inside

    deduplicated: list[tuple[float, float]] = []
    for point in output:
        if not deduplicated or _point_key(point) != _point_key(deduplicated[-1]):
            deduplicated.append(point)
    if len(deduplicated) > 1 and _point_key(deduplicated[0]) == _point_key(deduplicated[-1]):
        deduplicated.pop()
    return tuple(deduplicated)


def _clip_to_tile(
    triangle: tuple[tuple[float, float], ...],
    bounds: tuple[float, float, float, float],
) -> tuple[tuple[float, float], ...]:
    west, south, east, north = bounds
    polygon = triangle
    for axis, boundary, keep_greater in (
        (0, west, True),
        (0, east, False),
        (1, south, True),
        (1, north, False),
    ):
        polygon = _clip_polygon(
            polygon,
            axis=axis,
            boundary=boundary,
            keep_greater=keep_greater,
        )
        if len(polygon) < 3:
            return ()
    return polygon


def triangular_topology(
    grid: WorldGrid, tile_x: int, tile_y: int, lod: int
) -> TriangleTopology:
    """Clip one global triangular lattice to exact tile boundary planes."""

    spec = lod_spec(lod)
    west, south, east, north = grid.tile_bounds(tile_x, tile_y)
    row_spacing = spec.spacing_m * math.sqrt(3.0) / 2.0
    gy_min = math.floor((south - grid.origin_north_m) / row_spacing) - 2
    gy_max = math.ceil((north - grid.origin_north_m) / row_spacing) + 2
    gx_min = math.floor((west - grid.origin_east_m) / spec.spacing_m) - 3
    gx_max = math.ceil((east - grid.origin_east_m) / spec.spacing_m) + 3

    point_cache: dict[tuple[int, int], tuple[float, float]] = {}

    def point(key: tuple[int, int]) -> tuple[float, float]:
        if key not in point_cache:
            point_cache[key] = lattice_point(grid, spec, *key)
        return point_cache[key]

    clipped_faces: list[tuple[tuple[float, float], ...]] = []
    for gy in range(gy_min, gy_max):
        for gx in range(gx_min, gx_max):
            lower_w = (gy, gx)
            lower_e = (gy, gx + 1)
            upper_w = (gy + 1, gx)
            upper_e = (gy + 1, gx + 1)
            candidates = (
                ((lower_w, upper_w, upper_e), (lower_w, upper_e, lower_e))
                if gy & 1
                else ((lower_w, upper_w, lower_e), (lower_e, upper_w, upper_e))
            )
            for face in candidates:
                coordinates = tuple(point(key) for key in face)
                clipped = _clip_to_tile(coordinates, (west, south, east, north))
                if not clipped:
                    continue
                for index in range(1, len(clipped) - 1):
                    clipped_faces.append((clipped[0], clipped[index], clipped[index + 1]))

    key_indices: dict[tuple[int, int], int] = {}
    keys: list[tuple[int, int]] = []
    coordinates_by_key: dict[tuple[int, int], tuple[float, float]] = {}
    faces: list[tuple[int, int, int]] = []
    for source_face in clipped_faces:
        face_indices: list[int] = []
        for coordinate in source_face:
            key = _point_key(coordinate)
            if key not in key_indices:
                key_indices[key] = len(keys)
                keys.append(key)
                coordinates_by_key[key] = (
                    key[0] / 1_000_000.0,
                    key[1] / 1_000_000.0,
                )
            face_indices.append(key_indices[key])
        # Pingo x=north, z=-east. This ordering gives a positive Y normal.
        a, b, c = (coordinates_by_key[keys[index]] for index in face_indices)
        ab_x, ab_z = b[1] - a[1], -(b[0] - a[0])
        ac_x, ac_z = c[1] - a[1], -(c[0] - a[0])
        if abs(ab_z * ac_x - ab_x * ac_z) < 1e-8:
            continue
        if ab_z * ac_x - ab_x * ac_z <= 0.0:
            face_indices[1], face_indices[2] = face_indices[2], face_indices[1]
        faces.append(tuple(face_indices))

    edge_owners: dict[tuple[int, int], tuple[int, int, int]] = {}
    edge_counts: Counter[tuple[int, int]] = Counter()
    for face_index, face in enumerate(faces):
        for start, end in zip(face, face[1:] + face[:1], strict=True):
            edge_key = (min(start, end), max(start, end))
            edge_counts[edge_key] += 1
            edge_owners[edge_key] = (start, end, face_index)
    boundary = tuple(
        edge_owners[edge]
        for edge in sorted(edge_counts)
        if edge_counts[edge] == 1
    )
    return TriangleTopology(
        keys=tuple(keys),
        points=tuple(coordinates_by_key[key] for key in keys),
        faces=tuple(faces),
        boundary_edges=boundary,
    )


def selector_uv_words(material_id: int) -> tuple[int, int]:
    """Encode a row-major material ID as the center of a 4x4 selector cell."""

    if not 0 <= material_id < 16:
        raise ValueError(f"material selector is outside 0..15: {material_id}")

    def center(cell: int) -> int:
        lower = (cell * 65535 + 2) // 3
        upper = 65535 if cell == 3 else ((cell + 1) * 65535 + 2) // 3 - 1
        return (lower + upper) // 2

    column, row = material_id % 4, material_id // 4
    return center(column), 65535 - center(row)


def _encode_axis(value_m: float) -> int:
    encoded = round(value_m / MODEL_HALF_EXTENT_M * 32767)
    if not -32767 <= encoded <= 32767:
        raise ValueError(f"regional model coordinate exceeds half extent: {value_m}")
    return encoded


def build_terrain_tile(
    grid: WorldGrid,
    tile_x: int,
    tile_y: int,
    lod: int,
    *,
    elevations_m: Iterable[float],
    surface_materials: Iterable[int],
    stage_buffer_id: int = STAGING_BUFFER_ID,
) -> BuiltTerrainTile:
    """Normalize sampled topology and append deterministic boundary skirts."""

    topology = triangular_topology(grid, tile_x, tile_y, lod)
    elevations = tuple(float(item) for item in elevations_m)
    materials = tuple(int(item) for item in surface_materials)
    if len(elevations) != len(topology.points):
        raise ValueError("elevation count does not match terrain topology")
    if len(materials) != len(topology.faces):
        raise ValueError("material count does not match terrain topology")
    material_count = len(BERKELEY_TERRAIN_MATERIALS)
    if any(not 0 <= item < material_count for item in materials):
        raise ValueError(f"terrain material IDs must be in 0..{material_count - 1}")

    west, south, east, north = grid.tile_bounds(tile_x, tile_y)
    center_east = (west + east) / 2.0
    center_north = (south + north) / 2.0
    positions: list[tuple[int, int, int]] = [
        (
            _encode_axis(point_north - center_north),
            _encode_axis(elevation - REGIONAL_VERTICAL_ORIGIN_M),
            _encode_axis(-(point_east - center_east)),
        )
        for (point_east, point_north), elevation in zip(
            topology.points, elevations, strict=True
        )
    ]
    faces = list(topology.faces)
    face_materials = list(materials)
    bottom_indices: dict[int, int] = {}
    bottom_elevations: dict[int, float] = {}
    for start, end, owner_face in topology.boundary_edges:
        for top_index in (start, end):
            if top_index not in bottom_indices:
                point_east, point_north = topology.points[top_index]
                bottom_elevation = max(
                    elevations[top_index] - SKIRT_DEPTH_M,
                    SKIRT_FLOOR_ELEVATION_M,
                )
                bottom_elevations[top_index] = bottom_elevation
                bottom_indices[top_index] = len(positions)
                positions.append(
                    (
                        _encode_axis(point_north - center_north),
                        _encode_axis(
                            bottom_elevation - REGIONAL_VERTICAL_ORIGIN_M
                        ),
                        _encode_axis(-(point_east - center_east)),
                    )
                )
        bottom_start = bottom_indices[start]
        bottom_end = bottom_indices[end]
        # The directed edge comes from an upward surface face. These two faces
        # expose the tile's outward side and hide mixed-LOD T-junctions.
        faces.extend(
            (
                (start, bottom_start, bottom_end),
                (start, bottom_end, end),
            )
        )
        face_materials.extend((materials[owner_face], materials[owner_face]))

    uvs = tuple(selector_uv_words(index) for index in range(16))
    position_indices = tuple(index for face in faces for index in face)
    uv_indices = tuple(
        material for material in face_materials for _ in range(3)
    )
    surface_minimum = min(elevations)
    surface_maximum = max(elevations)
    mesh_minimum = min(
        surface_minimum,
        min(bottom_elevations.values()),
    )
    tile = P3DMTile(
        stage_buffer_id=stage_buffer_id,
        meta=P3DMMeta(
            layer_kind=LayerKind.TERRAIN,
            lod=lod,
            shading_mode=ShadingMode.FLAT_PATTERN,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
            tile_x=tile_x,
            tile_y=tile_y,
            center_east_m=round(center_east - grid.origin_east_m),
            center_north_m=round(center_north - grid.origin_north_m),
            minimum_elevation_dm=math.floor(mesh_minimum * 10.0),
            maximum_elevation_dm=math.ceil(surface_maximum * 10.0),
            model_half_extent_m=MODEL_HALF_EXTENT_M,
        ),
        positions=tuple(positions),
        position_indices=position_indices,
        uvs=uvs,
        uv_indices=uv_indices,
    )
    return BuiltTerrainTile(
        tile=tile,
        surface_vertex_count=len(topology.points),
        surface_triangle_count=len(topology.faces),
        skirt_triangle_count=len(topology.boundary_edges) * 2,
        surface_minimum_elevation_m=surface_minimum,
        surface_maximum_elevation_m=surface_maximum,
        mesh_minimum_elevation_m=mesh_minimum,
        clamped_skirt_vertices=sum(
            bottom > elevations[index] - SKIRT_DEPTH_M
            for index, bottom in bottom_elevations.items()
        ),
        material_histogram=tuple(sorted(Counter(materials).items())),
    )


def point_in_triangle(
    point: tuple[float, float], triangle: tuple[tuple[float, float], ...]
) -> bool:
    px, py = point
    (ax, ay), (bx, by), (cx, cy) = triangle
    denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denominator) < 1e-12:
        return False
    a = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
    b = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
    return min(a, b, 1.0 - a - b) >= -1e-10


def predominant_category(
    triangle: tuple[tuple[float, float], ...],
    candidates: Iterable[tuple[float, float, int | float | None, bool]],
    *,
    centroid_lookup: Callable[[float, float], int | None],
) -> tuple[int | None, bool]:
    """Choose the predominant valid category under a projected triangle."""

    categories: list[int] = []
    saw_nodata = False
    for x, y, value, nodata in candidates:
        saw_nodata |= nodata
        if value is not None and point_in_triangle((x, y), triangle):
            categories.append(int(value))
    if categories:
        counts = Counter(categories)
        largest = max(counts.values())
        return min(value for value, count in counts.items() if count == largest), saw_nodata
    x = sum(point[0] for point in triangle) / 3.0
    y = sum(point[1] for point in triangle) / 3.0
    return centroid_lookup(x, y), saw_nodata
