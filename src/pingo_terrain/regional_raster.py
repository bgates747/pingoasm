"""Lazy random access to the checksum-pinned regional GeoTIFF mosaic.

The acquisition deliberately consists of modest, uncompressed GeoTIFFs rather
than one multi-hundred-megabyte raster.  This module preserves that property:
it reads and caches TIFF blocks on demand and never materializes the complete
Bay Area source grid in memory.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
import struct
from typing import Iterator

from .geotiff import GeoTiffMetadata, read_geotiff_metadata


@dataclass(frozen=True, slots=True)
class RasterSample:
    """One sampled value and whether source-boundary padding was required."""

    value: float | int | None
    edge_padded: bool
    nodata: bool


class BlockRaster:
    """Random-access reader for one validated, uncompressed TIFF."""

    def __init__(self, path: Path, *, cache_blocks: int = 8) -> None:
        if cache_blocks < 1:
            raise ValueError("cache_blocks must be positive")
        self.metadata = read_geotiff_metadata(path)
        self._cache_blocks = cache_blocks
        self._cache: OrderedDict[int, bytes] = OrderedDict()

    def _block(self, block_index: int) -> bytes:
        cached = self._cache.get(block_index)
        if cached is not None:
            self._cache.move_to_end(block_index)
            return cached
        offset = self.metadata.block_offsets[block_index]
        size = self.metadata.block_byte_counts[block_index]
        with self.metadata.path.open("rb") as handle:
            handle.seek(offset)
            payload = handle.read(size)
        if len(payload) != size:
            raise ValueError(
                f"truncated TIFF block {block_index} in {self.metadata.path}"
            )
        self._cache[block_index] = payload
        self._cache.move_to_end(block_index)
        while len(self._cache) > self._cache_blocks:
            self._cache.popitem(last=False)
        return payload

    def value(self, column: int, row: int) -> float | int:
        metadata = self.metadata
        if not (0 <= column < metadata.width and 0 <= row < metadata.height):
            raise IndexError(f"raster cell is outside {metadata.path}: {column},{row}")
        blocks_across = math.ceil(metadata.width / metadata.block_width)
        block_column = column // metadata.block_width
        block_row = row // metadata.block_height
        block_index = block_row * blocks_across + block_column
        local_column = column - block_column * metadata.block_width
        local_row = row - block_row * metadata.block_height
        bytes_per_sample = metadata.bits_per_sample // 8
        byte_offset = (
            local_row * metadata.block_width + local_column
        ) * bytes_per_sample
        payload = self._block(block_index)
        code = "B" if metadata.bits_per_sample == 8 else "f"
        return struct.unpack_from(metadata.byte_order + code, payload, byte_offset)[0]


@dataclass(frozen=True, slots=True)
class _MosaicTile:
    tile_id: str
    west: float
    south: float
    east: float
    north: float
    raster: BlockRaster


class RasterMosaic:
    """Coordinate-addressed view over adjacent checksum-pinned TIFF tiles."""

    def __init__(
        self,
        root: Path,
        dataset: dict,
        *,
        cache_blocks_per_tile: int = 8,
    ) -> None:
        self.dataset = dataset
        self.west, self.south, self.east, self.north = map(float, dataset["bbox"])
        self.pixel_size_x, self.pixel_size_y = map(
            float, dataset["pixel_size_metres"]
        )
        self.nodata = dataset.get("nodata")
        tiles: list[_MosaicTile] = []
        for item in dataset["tiles"]:
            west, south, east, north = map(float, item["bbox"])
            path = root / item["local_path"]
            raster = BlockRaster(path, cache_blocks=cache_blocks_per_tile)
            tiles.append(
                _MosaicTile(
                    tile_id=item["id"],
                    west=west,
                    south=south,
                    east=east,
                    north=north,
                    raster=raster,
                )
            )
        if not tiles:
            raise ValueError(f"dataset {dataset.get('id')} has no tiles")
        self._tiles = tuple(tiles)
        self._last_tile: _MosaicTile | None = None

    @staticmethod
    def _contains(tile: _MosaicTile, x: float, y: float) -> bool:
        return tile.west <= x < tile.east and tile.south < y <= tile.north

    def _find_tile(self, x: float, y: float) -> _MosaicTile:
        if self._last_tile is not None and self._contains(self._last_tile, x, y):
            return self._last_tile
        for tile in self._tiles:
            if self._contains(tile, x, y):
                self._last_tile = tile
                return tile
        # Admit the outermost south/east pixel-center boundary after clamping.
        for tile in self._tiles:
            epsilon = max(tile.raster.metadata.pixel_size_x, tile.raster.metadata.pixel_size_y) * 1e-7
            if (
                tile.west - epsilon <= x <= tile.east + epsilon
                and tile.south - epsilon <= y <= tile.north + epsilon
            ):
                self._last_tile = tile
                return tile
        raise ValueError(f"coordinate is outside mosaic: {x},{y}")

    def sample_nearest(self, x: float, y: float, *, clamp: bool = True) -> RasterSample:
        edge_padded = not (
            self.west <= x <= self.east and self.south <= y <= self.north
        )
        if edge_padded:
            if not clamp:
                raise ValueError(f"coordinate is outside source mosaic: {x},{y}")
            half_x = self.pixel_size_x / 2.0
            half_y = self.pixel_size_y / 2.0
            x = min(max(x, self.west + half_x), self.east - half_x)
            y = min(max(y, self.south + half_y), self.north - half_y)
        tile = self._find_tile(x, y)
        metadata = tile.raster.metadata
        column = math.floor((x - metadata.origin_x) / metadata.pixel_size_x)
        row = math.floor((metadata.origin_y - y) / metadata.pixel_size_y)
        column = min(max(column, 0), metadata.width - 1)
        row = min(max(row, 0), metadata.height - 1)
        value = tile.raster.value(column, row)
        nodata = value == metadata.nodata or (
            isinstance(value, float) and not math.isfinite(value)
        )
        return RasterSample(None if nodata else value, edge_padded, nodata)

    def sample_bilinear(self, x: float, y: float) -> RasterSample:
        """Bilinearly sample the mosaic on its one global pixel-center grid."""

        gx = (x - self.west) / self.pixel_size_x - 0.5
        gy = (self.north - y) / self.pixel_size_y - 0.5
        x0 = math.floor(gx)
        y0 = math.floor(gy)
        fx = gx - x0
        fy = gy - y0
        edge_padded = False
        values: list[float] = []
        for row in (y0, y0 + 1):
            for column in (x0, x0 + 1):
                center_x = self.west + (column + 0.5) * self.pixel_size_x
                center_y = self.north - (row + 0.5) * self.pixel_size_y
                sample = self.sample_nearest(center_x, center_y, clamp=True)
                edge_padded |= sample.edge_padded
                if sample.value is None:
                    return RasterSample(None, edge_padded, True)
                values.append(float(sample.value))
        nw, ne, sw, se = values
        north_value = nw * (1.0 - fx) + ne * fx
        south_value = sw * (1.0 - fx) + se * fx
        return RasterSample(
            north_value * (1.0 - fy) + south_value * fy,
            edge_padded,
            False,
        )

    def cells_in_bbox(
        self, west: float, south: float, east: float, north: float
    ) -> Iterator[tuple[float, float, int | float | None, bool]]:
        """Yield source pixel centers intersecting a projected bounding box."""

        for tile in self._tiles:
            if east < tile.west or west > tile.east or north < tile.south or south > tile.north:
                continue
            metadata = tile.raster.metadata
            column_low = max(
                0, math.floor((west - metadata.origin_x) / metadata.pixel_size_x) - 1
            )
            column_high = min(
                metadata.width - 1,
                math.ceil((east - metadata.origin_x) / metadata.pixel_size_x) + 1,
            )
            row_low = max(
                0, math.floor((metadata.origin_y - north) / metadata.pixel_size_y) - 1
            )
            row_high = min(
                metadata.height - 1,
                math.ceil((metadata.origin_y - south) / metadata.pixel_size_y) + 1,
            )
            for row in range(row_low, row_high + 1):
                center_y = metadata.origin_y - (row + 0.5) * metadata.pixel_size_y
                if not south <= center_y <= north:
                    continue
                for column in range(column_low, column_high + 1):
                    center_x = metadata.origin_x + (column + 0.5) * metadata.pixel_size_x
                    if not west <= center_x <= east:
                        continue
                    value = tile.raster.value(column, row)
                    nodata = value == metadata.nodata or (
                        isinstance(value, float) and not math.isfinite(value)
                    )
                    yield center_x, center_y, None if nodata else value, nodata
