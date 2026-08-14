"""Read the narrow uncompressed 8-bit categorical GeoTIFF used by NLCD."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


@dataclass(frozen=True)
class CategoryRaster:
    width: int
    height: int
    values: bytes
    pixel_size_x: float
    pixel_size_y: float
    origin_x: float
    origin_y: float

    def value_at_projected(self, x: float, y: float) -> int | None:
        column = int((x - self.origin_x) / self.pixel_size_x)
        row = int((self.origin_y - y) / self.pixel_size_y)
        if 0 <= column < self.width and 0 <= row < self.height:
            return self.values[row * self.width + column]
        return None


def read_category_raster(path: str | Path) -> CategoryRaster:
    data = Path(path).read_bytes()
    byte_order = ">" if data[:2] == b"MM" else "<" if data[:2] == b"II" else None
    if byte_order is None or struct.unpack_from(byte_order + "H", data, 2)[0] != 42:
        raise ValueError("Not a classic TIFF")
    ifd = struct.unpack_from(byte_order + "I", data, 4)[0]
    count = struct.unpack_from(byte_order + "H", data, ifd)[0]
    tags: dict[int, tuple[int, int, bytes]] = {}
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}
    cursor = ifd + 2
    for _ in range(count):
        tag, kind, length = struct.unpack_from(byte_order + "HHI", data, cursor)
        size = sizes[kind] * length
        field = data[cursor + 8 : cursor + 12]
        payload = field[:size] if size <= 4 else data[
            struct.unpack(byte_order + "I", field)[0] :
        ][:size]
        tags[tag] = (kind, length, payload)
        cursor += 12

    def values(tag: int) -> tuple[int | float, ...]:
        kind, length, payload = tags[tag]
        code = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d"}[kind]
        return struct.unpack(byte_order + code * length, payload)

    width, height = int(values(256)[0]), int(values(257)[0])
    if (int(values(258)[0]), int(values(259)[0]), int(values(277)[0])) != (8, 1, 1):
        raise ValueError("Expected an uncompressed single-band 8-bit TIFF")
    if 273 in tags:
        offsets = tuple(int(item) for item in values(273))
        lengths = tuple(int(item) for item in values(279))
        raster = b"".join(data[offset : offset + length] for offset, length in zip(offsets, lengths, strict=True))
        if len(raster) != width * height:
            raise ValueError("Categorical TIFF raster has the wrong byte count")
    elif 324 in tags:
        tile_width, tile_height = int(values(322)[0]), int(values(323)[0])
        offsets = tuple(int(item) for item in values(324))
        lengths = tuple(int(item) for item in values(325))
        across = (width + tile_width - 1) // tile_width
        mutable = bytearray(width * height)
        for index, (offset, length) in enumerate(zip(offsets, lengths, strict=True)):
            tile = data[offset : offset + length]
            if len(tile) != tile_width * tile_height:
                raise ValueError("Expected full uncompressed categorical tiles")
            tile_x, tile_y = (index % across) * tile_width, (index // across) * tile_height
            copy_width, copy_height = min(tile_width, width - tile_x), min(tile_height, height - tile_y)
            for row in range(copy_height):
                source = row * tile_width
                destination = (tile_y + row) * width + tile_x
                mutable[destination : destination + copy_width] = tile[source : source + copy_width]
        raster = bytes(mutable)
    else:
        raise ValueError("Categorical TIFF has neither strips nor tiles")
    if 33550 in tags and 33922 in tags:
        scale = values(33550)
        tiepoint = values(33922)
        pixel_size_x, pixel_size_y = float(scale[0]), float(scale[1])
        origin_x, origin_y = float(tiepoint[3]), float(tiepoint[4])
    elif 34264 in tags:
        transform = values(34264)
        pixel_size_x, pixel_size_y = float(transform[0]), abs(float(transform[5]))
        origin_x, origin_y = float(transform[3]), float(transform[7])
    else:
        raise ValueError("Categorical TIFF has no supported geotransform")
    return CategoryRaster(
        width, height, raster, pixel_size_x, pixel_size_y, origin_x, origin_y,
    )
