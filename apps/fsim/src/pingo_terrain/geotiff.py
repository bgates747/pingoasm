"""Small, dependency-free validator for the USGS GeoTIFFs used here.

This is deliberately not a general TIFF implementation.  It accepts classic,
single-band, uncompressed strip- or tile-organized rasters and exposes enough
metadata to reject HTML/error payloads and subtly wrong WCS/export responses
before they enter a checksum-pinned source corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct
from typing import BinaryIO, Iterable


_TYPE_FORMAT = {
    1: "B",   # BYTE
    2: "c",   # ASCII
    3: "H",   # SHORT
    4: "I",   # LONG
    5: "II",  # RATIONAL
    11: "f",  # FLOAT
    12: "d",  # DOUBLE
}
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}


@dataclass(frozen=True)
class GeoTiffMetadata:
    path: Path
    byte_order: str
    width: int
    height: int
    bits_per_sample: int
    compression: int
    samples_per_pixel: int
    sample_format: int
    pixel_size_x: float
    pixel_size_y: float
    origin_x: float
    origin_y: float
    epsg: int | None
    nodata: float | int | None
    storage: str
    block_width: int
    block_height: int
    block_offsets: tuple[int, ...]
    block_byte_counts: tuple[int, ...]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            self.origin_x,
            self.origin_y - self.height * self.pixel_size_y,
            self.origin_x + self.width * self.pixel_size_x,
            self.origin_y,
        )


@dataclass(frozen=True)
class RasterSummary:
    valid_count: int
    nodata_count: int
    minimum: float | int | None
    maximum: float | int | None
    observed_values: tuple[int, ...] | None


@dataclass(frozen=True)
class GeoTiffExpectation:
    width: int
    height: int
    epsg: int
    bbox: tuple[float, float, float, float]
    bits_per_sample: int
    sample_format: int
    nodata: float | int
    pixel_size: float


def _read_exact(handle: BinaryIO, offset: int, count: int, file_size: int) -> bytes:
    if offset < 0 or count < 0 or offset + count > file_size:
        raise ValueError(
            f"TIFF field points outside file: offset={offset}, count={count}, "
            f"file_size={file_size}"
        )
    handle.seek(offset)
    data = handle.read(count)
    if len(data) != count:
        raise ValueError(f"Truncated TIFF field at byte {offset}")
    return data


def _numbers(
    tags: dict[int, tuple[int, int, bytes]], byte_order: str, tag: int
) -> tuple[int | float, ...]:
    try:
        field_type, count, payload = tags[tag]
    except KeyError as error:
        raise ValueError(f"Required TIFF tag {tag} is missing") from error
    if field_type == 5:
        raw = struct.unpack(byte_order + "II" * count, payload)
        return tuple(raw[index] / raw[index + 1] for index in range(0, len(raw), 2))
    try:
        code = _TYPE_FORMAT[field_type]
    except KeyError as error:
        raise ValueError(f"Unsupported TIFF field type {field_type}") from error
    return struct.unpack(byte_order + code * count, payload)


def _epsg_from_geokeys(
    tags: dict[int, tuple[int, int, bytes]], byte_order: str
) -> int | None:
    if 34735 not in tags:
        return None
    directory = tuple(int(value) for value in _numbers(tags, byte_order, 34735))
    if len(directory) < 4 or directory[0] != 1:
        raise ValueError("Unsupported or truncated GeoKeyDirectory")
    key_count = directory[3]
    if len(directory) != 4 + key_count * 4:
        raise ValueError("GeoKeyDirectory length does not match its key count")
    keys: dict[int, tuple[int, int, int]] = {}
    for offset in range(4, len(directory), 4):
        key_id, location, count, value = directory[offset : offset + 4]
        keys[key_id] = (location, count, value)

    # ProjectedCSTypeGeoKey is definitive for both source products.  Retain
    # GeographicTypeGeoKey as a useful fallback for future EPSG:4326 inputs.
    for key_id in (3072, 2048):
        if key_id not in keys:
            continue
        location, count, value = keys[key_id]
        if location != 0 or count != 1:
            raise ValueError(f"GeoKey {key_id} does not contain one inline EPSG code")
        if value not in (0, 32767):
            return value
    return None


def read_geotiff_metadata(path: str | Path) -> GeoTiffMetadata:
    """Parse and structurally validate one classic, uncompressed GeoTIFF."""

    raster_path = Path(path)
    file_size = raster_path.stat().st_size
    if file_size < 8:
        raise ValueError("Not a TIFF file: fewer than eight bytes")
    with raster_path.open("rb") as handle:
        header = _read_exact(handle, 0, 8, file_size)
        if header[:2] == b"II":
            byte_order = "<"
        elif header[:2] == b"MM":
            byte_order = ">"
        else:
            raise ValueError("Not a TIFF file: invalid byte-order marker")
        if struct.unpack_from(byte_order + "H", header, 2)[0] != 42:
            raise ValueError("Only classic TIFF files are supported")
        ifd_offset = struct.unpack_from(byte_order + "I", header, 4)[0]
        entry_count = struct.unpack(
            byte_order + "H", _read_exact(handle, ifd_offset, 2, file_size)
        )[0]
        table_size = entry_count * 12 + 4
        table = _read_exact(handle, ifd_offset + 2, table_size, file_size)
        tags: dict[int, tuple[int, int, bytes]] = {}
        for index in range(entry_count):
            cursor = index * 12
            tag, field_type, count = struct.unpack_from(
                byte_order + "HHI", table, cursor
            )
            if field_type not in _TYPE_SIZE:
                raise ValueError(f"Unsupported TIFF field type {field_type}")
            byte_count = _TYPE_SIZE[field_type] * count
            value_field = table[cursor + 8 : cursor + 12]
            if byte_count <= 4:
                payload = value_field[:byte_count]
            else:
                value_offset = struct.unpack(byte_order + "I", value_field)[0]
                payload = _read_exact(handle, value_offset, byte_count, file_size)
            tags[tag] = (field_type, count, payload)

    width = int(_numbers(tags, byte_order, 256)[0])
    height = int(_numbers(tags, byte_order, 257)[0])
    bits = int(_numbers(tags, byte_order, 258)[0])
    compression = int(_numbers(tags, byte_order, 259)[0])
    samples = int(_numbers(tags, byte_order, 277)[0])
    sample_format = int(_numbers(tags, byte_order, 339)[0]) if 339 in tags else 1
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid TIFF dimensions {width}x{height}")
    if compression != 1 or samples != 1:
        raise ValueError(
            "Expected an uncompressed single-band TIFF; got "
            f"compression={compression}, samples={samples}"
        )
    if (bits, sample_format) not in ((8, 1), (32, 3)):
        raise ValueError(
            "Expected uint8 or float32 raster samples; got "
            f"bits={bits}, sample_format={sample_format}"
        )

    if 33550 in tags and 33922 in tags:
        scale = _numbers(tags, byte_order, 33550)
        tiepoint = _numbers(tags, byte_order, 33922)
        if len(scale) < 2 or len(tiepoint) < 6:
            raise ValueError("Truncated GeoTIFF scale/tiepoint")
        pixel_size_x, pixel_size_y = abs(float(scale[0])), abs(float(scale[1]))
        origin_x, origin_y = float(tiepoint[3]), float(tiepoint[4])
    elif 34264 in tags:
        transform = _numbers(tags, byte_order, 34264)
        if len(transform) != 16:
            raise ValueError("GeoTIFF transformation matrix must have 16 values")
        if any(abs(transform[index]) > 1e-10 for index in (1, 2, 4, 6, 8, 9)):
            raise ValueError("Rotated or sheared GeoTIFF grids are unsupported")
        pixel_size_x, pixel_size_y = abs(float(transform[0])), abs(float(transform[5]))
        origin_x, origin_y = float(transform[3]), float(transform[7])
    else:
        raise ValueError("GeoTIFF has no supported geotransform")
    if pixel_size_x <= 0.0 or pixel_size_y <= 0.0:
        raise ValueError("GeoTIFF pixel dimensions must be positive")

    if 42113 in tags:
        text = tags[42113][2].rstrip(b"\0").decode("ascii").strip()
        nodata_value = float(text)
        nodata: float | int = int(nodata_value) if nodata_value.is_integer() else nodata_value
    else:
        nodata = None

    bytes_per_sample = bits // 8
    if 324 in tags:
        storage = "tiles"
        block_width = int(_numbers(tags, byte_order, 322)[0])
        block_height = int(_numbers(tags, byte_order, 323)[0])
        offsets = tuple(int(value) for value in _numbers(tags, byte_order, 324))
        counts = tuple(int(value) for value in _numbers(tags, byte_order, 325))
        expected_blocks = math.ceil(width / block_width) * math.ceil(height / block_height)
        expected_block_bytes = block_width * block_height * bytes_per_sample
        if len(offsets) != expected_blocks or len(counts) != expected_blocks:
            raise ValueError("TIFF tile arrays do not match raster dimensions")
        if any(count != expected_block_bytes for count in counts):
            raise ValueError("Expected full-size uncompressed TIFF tile payloads")
    elif 273 in tags:
        storage = "strips"
        block_width = width
        block_height = int(_numbers(tags, byte_order, 278)[0])
        offsets = tuple(int(value) for value in _numbers(tags, byte_order, 273))
        counts = tuple(int(value) for value in _numbers(tags, byte_order, 279))
        expected_blocks = math.ceil(height / block_height)
        if len(offsets) != expected_blocks or len(counts) != expected_blocks:
            raise ValueError("TIFF strip arrays do not match raster dimensions")
        for index, count in enumerate(counts):
            rows = min(block_height, height - index * block_height)
            if count != rows * width * bytes_per_sample:
                raise ValueError("TIFF strip payload size does not match its rows")
    else:
        raise ValueError("TIFF has neither strip nor tile storage")
    for offset, count in zip(offsets, counts, strict=True):
        if offset < 0 or count <= 0 or offset + count > file_size:
            raise ValueError("TIFF raster payload points outside the file")

    return GeoTiffMetadata(
        path=raster_path,
        byte_order=byte_order,
        width=width,
        height=height,
        bits_per_sample=bits,
        compression=compression,
        samples_per_pixel=samples,
        sample_format=sample_format,
        pixel_size_x=pixel_size_x,
        pixel_size_y=pixel_size_y,
        origin_x=origin_x,
        origin_y=origin_y,
        epsg=_epsg_from_geokeys(tags, byte_order),
        nodata=nodata,
        storage=storage,
        block_width=block_width,
        block_height=block_height,
        block_offsets=offsets,
        block_byte_counts=counts,
    )


def _iter_raster_values(metadata: GeoTiffMetadata) -> Iterable[int | float]:
    code = "B" if metadata.bits_per_sample == 8 else "f"
    bytes_per_sample = metadata.bits_per_sample // 8
    blocks_across = math.ceil(metadata.width / metadata.block_width)
    with metadata.path.open("rb") as handle:
        for block_index, (offset, count) in enumerate(
            zip(metadata.block_offsets, metadata.block_byte_counts, strict=True)
        ):
            handle.seek(offset)
            payload = handle.read(count)
            if len(payload) != count:
                raise ValueError(f"Truncated raster block {block_index}")
            block_x = (block_index % blocks_across) * metadata.block_width
            block_y = (block_index // blocks_across) * metadata.block_height
            valid_width = min(metadata.block_width, metadata.width - block_x)
            valid_height = min(metadata.block_height, metadata.height - block_y)
            if metadata.storage == "strips":
                values = struct.unpack(
                    metadata.byte_order + code * (count // bytes_per_sample), payload
                )
                yield from values
                continue
            row_stride = metadata.block_width * bytes_per_sample
            for row in range(valid_height):
                row_payload = payload[row * row_stride : row * row_stride + valid_width * bytes_per_sample]
                yield from struct.unpack(
                    metadata.byte_order + code * valid_width, row_payload
                )


def summarize_raster(metadata: GeoTiffMetadata) -> RasterSummary:
    """Stream valid samples and return integrity/provenance summary statistics."""

    valid_count = nodata_count = 0
    minimum: float | int | None = None
    maximum: float | int | None = None
    observed: set[int] | None = set() if metadata.bits_per_sample == 8 else None
    for value in _iter_raster_values(metadata):
        is_nodata = value == metadata.nodata or (
            isinstance(value, float) and not math.isfinite(value)
        )
        if is_nodata:
            nodata_count += 1
            continue
        valid_count += 1
        minimum = value if minimum is None else min(minimum, value)
        maximum = value if maximum is None else max(maximum, value)
        if observed is not None:
            observed.add(int(value))
    if valid_count + nodata_count != metadata.width * metadata.height:
        raise ValueError("Raster traversal did not cover every cell exactly once")
    return RasterSummary(
        valid_count=valid_count,
        nodata_count=nodata_count,
        minimum=minimum,
        maximum=maximum,
        observed_values=tuple(sorted(observed)) if observed is not None else None,
    )


def validate_geotiff(
    path: str | Path,
    expectation: GeoTiffExpectation,
    *,
    tolerance: float = 1e-6,
) -> GeoTiffMetadata:
    metadata = read_geotiff_metadata(path)
    exact = {
        "width": (metadata.width, expectation.width),
        "height": (metadata.height, expectation.height),
        "EPSG": (metadata.epsg, expectation.epsg),
        "bits": (metadata.bits_per_sample, expectation.bits_per_sample),
        "sample format": (metadata.sample_format, expectation.sample_format),
        "nodata": (metadata.nodata, expectation.nodata),
    }
    mismatches = [f"{name}={actual!r}, expected {wanted!r}" for name, (actual, wanted) in exact.items() if actual != wanted]
    for name, actual, wanted in (
        ("pixel size x", metadata.pixel_size_x, expectation.pixel_size),
        ("pixel size y", metadata.pixel_size_y, expectation.pixel_size),
    ):
        if not math.isclose(actual, wanted, rel_tol=0.0, abs_tol=tolerance):
            mismatches.append(f"{name}={actual!r}, expected {wanted!r}")
    for name, actual, wanted in zip(
        ("west", "south", "east", "north"), metadata.bbox, expectation.bbox, strict=True
    ):
        if not math.isclose(actual, wanted, rel_tol=0.0, abs_tol=tolerance):
            mismatches.append(f"bbox {name}={actual!r}, expected {wanted!r}")
    if mismatches:
        raise ValueError("GeoTIFF does not match request: " + "; ".join(mismatches))
    return metadata


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
