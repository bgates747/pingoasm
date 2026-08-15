"""Simple regular-hex distance terrain for the first mixed-LOD control.

The accepted natural terrain remains the near field.  This module converts the
already-reviewed one-centre/six-triangle representation of regular hex cells
into modest P3DM chunks for a deliberately crude distant annulus.  It is not
the final silhouette-aware reducer described by the design specification.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import PurePosixPath
from typing import Mapping, Sequence

from .hex_terrain import HEX_TERRAIN_Y_COUNT, hex_center_m
from .p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    P3DMMeta,
    P3DMTile,
    ShadingMode,
)
from .regional_terrain import (
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    REGIONAL_VERTICAL_ORIGIN_M,
    SKIRT_DEPTH_M,
    STAGING_BUFFER_ID,
    selector_uv_words,
)


START_CELL = (80, 125)
NEAR_RING = 5
MIDDLE_RING = 15
FAR_RING = 30
BUCKET_Q_COLUMNS = 7
BUCKET_OFFSET_ROWS = 6
BUCKET_OFFSET_ROW_BIAS = 5
MODEL_HALF_EXTENT_M = 1_792
OBJECT_SCALE_Q8_8 = MODEL_HALF_EXTENT_M * 32
NEAR_SLOT_COUNT = 91
MESH_ID_BASE = 1
OBJECT_ID_BASE = 1
P3DM_FILE_LIMIT = 16_384


@dataclass(frozen=True, slots=True)
class DistanceVertex:
    """One exact projected review vertex and its sampled elevation."""

    east_m: int
    north_m: int
    elevation_m: float


@dataclass(frozen=True, slots=True)
class DistanceFace:
    """One positive-up Blender triangle before Pingo handedness conversion."""

    vertices: tuple[int, int, int]
    q: int
    r: int
    material_id: int


@dataclass(frozen=True, slots=True)
class DistanceChunk:
    """One generated runtime record and its fixed initial transform."""

    ordinal: int
    tier: int
    bucket_q: int
    bucket_r: int
    cells: tuple[tuple[int, int], ...]
    tile: P3DMTile
    translation_counts: tuple[int, int, int]
    surface_triangles: int
    skirt_triangles: int

    @property
    def relative_path(self) -> PurePosixPath:
        return PurePosixPath(
            "DST",
            f"{self.ordinal >> 8:02X}",
            f"{self.ordinal & 0xFF:02X}.AGN",
        )


def axial_distance(q: int, r: int, origin: tuple[int, int] = START_CELL) -> int:
    """Return the canonical axial hex distance from ``origin``."""

    dq = q - origin[0]
    dr = r - origin[1]
    return max(abs(dq), abs(dr), abs(dq + dr))


def distance_tier(q: int, r: int) -> int | None:
    """Classify a cell as middle L1, far L2, or outside this experiment."""

    distance = axial_distance(q, r)
    if NEAR_RING < distance <= MIDDLE_RING:
        return 1
    if MIDDLE_RING < distance <= FAR_RING:
        return 2
    return None


def chunk_key(face: DistanceFace) -> tuple[int, int, int] | None:
    """Return a stable tier and compact offset-grid bucket for one face.

    Seven q columns by six staggered offset rows keep every selected chunk
    within a measured 1,760 x 1,787.5 metre half extent.  Keeping the tier in
    the key preserves an explicit middle/far contract even though this first
    control intentionally uses the same six-triangle topology for both.
    """

    tier = distance_tier(face.q, face.r)
    if tier is None:
        return None
    offset_row = face.r + face.q // 2
    return (
        tier,
        face.q // BUCKET_Q_COLUMNS,
        (offset_row - BUCKET_OFFSET_ROW_BIAS) // BUCKET_OFFSET_ROWS,
    )


def _encode_axis(value_m: float) -> int:
    encoded = round(value_m / MODEL_HALF_EXTENT_M * 32_767)
    if not -32_767 <= encoded <= 32_767:
        raise ValueError(
            f"distance-LOD coordinate {value_m} m exceeds "
            f"the {MODEL_HALF_EXTENT_M} m half extent"
        )
    return encoded


def _boundary_edges(
    faces: Sequence[tuple[int, int, int]],
) -> tuple[tuple[int, int, int], ...]:
    counts: Counter[tuple[int, int]] = Counter()
    owners: dict[tuple[int, int], tuple[int, int, int]] = {}
    for face_index, face in enumerate(faces):
        for start, end in zip(face, face[1:] + face[:1], strict=True):
            edge = min(start, end), max(start, end)
            counts[edge] += 1
            owners[edge] = start, end, face_index
    if any(count > 2 for count in counts.values()):
        raise ValueError("distance-LOD chunk contains a non-manifold edge")
    return tuple(owners[edge] for edge in sorted(counts) if counts[edge] == 1)


def build_chunk(
    ordinal: int,
    key: tuple[int, int, int],
    faces: Sequence[DistanceFace],
    vertices: Mapping[int, DistanceVertex],
) -> DistanceChunk:
    """Build one skirted P3DM chunk from regular six-triangle cell faces."""

    if not faces:
        raise ValueError("distance-LOD chunk cannot be empty")
    tier, bucket_q, bucket_r = key
    if tier not in (1, 2):
        raise ValueError(f"unsupported distance tier: {tier}")
    if any(chunk_key(face) != key for face in faces):
        raise ValueError("distance-LOD chunk mixes bucket identities")

    source_ids = sorted({index for face in faces for index in face.vertices})
    if any(index not in vertices for index in source_ids):
        raise ValueError("distance-LOD face references a missing source vertex")
    source = [vertices[index] for index in source_ids]
    center_east_m = round(
        (min(vertex.east_m for vertex in source) + max(vertex.east_m for vertex in source))
        / 2
    )
    center_north_m = round(
        (
            min(vertex.north_m for vertex in source)
            + max(vertex.north_m for vertex in source)
        )
        / 2
    )

    local_by_source = {source_id: local for local, source_id in enumerate(source_ids)}
    positions = [
        (
            _encode_axis(vertex.north_m - center_north_m),
            _encode_axis(vertex.elevation_m - REGIONAL_VERTICAL_ORIGIN_M),
            _encode_axis(-(vertex.east_m - center_east_m)),
        )
        for vertex in source
    ]

    # (east,north,up)->(Pingo x,y,z)=(north,up,-east) changes handedness.
    # Reverse every source triangle so the renderer sees the intended front.
    pingo_faces = [
        (
            local_by_source[face.vertices[0]],
            local_by_source[face.vertices[2]],
            local_by_source[face.vertices[1]],
        )
        for face in faces
    ]
    materials = [face.material_id for face in faces]
    if any(not 0 <= material < 16 for material in materials):
        raise ValueError("distance-LOD material ID lies outside 0..15")

    boundary = _boundary_edges(pingo_faces)
    bottom_indices: dict[int, int] = {}
    bottom_elevations: list[float] = []
    for start, end, owner_face in boundary:
        for top in (start, end):
            if top in bottom_indices:
                continue
            vertex = source[top]
            bottom_elevation = vertex.elevation_m - SKIRT_DEPTH_M
            bottom_indices[top] = len(positions)
            bottom_elevations.append(bottom_elevation)
            positions.append(
                (
                    _encode_axis(vertex.north_m - center_north_m),
                    _encode_axis(bottom_elevation - REGIONAL_VERTICAL_ORIGIN_M),
                    _encode_axis(-(vertex.east_m - center_east_m)),
                )
            )
        bottom_start = bottom_indices[start]
        bottom_end = bottom_indices[end]
        pingo_faces.extend(
            ((start, bottom_start, bottom_end), (start, bottom_end, end))
        )
        materials.extend((faces[owner_face].material_id,) * 2)

    elevations = [vertex.elevation_m for vertex in source]
    tile = P3DMTile(
        stage_buffer_id=STAGING_BUFFER_ID,
        meta=P3DMMeta(
            layer_kind=LayerKind.TERRAIN,
            lod=tier,
            shading_mode=ShadingMode.FLAT_PATTERN,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
            tile_x=bucket_q,
            tile_y=bucket_r,
            center_east_m=center_east_m - REGIONAL_ORIGIN_EAST_M,
            center_north_m=center_north_m - REGIONAL_ORIGIN_NORTH_M,
            minimum_elevation_dm=math.floor(
                min(elevations + bottom_elevations) * 10.0
            ),
            maximum_elevation_dm=math.ceil(max(elevations) * 10.0),
            model_half_extent_m=MODEL_HALF_EXTENT_M,
        ),
        positions=tuple(positions),
        position_indices=tuple(index for face in pingo_faces for index in face),
        uvs=tuple(selector_uv_words(index) for index in range(16)),
        uv_indices=tuple(material for material in materials for _ in range(3)),
    )

    origin_east_m, origin_north_m = hex_center_m(*START_CELL)
    translation = (
        round((center_north_m - origin_north_m) * 16),
        HEX_TERRAIN_Y_COUNT,
        round(-(center_east_m - origin_east_m) * 16),
    )
    return DistanceChunk(
        ordinal=ordinal,
        tier=tier,
        bucket_q=bucket_q,
        bucket_r=bucket_r,
        cells=tuple(sorted({(face.q, face.r) for face in faces})),
        tile=tile,
        translation_counts=translation,
        surface_triangles=len(faces),
        skirt_triangles=2 * len(boundary),
    )
