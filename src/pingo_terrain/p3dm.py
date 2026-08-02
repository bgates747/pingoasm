"""Versioned Pingo mesh records in an AGNB 0.3 RIFF envelope.

Each file contains exactly one independently loadable mesh component.  The
firmware-facing DATA payload is intentionally identical to the proposed
transactional Pingo mesh-import buffer.
"""

from __future__ import annotations

from binascii import crc32
from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Iterable


AGNB_VERSION = (0, 3)
P3DM_LAYOUT_VERSION = 1
RESERVED_BUFFER_ID = 0xFFFF
MAX_U16 = 0xFFFF
MIN_I16 = -0x8000
MAX_I16 = 0x7FFF
MIN_I32 = -0x80000000
MAX_I32 = 0x7FFFFFFF
MAX_U32 = 0xFFFFFFFF
P3DM_STRUCT = struct.Struct("<6B2h2i2h5HI")


class LayerKind(IntEnum):
    TERRAIN = 0
    AIRPORT_PAVEMENT = 1
    AIRPORT_MARKING = 2
    LANDMARK = 3


class ShadingMode(IntEnum):
    SOLID_FLAT = 1
    FLAT_PATTERN = 2


class IlluminationPolicy(IntEnum):
    SCENE = 0
    SELF = 1


class MaterialSet(IntEnum):
    TERRAIN_SELECTOR_4X4 = 0
    NATIVE_SOLID_PALETTE = 1


@dataclass(frozen=True)
class P3DMMeta:
    """Geographic and rendering metadata for one mesh component."""

    layer_kind: LayerKind
    lod: int
    shading_mode: ShadingMode
    illumination: IlluminationPolicy
    material_set: int
    tile_x: int
    tile_y: int
    center_east_m: int
    center_north_m: int
    minimum_elevation_dm: int
    maximum_elevation_dm: int
    model_half_extent_m: int


@dataclass(frozen=True)
class P3DMTile:
    """One validated mesh and its fixed VDP staging-buffer identity."""

    stage_buffer_id: int
    meta: P3DMMeta
    positions: tuple[tuple[int, int, int], ...]
    position_indices: tuple[int, ...]
    uvs: tuple[tuple[int, int], ...]
    uv_indices: tuple[int, ...]


@dataclass(frozen=True)
class P3DMDescriptor:
    """Decoded fixed-size P3DM descriptor, including DATA witnesses."""

    layout_version: int
    meta: P3DMMeta
    vertex_count: int
    position_index_count: int
    uv_count: int
    uv_index_count: int
    data_crc32: int


def _in_range(name: str, value: int, low: int, high: int) -> None:
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}: {value!r}")


def _validate_meta(meta: P3DMMeta) -> None:
    try:
        layer_kind = LayerKind(meta.layer_kind)
        shading_mode = ShadingMode(meta.shading_mode)
        illumination = IlluminationPolicy(meta.illumination)
    except ValueError as error:
        raise ValueError(f"unsupported P3DM render policy: {error}") from error

    _in_range("lod", meta.lod, 0, 0xFF)
    _in_range("material_set", meta.material_set, 0, 0xFF)
    _in_range("tile_x", meta.tile_x, MIN_I16, MAX_I16)
    _in_range("tile_y", meta.tile_y, MIN_I16, MAX_I16)
    _in_range("center_east_m", meta.center_east_m, MIN_I32, MAX_I32)
    _in_range("center_north_m", meta.center_north_m, MIN_I32, MAX_I32)
    _in_range(
        "minimum_elevation_dm", meta.minimum_elevation_dm, MIN_I16, MAX_I16
    )
    _in_range(
        "maximum_elevation_dm", meta.maximum_elevation_dm, MIN_I16, MAX_I16
    )
    if meta.minimum_elevation_dm > meta.maximum_elevation_dm:
        raise ValueError("minimum elevation exceeds maximum elevation")
    _in_range("model_half_extent_m", meta.model_half_extent_m, 1, MAX_U16)

    if layer_kind is LayerKind.TERRAIN:
        expected = (
            ShadingMode.FLAT_PATTERN,
            IlluminationPolicy.SCENE,
            MaterialSet.TERRAIN_SELECTOR_4X4,
        )
        actual = (shading_mode, illumination, meta.material_set)
        if actual != expected:
            raise ValueError(
                "terrain must use patterned scene illumination and material set 0"
            )
    elif layer_kind in (
        LayerKind.AIRPORT_PAVEMENT,
        LayerKind.AIRPORT_MARKING,
    ):
        expected = (
            ShadingMode.SOLID_FLAT,
            IlluminationPolicy.SELF,
            MaterialSet.NATIVE_SOLID_PALETTE,
        )
        actual = (shading_mode, illumination, meta.material_set)
        if actual != expected:
            raise ValueError(
                "airport hard surfaces must use solid-flat self illumination "
                "and the native solid palette"
            )
    elif shading_mode is not ShadingMode.SOLID_FLAT:
        raise ValueError("landmarks must begin in solid-flat shading mode")


def validate_tile(tile: P3DMTile) -> None:
    """Validate every host-side and firmware-facing P3DM invariant."""

    _in_range("stage_buffer_id", tile.stage_buffer_id, 0, MAX_U16 - 1)
    _validate_meta(tile.meta)

    vertex_count = len(tile.positions)
    index_count = len(tile.position_indices)
    uv_count = len(tile.uvs)
    uv_index_count = len(tile.uv_indices)
    _in_range("vertex_count", vertex_count, 1, MAX_U16)
    _in_range("position_index_count", index_count, 3, MAX_U16)
    _in_range("uv_count", uv_count, 1, MAX_U16)
    _in_range("uv_index_count", uv_index_count, 3, MAX_U16)
    if index_count % 3:
        raise ValueError("position index count must be a multiple of three")
    if uv_index_count != index_count:
        raise ValueError("UV index count must equal position index count")

    for vertex_index, position in enumerate(tile.positions):
        if len(position) != 3:
            raise ValueError(f"position {vertex_index} does not have three axes")
        for axis_index, value in enumerate(position):
            _in_range(
                f"position[{vertex_index}][{axis_index}]",
                value,
                MIN_I16,
                MAX_I16,
            )
    for uv_index, uv in enumerate(tile.uvs):
        if len(uv) != 2:
            raise ValueError(f"UV {uv_index} does not have two axes")
        for axis_index, value in enumerate(uv):
            _in_range(f"uv[{uv_index}][{axis_index}]", value, 0, MAX_U16)
    for offset, index in enumerate(tile.position_indices):
        _in_range(f"position_indices[{offset}]", index, 0, vertex_count - 1)
    for offset, index in enumerate(tile.uv_indices):
        _in_range(f"uv_indices[{offset}]", index, 0, uv_count - 1)

    # P3DM is a flat-face format. Requiring one selector per triangle prevents
    # accidental interpolation or texture sampling from entering streamed
    # terrain, hard-surface, or landmark records.
    for offset in range(0, uv_index_count, 3):
        face = tile.uv_indices[offset : offset + 3]
        if face[0] != face[1] or face[0] != face[2]:
            raise ValueError(f"triangle {offset // 3} spans several UV selectors")


def _pack_many(format_string: str, values: Iterable[tuple[int, ...] | int]) -> bytes:
    output = bytearray()
    packer = struct.Struct(format_string)
    for value in values:
        if isinstance(value, int):
            output.extend(packer.pack(value))
        else:
            output.extend(packer.pack(*value))
    return bytes(output)


def make_data(tile: P3DMTile) -> bytes:
    """Return the exact consolidated VDP buffer consumed by subcommand 50."""

    validate_tile(tile)
    return b"".join(
        (
            _pack_many("<hhh", tile.positions),
            _pack_many("<H", tile.position_indices),
            _pack_many("<HH", tile.uvs),
            _pack_many("<H", tile.uv_indices),
        )
    )


def expected_data_size(
    vertex_count: int,
    position_index_count: int,
    uv_count: int,
    uv_index_count: int,
) -> int:
    return (
        6 * vertex_count
        + 2 * position_index_count
        + 4 * uv_count
        + 2 * uv_index_count
    )


def make_descriptor(tile: P3DMTile, data: bytes | None = None) -> bytes:
    validate_tile(tile)
    if data is None:
        data = make_data(tile)
    meta = tile.meta
    return P3DM_STRUCT.pack(
        P3DM_LAYOUT_VERSION,
        int(meta.layer_kind),
        meta.lod,
        int(meta.shading_mode),
        int(meta.illumination),
        meta.material_set,
        meta.tile_x,
        meta.tile_y,
        meta.center_east_m,
        meta.center_north_m,
        meta.minimum_elevation_dm,
        meta.maximum_elevation_dm,
        meta.model_half_extent_m,
        len(tile.positions),
        len(tile.position_indices),
        len(tile.uvs),
        len(tile.uv_indices),
        crc32(data) & MAX_U32,
    )


def align4(size: int) -> int:
    return (size + 3) & ~3


def make_chunk(chunk_id: bytes, payload: bytes) -> bytes:
    if len(chunk_id) != 4:
        raise ValueError(f"RIFF chunk ID must contain four bytes: {chunk_id!r}")
    if len(payload) > MAX_U32:
        raise ValueError(f"RIFF payload is too large: {len(payload)} bytes")
    return (
        chunk_id
        + struct.pack("<I", len(payload))
        + payload
        + bytes(align4(len(payload)) - len(payload))
    )


def make_container(tile: P3DMTile) -> bytes:
    """Build one exact AGNB 0.3 LIST BUFR/P3DM file."""

    data = make_data(tile)
    nested = b"".join(
        (
            make_chunk(b"BHDR", struct.pack("<H", tile.stage_buffer_id)),
            make_chunk(b"P3DM", make_descriptor(tile, data)),
            make_chunk(b"DATA", data),
        )
    )
    body = b"AGNB" + make_chunk(b"VERS", bytes(AGNB_VERSION)) + make_chunk(
        b"LIST", b"BUFR" + nested
    )
    if len(body) > MAX_U32:
        raise ValueError(f"RIFF container is too large: {len(body) + 8} bytes")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _read_chunk(
    container: bytes, offset: int, boundary: int
) -> tuple[bytes, bytes, int]:
    if offset + 8 > boundary:
        raise ValueError(f"truncated RIFF chunk header at byte {offset}")
    chunk_id = container[offset : offset + 4]
    payload_size = struct.unpack_from("<I", container, offset + 4)[0]
    payload_start = offset + 8
    payload_end = payload_start + payload_size
    next_offset = payload_start + align4(payload_size)
    if payload_end > boundary or next_offset > boundary:
        raise ValueError(f"chunk {chunk_id!r} crosses its enclosing boundary")
    if any(container[payload_end:next_offset]):
        raise ValueError(f"chunk {chunk_id!r} contains nonzero alignment padding")
    return chunk_id, container[payload_start:payload_end], next_offset


def _decode_descriptor(payload: bytes) -> P3DMDescriptor:
    if len(payload) != P3DM_STRUCT.size:
        raise ValueError(f"P3DM descriptor must contain {P3DM_STRUCT.size} bytes")
    values = P3DM_STRUCT.unpack(payload)
    try:
        meta = P3DMMeta(
            layer_kind=LayerKind(values[1]),
            lod=values[2],
            shading_mode=ShadingMode(values[3]),
            illumination=IlluminationPolicy(values[4]),
            material_set=values[5],
            tile_x=values[6],
            tile_y=values[7],
            center_east_m=values[8],
            center_north_m=values[9],
            minimum_elevation_dm=values[10],
            maximum_elevation_dm=values[11],
            model_half_extent_m=values[12],
        )
    except ValueError as error:
        raise ValueError(f"unsupported P3DM descriptor value: {error}") from error
    return P3DMDescriptor(
        layout_version=values[0],
        meta=meta,
        vertex_count=values[13],
        position_index_count=values[14],
        uv_count=values[15],
        uv_index_count=values[16],
        data_crc32=values[17],
    )


def parse_container(container: bytes) -> P3DMTile:
    """Parse and independently validate one complete P3DM container."""

    if len(container) < 12 or container[:4] != b"RIFF":
        raise ValueError("container is not RIFF")
    if struct.unpack_from("<I", container, 4)[0] != len(container) - 8:
        raise ValueError("RIFF size does not equal the physical file size")
    if container[8:12] != b"AGNB":
        raise ValueError("RIFF form is not AGNB")

    offset = 12
    chunk_id, version, offset = _read_chunk(container, offset, len(container))
    if chunk_id != b"VERS" or version != bytes(AGNB_VERSION):
        raise ValueError("container is not supported AGNB version 0.3")
    chunk_id, list_payload, offset = _read_chunk(
        container, offset, len(container)
    )
    if chunk_id != b"LIST" or not list_payload.startswith(b"BUFR"):
        raise ValueError("container does not contain one LIST BUFR record")
    if offset != len(container):
        raise ValueError("P3DM file contains unexpected top-level chunks")

    nested_offset = 4
    nested: list[tuple[bytes, bytes]] = []
    while nested_offset < len(list_payload):
        item_id, item_payload, nested_offset = _read_chunk(
            list_payload, nested_offset, len(list_payload)
        )
        nested.append((item_id, item_payload))
    if nested_offset != len(list_payload):
        raise ValueError("LIST BUFR ends between nested chunks")
    if [item[0] for item in nested] != [b"BHDR", b"P3DM", b"DATA"]:
        raise ValueError("LIST BUFR must contain BHDR, P3DM, DATA in order")

    if len(nested[0][1]) != 2:
        raise ValueError("BHDR must contain one u16 staging buffer ID")
    stage_buffer_id = struct.unpack("<H", nested[0][1])[0]
    descriptor = _decode_descriptor(nested[1][1])
    data = nested[2][1]
    if descriptor.layout_version != P3DM_LAYOUT_VERSION:
        raise ValueError(
            f"unsupported P3DM layout version {descriptor.layout_version}"
        )
    expected_size = expected_data_size(
        descriptor.vertex_count,
        descriptor.position_index_count,
        descriptor.uv_count,
        descriptor.uv_index_count,
    )
    if len(data) != expected_size:
        raise ValueError(
            f"P3DM DATA size is {len(data)} bytes, expected {expected_size}"
        )
    if crc32(data) & MAX_U32 != descriptor.data_crc32:
        raise ValueError("P3DM DATA CRC32 mismatch")

    data_offset = 0
    positions_bytes = descriptor.vertex_count * 6
    index_bytes = descriptor.position_index_count * 2
    uv_bytes = descriptor.uv_count * 4
    uv_index_bytes = descriptor.uv_index_count * 2
    positions = tuple(
        struct.iter_unpack("<hhh", data[data_offset : data_offset + positions_bytes])
    )
    data_offset += positions_bytes
    position_indices = tuple(
        item[0]
        for item in struct.iter_unpack(
            "<H", data[data_offset : data_offset + index_bytes]
        )
    )
    data_offset += index_bytes
    uvs = tuple(
        struct.iter_unpack("<HH", data[data_offset : data_offset + uv_bytes])
    )
    data_offset += uv_bytes
    uv_indices = tuple(
        item[0]
        for item in struct.iter_unpack(
            "<H", data[data_offset : data_offset + uv_index_bytes]
        )
    )
    data_offset += uv_index_bytes
    if data_offset != len(data):
        raise ValueError("P3DM DATA decoder did not consume the complete payload")

    tile = P3DMTile(
        stage_buffer_id=stage_buffer_id,
        meta=descriptor.meta,
        positions=positions,
        position_indices=position_indices,
        uvs=uvs,
        uv_indices=uv_indices,
    )
    validate_tile(tile)
    return tile
