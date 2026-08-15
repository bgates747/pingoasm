from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
import unittest

from pingo_terrain.airport_p3dm import (
    MAX_MODEL_HALF_EXTENT_M,
    PAVEMENT_SELECTOR,
    REGIONAL_COLUMNS,
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    REGIONAL_VERTICAL_ORIGIN_M,
    SOLID_PALETTE,
    WHITE_SELECTOR,
    YELLOW_SELECTOR,
    build_airport_p3dm_corpus,
    project_wgs84_utm10,
    resolve_solid_palette_uv,
    solid_palette_uv,
)
from pingo_terrain.airports import NASR_ARCHIVE_NAME, load_airports
from pingo_terrain.p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    ShadingMode,
    parse_container,
)


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = (
    ROOT
    / "data"
    / "downloads"
    / "airports"
    / "faa-nasr-2026-07-09"
    / NASR_ARCHIVE_NAME
)


class ProjectionAndPaletteTests(unittest.TestCase):
    def test_pure_projection_matches_pinned_proj_witness(self) -> None:
        # PROJ 9.4: Ballpark geographic offset NAD83 -> WGS84 + UTM zone 10N.
        east, north = project_wgs84_utm10(37.72126138, -122.22115055)
        self.assertAlmostEqual(east, 568_639.449102, places=6)
        self.assertAlmostEqual(north, 4_175_174.564461, places=3)

    def test_raw_cube_palette_has_exact_hard_surface_selectors(self) -> None:
        self.assertEqual(len(SOLID_PALETTE), 64)
        self.assertEqual(SOLID_PALETTE[PAVEMENT_SELECTOR], 0xD5)
        self.assertEqual(SOLID_PALETTE[WHITE_SELECTOR], 0xFF)
        self.assertEqual(SOLID_PALETTE[YELLOW_SELECTOR], 0xCF)
        self.assertEqual((PAVEMENT_SELECTOR, WHITE_SELECTOR, YELLOW_SELECTOR), (21, 63, 15))
        self.assertEqual(
            sha256(SOLID_PALETTE).hexdigest(),
            "47f7e1441be49b5e4701d19e2af2c31a5ee056914c03bd8d6249bdb085bb374d",
        )
        for selector in range(64):
            self.assertEqual(resolve_solid_palette_uv(solid_palette_uv(selector)), selector)


@unittest.skipUnless(ARCHIVE.is_file(), "ignored FAA NASR source is not installed")
class AirportP3DMCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name)
        cls.index = build_airport_p3dm_corpus(load_airports(ARCHIVE), cls.output)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def component_records(self):
        for airport in self.index["airports"]:
            for group in airport["groups"]:
                for component in group["components"]:
                    yield airport, group, component

    def test_index_and_component_bytes_are_deterministic(self) -> None:
        index_bytes = (self.output / "AIRPORTS.json").read_bytes()
        self.assertEqual(
            sha256(index_bytes).hexdigest(),
            "0653fb8cfe5b0f09bd47951cb4ed150202dd25bb681ed9412db03f60092f9503",
        )
        self.assertEqual(json.loads(index_bytes), self.index)
        expected = {
            "APT/KCCR/M00.AGN": "4b8aaf1df31c6704ed538d36639f687054215d6bbc06b351cc39ef2d59e14c44",
            "APT/KCCR/P00.AGN": "3d36fd05065e5be2c283fb487c4f11cad8301ff9088c10db05fc1399435fc385",
            "APT/KHWD/M00.AGN": "383b923b1c4237c651e58aab9c2cc4bbc15e8e7fadfe31065d5f9a920f382c53",
            "APT/KHWD/P00.AGN": "52f2cac2d09844658cb7c0602d301dacb7ebbbeee50964b6cadb8d0c4fac2269",
            "APT/KOAK/M00.AGN": "26f4873fca9b5c9ec26ec9d8b71358a23e44426e8b395870ea05bf52c8d040f3",
            "APT/KOAK/M01.AGN": "6586be4c61b23b5f0943981091a5cc48d3673eabee4b90b9b6f981d03f1fdff8",
            "APT/KOAK/P00.AGN": "4d77a585a5581039eeed93001df34c116a3f86e3b00fe22a2b3963b0f7285432",
            "APT/KOAK/P01.AGN": "c1b17984521c42cd512a1221efada69034d1a2d4c3ad4d4b80bdb424ce6dee20",
            "APT/KSFO/M00.AGN": "b97135b7089ea863cdd52276f7ec7ef3bbcea7d68675ac19b2dc78adc8d0c890",
            "APT/KSFO/P00.AGN": "280b07e9b4f235d1293e55dfc15f418cf431d46402abab757d69510c154f9135",
            "APT/KSQL/M00.AGN": "e77ff1dd42aa6ea882a082b4072144acc839940c0943561d6d2938fd7f047b58",
            "APT/KSQL/P00.AGN": "7a9bf05b08b2416ed28ce9635f0e9330555f05e2e30fdeda535fa6e18f58c19a",
        }
        self.assertEqual(
            {record["path"]: record["sha256"] for _, _, record in self.component_records()},
            expected,
        )

    def test_components_round_trip_with_exact_policy_and_upward_winding(self) -> None:
        for _airport, _group, record in self.component_records():
            tile = parse_container((self.output / record["path"]).read_bytes())
            self.assertEqual(tile.meta.shading_mode, ShadingMode.SOLID_FLAT)
            self.assertEqual(tile.meta.illumination, IlluminationPolicy.SELF)
            self.assertEqual(tile.meta.material_set, MaterialSet.NATIVE_SOLID_PALETTE)
            expected_selector = (
                PAVEMENT_SELECTOR
                if tile.meta.layer_kind is LayerKind.AIRPORT_PAVEMENT
                else WHITE_SELECTOR
            )
            self.assertEqual(resolve_solid_palette_uv(tile.uvs[0]), expected_selector)
            self.assertEqual(set(tile.uv_indices), {0})
            self.assertLessEqual(tile.meta.model_half_extent_m, MAX_MODEL_HALF_EXTENT_M)
            self.assertLessEqual(
                record["object_transform"]["uniform_object_scale_q8_8"], 65_535
            )
            for offset in range(0, len(tile.position_indices), 3):
                first, second, third = (
                    tile.positions[tile.position_indices[offset + index]]
                    for index in range(3)
                )
                ab_x, ab_z = second[0] - first[0], second[2] - first[2]
                ac_x, ac_z = third[0] - first[0], third[2] - first[2]
                self.assertGreater(ab_z * ac_x - ab_x * ac_z, 0)

    def test_normalization_witness_bounds_every_error_and_elevation(self) -> None:
        for _airport, _group, record in self.component_records():
            tile = parse_container((self.output / record["path"]).read_bytes())
            witness = record["normalization_witness"]
            self.assertLessEqual(
                witness["maximum_decode_error_m"],
                witness["theoretical_decode_error_bound_m"] + 1e-9,
            )
            source_min, source_max = witness["source_elevation_bounds_faa_msl_m"]
            self.assertEqual(tile.meta.minimum_elevation_dm, math.floor(source_min * 10))
            self.assertEqual(tile.meta.maximum_elevation_dm, math.ceil(source_max * 10))
            self.assertEqual(record["meta"]["center_east_m"], tile.meta.center_east_m)
            self.assertEqual(record["meta"]["center_north_m"], tile.meta.center_north_m)

    def test_partition_is_minimal_for_scale_and_keeps_koak_28l_layers_together(self) -> None:
        groups = {
            airport["icao_id"]: [group["runways"] for group in airport["groups"]]
            for airport in self.index["airports"]
        }
        self.assertEqual(
            groups["KOAK"],
            [["10L/28R", "10R/28L", "12/30"], ["15/33"]],
        )
        self.assertTrue(all(len(value) == 1 for key, value in groups.items() if key != "KOAK"))
        start = self.index["canonical_start"]
        self.assertEqual(start["runway_end_id"], "28L")
        self.assertEqual(start["activation_group"], 0)
        self.assertEqual(
            start["required_before_first_render"],
            ["APT/KOAK/P00.AGN", "APT/KOAK/M00.AGN"],
        )
        self.assertEqual(start["anchor_tile"], {"tile_x": 94, "tile_y": 146})
        self.assertEqual(start["surface_elevation_m_faa_msl"], 2.49936)
        self.assertEqual(start["faa_true_alignment_deg_nearest_degree"], 292)
        wire = start["pingo_wire_start_witness"]
        self.assertEqual(
            wire["coarse_cell_center_absolute_utm_m"],
            {"east": 570_112, "north": 4_175_104},
        )
        self.assertEqual(
            wire["camera_translation_counts"],
            {"x_north": 3106, "y_absolute_altitude": 64, "z_west": 2226},
        )
        self.assertEqual(
            wire["camera_euler_rotation_words"],
            {"pitch_x": 0, "yaw_y": -14411, "roll_z": 0, "yaw_y_unsigned_hex": "0xC7B5"},
        )
        self.assertEqual(
            wire["required_group_object"]["translation_counts"],
            {"x_north": -8176, "y_absolute_model_origin": 9728, "z_west": 26816},
        )
        self.assertEqual(wire["required_group_object"]["uniform_object_scale_q8_8"], 53056)
        self.assertIn(
            "Y is altitude relative to the shared 608.0 m",
            start["aircraft_position_pingo_relative_to_region_m_convention"],
        )
        koak = next(
            airport for airport in self.index["airports"] if airport["icao_id"] == "KOAK"
        )
        self.assertEqual(koak["groups"][0]["activation_circle"]["geometry_radius_m"], 1941)
        self.assertEqual(koak["groups"][1]["activation_circle"]["geometry_radius_m"], 515)

    def test_regional_origin_and_vertical_datum_mismatch_are_explicit(self) -> None:
        frame = self.index["regional_frame"]
        self.assertEqual(frame["origin_easting_m"], REGIONAL_ORIGIN_EAST_M)
        self.assertEqual(frame["origin_northing_m"], REGIONAL_ORIGIN_NORTH_M)
        self.assertEqual(frame["vertical_origin_m"], REGIONAL_VERTICAL_ORIGIN_M)
        self.assertEqual(frame["columns"], REGIONAL_COLUMNS)
        datum = self.index["datum_contract"]
        self.assertIn("NAVD88", datum["terrain_vertical_source"])
        self.assertIn("FAA feet MSL", datum["airport_vertical_source"])
        self.assertIn("not relabelled", datum["vertical_alignment_status"])


if __name__ == "__main__":
    unittest.main()
