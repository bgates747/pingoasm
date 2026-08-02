"""Minimal reader for uncompressed single-band float32 GeoTIFF DEMs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


_TYPE_SIZE = {
    1: 1,   # BYTE
    2: 1,   # ASCII
    3: 2,   # SHORT
    4: 4,   # LONG
    5: 8,   # RATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
}


@dataclass(frozen=True)
class FloatDem:
    width: int
    height: int
    values: tuple[float, ...]
    pixel_size_x: float | None
    pixel_size_y: float | None
    nodata: float | None
    origin_x: float | None
    origin_y: float | None

    def value(self, x: int, y: int) -> float:
        return self.values[y * self.width + x]


def _unpack_values(
    payload: bytes, byte_order: str, field_type: int, count: int
) -> tuple[int | float, ...]:
    formats = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d"}
    if field_type not in formats:
        raise ValueError(f"Unsupported TIFF field type {field_type}")
    return struct.unpack(byte_order + formats[field_type] * count, payload)


def read_float32_dem(path: str | Path) -> FloatDem:
    """Read the narrow GeoTIFF form returned by the USGS export service."""

    data = Path(path).read_bytes()
    if data[:2] == b"II":
        byte_order = "<"
    elif data[:2] == b"MM":
        byte_order = ">"
    else:
        raise ValueError("Not a TIFF file: invalid byte-order marker")
    if struct.unpack_from(byte_order + "H", data, 2)[0] != 42:
        raise ValueError("Only classic TIFF files are supported")

    ifd_offset = struct.unpack_from(byte_order + "I", data, 4)[0]
    entry_count = struct.unpack_from(byte_order + "H", data, ifd_offset)[0]
    tags: dict[int, tuple[int, int, bytes]] = {}
    cursor = ifd_offset + 2
    for _ in range(entry_count):
        tag, field_type, count = struct.unpack_from(
            byte_order + "HHI", data, cursor
        )
        size = _TYPE_SIZE.get(field_type)
        if size is None:
            raise ValueError(f"Unsupported TIFF field type {field_type}")
        byte_count = size * count
        value_field = data[cursor + 8 : cursor + 12]
        if byte_count <= 4:
            payload = value_field[:byte_count]
        else:
            offset = struct.unpack(byte_order + "I", value_field)[0]
            payload = data[offset : offset + byte_count]
        tags[tag] = (field_type, count, payload)
        cursor += 12

    def numbers(tag: int) -> tuple[int | float, ...]:
        field_type, count, payload = tags[tag]
        return _unpack_values(payload, byte_order, field_type, count)

    width = int(numbers(256)[0])
    height = int(numbers(257)[0])
    bits = int(numbers(258)[0])
    compression = int(numbers(259)[0])
    samples = int(numbers(277)[0])
    sample_format = int(numbers(339)[0])
    if (bits, compression, samples, sample_format) != (32, 1, 1, 3):
        raise ValueError(
            "Expected an uncompressed, single-band float32 TIFF; got "
            f"bits={bits}, compression={compression}, samples={samples}, "
            f"sample_format={sample_format}"
        )

    expected_bytes = width * height * 4
    if 273 in tags:
        strip_offsets = tuple(int(value) for value in numbers(273))
        strip_sizes = tuple(int(value) for value in numbers(279))
        if len(strip_offsets) != len(strip_sizes):
            raise ValueError("TIFF strip offset/count arrays disagree")
        raster = b"".join(
            data[offset : offset + size]
            for offset, size in zip(strip_offsets, strip_sizes, strict=True)
        )
        if len(raster) != expected_bytes:
            raise ValueError(
                f"Expected {expected_bytes} raster bytes, found {len(raster)}"
            )
        values = struct.unpack(byte_order + "f" * (width * height), raster)
    elif 324 in tags:
        tile_width = int(numbers(322)[0])
        tile_height = int(numbers(323)[0])
        tile_offsets = tuple(int(value) for value in numbers(324))
        tile_sizes = tuple(int(value) for value in numbers(325))
        tiles_across = (width + tile_width - 1) // tile_width
        tiles_down = (height + tile_height - 1) // tile_height
        if len(tile_offsets) != len(tile_sizes) or len(tile_offsets) != (
            tiles_across * tiles_down
        ):
            raise ValueError("TIFF tile arrays do not match raster dimensions")
        mutable_values = [0.0] * (width * height)
        for tile_index, (offset, size) in enumerate(
            zip(tile_offsets, tile_sizes, strict=True)
        ):
            expected_tile_bytes = tile_width * tile_height * 4
            if size != expected_tile_bytes:
                raise ValueError(
                    "Expected uncompressed full-size TIFF tiles; "
                    f"tile {tile_index} has {size} bytes"
                )
            tile_values = struct.unpack(
                byte_order + "f" * (tile_width * tile_height),
                data[offset : offset + size],
            )
            tile_x = (tile_index % tiles_across) * tile_width
            tile_y = (tile_index // tiles_across) * tile_height
            copy_width = min(tile_width, width - tile_x)
            copy_height = min(tile_height, height - tile_y)
            for row in range(copy_height):
                source_start = row * tile_width
                destination_start = (tile_y + row) * width + tile_x
                mutable_values[
                    destination_start : destination_start + copy_width
                ] = tile_values[source_start : source_start + copy_width]
        values = tuple(mutable_values)
    else:
        raise ValueError("TIFF has neither strip nor tile storage")

    pixel_size_x = pixel_size_y = None
    if 33550 in tags:
        scale = numbers(33550)
        pixel_size_x = float(scale[0])
        pixel_size_y = float(scale[1])

    nodata = None
    if 42113 in tags:
        _, _, payload = tags[42113]
        text = payload.rstrip(b"\0").decode("ascii")
        nodata = float(text)

    origin_x = origin_y = None
    if 33922 in tags:
        tiepoint = numbers(33922)
        if len(tiepoint) >= 6:
            origin_x = float(tiepoint[3])
            origin_y = float(tiepoint[4])

    return FloatDem(
        width=width,
        height=height,
        values=tuple(float(value) for value in values),
        pixel_size_x=pixel_size_x,
        pixel_size_y=pixel_size_y,
        nodata=nodata,
        origin_x=origin_x,
        origin_y=origin_y,
    )
