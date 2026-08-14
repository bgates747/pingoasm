"""Exact-count flat-top hexagonal terrain cells for the Bay Area corpus.

The runtime Pingo coordinate is one sixteenth of a metre.  This module keeps
all horizontal topology in that integer domain: independently generated cells
therefore reuse byte-identical edge and corner keys without relying on float
rounding.  Projected metres are exposed only at raster-sampling boundaries.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Iterable

from .materials import BERKELEY_TERRAIN_MATERIALS
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


COUNTS_PER_METRE = 16
HEX_SIDE_STEPS = 5
LATTICE_U_EAST_M = 64
LATTICE_V_EAST_M = 32
LATTICE_V_NORTH_M = 55
HEX_SIDE_M = HEX_SIDE_STEPS * LATTICE_U_EAST_M
HEX_AREA_M2 = 6 * HEX_SIDE_STEPS**2 * (
    LATTICE_U_EAST_M * LATTICE_V_NORTH_M / 2
)
SQUARE_CONTROL_AREA_M2 = 512**2

# Cell (0,0) is centred on the old rectangular tile (0,0).  Both basis
# vectors are exact whole metres, preserving the P3DM layout-1 centre fields.
HEX_ORIGIN_EAST_M = REGIONAL_ORIGIN_EAST_M + 256
HEX_ORIGIN_NORTH_M = REGIONAL_ORIGIN_NORTH_M + 256
HEX_BASIS_Q_EAST_M = 480
HEX_BASIS_Q_NORTH_M = 275
HEX_BASIS_R_EAST_M = 0
HEX_BASIS_R_NORTH_M = 550

HEX_Q_MIN = 0
HEX_Q_MAX = 213
HEX_EVEN_COLUMN_ROWS = 235
HEX_ODD_COLUMN_ROWS = 234
HEX_CELL_COUNT = 50_183

# A half extent of 1024 metres deliberately makes every horizontal normalized
# word exactly twice its signed 1/16-metre delta.  With Q8.8 scale 32768, the
# mesh term and command-52 translation term then share the same 256/32767
# multiplier and reconstruct common seams identically in Pingo.
HEX_MODEL_HALF_EXTENT_M = 1024
HEX_OBJECT_SCALE_Q8_8 = HEX_MODEL_HALF_EXTENT_M * 32
HEX_TERRAIN_Y_COUNT = round(REGIONAL_VERTICAL_ORIGIN_M * COUNTS_PER_METRE)
HEX_SKIRT_DEPTH_COUNTS = round(SKIRT_DEPTH_M * COUNTS_PER_METRE)
HEX_CORNER_OFFSETS_COUNTS: tuple[tuple[int, int], ...] = (
    (5_120, 0),
    (2_560, 4_400),
    (-2_560, 4_400),
    (-5_120, 0),
    (-2_560, -4_400),
    (2_560, -4_400),
)


@dataclass(frozen=True, slots=True)
class HexCell:
    """One bounded regional axial identity."""

    q: int
    r: int

    @property
    def offset_row(self) -> int:
        return self.r + self.q // 2

    @property
    def cell_id(self) -> int:
        validate_cell(self.q, self.r)
        return (
            (self.q // 2) * (HEX_EVEN_COLUMN_ROWS + HEX_ODD_COLUMN_ROWS)
            + (HEX_EVEN_COLUMN_ROWS if self.q & 1 else 0)
            + self.offset_row
        )

    @property
    def center_m(self) -> tuple[int, int]:
        return hex_center_m(self.q, self.r)


@dataclass(frozen=True, slots=True)
class HexTopology:
    """One cell's exact share of the global triangular lattice."""

    # Exact projected 1/16-metre (east, north) keys.
    keys: tuple[tuple[int, int], ...]
    points: tuple[tuple[float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    boundary_edges: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True, slots=True)
class BuiltHexTerrainCell:
    tile: P3DMTile
    surface_vertex_count: int
    surface_triangle_count: int
    skirt_triangle_count: int
    surface_minimum_elevation_m: float
    surface_maximum_elevation_m: float
    mesh_minimum_elevation_m: float
    material_histogram: tuple[tuple[int, int], ...]


def rows_for_q(q: int) -> int:
    if not HEX_Q_MIN <= q <= HEX_Q_MAX:
        raise ValueError(f"hex q is outside {HEX_Q_MIN}..{HEX_Q_MAX}: {q}")
    return HEX_ODD_COLUMN_ROWS if q & 1 else HEX_EVEN_COLUMN_ROWS


def validate_cell(q: int, r: int) -> None:
    rows = rows_for_q(q)
    offset_row = r + q // 2
    if not 0 <= offset_row < rows:
        raise ValueError(f"hex cell is outside regional coverage: {q},{r}")


def cell_from_id(cell_id: int) -> HexCell:
    if not 0 <= cell_id < HEX_CELL_COUNT:
        raise ValueError(f"hex cell ID is outside 0..{HEX_CELL_COUNT - 1}: {cell_id}")
    pair, within_pair = divmod(
        cell_id, HEX_EVEN_COLUMN_ROWS + HEX_ODD_COLUMN_ROWS
    )
    if within_pair < HEX_EVEN_COLUMN_ROWS:
        q = pair * 2
        offset_row = within_pair
    else:
        q = pair * 2 + 1
        offset_row = within_pair - HEX_EVEN_COLUMN_ROWS
    cell = HexCell(q, offset_row - q // 2)
    validate_cell(cell.q, cell.r)
    return cell


def iter_cells() -> Iterable[HexCell]:
    for q in range(HEX_Q_MIN, HEX_Q_MAX + 1):
        for offset_row in range(rows_for_q(q)):
            yield HexCell(q, offset_row - q // 2)


def hex_center_m(q: int, r: int) -> tuple[int, int]:
    validate_cell(q, r)
    return (
        HEX_ORIGIN_EAST_M + q * HEX_BASIS_Q_EAST_M + r * HEX_BASIS_R_EAST_M,
        HEX_ORIGIN_NORTH_M + q * HEX_BASIS_Q_NORTH_M + r * HEX_BASIS_R_NORTH_M,
    )


def hex_corners_counts(q: int, r: int) -> tuple[tuple[int, int], ...]:
    center_east_m, center_north_m = hex_center_m(q, r)
    center = (
        center_east_m * COUNTS_PER_METRE,
        center_north_m * COUNTS_PER_METRE,
    )
    return tuple(
        (center[0] + east, center[1] + north)
        for east, north in HEX_CORNER_OFFSETS_COUNTS
    )


def _point_in_closed_hex(east_count: int, north_count: int, cell: HexCell) -> bool:
    corners = hex_corners_counts(cell.q, cell.r)
    for first, second in zip(corners, corners[1:] + corners[:1], strict=True):
        edge_east = second[0] - first[0]
        edge_north = second[1] - first[1]
        point_east = east_count - first[0]
        point_north = north_count - first[1]
        if edge_east * point_north - edge_north * point_east < 0:
            return False
    return True


def locate_hex_cell_counts(east_count: int, north_count: int) -> HexCell:
    """Locate a projected count in the exact polygon tiling.

    Closed polygons intentionally admit both owners on a shared boundary;
    lexicographic ``(q,r)`` order is the corpus-wide deterministic tie rule.
    Runtime hysteresis may retain the previous valid owner near that boundary,
    but may not select a different non-neighboring cell.
    """

    if not isinstance(east_count, int) or not isinstance(north_count, int):
        raise TypeError("hex lookup coordinates must be integer 1/16-metre counts")
    origin_east_count = HEX_ORIGIN_EAST_M * COUNTS_PER_METRE
    origin_north_count = HEX_ORIGIN_NORTH_M * COUNTS_PER_METRE
    q_estimate = (east_count - origin_east_count) // (
        HEX_BASIS_Q_EAST_M * COUNTS_PER_METRE
    )
    # Remove the exact q contribution before estimating r.  A four-cell
    # neighborhood absorbs floor bias near the two sloped boundaries.
    r_estimate = (
        north_count
        - origin_north_count
        - q_estimate * HEX_BASIS_Q_NORTH_M * COUNTS_PER_METRE
    ) // (HEX_BASIS_R_NORTH_M * COUNTS_PER_METRE)
    candidates: list[HexCell] = []
    for q in range(q_estimate - 3, q_estimate + 4):
        if not HEX_Q_MIN <= q <= HEX_Q_MAX:
            continue
        for r in range(r_estimate - 3, r_estimate + 4):
            try:
                cell = HexCell(q, r)
                validate_cell(q, r)
            except ValueError:
                continue
            if _point_in_closed_hex(east_count, north_count, cell):
                candidates.append(cell)
    if not candidates:
        raise ValueError(
            f"projected count is outside bounded hex coverage: "
            f"{east_count},{north_count}"
        )
    return min(candidates, key=lambda cell: (cell.q, cell.r))


def locate_hex_cell(east_m: float, north_m: float) -> HexCell:
    return locate_hex_cell_counts(
        round(east_m * COUNTS_PER_METRE),
        round(north_m * COUNTS_PER_METRE),
    )


def hex_distance(first: tuple[int, int], second: tuple[int, int]) -> int:
    dq = first[0] - second[0]
    dr = first[1] - second[1]
    return max(abs(dq), abs(dr), abs(-dq - dr))


def ring_offsets(radius: int) -> tuple[tuple[int, int], ...]:
    """Return one clockwise axial ring, with a deterministic west start."""

    if radius < 0:
        raise ValueError("hex radius cannot be negative")
    if radius == 0:
        return ((0, 0),)
    directions = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
    q, r = -radius, radius
    result: list[tuple[int, int]] = []
    for dq, dr in directions:
        for _ in range(radius):
            result.append((q, r))
            q += dq
            r += dr
    if (q, r) != (-radius, radius):
        raise AssertionError("hex ring walk did not close")
    return tuple(result)


def disk_offsets(radius: int) -> tuple[tuple[int, int], ...]:
    if radius < 0:
        raise ValueError("hex radius cannot be negative")
    return tuple(
        offset
        for ring in range(radius + 1)
        for offset in ring_offsets(ring)
    )


def _inside_local_hex(i: int, j: int) -> bool:
    return max(abs(i), abs(j), abs(i + j)) <= HEX_SIDE_STEPS


def hex_topology(q: int, r: int) -> HexTopology:
    """Build one N=5 hex from canonical global triangular-lattice keys."""

    center_east_m, center_north_m = hex_center_m(q, r)
    center_east_count = center_east_m * COUNTS_PER_METRE
    center_north_count = center_north_m * COUNTS_PER_METRE

    local_vertices = tuple(
        (i, j)
        for i in range(-HEX_SIDE_STEPS, HEX_SIDE_STEPS + 1)
        for j in range(-HEX_SIDE_STEPS, HEX_SIDE_STEPS + 1)
        if _inside_local_hex(i, j)
    )
    key_for_local = {
        (i, j): (
            center_east_count
            + i * LATTICE_U_EAST_M * COUNTS_PER_METRE
            + j * LATTICE_V_EAST_M * COUNTS_PER_METRE,
            center_north_count + j * LATTICE_V_NORTH_M * COUNTS_PER_METRE,
        )
        for i, j in local_vertices
    }
    keys = tuple(sorted(key_for_local.values()))
    key_indices = {key: index for index, key in enumerate(keys)}

    source_faces: list[tuple[tuple[int, int], ...]] = []
    for i in range(-HEX_SIDE_STEPS - 1, HEX_SIDE_STEPS + 1):
        for j in range(-HEX_SIDE_STEPS - 1, HEX_SIDE_STEPS + 1):
            for face in (
                ((i, j), (i + 1, j), (i, j + 1)),
                ((i + 1, j), (i + 1, j + 1), (i, j + 1)),
            ):
                if all(_inside_local_hex(*vertex) for vertex in face):
                    source_faces.append(face)

    faces: list[tuple[int, int, int]] = []
    for source_face in source_faces:
        face = [key_indices[key_for_local[vertex]] for vertex in source_face]
        # Pingo x=north and z=-east.  Keep every surface normal upward.
        a, b, c = (keys[index] for index in face)
        ab_x, ab_z = b[1] - a[1], -(b[0] - a[0])
        ac_x, ac_z = c[1] - a[1], -(c[0] - a[0])
        if ab_z * ac_x - ab_x * ac_z <= 0:
            face[1], face[2] = face[2], face[1]
        faces.append(tuple(face))

    edge_counts: Counter[tuple[int, int]] = Counter()
    edge_owners: dict[tuple[int, int], tuple[int, int, int]] = {}
    for face_index, face in enumerate(faces):
        for start, end in zip(face, face[1:] + face[:1], strict=True):
            edge = min(start, end), max(start, end)
            edge_counts[edge] += 1
            edge_owners[edge] = start, end, face_index
    boundary_edges = tuple(
        edge_owners[edge] for edge in sorted(edge_counts) if edge_counts[edge] == 1
    )
    return HexTopology(
        keys=keys,
        points=tuple(
            (east / COUNTS_PER_METRE, north / COUNTS_PER_METRE)
            for east, north in keys
        ),
        faces=tuple(faces),
        boundary_edges=boundary_edges,
    )


def _encoded_horizontal(delta_count: int) -> int:
    encoded = 2 * delta_count
    if not -32767 <= encoded <= 32767:
        raise ValueError(f"hex horizontal coordinate exceeds model extent: {delta_count}")
    return encoded


def _encoded_elevation(elevation_m: float) -> tuple[int, int]:
    elevation_count = round(elevation_m * COUNTS_PER_METRE)
    encoded = 2 * (elevation_count - HEX_TERRAIN_Y_COUNT)
    if not -32767 <= encoded <= 32767:
        raise ValueError(f"hex elevation exceeds model extent: {elevation_m}")
    return encoded, elevation_count


def build_hex_terrain_cell(
    q: int,
    r: int,
    *,
    elevations_m: Iterable[float],
    surface_materials: Iterable[int],
    stage_buffer_id: int = STAGING_BUFFER_ID,
) -> BuiltHexTerrainCell:
    """Encode a sampled hex cell and its deterministic boundary skirt."""

    topology = hex_topology(q, r)
    elevations = tuple(float(value) for value in elevations_m)
    materials = tuple(int(value) for value in surface_materials)
    if len(elevations) != len(topology.points):
        raise ValueError("elevation count does not match hex topology")
    if len(materials) != len(topology.faces):
        raise ValueError("material count does not match hex topology")
    if any(not 0 <= value < len(BERKELEY_TERRAIN_MATERIALS) for value in materials):
        raise ValueError("hex terrain material ID is outside the terrain vocabulary")

    center_east_m, center_north_m = hex_center_m(q, r)
    center_east_count = center_east_m * COUNTS_PER_METRE
    center_north_count = center_north_m * COUNTS_PER_METRE
    encoded_elevations = tuple(_encoded_elevation(value) for value in elevations)
    positions: list[tuple[int, int, int]] = [
        (
            _encoded_horizontal(north_count - center_north_count),
            encoded_elevations[index][0],
            _encoded_horizontal(-(east_count - center_east_count)),
        )
        for index, (east_count, north_count) in enumerate(topology.keys)
    ]
    faces = list(topology.faces)
    face_materials = list(materials)
    bottom_indices: dict[int, int] = {}
    bottom_elevation_counts: dict[int, int] = {}
    for start, end, owner_face in topology.boundary_edges:
        for top_index in (start, end):
            if top_index not in bottom_indices:
                east_count, north_count = topology.keys[top_index]
                bottom_count = encoded_elevations[top_index][1] - HEX_SKIRT_DEPTH_COUNTS
                encoded_y = 2 * (bottom_count - HEX_TERRAIN_Y_COUNT)
                if encoded_y < -32767:
                    encoded_y = -32767
                    bottom_count = HEX_TERRAIN_Y_COUNT + math.ceil(encoded_y / 2)
                bottom_indices[top_index] = len(positions)
                bottom_elevation_counts[top_index] = bottom_count
                positions.append(
                    (
                        _encoded_horizontal(north_count - center_north_count),
                        encoded_y,
                        _encoded_horizontal(-(east_count - center_east_count)),
                    )
                )
        bottom_start = bottom_indices[start]
        bottom_end = bottom_indices[end]
        faces.extend(((start, bottom_start, bottom_end), (start, bottom_end, end)))
        face_materials.extend((materials[owner_face], materials[owner_face]))

    position_indices = tuple(index for face in faces for index in face)
    uv_indices = tuple(material for material in face_materials for _ in range(3))
    surface_minimum = min(elevations)
    surface_maximum = max(elevations)
    mesh_minimum = min(
        surface_minimum,
        min(bottom_elevation_counts.values()) / COUNTS_PER_METRE,
    )
    tile = P3DMTile(
        stage_buffer_id=stage_buffer_id,
        meta=P3DMMeta(
            layer_kind=LayerKind.TERRAIN,
            lod=0,
            shading_mode=ShadingMode.FLAT_PATTERN,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
            tile_x=q,
            tile_y=r,
            center_east_m=center_east_m - REGIONAL_ORIGIN_EAST_M,
            center_north_m=center_north_m - REGIONAL_ORIGIN_NORTH_M,
            minimum_elevation_dm=math.floor(mesh_minimum * 10),
            maximum_elevation_dm=math.ceil(surface_maximum * 10),
            model_half_extent_m=HEX_MODEL_HALF_EXTENT_M,
        ),
        positions=tuple(positions),
        position_indices=position_indices,
        uvs=tuple(selector_uv_words(index) for index in range(16)),
        uv_indices=uv_indices,
    )
    return BuiltHexTerrainCell(
        tile=tile,
        surface_vertex_count=len(topology.keys),
        surface_triangle_count=len(topology.faces),
        skirt_triangle_count=len(topology.boundary_edges) * 2,
        surface_minimum_elevation_m=surface_minimum,
        surface_maximum_elevation_m=surface_maximum,
        mesh_minimum_elevation_m=mesh_minimum,
        material_histogram=tuple(sorted(Counter(materials).items())),
    )
