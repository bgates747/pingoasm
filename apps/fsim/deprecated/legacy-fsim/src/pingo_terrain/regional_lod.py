"""Executable design reference for a bundled regional terrain hierarchy.

The first regional compiler deliberately emits one 512 metre P3DM record per
file.  That is a useful loader proof, but three complete LODs would create
151,956 FAT files.  This module explores the next packaging step without
changing that proven compiler:

* one 2,048 metre, four-by-four-cell *family* per AGNB file;
* eight 1,024 by 512 metre L0 strips for the current family;
* one complete 2,048 metre L1 component for the transition ring; and
* one complete 2,048 metre L2 component for sparse distant relief.

AGNB already permits more than one ``LIST BUFR`` record.  A family bundle is
therefore ordinary version-0.3 AGNB rather than a new archive format.  Each
record retains the exact BHDR/P3DM/DATA layout and can be selected with an SD
seek into a bounded staging window.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import struct
import subprocess
from typing import Iterable, Mapping, Sequence

from .materials import BERKELEY_TERRAIN_MATERIALS
from .p3dm import (
    AGNB_VERSION,
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    P3DMMeta,
    P3DMTile,
    ShadingMode,
    align4,
    make_chunk,
    make_container,
    make_data,
    make_descriptor,
    parse_container,
)
from .regional_raster import RasterMosaic
from .regional_terrain import (
    REGIONAL_VERTICAL_ORIGIN_M,
    SKIRT_DEPTH_M,
    TriangleTopology,
    WorldGrid,
    _clip_to_tile,
    _point_key,
    lattice_point,
    lod_spec,
    predominant_category,
    selector_uv_words,
)


SUPERTILE_SIDE_CELLS = 4
SUPERTILE_SIDE_M = 2_048
NEAR_STRIP_WIDTH_CELLS = 2
NEAR_STRIP_HEIGHT_CELLS = 1
NEAR_MODEL_HALF_EXTENT_M = 768
DISTANT_MODEL_HALF_EXTENT_M = 1_024
STAGING_BUFFER_ID = 0x7400
TERRAIN_ACTIVE_BUDGET = 24
NEAR_ACTIVE_BUDGET = 8
TRANSITION_ACTIVE_BUDGET = 8
DISTANT_ACTIVE_BUDGET = 8
PINGO_TRANSLATION_COUNTS_PER_METRE = 16
PINGO_SIGNED_WORD_MAX = 0x7FFF
PINGO_SIGNED_24_MAX = 0x7FFFFF
PINGO_METRES_PER_UNIT = 8
PINGO_CURRENT_FAR_UNITS = 2_500
PINGO_CURRENT_FAR_METRES = PINGO_CURRENT_FAR_UNITS * PINGO_METRES_PER_UNIT
UART_BITS_PER_BYTE_8N1 = 10
UART_BAUD = 1_152_000

DEM_DATASET_ID = "usgs-3dep-10m-utm10n"
NLCD_DATASET_ID = "usgs-annual-nlcd-2025-epsg5070"
NLCD_TO_MATERIAL = {
    item.nlcd_category: item.material_id for item in BERKELEY_TERRAIN_MATERIALS
}
UNKNOWN_LAND_MATERIAL = NLCD_TO_MATERIAL[24]
WATER_MATERIAL = NLCD_TO_MATERIAL[11]


@dataclass(frozen=True, slots=True)
class CellRectangle:
    """A nonempty rectangle aligned to the proven 512 metre world grid."""

    tile_x: int
    tile_y: int
    width_cells: int
    height_cells: int

    def validate(self, grid: WorldGrid) -> None:
        if self.width_cells <= 0 or self.height_cells <= 0:
            raise ValueError("cell rectangle dimensions must be positive")
        grid.validate_tile(self.tile_x, self.tile_y)
        grid.validate_tile(
            self.tile_x + self.width_cells - 1,
            self.tile_y + self.height_cells - 1,
        )

    def bounds(self, grid: WorldGrid) -> tuple[float, float, float, float]:
        self.validate(grid)
        west = grid.origin_east_m + self.tile_x * grid.chunk_width_m
        south = grid.origin_north_m + self.tile_y * grid.chunk_width_m
        return (
            float(west),
            float(south),
            float(west + self.width_cells * grid.chunk_width_m),
            float(south + self.height_cells * grid.chunk_width_m),
        )


@dataclass(frozen=True, slots=True)
class SuperTile:
    super_x: int
    super_y: int
    rectangle: CellRectangle
    super_id: int


@dataclass(frozen=True, slots=True)
class SuperTileGrid:
    """Four-by-four grouping over a possibly non-divisible base grid."""

    base: WorldGrid = WorldGrid()
    side_cells: int = SUPERTILE_SIDE_CELLS

    def __post_init__(self) -> None:
        if self.side_cells <= 0:
            raise ValueError("supertile side must be positive")

    @property
    def columns(self) -> int:
        return (self.base.columns + self.side_cells - 1) // self.side_cells

    @property
    def rows(self) -> int:
        return (self.base.rows + self.side_cells - 1) // self.side_cells

    def contains(self, super_x: int, super_y: int) -> bool:
        return 0 <= super_x < self.columns and 0 <= super_y < self.rows

    def supertile(self, super_x: int, super_y: int) -> SuperTile:
        if not self.contains(super_x, super_y):
            raise ValueError(f"supertile is outside world: {super_x},{super_y}")
        tile_x = super_x * self.side_cells
        tile_y = super_y * self.side_cells
        rectangle = CellRectangle(
            tile_x,
            tile_y,
            min(self.side_cells, self.base.columns - tile_x),
            min(self.side_cells, self.base.rows - tile_y),
        )
        return SuperTile(
            super_x,
            super_y,
            rectangle,
            super_y * self.columns + super_x,
        )

    def from_base_tile(self, tile_x: int, tile_y: int) -> SuperTile:
        self.base.validate_tile(tile_x, tile_y)
        return self.supertile(tile_x // self.side_cells, tile_y // self.side_cells)

    def all_supertiles(self) -> Iterable[SuperTile]:
        for super_y in range(self.rows):
            for super_x in range(self.columns):
                yield self.supertile(super_x, super_y)

    def path(self, super_x: int, super_y: int) -> PurePosixPath:
        """Return a deterministic 8.3 path for one multi-record family."""

        supertile = self.supertile(super_x, super_y)
        return PurePosixPath(
            "RGN",
            f"{supertile.super_id >> 8:02X}",
            f"{supertile.super_id & 0xFF:02X}.AGN",
        )


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """One selectable P3DM record inside a supertile family bundle."""

    key: str
    tier: str
    lod: int
    rectangle: CellRectangle
    model_half_extent_m: int


def component_specs(supertile: SuperTile) -> tuple[ComponentSpec, ...]:
    """Return wire order: cheap distant records first, then L0 strips."""

    rectangle = supertile.rectangle
    specs = [
        ComponentSpec(
            "D2",
            "distant",
            2,
            rectangle,
            DISTANT_MODEL_HALF_EXTENT_M,
        ),
        ComponentSpec(
            "D1",
            "transition",
            1,
            rectangle,
            DISTANT_MODEL_HALF_EXTENT_M,
        ),
    ]
    strip_index = 0
    for row in range(rectangle.height_cells):
        for column in range(0, rectangle.width_cells, NEAR_STRIP_WIDTH_CELLS):
            width = min(
                NEAR_STRIP_WIDTH_CELLS,
                rectangle.width_cells - column,
            )
            specs.append(
                ComponentSpec(
                    f"N{strip_index:02d}",
                    "near",
                    0,
                    CellRectangle(
                        rectangle.tile_x + column,
                        rectangle.tile_y + row,
                        width,
                        NEAR_STRIP_HEIGHT_CELLS,
                    ),
                    NEAR_MODEL_HALF_EXTENT_M,
                )
            )
            strip_index += 1
    return tuple(specs)


def rectangular_topology(
    grid: WorldGrid,
    rectangle: CellRectangle,
    lod: int,
) -> TriangleTopology:
    """Clip the existing global triangular lattice to an aligned rectangle."""

    spec = lod_spec(lod)
    west, south, east, north = rectangle.bounds(grid)
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
                clipped = _clip_to_tile(
                    tuple(point(key) for key in face),
                    (west, south, east, north),
                )
                if not clipped:
                    continue
                for index in range(1, len(clipped) - 1):
                    clipped_faces.append(
                        (clipped[0], clipped[index], clipped[index + 1])
                    )

    key_indices: dict[tuple[int, int], int] = {}
    keys: list[tuple[int, int]] = []
    points_by_key: dict[tuple[int, int], tuple[float, float]] = {}
    faces: list[tuple[int, int, int]] = []
    for source_face in clipped_faces:
        face_indices = []
        for coordinate in source_face:
            key = _point_key(coordinate)
            if key not in key_indices:
                key_indices[key] = len(keys)
                keys.append(key)
                points_by_key[key] = (
                    key[0] / 1_000_000.0,
                    key[1] / 1_000_000.0,
                )
            face_indices.append(key_indices[key])
        a, b, c = (points_by_key[keys[index]] for index in face_indices)
        ab_x, ab_z = b[1] - a[1], -(b[0] - a[0])
        ac_x, ac_z = c[1] - a[1], -(c[0] - a[0])
        cross = ab_z * ac_x - ab_x * ac_z
        if abs(cross) < 1e-8:
            continue
        if cross <= 0.0:
            face_indices[1], face_indices[2] = face_indices[2], face_indices[1]
        faces.append(tuple(face_indices))

    edge_counts: Counter[tuple[int, int]] = Counter()
    edge_owners: dict[tuple[int, int], tuple[int, int, int]] = {}
    for face_index, face in enumerate(faces):
        for start, end in zip(face, face[1:] + face[:1], strict=True):
            edge = (min(start, end), max(start, end))
            edge_counts[edge] += 1
            edge_owners[edge] = (start, end, face_index)
    boundary = tuple(
        edge_owners[edge]
        for edge in sorted(edge_counts)
        if edge_counts[edge] == 1
    )
    return TriangleTopology(
        keys=tuple(keys),
        points=tuple(points_by_key[key] for key in keys),
        faces=tuple(faces),
        boundary_edges=boundary,
    )


@dataclass(frozen=True, slots=True)
class BuiltComponent:
    spec: ComponentSpec
    tile: P3DMTile
    surface_vertices: int
    surface_triangles: int
    skirt_triangles: int
    surface_minimum_elevation_m: float
    surface_maximum_elevation_m: float


def _encode_axis(value_m: float, half_extent_m: int) -> int:
    encoded = round(value_m / half_extent_m * 32767)
    if not -32767 <= encoded <= 32767:
        raise ValueError(
            f"component coordinate {value_m} m exceeds {half_extent_m} m half extent"
        )
    return encoded


def build_component(
    grid: WorldGrid,
    spec: ComponentSpec,
    *,
    elevations_m: Sequence[float],
    surface_materials: Sequence[int],
    stage_buffer_id: int = STAGING_BUFFER_ID,
) -> BuiltComponent:
    """Normalize one rectangular terrain component and add outer skirts."""

    topology = rectangular_topology(grid, spec.rectangle, spec.lod)
    elevations = tuple(float(value) for value in elevations_m)
    materials = tuple(int(value) for value in surface_materials)
    if len(elevations) != len(topology.points):
        raise ValueError("elevation count does not match rectangular topology")
    if len(materials) != len(topology.faces):
        raise ValueError("material count does not match rectangular topology")
    if any(not 0 <= value < 16 for value in materials):
        raise ValueError("terrain materials must be in 0..15")

    west, south, east, north = spec.rectangle.bounds(grid)
    center_east = (west + east) / 2.0
    center_north = (south + north) / 2.0
    half = spec.model_half_extent_m
    positions = [
        (
            _encode_axis(point_north - center_north, half),
            _encode_axis(elevation - REGIONAL_VERTICAL_ORIGIN_M, half),
            _encode_axis(-(point_east - center_east), half),
        )
        for (point_east, point_north), elevation in zip(
            topology.points, elevations, strict=True
        )
    ]
    faces = list(topology.faces)
    face_materials = list(materials)
    bottom_indices: dict[int, int] = {}
    bottom_elevations: dict[int, float] = {}
    mesh_floor = REGIONAL_VERTICAL_ORIGIN_M - half
    for start, end, owner_face in topology.boundary_edges:
        for top_index in (start, end):
            if top_index in bottom_indices:
                continue
            point_east, point_north = topology.points[top_index]
            bottom_elevation = max(
                elevations[top_index] - SKIRT_DEPTH_M,
                mesh_floor,
            )
            bottom_elevations[top_index] = bottom_elevation
            bottom_indices[top_index] = len(positions)
            positions.append(
                (
                    _encode_axis(point_north - center_north, half),
                    _encode_axis(
                        bottom_elevation - REGIONAL_VERTICAL_ORIGIN_M,
                        half,
                    ),
                    _encode_axis(-(point_east - center_east), half),
                )
            )
        bottom_start = bottom_indices[start]
        bottom_end = bottom_indices[end]
        faces.extend(
            ((start, bottom_start, bottom_end), (start, bottom_end, end))
        )
        face_materials.extend((materials[owner_face], materials[owner_face]))

    position_indices = tuple(index for face in faces for index in face)
    uv_indices = tuple(material for material in face_materials for _ in range(3))
    tile = P3DMTile(
        stage_buffer_id=stage_buffer_id,
        meta=P3DMMeta(
            layer_kind=LayerKind.TERRAIN,
            lod=spec.lod,
            shading_mode=ShadingMode.FLAT_PATTERN,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
            tile_x=spec.rectangle.tile_x,
            tile_y=spec.rectangle.tile_y,
            center_east_m=round(center_east - grid.origin_east_m),
            center_north_m=round(center_north - grid.origin_north_m),
            minimum_elevation_dm=math.floor(
                min(min(elevations), min(bottom_elevations.values()))
                * 10.0
            ),
            maximum_elevation_dm=math.ceil(max(elevations) * 10.0),
            model_half_extent_m=half,
        ),
        positions=tuple(positions),
        position_indices=position_indices,
        uvs=tuple(selector_uv_words(index) for index in range(16)),
        uv_indices=uv_indices,
    )
    return BuiltComponent(
        spec=spec,
        tile=tile,
        surface_vertices=len(topology.points),
        surface_triangles=len(topology.faces),
        skirt_triangles=2 * len(topology.boundary_edges),
        surface_minimum_elevation_m=min(elevations),
        surface_maximum_elevation_m=max(elevations),
    )


def _p3dm_list_chunk(tile: P3DMTile) -> bytes:
    data = make_data(tile)
    nested = b"".join(
        (
            make_chunk(b"BHDR", struct.pack("<H", tile.stage_buffer_id)),
            make_chunk(b"P3DM", make_descriptor(tile, data)),
            make_chunk(b"DATA", data),
        )
    )
    return make_chunk(b"LIST", b"BUFR" + nested)


def make_bundle(tiles: Sequence[P3DMTile]) -> bytes:
    """Build canonical multi-record AGNB 0.3 from exact P3DM records."""

    if not tiles:
        raise ValueError("a terrain family bundle requires at least one record")
    identities = [
        (
            tile.meta.lod,
            tile.meta.tile_x,
            tile.meta.tile_y,
            tile.meta.center_east_m,
            tile.meta.center_north_m,
        )
        for tile in tiles
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("bundle contains duplicate P3DM component identities")
    body = b"AGNB" + make_chunk(b"VERS", bytes(AGNB_VERSION)) + b"".join(
        _p3dm_list_chunk(tile) for tile in tiles
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _read_chunk(
    container: bytes, offset: int, boundary: int
) -> tuple[bytes, bytes, int]:
    if offset + 8 > boundary:
        raise ValueError("truncated AGNB bundle chunk header")
    chunk_id = container[offset : offset + 4]
    size = struct.unpack_from("<I", container, offset + 4)[0]
    payload_start = offset + 8
    payload_end = payload_start + size
    next_offset = payload_start + align4(size)
    if payload_end > boundary or next_offset > boundary:
        raise ValueError("AGNB bundle chunk crosses RIFF boundary")
    if any(container[payload_end:next_offset]):
        raise ValueError("AGNB bundle chunk has nonzero alignment padding")
    return chunk_id, container[payload_start:payload_end], next_offset


@dataclass(frozen=True, slots=True)
class BundleRecordSpan:
    record_index: int
    list_offset: int
    list_bytes: int
    data_offset: int
    data_bytes: int


def parse_bundle(container: bytes) -> tuple[tuple[P3DMTile, ...], tuple[BundleRecordSpan, ...]]:
    """Validate a family bundle and expose seek witnesses for an eZ80 loader."""

    if len(container) < 24 or container[:4] != b"RIFF" or container[8:12] != b"AGNB":
        raise ValueError("not a RIFF/AGNB terrain family bundle")
    if struct.unpack_from("<I", container, 4)[0] + 8 != len(container):
        raise ValueError("AGNB terrain family RIFF size disagrees with file")
    offset = 12
    chunk_id, version, offset = _read_chunk(container, offset, len(container))
    if chunk_id != b"VERS" or version != bytes(AGNB_VERSION):
        raise ValueError("terrain family requires AGNB version 0.3")

    tiles = []
    spans = []
    version_chunk = make_chunk(b"VERS", version)
    while offset < len(container):
        list_offset = offset
        chunk_id, payload, offset = _read_chunk(container, offset, len(container))
        if chunk_id != b"LIST" or payload[:4] != b"BUFR":
            raise ValueError("terrain family permits only LIST BUFR records")
        list_chunk = make_chunk(b"LIST", payload)
        single_body = b"AGNB" + version_chunk + list_chunk
        single = b"RIFF" + struct.pack("<I", len(single_body)) + single_body
        tile = parse_container(single)

        nested = 4
        data_absolute = None
        data_size = None
        while nested < len(payload):
            nested_id, nested_payload, next_nested = _read_chunk(
                payload, nested, len(payload)
            )
            if nested_id == b"DATA":
                # LIST payload starts after its eight-byte header in the file.
                data_absolute = list_offset + 8 + nested + 8
                data_size = len(nested_payload)
            nested = next_nested
        if data_absolute is None or data_size is None:
            raise ValueError("P3DM bundle record has no DATA chunk")
        tiles.append(tile)
        spans.append(
            BundleRecordSpan(
                len(tiles) - 1,
                list_offset,
                len(list_chunk),
                data_absolute,
                data_size,
            )
        )
    if not tiles:
        raise ValueError("terrain family bundle contains no records")
    identities = [
        (
            tile.meta.lod,
            tile.meta.tile_x,
            tile.meta.tile_y,
            tile.meta.center_east_m,
            tile.meta.center_north_m,
        )
        for tile in tiles
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("terrain family bundle has duplicate component identities")
    return tuple(tiles), tuple(spans)


@dataclass(frozen=True, slots=True)
class ComponentCost:
    tier: str
    records: int
    vertices: int
    triangles: int
    data_bytes: int
    record_bytes: int
    data_bytes_min: int
    data_bytes_max: int


def _topology_cost(spec: ComponentSpec, topology: TriangleTopology) -> tuple[int, int, int]:
    boundary_vertices = len(
        {index for edge in topology.boundary_edges for index in edge[:2]}
    )
    vertices = len(topology.points) + boundary_vertices
    triangles = len(topology.faces) + 2 * len(topology.boundary_edges)
    data_bytes = 6 * vertices + 12 * triangles + 64
    return vertices, triangles, data_bytes


def world_budget(grid: SuperTileGrid = SuperTileGrid()) -> dict[str, object]:
    """Calculate exact topology/storage costs without opening source rasters."""

    totals: dict[str, Counter[str]] = {
        "near": Counter(),
        "transition": Counter(),
        "distant": Counter(),
    }
    sizes: dict[str, list[int]] = {tier: [] for tier in totals}
    bundle_bytes = 0
    bundle_sizes = []
    for supertile in grid.all_supertiles():
        current_bundle_bytes = 24  # RIFF/AGNB plus one padded VERS chunk.
        for spec in component_specs(supertile):
            topology = rectangular_topology(grid.base, spec.rectangle, spec.lod)
            vertices, triangles, data_bytes = _topology_cost(spec, topology)
            record_bytes = 76 + align4(data_bytes)
            totals[spec.tier].update(
                records=1,
                vertices=vertices,
                triangles=triangles,
                data_bytes=data_bytes,
                record_bytes=record_bytes,
            )
            sizes[spec.tier].append(data_bytes)
            current_bundle_bytes += record_bytes
        bundle_sizes.append(current_bundle_bytes)
        bundle_bytes += current_bundle_bytes

    tiers = {}
    for tier, counter in totals.items():
        tiers[tier] = {
            **counter,
            "data_bytes_min": min(sizes[tier]),
            "data_bytes_max": max(sizes[tier]),
            "data_bytes_mean": counter["data_bytes"] / counter["records"],
            "uart_floor_ms_mean": (
                counter["data_bytes"]
                / counter["records"]
                * UART_BITS_PER_BYTE_8N1
                / UART_BAUD
                * 1_000.0
            ),
            "uart_floor_ms_max": (
                max(sizes[tier])
                * UART_BITS_PER_BYTE_8N1
                / UART_BAUD
                * 1_000.0
            ),
        }
    return {
        "schema": "pingo-terrain-regional-lod-budget-v1",
        "supertile_columns": grid.columns,
        "supertile_rows": grid.rows,
        "bundle_files": grid.columns * grid.rows,
        "records": sum(value["records"] for value in tiers.values()),
        "bundle_bytes": bundle_bytes,
        "bundle_bytes_min": min(bundle_sizes),
        "bundle_bytes_max": max(bundle_sizes),
        "fat_allocation_bytes_4096": sum(
            math.ceil(size / 4_096) * 4_096 for size in bundle_sizes
        ),
        "fat_allocation_bytes_32768": sum(
            math.ceil(size / 32_768) * 32_768 for size in bundle_sizes
        ),
        "tiers": tiers,
    }


@dataclass(frozen=True, slots=True)
class ActiveComponent:
    tier: str
    super_x: int
    super_y: int
    component_key: str


@dataclass(frozen=True, slots=True)
class ActiveTerrainPlan:
    near: tuple[ActiveComponent, ...]
    transition: tuple[ActiveComponent, ...]
    distant: tuple[ActiveComponent, ...]

    @property
    def terrain_count(self) -> int:
        return len(self.near) + len(self.transition) + len(self.distant)

    def scene_count(
        self,
        *,
        airport_components: int = 2,
        aircraft_components: int = 1,
        landmark_components: int = 0,
    ) -> int:
        count = (
            self.terrain_count
            + airport_components
            + aircraft_components
            + landmark_components
        )
        if count > 32:
            raise ValueError(f"active scene would exceed Pingo's limit: {count}")
        return count


def active_plan(
    grid: SuperTileGrid,
    super_x: int,
    super_y: int,
    *,
    heading_east: float = 1.0,
    heading_north: float = 0.0,
    distant_interest: Mapping[tuple[int, int], float] | None = None,
) -> ActiveTerrainPlan:
    """Plan 8 near strips, an L1 neighbor ring, and 8 sparse L2 blocks."""

    current = grid.supertile(super_x, super_y)
    near = tuple(
        ActiveComponent("near", super_x, super_y, spec.key)
        for spec in component_specs(current)
        if spec.tier == "near"
    )
    transition = tuple(
        ActiveComponent("transition", x, y, "D1")
        for y in range(super_y - 1, super_y + 2)
        for x in range(super_x - 1, super_x + 2)
        if (x, y) != (super_x, super_y) and grid.contains(x, y)
    )

    magnitude = math.hypot(heading_east, heading_north)
    if magnitude == 0.0:
        heading_east, heading_north = 1.0, 0.0
    else:
        heading_east /= magnitude
        heading_north /= magnitude
    interest = distant_interest or {}
    candidates = []
    max_radius = max(grid.columns, grid.rows)
    for y in range(grid.rows):
        for x in range(grid.columns):
            dx, dy = x - super_x, y - super_y
            chebyshev = max(abs(dx), abs(dy))
            if chebyshev <= 1:
                continue
            distance = math.hypot(dx, dy)
            forward = (dx * heading_east + dy * heading_north) / distance
            cross = abs(dx * heading_north - dy * heading_east) / distance
            importance = float(interest.get((x, y), 0.0))
            # Relief/landmark interest is useful only if it is not well behind
            # the aircraft.  In the ordinary case the nearest forward wedge
            # wins; the stable ID closes all ties.
            rank = (
                0 if forward >= 0.0 else 1,
                -importance,
                cross,
                chebyshev / max_radius,
                grid.supertile(x, y).super_id,
            )
            candidates.append((rank, x, y))
    candidates.sort()
    distant = tuple(
        ActiveComponent("distant", x, y, "D2")
        for _, x, y in candidates[:DISTANT_ACTIVE_BUDGET]
    )
    plan = ActiveTerrainPlan(near, transition, distant)
    if plan.terrain_count > TERRAIN_ACTIVE_BUDGET:
        raise AssertionError("terrain hierarchy exceeded its active-object budget")
    return plan


@dataclass(frozen=True, slots=True)
class WideWireWitness:
    delta_east_m: int
    delta_north_m: int
    east_counts: int
    north_counts: int
    fits_signed_word: bool
    fits_signed_24: bool
    distance_m: float
    inside_current_far_plane: bool


def wide_wire_witness(
    delta_east_m: int,
    delta_north_m: int,
) -> WideWireWitness:
    east_counts = delta_east_m * PINGO_TRANSLATION_COUNTS_PER_METRE
    north_counts = delta_north_m * PINGO_TRANSLATION_COUNTS_PER_METRE
    distance_m = math.hypot(delta_east_m, delta_north_m)
    return WideWireWitness(
        delta_east_m,
        delta_north_m,
        east_counts,
        north_counts,
        max(abs(east_counts), abs(north_counts)) <= PINGO_SIGNED_WORD_MAX,
        max(abs(east_counts), abs(north_counts)) <= PINGO_SIGNED_24_MAX,
        distance_m,
        distance_m <= PINGO_CURRENT_FAR_METRES,
    )


class Cs2CsTransformer:
    """Persistent UTM-to-NLCD projection helper for proof generation."""

    def __init__(self) -> None:
        self._process = subprocess.Popen(
            ["cs2cs", "-f", "%.9f", "EPSG:32610", "EPSG:5070"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def transform(
        self, points: Sequence[tuple[float, float]]
    ) -> tuple[tuple[float, float], ...]:
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        for east, north in points:
            self._process.stdin.write(f"{east:.9f} {north:.9f}\n")
        self._process.stdin.flush()
        transformed = []
        for _ in points:
            line = self._process.stdout.readline()
            fields = line.split()
            if len(fields) < 2 or fields[0] == "*" or fields[1] == "*":
                raise ValueError(f"cs2cs rejected regional point: {line.strip()}")
            transformed.append((float(fields[0]), float(fields[1])))
        return tuple(transformed)

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        stderr = self._process.stderr.read() if self._process.stderr is not None else ""
        return_code = self._process.wait()
        if return_code or stderr.strip():
            raise RuntimeError(
                f"cs2cs exited {return_code}: {stderr.strip() or 'no diagnostic'}"
            )

    def __enter__(self) -> "Cs2CsTransformer":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.close()
        else:
            self._process.terminate()
            self._process.wait()


def sample_component(
    grid: WorldGrid,
    spec: ComponentSpec,
    dem: RasterMosaic,
    nlcd: RasterMosaic,
    transformer: Cs2CsTransformer,
) -> BuiltComponent:
    """Sample the pinned DEM/NLCD mosaics for one hierarchy component."""

    topology = rectangular_topology(grid, spec.rectangle, spec.lod)
    elevations = []
    for east, north in topology.points:
        sample = dem.sample_bilinear(east, north)
        if sample.value is None:
            raise ValueError(f"DEM nodata at hierarchy vertex {east},{north}")
        elevations.append(float(sample.value))
    projected = transformer.transform(topology.points)
    materials = []
    for face in topology.faces:
        triangle = tuple(projected[index] for index in face)
        west = min(point[0] for point in triangle)
        south = min(point[1] for point in triangle)
        east = max(point[0] for point in triangle)
        north = max(point[1] for point in triangle)

        def centroid_lookup(x: float, y: float) -> int | None:
            sample = nlcd.sample_nearest(x, y, clamp=True)
            return None if sample.value is None else int(sample.value)

        category, _ = predominant_category(
            triangle,
            nlcd.cells_in_bbox(west, south, east, north),
            centroid_lookup=centroid_lookup,
        )
        average_elevation = sum(elevations[index] for index in face) / 3.0
        if category not in NLCD_TO_MATERIAL:
            material = (
                WATER_MATERIAL
                if average_elevation <= 3.0
                else UNKNOWN_LAND_MATERIAL
            )
        else:
            material = NLCD_TO_MATERIAL[category]
        materials.append(material)
    return build_component(
        grid,
        spec,
        elevations_m=elevations,
        surface_materials=materials,
    )


def build_pinned_proof(
    project_root: Path,
    output_root: Path,
    *,
    super_x: int = 23,
    super_y: int = 36,
    verify_sources: bool = True,
) -> dict[str, object]:
    """Build one KOAK-adjacent family directly from the pinned source files."""

    manifest_path = project_root / "data/manifests/bay-area-2026-08-02.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if verify_sources:
        for dataset in manifest["datasets"]:
            for source in dataset["tiles"]:
                source_path = project_root / source["local_path"]
                if source_path.stat().st_size != source["byte_size"]:
                    raise ValueError(f"source size changed: {source_path}")
                digest = hashlib.sha256()
                with source_path.open("rb") as source_file:
                    while block := source_file.read(1 << 20):
                        digest.update(block)
                if digest.hexdigest() != source["sha256"]:
                    raise ValueError(f"source SHA-256 changed: {source_path}")
    datasets = {item["id"]: item for item in manifest["datasets"]}
    dem = RasterMosaic(project_root, datasets[DEM_DATASET_ID])
    nlcd = RasterMosaic(project_root, datasets[NLCD_DATASET_ID])
    hierarchy = SuperTileGrid()
    supertile = hierarchy.supertile(super_x, super_y)
    built = []
    with Cs2CsTransformer() as transformer:
        for spec in component_specs(supertile):
            built.append(sample_component(hierarchy.base, spec, dem, nlcd, transformer))
    bundle = make_bundle(tuple(item.tile for item in built))
    parsed, spans = parse_bundle(bundle)
    if parsed != tuple(item.tile for item in built):
        raise AssertionError("multi-record AGNB proof did not round trip")
    output = output_root / hierarchy.path(super_x, super_y)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bundle)
    return {
        "schema": "pingo-terrain-regional-lod-proof-v1",
        "source_manifest": str(manifest_path.relative_to(project_root)),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_files_verified": verify_sources,
        "super_x": super_x,
        "super_y": super_y,
        "path": hierarchy.path(super_x, super_y).as_posix(),
        "output": str(output),
        "bytes": len(bundle),
        "sha256": hashlib.sha256(bundle).hexdigest(),
        "records": [
            {
                "key": item.spec.key,
                "tier": item.spec.tier,
                "lod": item.spec.lod,
                "data_bytes": span.data_bytes,
                "vertices": len(item.tile.positions),
                "triangles": len(item.tile.position_indices) // 3,
                "minimum_elevation_m": item.surface_minimum_elevation_m,
                "maximum_elevation_m": item.surface_maximum_elevation_m,
                "list_offset": span.list_offset,
                "data_offset": span.data_offset,
            }
            for item, span in zip(built, spans, strict=True)
        ],
    }


def build_pinned_family_set(
    project_root: Path,
    output_root: Path,
    families: Sequence[tuple[int, int]],
    *,
    verify_sources: bool = True,
) -> dict[str, object]:
    """Build a deterministic set of family files with shared raster handles.

    This is the fixture-scale compiler entry point.  It performs source
    verification once, keeps one DEM/NLCD mosaic and one ``cs2cs`` process
    alive, and still round-trips every emitted multi-record AGNB independently.
    """

    if not families:
        raise ValueError("family set must not be empty")
    if len(set(families)) != len(families):
        raise ValueError("family set contains duplicate coordinates")
    manifest_path = project_root / "data/manifests/bay-area-2026-08-02.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if verify_sources:
        for dataset in manifest["datasets"]:
            for source in dataset["tiles"]:
                source_path = project_root / source["local_path"]
                if source_path.stat().st_size != source["byte_size"]:
                    raise ValueError(f"source size changed: {source_path}")
                digest = hashlib.sha256()
                with source_path.open("rb") as source_file:
                    while block := source_file.read(1 << 20):
                        digest.update(block)
                if digest.hexdigest() != source["sha256"]:
                    raise ValueError(f"source SHA-256 changed: {source_path}")

    datasets = {item["id"]: item for item in manifest["datasets"]}
    dem = RasterMosaic(project_root, datasets[DEM_DATASET_ID])
    nlcd = RasterMosaic(project_root, datasets[NLCD_DATASET_ID])
    hierarchy = SuperTileGrid()
    reports = []
    with Cs2CsTransformer() as transformer:
        for super_x, super_y in families:
            supertile = hierarchy.supertile(super_x, super_y)
            built = [
                sample_component(hierarchy.base, spec, dem, nlcd, transformer)
                for spec in component_specs(supertile)
            ]
            bundle = make_bundle(tuple(item.tile for item in built))
            parsed, spans = parse_bundle(bundle)
            if parsed != tuple(item.tile for item in built):
                raise AssertionError(
                    f"family {super_x},{super_y} changed during AGNB round trip"
                )
            relative = hierarchy.path(super_x, super_y)
            output = output_root / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(bundle)
            reports.append(
                {
                    "super_x": super_x,
                    "super_y": super_y,
                    "family_id": supertile.super_id,
                    "path": relative.as_posix(),
                    "bytes": len(bundle),
                    "sha256": hashlib.sha256(bundle).hexdigest(),
                    "records": [
                        {
                            "key": item.spec.key,
                            "tier": item.spec.tier,
                            "lod": item.spec.lod,
                            "tile_x": item.tile.meta.tile_x,
                            "tile_y": item.tile.meta.tile_y,
                            "data_bytes": span.data_bytes,
                            "record_index": span.record_index,
                        }
                        for item, span in zip(built, spans, strict=True)
                    ],
                }
            )
    return {
        "schema": "pingo-terrain-regional-lod-family-set-v1",
        "source_manifest": str(manifest_path.relative_to(project_root)),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_files_verified": verify_sources,
        "family_count": len(reports),
        "bytes": sum(item["bytes"] for item in reports),
        "families": reports,
    }


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("budget", help="calculate the exact whole-world topology budget")
    proof = subparsers.add_parser("proof", help="build one KOAK-adjacent pinned-raster bundle")
    proof.add_argument("--project-root", type=Path, required=True)
    proof.add_argument("--output-root", type=Path, required=True)
    proof.add_argument("--super-x", type=int, default=23)
    proof.add_argument("--super-y", type=int, default=36)
    proof.add_argument(
        "--skip-source-hash",
        action="store_true",
        help="development-only: do not verify every pinned source file",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if arguments.command == "budget":
        result = world_budget()
    else:
        result = build_pinned_proof(
            arguments.project_root.resolve(),
            arguments.output_root.resolve(),
            super_x=arguments.super_x,
            super_y=arguments.super_y,
            verify_sources=not arguments.skip_source_hash,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
