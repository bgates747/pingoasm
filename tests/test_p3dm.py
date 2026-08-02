from __future__ import annotations

from dataclasses import replace
import hashlib
import struct
import unittest

from pingo_terrain.p3dm import (
    AGNB_VERSION,
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    P3DMMeta,
    P3DMTile,
    ShadingMode,
    align4,
    make_container,
    make_data,
    parse_container,
    validate_tile,
)


def terrain_tile() -> P3DMTile:
    return P3DMTile(
        stage_buffer_id=0x7400,
        meta=P3DMMeta(
            layer_kind=LayerKind.TERRAIN,
            lod=0,
            shading_mode=ShadingMode.FLAT_PATTERN,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
            tile_x=-3,
            tile_y=7,
            center_east_m=12_345,
            center_north_m=-54_321,
            minimum_elevation_dm=-25,
            maximum_elevation_dm=1_325,
            model_half_extent_m=544,
        ),
        positions=(
            (-32767, 0, -32767),
            (32767, 1200, -32767),
            (-32767, 500, 32767),
            (32767, 900, 32767),
        ),
        position_indices=(0, 2, 1, 1, 2, 3),
        uvs=((10_922, 54_612), (32_767, 32_767)),
        uv_indices=(0, 0, 0, 1, 1, 1),
    )


def airport_tile(layer: LayerKind) -> P3DMTile:
    source = terrain_tile()
    return replace(
        source,
        meta=replace(
            source.meta,
            layer_kind=layer,
            shading_mode=ShadingMode.SOLID_FLAT,
            illumination=IlluminationPolicy.SELF,
            material_set=MaterialSet.NATIVE_SOLID_PALETTE,
        ),
    )


def chunk_offsets(container: bytes) -> dict[bytes, tuple[int, int, int]]:
    """Return absolute nested chunk payload locations for mutation tests."""

    top = 12
    vers_size = struct.unpack_from("<I", container, top + 4)[0]
    top += 8 + align4(vers_size)
    list_size = struct.unpack_from("<I", container, top + 4)[0]
    list_start = top + 8
    list_end = list_start + list_size
    nested = list_start + 4
    result = {}
    while nested < list_end:
        chunk_id = bytes(container[nested : nested + 4])
        size = struct.unpack_from("<I", container, nested + 4)[0]
        result[chunk_id] = (nested + 8, size, nested + 8 + align4(size))
        nested += 8 + align4(size)
    return result


class P3DMTests(unittest.TestCase):
    def test_terrain_container_round_trip_is_byte_deterministic(self):
        tile = terrain_tile()
        first = make_container(tile)
        second = make_container(tile)

        self.assertEqual(first, second)
        self.assertEqual(parse_container(first), tile)
        self.assertEqual(first[:4], b"RIFF")
        self.assertEqual(first[8:12], b"AGNB")
        self.assertEqual(struct.unpack_from("<I", first, 4)[0], len(first) - 8)
        self.assertEqual(first[20:22], bytes(AGNB_VERSION))
        self.assertEqual(
            hashlib.sha256(first).hexdigest(),
            "b12c0e671eff2cab25791871845bd81fd4b0176676aa154e96580e60636fa877",
        )

    def test_data_layout_has_exact_firmware_import_size(self):
        tile = terrain_tile()
        data = make_data(tile)
        self.assertEqual(len(data), 6 * 4 + 2 * 6 + 4 * 2 + 2 * 6)
        self.assertEqual(struct.unpack_from("<hhh", data), tile.positions[0])
        position_indices_offset = 6 * len(tile.positions)
        self.assertEqual(
            struct.unpack_from("<6H", data, position_indices_offset),
            tile.position_indices,
        )

    def test_airport_layers_require_solid_flat_self_illumination(self):
        for layer in (LayerKind.AIRPORT_PAVEMENT, LayerKind.AIRPORT_MARKING):
            with self.subTest(layer=layer):
                tile = airport_tile(layer)
                self.assertEqual(parse_container(make_container(tile)), tile)
                for bad_meta in (
                    replace(tile.meta, shading_mode=ShadingMode.FLAT_PATTERN),
                    replace(tile.meta, illumination=IlluminationPolicy.SCENE),
                    replace(
                        tile.meta,
                        material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, "airport hard surfaces"):
                        validate_tile(replace(tile, meta=bad_meta))

    def test_terrain_policy_cannot_be_downgraded_to_solid_flat(self):
        tile = terrain_tile()
        with self.assertRaisesRegex(ValueError, "terrain must use patterned"):
            validate_tile(
                replace(
                    tile,
                    meta=replace(tile.meta, shading_mode=ShadingMode.SOLID_FLAT),
                )
            )

    def test_flat_triangles_cannot_span_several_material_selectors(self):
        tile = terrain_tile()
        with self.assertRaisesRegex(ValueError, "spans several UV selectors"):
            validate_tile(replace(tile, uv_indices=(0, 1, 0, 1, 1, 1)))

    def test_index_and_count_invariants_are_enforced(self):
        tile = terrain_tile()
        invalid = (
            replace(tile, position_indices=(0, 2)),
            replace(tile, position_indices=(0, 2, 4)),
            replace(tile, uv_indices=(0, 0, 0)),
            replace(tile, uvs=()),
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    validate_tile(candidate)

    def test_reserved_staging_buffer_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stage_buffer_id"):
            validate_tile(replace(terrain_tile(), stage_buffer_id=0xFFFF))

    def test_crc_detects_data_corruption(self):
        container = bytearray(make_container(terrain_tile()))
        data_start, data_size, _ = chunk_offsets(container)[b"DATA"]
        self.assertGreater(data_size, 10)
        container[data_start + 7] ^= 0x40
        with self.assertRaisesRegex(ValueError, "CRC32 mismatch"):
            parse_container(bytes(container))

    def test_descriptor_count_cannot_reinterpret_data(self):
        container = bytearray(make_container(terrain_tile()))
        descriptor_start, descriptor_size, _ = chunk_offsets(container)[b"P3DM"]
        self.assertEqual(descriptor_size, 36)
        # vertex_count begins at descriptor byte 24.
        struct.pack_into("<H", container, descriptor_start + 24, 5)
        with self.assertRaisesRegex(ValueError, "DATA size"):
            parse_container(bytes(container))

    def test_riff_bounds_and_zero_padding_are_enforced(self):
        original = make_container(terrain_tile())
        bad_size = bytearray(original)
        struct.pack_into("<I", bad_size, 4, len(original) - 9)
        with self.assertRaisesRegex(ValueError, "RIFF size"):
            parse_container(bytes(bad_size))

        bad_padding = bytearray(original)
        bhdr_start, bhdr_size, bhdr_next = chunk_offsets(original)[b"BHDR"]
        self.assertEqual(bhdr_size, 2)
        bad_padding[bhdr_next - 1] = 1
        with self.assertRaisesRegex(ValueError, "nonzero alignment padding"):
            parse_container(bytes(bad_padding))

    def test_truncation_and_extra_top_level_chunks_are_rejected(self):
        original = make_container(terrain_tile())
        with self.assertRaises(ValueError):
            parse_container(original[:-1])

        extra = bytearray(original + b"JUNK\x00\x00\x00\x00")
        struct.pack_into("<I", extra, 4, len(extra) - 8)
        with self.assertRaisesRegex(ValueError, "unexpected top-level"):
            parse_container(bytes(extra))


if __name__ == "__main__":
    unittest.main()
