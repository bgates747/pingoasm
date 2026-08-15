from pathlib import Path
import struct
import tempfile
import unittest

from pingo_terrain.geotiff import (
    GeoTiffExpectation,
    read_geotiff_metadata,
    sha256_file,
    summarize_raster,
    validate_geotiff,
)


def _tiny_category_tiff(path: Path, byte_order: str = ">") -> None:
    fields: list[tuple[int, int, int, bytes | int]] = [
        (256, 4, 1, 2),
        (257, 4, 1, 2),
        (258, 3, 1, 8),
        (259, 3, 1, 1),
        (262, 3, 1, 1),
        (273, 4, 1, -1),
        (277, 3, 1, 1),
        (278, 4, 1, 2),
        (279, 4, 1, 4),
        (339, 3, 1, 1),
        (33550, 12, 3, struct.pack(byte_order + "ddd", 30.0, 30.0, 0.0)),
        (33922, 12, 6, struct.pack(byte_order + "dddddd", 0.0, 0.0, 0.0, 100.0, 200.0, 0.0)),
        (
            34735,
            3,
            20,
            struct.pack(
                byte_order + "H" * 20,
                1, 1, 0, 4,
                1024, 0, 1, 1,
                1025, 0, 1, 1,
                3072, 0, 1, 5070,
                3076, 0, 1, 9001,
            ),
        ),
        (42113, 2, 4, b"250\0"),
    ]
    ifd_offset = 8
    external_offset = ifd_offset + 2 + len(fields) * 12 + 4
    external: list[tuple[int, bytes]] = []
    resolved: list[tuple[int, int, int, bytes]] = []
    for tag, kind, count, value in fields:
        if isinstance(value, bytes):
            if len(value) <= 4:
                packed = value.ljust(4, b"\0")
            else:
                packed = struct.pack(byte_order + "I", external_offset)
                external.append((external_offset, value))
                external_offset += len(value)
        elif kind == 3:
            packed = struct.pack(byte_order + "H", value) + b"\0\0"
        elif value == -1:
            packed = b""  # filled after external metadata establishes raster offset
        else:
            packed = struct.pack(byte_order + "I", value)
        resolved.append((tag, kind, count, packed))
    raster_offset = external_offset
    output = bytearray(b"MM" if byte_order == ">" else b"II")
    output.extend(struct.pack(byte_order + "HI", 42, ifd_offset))
    output.extend(struct.pack(byte_order + "H", len(resolved)))
    for tag, kind, count, packed in resolved:
        if tag == 273:
            packed = struct.pack(byte_order + "I", raster_offset)
        output.extend(struct.pack(byte_order + "HHI", tag, kind, count))
        output.extend(packed)
    output.extend(struct.pack(byte_order + "I", 0))
    for offset, payload in external:
        assert len(output) == offset
        output.extend(payload)
    assert len(output) == raster_offset
    output.extend(bytes((11, 22, 250, 95)))
    path.write_bytes(output)


class GeoTiffTests(unittest.TestCase):
    def test_metadata_validation_and_streaming_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny.tif"
            _tiny_category_tiff(path)
            metadata = read_geotiff_metadata(path)
            self.assertEqual((metadata.width, metadata.height), (2, 2))
            self.assertEqual(metadata.epsg, 5070)
            self.assertEqual(metadata.nodata, 250)
            self.assertEqual(metadata.bbox, (100.0, 140.0, 160.0, 200.0))
            self.assertEqual(metadata.storage, "strips")
            summary = summarize_raster(metadata)
            self.assertEqual(summary.valid_count, 3)
            self.assertEqual(summary.nodata_count, 1)
            self.assertEqual((summary.minimum, summary.maximum), (11, 95))
            self.assertEqual(summary.observed_values, (11, 22, 95))
            validate_geotiff(
                path,
                GeoTiffExpectation(
                    width=2,
                    height=2,
                    epsg=5070,
                    bbox=(100.0, 140.0, 160.0, 200.0),
                    bits_per_sample=8,
                    sample_format=1,
                    nodata=250,
                    pixel_size=30.0,
                ),
            )
            self.assertEqual(len(sha256_file(path)), 64)

    def test_rejects_non_tiff_and_wrong_expectation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "error.tif"
            bad.write_text("<html>service error</html>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Not a TIFF"):
                read_geotiff_metadata(bad)
            good = Path(directory) / "tiny.tif"
            _tiny_category_tiff(good, "<")
            with self.assertRaisesRegex(ValueError, "EPSG=5070, expected 32610"):
                validate_geotiff(
                    good,
                    GeoTiffExpectation(2, 2, 32610, (100.0, 140.0, 160.0, 200.0), 8, 1, 250, 30.0),
                )


if __name__ == "__main__":
    unittest.main()
