"""Algorithmic regular-lattice distance terrain for the complete Bay Area.

The qualified detailed corpus is an N=5 triangular lattice inside every
canonical flat-top hex cell. The first distance level is a strict N=1
decimation: it retains only the N=5 centre and six N=5 corners, joins the
centre to each boundary side, and derives each coarse material from the 25
fine triangles in that sector. Source encoded positions are reused verbatim,
so independently generated neighboring cells retain byte-identical shared
vertices at the same object scale.

The reusable coarse corpus is grouped by an aligned
``8x4 -> 4x2 -> 2x1 -> 1x1`` hierarchy in ``(q, offset_row)`` space. Runtime
selection recursively refines only nodes that touch the detailed near disk,
so rings 0..5 retain N=5 cells while rings 6..30 have exactly one N=1 owner.
The partition, seams, transforms, and runtime neighborhoods are all derived
from the same lattice equations; none is hand authored.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Iterable, Sequence

from .hex_terrain import (
    HEX_BASIS_Q_EAST_M,
    HEX_BASIS_Q_NORTH_M,
    HEX_BASIS_R_NORTH_M,
    HEX_CELL_COUNT,
    HEX_CORNER_OFFSETS_COUNTS,
    HEX_EVEN_COLUMN_ROWS,
    HEX_MODEL_HALF_EXTENT_M,
    HEX_OBJECT_SCALE_Q8_8,
    HEX_ORIGIN_EAST_M,
    HEX_ORIGIN_NORTH_M,
    HEX_Q_MAX,
    HEX_SIDE_STEPS,
    HexCell,
    hex_center_m,
    hex_topology,
    iter_cells,
    ring_offsets,
    validate_cell,
)
from .p3dm import P3DMTile


NEAR_RING_MAX = 5
FAR_RING = 30
ACTIVE_CELL_COUNT = 1 + 3 * FAR_RING * (FAR_RING + 1)
SLOT_COUNT = ACTIVE_CELL_COUNT
SLOT_HASH_Q = 92
SLOT_HASH_R = 1
OBJECT_SCALE_Q8_8 = HEX_OBJECT_SCALE_Q8_8
MODEL_HALF_EXTENT_M = HEX_MODEL_HALF_EXTENT_M
P3DM_FILE_LIMIT = 16_384
SURFACE_VERTICES = 7
SURFACE_TRIANGLES = 6
SKIRT_VERTICES = 6
SKIRT_TRIANGLES = 12
TOTAL_VERTICES = SURFACE_VERTICES + SKIRT_VERTICES
TOTAL_TRIANGLES = SURFACE_TRIANGLES + SKIRT_TRIANGLES
FINE_SURFACE_TRIANGLES = 6 * HEX_SIDE_STEPS * HEX_SIDE_STEPS
FINE_TRIANGLES_PER_SECTOR = HEX_SIDE_STEPS * HEX_SIDE_STEPS
ENCODED_SKIRT_DEPTH = 2 * 64 * 16
COARSE_SLOT_FIRST = 91
COARSE_SLOT_COUNT = 164
MANAGER_SLOT_COUNT = COARSE_SLOT_FIRST + COARSE_SLOT_COUNT


@dataclass(frozen=True, slots=True)
class HierarchyLevel:
    """One aligned N=1 chunk level in q/offset-row coordinates."""

    name: str
    lod: int
    width_q: int
    height_rows: int
    model_half_extent_m: int

    @property
    def object_scale_q8_8(self) -> int:
        return self.model_half_extent_m * 32


LEVEL_L8 = HierarchyLevel("L8", 4, 8, 4, 2_001)
LEVEL_L4 = HierarchyLevel("L4", 3, 4, 2, 1_041)
LEVEL_L2 = HierarchyLevel("L2", 2, 2, 1, 1_024)
LEVEL_L1 = HierarchyLevel("L1", 1, 1, 1, 1_024)
HIERARCHY_LEVELS = (LEVEL_L8, LEVEL_L4, LEVEL_L2, LEVEL_L1)
HIERARCHY_LEVEL_BY_LOD = {level.lod: level for level in HIERARCHY_LEVELS}


@dataclass(frozen=True, slots=True)
class HierarchyNode:
    """One reusable aligned hierarchy record identified without an origin."""

    level: HierarchyLevel
    anchor_q: int
    anchor_offset_row: int

    def __post_init__(self) -> None:
        if self.anchor_q % self.level.width_q:
            raise ValueError("hierarchy q anchor is not level aligned")
        if self.anchor_offset_row % self.level.height_rows:
            raise ValueError("hierarchy row anchor is not level aligned")

    @property
    def relative_path(self) -> PurePosixPath:
        return PurePosixPath(
            "RGL",
            self.level.name,
            f"{self.anchor_q:02X}",
            f"{self.anchor_offset_row:02X}.AGN",
        )

    @property
    def identity(self) -> tuple[int, int, int]:
        return self.level.lod, self.anchor_q, self.anchor_offset_row


def offset_row(q: int, r: int) -> int:
    """Convert axial r to the corpus's non-negative row coordinate."""

    return r + q // 2


def axial_from_offset_row(q: int, row: int) -> tuple[int, int]:
    """Return the axial identity represented by q and an offset row."""

    return q, row - q // 2


def theoretical_node_cells(node: HierarchyNode) -> tuple[tuple[int, int], ...]:
    """Return every infinite-grid cell covered by one aligned node."""

    return tuple(
        axial_from_offset_row(q, row)
        for q in range(node.anchor_q, node.anchor_q + node.level.width_q)
        for row in range(
            node.anchor_offset_row,
            node.anchor_offset_row + node.level.height_rows,
        )
    )


def bounded_node_cells(node: HierarchyNode) -> tuple[HexCell, ...]:
    """Clip one reusable hierarchy node to the finite regional corpus."""

    cells = []
    for q, r in theoretical_node_cells(node):
        try:
            validate_cell(q, r)
        except ValueError:
            continue
        cells.append(HexCell(q, r))
    return tuple(cells)


def node_bounds_m(node: HierarchyNode) -> tuple[int, int, int, int]:
    """Return theoretical west/south/east/north bounds in projected metres."""

    corner_offsets_m = tuple(
        (east // 16, north // 16) for east, north in HEX_CORNER_OFFSETS_COUNTS
    )
    points = []
    for q, r in theoretical_node_cells(node):
        center = (
            HEX_ORIGIN_EAST_M + q * HEX_BASIS_Q_EAST_M,
            HEX_ORIGIN_NORTH_M
            + q * HEX_BASIS_Q_NORTH_M
            + r * HEX_BASIS_R_NORTH_M,
        )
        points.extend(
            (center[0] + east, center[1] + north)
            for east, north in corner_offsets_m
        )
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def node_center_m(node: HierarchyNode) -> tuple[int, int]:
    """Return the deterministic integer-metre P3DM origin for a node."""

    west, south, east, north = node_bounds_m(node)
    return round((west + east) / 2), round((south + north) / 2)


def node_planar_half_extents_m(node: HierarchyNode) -> tuple[float, float]:
    west, south, east, north = node_bounds_m(node)
    return (east - west) / 2, (north - south) / 2


def hierarchy_children(node: HierarchyNode) -> tuple[HierarchyNode, ...]:
    """Split one node into its complete aligned children."""

    try:
        child_level = HIERARCHY_LEVELS[HIERARCHY_LEVELS.index(node.level) + 1]
    except IndexError:
        return ()
    return tuple(
        HierarchyNode(child_level, q, row)
        for q in range(
            node.anchor_q,
            node.anchor_q + node.level.width_q,
            child_level.width_q,
        )
        for row in range(
            node.anchor_offset_row,
            node.anchor_offset_row + node.level.height_rows,
            child_level.height_rows,
        )
    )


def root_node_for_cell(q: int, r: int) -> HierarchyNode:
    row = offset_row(q, r)
    return HierarchyNode(
        LEVEL_L8,
        (q // LEVEL_L8.width_q) * LEVEL_L8.width_q,
        (row // LEVEL_L8.height_rows) * LEVEL_L8.height_rows,
    )


def _node_distances(
    node: HierarchyNode,
    origin_q: int,
    origin_r: int,
) -> tuple[int, ...]:
    return tuple(
        axial_distance(q - origin_q, r - origin_r)
        for q, r in theoretical_node_cells(node)
    )


def select_hierarchy_nodes(
    origin_q: int,
    origin_r: int,
    near_ring: int = NEAR_RING_MAX,
) -> tuple[HierarchyNode, ...]:
    """Select a disjoint N=1 hierarchy outside the detailed near disk.

    A node wholly outside the near disk is retained when it contains at least
    one ring-6..30 cell. A node touching the near disk is recursively refined;
    near leaves are omitted. Consequently every required annulus cell has one
    owner, no near cell has a coarse owner, and overfetch can occur only beyond
    the outer range where the neutral backdrop already provides fail-soft fill.
    """

    if not 0 <= near_ring <= NEAR_RING_MAX:
        raise ValueError(f"near ring lies outside 0..{NEAR_RING_MAX}: {near_ring}")
    roots = {
        root_node_for_cell(origin_q + delta_q, origin_r + delta_r)
        for delta_q, delta_r in (
            offset
            for ring in range(FAR_RING + 1)
            for offset in ring_offsets(ring)
        )
    }
    selected: list[HierarchyNode] = []

    def visit(node: HierarchyNode) -> None:
        distances = _node_distances(node, origin_q, origin_r)
        contains_annulus = any(near_ring < value <= FAR_RING for value in distances)
        if not contains_annulus:
            return
        if any(value <= near_ring for value in distances):
            for child in hierarchy_children(node):
                visit(child)
            return
        selected.append(node)

    for root in sorted(roots, key=lambda node: node.identity):
        visit(root)
    return tuple(
        sorted(
            selected,
            key=lambda node: (
                min(_node_distances(node, origin_q, origin_r)),
                -node.level.width_q,
                node.anchor_q,
                node.anchor_offset_row,
            ),
        )
    )


def validate_hierarchy_plan(
    origin_q: int,
    origin_r: int,
    near_ring: int = NEAR_RING_MAX,
) -> None:
    """Prove exact inner ownership and bounded active-node count."""

    owners: Counter[tuple[int, int]] = Counter()
    plan = select_hierarchy_nodes(origin_q, origin_r, near_ring)
    if len(plan) > 159:
        raise ValueError("regular hierarchy exceeds the proven 159-node maximum")
    for node in plan:
        owners.update(theoretical_node_cells(node))
    for ring in range(FAR_RING + 1):
        for delta_q, delta_r in ring_offsets(ring):
            cell = origin_q + delta_q, origin_r + delta_r
            expected = int(ring > near_ring)
            if owners[cell] != expected:
                raise ValueError(
                    f"hierarchy ownership at ring {ring} is {owners[cell]}, "
                    f"expected {expected}"
                )
    if any(count != 1 for count in owners.values()):
        raise ValueError("hierarchy node footprints overlap")


def bounded_hierarchy_nodes(
    origin_q: int,
    origin_r: int,
    near_ring: int = NEAR_RING_MAX,
) -> tuple[HierarchyNode, ...]:
    """Clip the phase-stable infinite plan to records present in the corpus."""

    validate_cell(origin_q, origin_r)
    return tuple(
        node
        for node in select_hierarchy_nodes(origin_q, origin_r, near_ring)
        if bounded_node_cells(node)
    )


def validate_bounded_hierarchy_plan(
    origin_q: int,
    origin_r: int,
    near_ring: int = NEAR_RING_MAX,
) -> None:
    """Prove exact ownership after clipping at a regional corpus edge."""

    owners: Counter[tuple[int, int]] = Counter()
    for node in bounded_hierarchy_nodes(origin_q, origin_r, near_ring):
        owners.update((cell.q, cell.r) for cell in bounded_node_cells(node))
    for cell in iter_cells():
        distance = axial_distance(cell.q - origin_q, cell.r - origin_r)
        if distance > FAR_RING:
            continue
        expected = int(distance > near_ring)
        if owners[(cell.q, cell.r)] != expected:
            raise ValueError(
                f"bounded hierarchy ownership for {cell.q},{cell.r} is "
                f"{owners[(cell.q, cell.r)]}, expected {expected}"
            )
    if any(count != 1 for count in owners.values()):
        raise ValueError("bounded hierarchy node footprints overlap")


def iter_hierarchy_nodes() -> Iterable[HierarchyNode]:
    """Yield every nonempty reusable regional node at all four levels."""

    for level in HIERARCHY_LEVELS:
        for anchor_q in range(0, HEX_Q_MAX + 1, level.width_q):
            for anchor_row in range(0, HEX_EVEN_COLUMN_ROWS, level.height_rows):
                node = HierarchyNode(level, anchor_q, anchor_row)
                if bounded_node_cells(node):
                    yield node


@dataclass(frozen=True, slots=True)
class DecimatedCell:
    """One deterministic N=1 cell derived from its exact N=5 payload."""

    cell: HexCell
    tile: P3DMTile
    sector_material_ids: tuple[int, ...]
    sector_class_histograms: tuple[tuple[int, int, int], ...]

    @property
    def relative_path(self) -> PurePosixPath:
        cell_id = self.cell.cell_id
        return PurePosixPath(
            "TRH", "L1", f"{cell_id >> 8:02X}", f"{cell_id & 0xFF:02X}.AGN"
        )


def terrain_class(material_id: int) -> int:
    """Map the 15 semantic materials onto water/developed/other classes."""

    if material_id == 0:
        return 0
    if 1 <= material_id <= 4:
        return 1
    if 5 <= material_id <= 14:
        return 2
    raise ValueError(f"terrain material ID lies outside 0..14: {material_id}")


def canonical_material_id(runtime_class: int) -> int:
    """Return one stable selector whose palette class is unambiguous."""

    try:
        return (0, 1, 5)[runtime_class]
    except IndexError as error:
        raise ValueError(
            f"runtime terrain class lies outside 0..2: {runtime_class}"
        ) from error


def _local_key_indices(cell: HexCell) -> tuple[int, tuple[int, ...]]:
    topology = hex_topology(cell.q, cell.r)
    center_east_m, center_north_m = hex_center_m(cell.q, cell.r)
    center_counts = center_east_m * 16, center_north_m * 16
    relative = tuple(
        (east - center_counts[0], north - center_counts[1])
        for east, north in topology.keys
    )
    return relative.index((0, 0)), tuple(
        relative.index(offset) for offset in HEX_CORNER_OFFSETS_COUNTS
    )


def _cross(
    first: tuple[int, int],
    second: tuple[int, int],
    point: tuple[int, int],
) -> int:
    return (second[0] - first[0]) * (point[1] - first[1]) - (
        second[1] - first[1]
    ) * (point[0] - first[0])


def _point_in_closed_triangle(
    point: tuple[int, int],
    triangle: Sequence[tuple[int, int]],
) -> bool:
    signs = tuple(
        _cross(start, end, point)
        for start, end in zip(triangle, triangle[1:] + triangle[:1], strict=True)
    )
    return all(value >= 0 for value in signs) or all(value <= 0 for value in signs)


def sector_fine_faces(cell: HexCell) -> tuple[tuple[int, ...], ...]:
    """Partition the 150 equal-area N=5 faces into six N=1 sectors."""

    topology = hex_topology(cell.q, cell.r)
    center_index, corner_indices = _local_key_indices(cell)
    sectors: list[list[int]] = [[] for _ in range(6)]
    for face_index, face in enumerate(topology.faces):
        # Work in exact global counts. Multiplying triangle vertices by three
        # avoids rounding the fine-face centroid.
        centroid3 = (
            sum(topology.keys[index][0] for index in face),
            sum(topology.keys[index][1] for index in face),
        )
        owners = []
        for sector in range(6):
            following = (sector + 1) % 6
            triangle3 = tuple(
                (
                    topology.keys[index][0] * 3,
                    topology.keys[index][1] * 3,
                )
                for index in (
                    center_index,
                    corner_indices[sector],
                    corner_indices[following],
                )
            )
            if _point_in_closed_triangle(centroid3, triangle3):
                owners.append(sector)
        if len(owners) != 1:
            raise ValueError(
                f"fine face {face_index} has {len(owners)} coarse sector owners"
            )
        sectors[owners[0]].append(face_index)
    result = tuple(tuple(indices) for indices in sectors)
    if tuple(map(len, result)) != (FINE_TRIANGLES_PER_SECTOR,) * 6:
        raise ValueError("N=5 faces did not partition into six equal sectors")
    return result


def _surface_faces() -> tuple[tuple[int, int, int], ...]:
    """Return upward Pingo winding for centre plus clockwise source corners."""

    # Source preview winding is centre, corner, following. Pingo's
    # (north,up,-east) basis changes handedness, hence the reversal here.
    return tuple((0, 1 + (sector + 1) % 6, 1 + sector) for sector in range(6))


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
    boundary = tuple(owners[edge] for edge in sorted(counts) if counts[edge] == 1)
    if len(boundary) != 6 or any(count > 2 for count in counts.values()):
        raise ValueError("N=1 surface boundary is not one manifold hexagon")
    return boundary


def decimate_l0_tile(cell: HexCell, source: P3DMTile) -> DecimatedCell:
    """Derive one exact N=1 payload from a validated N=5 L0 tile."""

    validate_cell(cell.q, cell.r)
    if (
        source.meta.lod,
        source.meta.tile_x,
        source.meta.tile_y,
        source.meta.model_half_extent_m,
        len(source.positions),
        len(source.position_indices) // 3,
    ) != (
        0,
        cell.q,
        cell.r,
        MODEL_HALF_EXTENT_M,
        121,
        210,
    ):
        raise ValueError("source tile is not the qualified N=5 regular payload")
    topology = hex_topology(cell.q, cell.r)
    expected_surface_indices = tuple(
        index for face in topology.faces for index in face
    )
    if source.position_indices[: len(expected_surface_indices)] != expected_surface_indices:
        raise ValueError("source N=5 surface topology changed")

    center_index, corner_indices = _local_key_indices(cell)
    selected_source = (center_index,) + corner_indices
    positions = [source.positions[index] for index in selected_source]
    if len(set(positions)) != SURFACE_VERTICES:
        raise ValueError("N=1 selected source positions are not unique")

    sectors = sector_fine_faces(cell)
    source_materials = tuple(
        source.uv_indices[3 * face_index]
        for face_index in range(FINE_SURFACE_TRIANGLES)
    )
    histograms = tuple(
        tuple(
            Counter(
                terrain_class(source_materials[index]) for index in indices
            )[kind]
            for kind in range(3)
        )
        for indices in sectors
    )
    if any(sum(histogram) != FINE_TRIANGLES_PER_SECTOR for histogram in histograms):
        raise ValueError("coarse sector material histogram changed area")
    winning_classes = tuple(
        max(range(3), key=lambda kind: (histogram[kind], -kind))
        for histogram in histograms
    )
    materials = [canonical_material_id(kind) for kind in winning_classes]

    faces = list(_surface_faces())
    bottom_indices: dict[int, int] = {}
    for start, end, owner_face in _boundary_edges(faces):
        for top in (start, end):
            if top in bottom_indices:
                continue
            x, y, z = positions[top]
            bottom_indices[top] = len(positions)
            positions.append((x, max(-32_767, y - ENCODED_SKIRT_DEPTH), z))
        bottom_start = bottom_indices[start]
        bottom_end = bottom_indices[end]
        faces.extend(((start, bottom_start, bottom_end), (start, bottom_end, end)))
        materials.extend((materials[owner_face], materials[owner_face]))

    if len(positions) != TOTAL_VERTICES or len(faces) != TOTAL_TRIANGLES:
        raise AssertionError("N=1 surface/skirt budget changed")
    tile = P3DMTile(
        stage_buffer_id=source.stage_buffer_id,
        meta=replace(source.meta, lod=1),
        positions=tuple(positions),
        position_indices=tuple(index for face in faces for index in face),
        uvs=source.uvs,
        uv_indices=tuple(material for material in materials for _ in range(3)),
    )
    return DecimatedCell(
        cell=cell,
        tile=tile,
        sector_material_ids=tuple(materials[:SURFACE_TRIANGLES]),
        sector_class_histograms=histograms,
    )


def ordered_disk_offsets() -> tuple[tuple[int, int], ...]:
    """Load detailed near rings first, then coarse rings outside-in."""

    return (
        ((0, 0),)
        + tuple(
            offset
            for ring in range(1, NEAR_RING_MAX + 1)
            for offset in ring_offsets(ring)
        )
        + tuple(
            offset
            for ring in range(FAR_RING, NEAR_RING_MAX, -1)
            for offset in ring_offsets(ring)
        )
    )


def axial_distance(delta_q: int, delta_r: int) -> int:
    return max(abs(delta_q), abs(delta_r), abs(delta_q + delta_r))


def lod_for_offset(delta_q: int, delta_r: int, near_ring: int) -> int:
    if not 0 <= near_ring <= NEAR_RING_MAX:
        raise ValueError(f"near ring lies outside 0..{NEAR_RING_MAX}: {near_ring}")
    distance = axial_distance(delta_q, delta_r)
    if distance > FAR_RING:
        raise ValueError("terrain offset lies beyond the distance disk")
    return 0 if distance <= near_ring else 1


def stable_slot(q: int, r: int) -> int:
    """Return the globally stable radius-30 slot in 0..2790."""

    return (SLOT_HASH_Q * q + SLOT_HASH_R * r) % SLOT_COUNT


def validate_slot_hash(offsets: Iterable[tuple[int, int]] | None = None) -> None:
    selected = tuple(ordered_disk_offsets() if offsets is None else offsets)
    if len(selected) != ACTIVE_CELL_COUNT:
        raise ValueError("distance disk changed its exact cell count")
    slots = {stable_slot(q, r) for q, r in selected}
    if len(slots) != len(selected):
        raise ValueError("radius-30 stable slot hash contains a collision")


def validate_full_partition(cells: Iterable[HexCell] | None = None) -> None:
    selected = tuple(iter_cells() if cells is None else cells)
    if len(selected) != HEX_CELL_COUNT:
        raise ValueError("regular LOD corpus changed the complete cell count")
    if {cell.cell_id for cell in selected} != set(range(HEX_CELL_COUNT)):
        raise ValueError("regular LOD cell IDs are not one dense partition")
