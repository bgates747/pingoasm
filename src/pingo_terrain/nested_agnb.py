"""Bounded selected-record reads from ordinary multi-record AGNB 0.3 files.

This is the executable host reference for the eZ80 family-loader fixture.  It
reads the 24-byte RIFF/VERS prefix, each fixed 76-byte LIST/descriptor prefix,
and only the selected DATA payload.  Unmatched mesh payloads are skipped with
absolute seeks and never enter the staging window.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import BinaryIO

from .p3dm import AGNB_VERSION, P3DMTile, align4, parse_container


PREFIX_BYTES = 24
RECORD_PREFIX_BYTES = 76
SINGLE_RECORD_DATA_OFFSET = 100
LIST_FIXED_PAYLOAD_BYTES = 68
P3DM_DESCRIPTOR_OFFSET = 32
P3DM_DESCRIPTOR_BYTES = 36
MAX_RECORDS = 16
MAX_DATA_BYTES = 16_284
MAX_FAMILY_BYTES = 0x00FF_FFFF


@dataclass(frozen=True, slots=True)
class RecordIdentity:
    """Fields that identify one component independently of mesh counts."""

    layer_kind: int
    lod: int
    shading_mode: int
    illumination: int
    material_set: int
    tile_x: int
    tile_y: int

    @classmethod
    def from_tile(cls, tile: P3DMTile) -> "RecordIdentity":
        meta = tile.meta
        return cls(
            int(meta.layer_kind),
            meta.lod,
            int(meta.shading_mode),
            int(meta.illumination),
            meta.material_set,
            meta.tile_x,
            meta.tile_y,
        )


@dataclass(frozen=True, slots=True)
class SelectedRecord:
    """A fully validated selected mesh plus bounded-I/O witnesses."""

    tile: P3DMTile
    record_index: int
    list_offset: int
    data_offset: int
    data_bytes: int
    records_scanned: int
    bytes_read: int


class _CountingReader:
    def __init__(self, source: BinaryIO):
        self.source = source
        self.bytes_read = 0

    def seek(self, offset: int) -> None:
        position = self.source.seek(offset)
        if position != offset:
            raise ValueError("AGNB seek did not reach the requested offset")

    def read_exact(self, count: int) -> bytes:
        output = bytearray()
        while len(output) < count:
            block = self.source.read(count - len(output))
            if not block:
                raise ValueError("truncated AGNB family")
            output.extend(block)
            self.bytes_read += len(block)
        return bytes(output)


def _stream_size(source: BinaryIO) -> int:
    current = source.tell()
    source.seek(0, 2)
    size = source.tell()
    source.seek(current)
    if not PREFIX_BYTES + RECORD_PREFIX_BYTES <= size <= MAX_FAMILY_BYTES:
        raise ValueError("AGNB family size is outside the bounded loader domain")
    return size


def _validate_outer_prefix(prefix: bytes, file_size: int) -> None:
    if len(prefix) != PREFIX_BYTES:
        raise ValueError("truncated AGNB prefix")
    if prefix[:4] != b"RIFF" or prefix[8:12] != b"AGNB":
        raise ValueError("not a RIFF/AGNB family")
    if struct.unpack_from("<I", prefix, 4)[0] + 8 != file_size:
        raise ValueError("AGNB RIFF size disagrees with the file")
    if prefix[12:16] != b"VERS" or struct.unpack_from("<I", prefix, 16)[0] != 2:
        raise ValueError("AGNB family has no exact VERS chunk")
    if prefix[20:22] != bytes(AGNB_VERSION) or prefix[22:24] != b"\0\0":
        raise ValueError("AGNB family requires padded version 0.3")


def _record_header(
    prefix: bytes, *, list_offset: int, file_size: int
) -> tuple[RecordIdentity, int, int]:
    """Return identity, DATA bytes, and next LIST offset after fixed checks."""

    if len(prefix) != RECORD_PREFIX_BYTES:
        raise ValueError("truncated AGNB LIST prefix")
    if prefix[0:4] != b"LIST" or prefix[8:12] != b"BUFR":
        raise ValueError("AGNB family permits only LIST BUFR records")
    if prefix[12:16] != b"BHDR" or struct.unpack_from("<I", prefix, 16)[0] != 2:
        raise ValueError("AGNB record has an invalid BHDR")
    if prefix[22:24] != b"\0\0":
        raise ValueError("AGNB BHDR has nonzero alignment padding")
    if (
        prefix[24:28] != b"P3DM"
        or struct.unpack_from("<I", prefix, 28)[0] != P3DM_DESCRIPTOR_BYTES
    ):
        raise ValueError("AGNB record has an invalid P3DM descriptor chunk")
    if prefix[68:72] != b"DATA":
        raise ValueError("AGNB record has no fixed DATA chunk")

    descriptor = prefix[P3DM_DESCRIPTOR_OFFSET : P3DM_DESCRIPTOR_OFFSET + P3DM_DESCRIPTOR_BYTES]
    if descriptor[0] != 1:
        raise ValueError("AGNB record uses an unsupported P3DM layout")
    data_bytes = struct.unpack_from("<I", prefix, 72)[0]
    if data_bytes > MAX_DATA_BYTES:
        raise ValueError("AGNB record DATA exceeds the staging window")
    list_bytes = struct.unpack_from("<I", prefix, 4)[0]
    expected_list_bytes = LIST_FIXED_PAYLOAD_BYTES + align4(data_bytes)
    if list_bytes != expected_list_bytes:
        raise ValueError("AGNB LIST size disagrees with DATA length")
    next_offset = list_offset + 8 + align4(list_bytes)
    if next_offset > file_size or next_offset <= list_offset:
        raise ValueError("AGNB LIST crosses the RIFF boundary")

    return (
        RecordIdentity(
            descriptor[1],
            descriptor[2],
            descriptor[3],
            descriptor[4],
            descriptor[5],
            struct.unpack_from("<h", descriptor, 6)[0],
            struct.unpack_from("<h", descriptor, 8)[0],
        ),
        data_bytes,
        next_offset,
    )


def select_record(
    source: BinaryIO,
    expected: RecordIdentity,
    *,
    stage_buffer_id: int = 0x7400,
    max_records: int = MAX_RECORDS,
) -> SelectedRecord:
    """Seek-select and fully validate one P3DM record without reading siblings.

    All record prefixes and alignment padding are checked so a malformed
    sibling cannot redirect the scanner.  The selected record is reconstructed
    as the canonical one-record AGNB envelope and passed through the existing
    P3DM parser, which validates policy, counts, indices, DATA length and CRC.
    """

    if not 1 <= max_records <= MAX_RECORDS:
        raise ValueError(f"max_records must be in 1..{MAX_RECORDS}")
    file_size = _stream_size(source)
    reader = _CountingReader(source)
    reader.seek(0)
    outer = reader.read_exact(PREFIX_BYTES)
    _validate_outer_prefix(outer, file_size)

    offset = PREFIX_BYTES
    selected: tuple[int, int, int, bytes] | None = None
    count = 0
    while offset < file_size:
        if count >= max_records:
            raise ValueError("AGNB family exceeds the bounded record count")
        if file_size - offset < RECORD_PREFIX_BYTES:
            raise ValueError("truncated AGNB LIST prefix")
        reader.seek(offset)
        record_prefix = reader.read_exact(RECORD_PREFIX_BYTES)
        identity, data_bytes, next_offset = _record_header(
            record_prefix,
            list_offset=offset,
            file_size=file_size,
        )
        if struct.unpack_from("<H", record_prefix, 20)[0] != stage_buffer_id:
            raise ValueError("AGNB record names the wrong staging buffer")

        padding_bytes = align4(data_bytes) - data_bytes
        if padding_bytes:
            reader.seek(offset + RECORD_PREFIX_BYTES + data_bytes)
            if any(reader.read_exact(padding_bytes)):
                raise ValueError("AGNB DATA has nonzero alignment padding")

        if identity == expected:
            if selected is not None:
                raise ValueError("AGNB family contains a duplicate selected identity")
            selected = (count, offset, data_bytes, record_prefix)
        count += 1
        offset = next_offset
    if offset != file_size:
        raise ValueError("AGNB scan did not end at the RIFF boundary")
    if selected is None:
        raise ValueError("selected P3DM identity is absent from the AGNB family")

    record_index, list_offset, data_bytes, _ = selected
    reader.seek(list_offset)
    record_prefix = reader.read_exact(RECORD_PREFIX_BYTES)
    identity, reread_data_bytes, _ = _record_header(
        record_prefix,
        list_offset=list_offset,
        file_size=file_size,
    )
    if identity != expected or reread_data_bytes != data_bytes:
        raise ValueError("selected AGNB descriptor changed while the file was open")
    if struct.unpack_from("<H", record_prefix, 20)[0] != stage_buffer_id:
        raise ValueError("selected AGNB record changed its staging buffer")
    data_offset = list_offset + RECORD_PREFIX_BYTES
    padded_data_bytes = align4(data_bytes)
    reader.seek(data_offset)
    data = reader.read_exact(padded_data_bytes)

    # Reconstitute the exact single-record envelope expected by parse_container.
    single_size = SINGLE_RECORD_DATA_OFFSET + padded_data_bytes
    synthetic_outer = bytearray(outer)
    struct.pack_into("<I", synthetic_outer, 4, single_size - 8)
    synthetic_record = bytearray(record_prefix)
    struct.pack_into("<I", synthetic_record, 4, single_size - 32)
    tile = parse_container(bytes(synthetic_outer + synthetic_record + data))
    if RecordIdentity.from_tile(tile) != expected:
        raise ValueError("selected descriptor changed during validation")

    return SelectedRecord(
        tile=tile,
        record_index=record_index,
        list_offset=list_offset,
        data_offset=data_offset,
        data_bytes=data_bytes,
        records_scanned=count,
        bytes_read=reader.bytes_read,
    )
