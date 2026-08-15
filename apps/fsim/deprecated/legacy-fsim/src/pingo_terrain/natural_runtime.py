"""P3DM encoding and exact-seam proofs for post-partition natural terrain.

The natural terrain experiment triangulates one master surface before assigning
whole faces to streaming components.  This module deliberately knows nothing
about Blender: it accepts integer projected vertices and triangle ownership,
then produces the same loose one-component P3DM records consumed by the
universal eZ80 terrain manager.

Horizontal and vertical source coordinates use Pingo terrain counts (1/16 m).
Every component retains its ideal axial-cell centre and the common 1024 m model
half extent. Consequently independently encoded copies of a master vertex have
one exact ideal-world integer numerator at a physical seam. The VDP evaluates
local scale and object translation as separate binary32 operations, so this
module also measures their much smaller renderer-path rounding difference.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from itertools import chain
import struct
from typing import Iterable, Sequence

from .hex_terrain import (
    COUNTS_PER_METRE,
    HEX_MODEL_HALF_EXTENT_M,
    HEX_OBJECT_SCALE_Q8_8,
    HEX_TERRAIN_Y_COUNT,
    HexCell,
)
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
    STAGING_BUFFER_ID,
    selector_uv_words,
)


GlobalVertexKey = tuple[int, int, int]
Face = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class NaturalRuntimeComponent:
    """One connected face owner extracted from the natural master surface.

    ``vertices`` contain exact ``(east, north, elevation)`` counts.  Faces use
    component-local indices; they may arrive in either winding because the
    encoder independently establishes Pingo's upward-facing convention.
    """

    cell: HexCell
    vertices: tuple[GlobalVertexKey, ...]
    faces: tuple[Face, ...]
    materials: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ComponentBoundaryEdge:
    """One directed edge owned by exactly one face inside a component."""

    cell: HexCell
    start_index: int
    end_index: int
    start: GlobalVertexKey
    end: GlobalVertexKey

    @property
    def undirected_key(self) -> tuple[GlobalVertexKey, GlobalVertexKey]:
        return tuple(sorted((self.start, self.end)))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class BuiltNaturalRuntimeComponent:
    """A validated component, its P3DM record, and seam witnesses."""

    source: NaturalRuntimeComponent
    tile: P3DMTile
    oriented_faces: tuple[Face, ...]
    boundary_edges: tuple[ComponentBoundaryEdge, ...]
    minimum_elevation_count: int
    maximum_elevation_count: int
    material_histogram: tuple[tuple[int, int], ...]


def _require_exact_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an exact integer: {value!r}")
    return value


def _encode_axis_count(name: str, delta_count: int) -> int:
    """Encode a 1/16-metre delta under the common 1024 m normalization."""

    encoded = 2 * delta_count
    if not -32767 <= encoded <= 32767:
        raise ValueError(
            f"{name} exceeds the common {HEX_MODEL_HALF_EXTENT_M} m model "
            f"extent: delta_count={delta_count}, encoded={encoded}"
        )
    return encoded


def _pingo_up_witness(
    vertices: Sequence[GlobalVertexKey], face: Face
) -> int:
    """Return the exact horizontal contribution to the Pingo +Y normal."""

    first, second, third = (vertices[index] for index in face)
    ab_x = second[1] - first[1]
    ab_z = -(second[0] - first[0])
    ac_x = third[1] - first[1]
    ac_z = -(third[0] - first[0])
    return ab_z * ac_x - ab_x * ac_z


def _validate_and_orient(
    component: NaturalRuntimeComponent,
) -> tuple[tuple[Face, ...], tuple[ComponentBoundaryEdge, ...]]:
    vertices = component.vertices
    faces = component.faces
    materials = component.materials
    if not vertices or not faces:
        raise ValueError("a natural runtime component cannot be empty")
    if len(vertices) != len(set(vertices)):
        raise ValueError("component repeats a global master vertex")
    if len(materials) != len(faces):
        raise ValueError("material count does not match component face count")
    material_count = len(BERKELEY_TERRAIN_MATERIALS)
    if any(type(item) is not int or not 0 <= item < material_count for item in materials):
        raise ValueError(
            f"terrain material IDs must be exact integers in 0..{material_count - 1}"
        )

    for vertex_index, vertex in enumerate(vertices):
        if len(vertex) != 3:
            raise ValueError(f"vertex {vertex_index} does not have three counts")
        for axis_name, value in zip(("east", "north", "elevation"), vertex, strict=True):
            _require_exact_int(f"vertex[{vertex_index}].{axis_name}", value)

    oriented: list[Face] = []
    used_vertices: set[int] = set()
    for face_index, raw_face in enumerate(faces):
        if len(raw_face) != 3:
            raise ValueError(f"face {face_index} is not triangular")
        face = tuple(
            _require_exact_int(f"face[{face_index}][{offset}]", value)
            for offset, value in enumerate(raw_face)
        )
        if len(set(face)) != 3:
            raise ValueError(f"face {face_index} repeats a vertex")
        if any(not 0 <= index < len(vertices) for index in face):
            raise ValueError(f"face {face_index} contains an out-of-range index")
        witness = _pingo_up_witness(vertices, face)
        if witness == 0:
            raise ValueError(f"face {face_index} has zero projected area")
        if witness < 0:
            face = face[0], face[2], face[1]
        if _pingo_up_witness(vertices, face) <= 0:
            raise AssertionError("natural face did not orient toward Pingo +Y")
        oriented.append(face)
        used_vertices.update(face)
    if used_vertices != set(range(len(vertices))):
        unused = sorted(set(range(len(vertices))) - used_vertices)
        raise ValueError(f"component contains unused vertices: {unused[:20]}")
    if len(oriented) != len(set(tuple(sorted(face)) for face in oriented)):
        raise ValueError("component repeats a triangle")

    edge_owners: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    face_neighbors: list[set[int]] = [set() for _ in oriented]
    for face_index, face in enumerate(oriented):
        for start, end in zip(face, face[1:] + face[:1], strict=True):
            edge_owners[tuple(sorted((start, end)))].append((start, end, face_index))
    for edge, owners in edge_owners.items():
        if len(owners) > 2:
            raise ValueError(f"component contains a non-manifold edge: {edge}")
        if len(owners) == 2:
            first, second = owners
            if first[:2] != second[1::-1]:
                raise ValueError(f"adjacent faces do not oppose edge {edge}")
            face_neighbors[first[2]].add(second[2])
            face_neighbors[second[2]].add(first[2])

    visited = {0}
    pending = deque((0,))
    while pending:
        face_index = pending.popleft()
        for neighbor in face_neighbors[face_index]:
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    if len(visited) != len(oriented):
        raise ValueError(
            "component faces are not connected through complete shared edges"
        )

    boundary = tuple(
        ComponentBoundaryEdge(
            cell=component.cell,
            start_index=owners[0][0],
            end_index=owners[0][1],
            start=vertices[owners[0][0]],
            end=vertices[owners[0][1]],
        )
        for _edge, owners in sorted(edge_owners.items())
        if len(owners) == 1
    )
    return tuple(oriented), boundary


def build_natural_runtime_component(
    component: NaturalRuntimeComponent,
    *,
    stage_buffer_id: int = STAGING_BUFFER_ID,
) -> BuiltNaturalRuntimeComponent:
    """Encode one post-partition owner without a crack-masking boundary skirt."""

    # Accessing cell_id performs the bounded regional q/r validation.
    _ = component.cell.cell_id
    oriented_faces, boundary_edges = _validate_and_orient(component)
    center_east_m, center_north_m = component.cell.center_m
    center_east_count = center_east_m * COUNTS_PER_METRE
    center_north_count = center_north_m * COUNTS_PER_METRE

    positions = tuple(
        (
            _encode_axis_count("north coordinate", north - center_north_count),
            _encode_axis_count("elevation", elevation - HEX_TERRAIN_Y_COUNT),
            _encode_axis_count("east coordinate", -(east - center_east_count)),
        )
        for east, north, elevation in component.vertices
    )
    position_indices = tuple(index for face in oriented_faces for index in face)
    uv_indices = tuple(
        material
        for material in component.materials
        for _vertex in range(3)
    )
    minimum_elevation = min(vertex[2] for vertex in component.vertices)
    maximum_elevation = max(vertex[2] for vertex in component.vertices)

    tile = P3DMTile(
        stage_buffer_id=stage_buffer_id,
        meta=P3DMMeta(
            layer_kind=LayerKind.TERRAIN,
            lod=0,
            shading_mode=ShadingMode.FLAT_PATTERN,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
            tile_x=component.cell.q,
            tile_y=component.cell.r,
            center_east_m=center_east_m - REGIONAL_ORIGIN_EAST_M,
            center_north_m=center_north_m - REGIONAL_ORIGIN_NORTH_M,
            minimum_elevation_dm=(minimum_elevation * 10) // COUNTS_PER_METRE,
            maximum_elevation_dm=-(
                (-maximum_elevation * 10) // COUNTS_PER_METRE
            ),
            model_half_extent_m=HEX_MODEL_HALF_EXTENT_M,
        ),
        positions=positions,
        position_indices=position_indices,
        uvs=tuple(selector_uv_words(index) for index in range(16)),
        uv_indices=uv_indices,
    )
    return BuiltNaturalRuntimeComponent(
        source=component,
        tile=tile,
        oriented_faces=oriented_faces,
        boundary_edges=boundary_edges,
        minimum_elevation_count=minimum_elevation,
        maximum_elevation_count=maximum_elevation,
        material_histogram=tuple(sorted(Counter(component.materials).items())),
    )


def reconstruct_vertex_numerators(
    built: BuiltNaturalRuntimeComponent, vertex_index: int
) -> tuple[int, int, int]:
    """Reconstruct exact pre-division Pingo world numerators for one vertex.

    Pingo's normalized mesh scale and command-52 translation both ultimately
    carry a common ``256/32767`` factor.  Keeping the numerator in integers is
    therefore the strongest useful seam proof; no host floating approximation
    enters the comparison.
    """

    if not 0 <= vertex_index < len(built.tile.positions):
        raise IndexError("natural component vertex index is out of range")
    center_east_m, center_north_m = built.source.cell.center_m
    raw_x, raw_y, raw_z = built.tile.positions[vertex_index]
    return (
        center_north_m * COUNTS_PER_METRE * 256 + raw_x * 128,
        HEX_TERRAIN_Y_COUNT * 256 + raw_y * 128,
        -center_east_m * COUNTS_PER_METRE * 256 + raw_z * 128,
    )


def _binary32(value: float) -> float:
    """Round one host value to the IEEE-754 binary32 used by Pingo."""

    return struct.unpack("<f", struct.pack("<f", value))[0]


def reconstruct_renderer_float32(
    built: BuiltNaturalRuntimeComponent,
    vertex_index: int,
    origin_cell: HexCell,
) -> tuple[float, float, float]:
    """Model Pingo's actual local-position, scale, and translation rounding.

    Pingo converts an imported position with ``1/32767``, the Q8.8 object
    scale with ``1/256``, and command-52 translation counts with
    ``256/32767``. Each multiply/add is binary32. This is deliberately
    distinct from :func:`reconstruct_vertex_numerators`, which proves the
    exact rational coordinate before renderer rounding.
    """

    if not 0 <= vertex_index < len(built.tile.positions):
        raise IndexError("natural component vertex index is out of range")
    center_east_m, center_north_m = built.source.cell.center_m
    origin_east_m, origin_north_m = origin_cell.center_m
    translations = (
        (center_north_m - origin_north_m) * COUNTS_PER_METRE,
        HEX_TERRAIN_Y_COUNT,
        -(center_east_m - origin_east_m) * COUNTS_PER_METRE,
    )
    position_factor = _binary32(1.0 / 32767.0)
    translation_factor = _binary32(256.0 / 32767.0)
    scale = _binary32(
        _binary32(float(HEX_OBJECT_SCALE_Q8_8)) * _binary32(1.0 / 256.0)
    )

    result: list[float] = []
    for raw_position, raw_translation in zip(
        built.tile.positions[vertex_index], translations, strict=True
    ):
        position = _binary32(_binary32(float(raw_position)) * position_factor)
        translation = _binary32(
            _binary32(float(raw_translation)) * translation_factor
        )
        result.append(_binary32(_binary32(position * scale) + translation))
    if len(result) != 3:
        raise AssertionError("a natural position did not have three axes")
    return result[0], result[1], result[2]


def validate_same_lod_seams(
    components: Iterable[BuiltNaturalRuntimeComponent],
) -> dict[str, int | float]:
    """Prove P3DM reconstruction and every selected same-LOD physical seam.

    A master boundary edge may occur once (the selected subset perimeter) or
    twice (a selected-to-selected component seam).  Two copies must be exact
    endpoint reversals.  Counts above two are non-manifold.  Vertices shared by
    three or more selected owners are checked separately and reported because
    they exercise more than pairwise seam agreement.
    """

    iterator = iter(components)
    first = next(iterator, None)
    if first is None:
        raise ValueError("at least one natural component is required")

    edge_ledger: dict[
        tuple[GlobalVertexKey, GlobalVertexKey], list[ComponentBoundaryEdge]
    ] = defaultdict(list)
    vertex_owners: dict[GlobalVertexKey, set[tuple[int, int]]] = defaultdict(set)
    renderer_positions: dict[
        GlobalVertexKey, list[tuple[tuple[int, int], tuple[float, float, float]]]
    ] = defaultdict(list)
    renderer_origin = first.source.cell
    cells: set[tuple[int, int]] = set()
    component_count = 0
    reconstruction_instances = 0
    for built in chain((first,), iterator):
        cell = (built.source.cell.q, built.source.cell.r)
        if cell in cells:
            raise ValueError("natural component set repeats an axial owner")
        cells.add(cell)
        component_count += 1
        for edge in built.boundary_edges:
            edge_ledger[edge.undirected_key].append(edge)
            for vertex_index, source in (
                (edge.start_index, edge.start),
                (edge.end_index, edge.end),
            ):
                reconstructed = reconstruct_vertex_numerators(built, vertex_index)
                expected = (source[1] * 256, source[2] * 256, -source[0] * 256)
                if reconstructed != expected:
                    raise ValueError(
                        f"component {built.source.cell.q},{built.source.cell.r} "
                        f"does not reconstruct boundary vertex {source}: "
                        f"{reconstructed} != {expected}"
                    )
                reconstruction_instances += 1
                owner = (built.source.cell.q, built.source.cell.r)
                vertex_owners[source].add(owner)
                renderer_positions[source].append(
                    (
                        owner,
                        reconstruct_renderer_float32(
                            built, vertex_index, renderer_origin
                        ),
                    )
                )

    seam_edges = 0
    outer_edges = 0
    physical_pairs: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for key, copies in edge_ledger.items():
        if len(copies) == 1:
            outer_edges += 1
            continue
        if len(copies) != 2:
            raise ValueError(
                f"natural physical edge has {len(copies)} component owners: {key}"
            )
        first, second = copies
        if first.start != second.end or first.end != second.start:
            raise ValueError(f"natural seam copies are not opposite: {key}")
        first_cell = (first.cell.q, first.cell.r)
        second_cell = (second.cell.q, second.cell.r)
        if first_cell == second_cell:
            raise ValueError(f"one component owns both copies of seam {key}")
        physical_pairs.add(tuple(sorted((first_cell, second_cell))))
        seam_edges += 1

    multi_owner_vertices = {
        key: owners for key, owners in vertex_owners.items() if len(owners) >= 3
    }
    maximum_vertex_owners = max(map(len, vertex_owners.values()), default=0)
    shared_renderer_positions = {
        key: positions
        for key, positions in renderer_positions.items()
        if len({owner for owner, _position in positions}) >= 2
    }
    renderer_mismatches = 0
    renderer_maximum_span = 0.0
    for positions in shared_renderer_positions.values():
        unique_bits = {
            struct.pack("<fff", *position) for _owner, position in positions
        }
        if len(unique_bits) > 1:
            renderer_mismatches += 1
        for axis in range(3):
            values = [position[axis] for _owner, position in positions]
            renderer_maximum_span = max(
                renderer_maximum_span,
                max(values) - min(values),
            )
    return {
        "components": component_count,
        "boundary_edge_incidences": sum(map(len, edge_ledger.values())),
        "selected_selected_seam_edges": seam_edges,
        "selected_subset_outer_edges": outer_edges,
        "physical_component_pairs": len(physical_pairs),
        "boundary_reconstruction_instances": reconstruction_instances,
        "reconstruction_mismatches": 0,
        "multi_owner_boundary_vertices": len(multi_owner_vertices),
        "maximum_boundary_vertex_owners": maximum_vertex_owners,
        "renderer_float32_shared_vertices": len(shared_renderer_positions),
        "renderer_float32_nonidentical_shared_vertices": renderer_mismatches,
        "renderer_float32_maximum_span_pingo_units": renderer_maximum_span,
    }


def maximum_absolute_position_word(
    components: Iterable[BuiltNaturalRuntimeComponent],
) -> int:
    """Return the largest absolute encoded coordinate in a component set."""

    return max(
        abs(axis)
        for component in components
        for position in component.tile.positions
        for axis in position
    )
