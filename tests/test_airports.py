from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from pingo_terrain.airports import (
    NASR_ARCHIVE_NAME,
    NASR_ARCHIVE_SHA256,
    TARGET_ICAO_IDS,
    airport_manifest_record,
    build_airport_geometry,
    canonical_json_bytes,
    load_airports,
    verify_nasr_archive,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = (
    PROJECT_ROOT / "data" / "downloads" / "airports" / "faa-nasr-2026-07-09"
)
ARCHIVE = SOURCE_DIR / NASR_ARCHIVE_NAME
MANIFEST = (
    PROJECT_ROOT / "data" / "manifests" / "faa-nasr-airports-2026-07-09.json"
)


class AirportManifestTests(unittest.TestCase):
    def test_manifest_pins_official_source_and_render_policy(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        source = manifest["source_artifacts"]["apt_csv_archive"]
        self.assertEqual(source["sha256"], NASR_ARCHIVE_SHA256)
        self.assertEqual(source["bytes"], 8_031_616)
        self.assertTrue(source["url"].startswith("https://nfdc.faa.gov/"))
        self.assertEqual(manifest["effective_date"], "2026-07-09")
        self.assertEqual(manifest["selection"]["runway_records"], 15)
        self.assertEqual(manifest["selection"]["runway_end_records"], 30)
        self.assertEqual(manifest["render_policy"]["pingo_shading_mode"], 1)
        self.assertEqual(manifest["render_policy"]["illumination"], "self")
        self.assertFalse(manifest["render_policy"]["dither"])
        self.assertFalse(manifest["render_policy"]["merge_with_terrain"])


@unittest.skipUnless(ARCHIVE.is_file(), "ignored FAA NASR source is not installed")
class AirportGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.airports = load_airports(ARCHIVE)
        cls.by_icao = {airport.icao_id: airport for airport in cls.airports}

    def test_archive_and_selected_records_match_manifest(self) -> None:
        verify_nasr_archive(ARCHIVE)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        records = [airport_manifest_record(airport) for airport in self.airports]
        self.assertEqual(records, manifest["selected_airports"])
        self.assertEqual(tuple(self.by_icao), TARGET_ICAO_IDS)
        self.assertEqual(sum(len(airport.runways) for airport in self.airports), 15)

    def test_koak_28l_is_exact_and_centerline_derived(self) -> None:
        koak = self.by_icao["KOAK"]
        runway = next(value for value in koak.runways if value.identifier == "10R/28L")
        self.assertEqual((runway.length_ft, runway.width_ft), (6213, 150))
        end = next(value for value in runway.ends if value.identifier == "28L")
        self.assertEqual(end.true_alignment_deg, 292)
        self.assertEqual(end.physical_end.latitude_deg, 37.72227386)
        self.assertEqual(end.physical_end.longitude_deg, -122.2060093)
        self.assertEqual(end.physical_end.elevation_ft_msl, 8.2)
        self.assertIsNone(end.displaced_threshold)

        start = build_airport_geometry(koak)["canonical_start"]
        self.assertEqual(start["runway_end_id"], "28L")
        self.assertEqual(start["threshold_source"], "FAA physical runway end")
        self.assertAlmostEqual(
            start["heading_true_deg_from_threshold_centerline"], 292.163062, places=6
        )
        self.assertEqual(start["initial_clearance_m"], 1.5)

    def test_geometry_is_separate_solid_flat_self_lit_and_upward(self) -> None:
        for airport in self.airports:
            geometry = build_airport_geometry(airport)
            policy = geometry["render_policy"]
            self.assertEqual(policy["pingo_shading_mode"], 1)
            self.assertEqual(policy["illumination"], "self")
            self.assertFalse(policy["dither"])
            self.assertFalse(policy["merge_with_terrain"])
            self.assertFalse(policy["terrain_pattern_lookup"])
            self.assertEqual(
                [mesh["id"] for mesh in geometry["meshes"]],
                ["runway_pavement", "runway_markings"],
            )
            for mesh in geometry["meshes"]:
                self.assertEqual(mesh["render"]["pingo_shading_mode"], 1)
                self.assertEqual(mesh["render"]["illumination"], "self")
                self.assertFalse(mesh["render"]["dither"])
                vertices = mesh["vertices_pingo_m"]
                for triangle in mesh["triangles"]:
                    first, second, third = (vertices[index] for index in triangle[:3])
                    ab_x, ab_z = second[0] - first[0], second[2] - first[2]
                    ac_x, ac_z = third[0] - first[0], third[2] - first[2]
                    normal_y = ab_z * ac_x - ab_x * ac_z
                    self.assertGreater(normal_y, 0.0)

    def test_geometry_counts_and_hashes_are_deterministic(self) -> None:
        expected = {
            "KSFO": (1184, 592, "7d473943b37d672e748d0a9fc97dabba0d77089974139895f9b432e1e2c11678"),
            "KOAK": (776, 388, "782d4f51ee37aff6fc2ae8cdc420fe4df7573560da4ffd54e0978228c004eff1"),
            "KHWD": (260, 130, "a317108601876772acdeea8a0ed186d55b1e0ed4f5fc40123416e79c22d50373"),
            "KSQL": (92, 46, "4a0b729b6f998a553d7892c03fddd3ae067b1489082388cfa8956edc644c65d3"),
            "KCCR": (504, 252, "443ebe6e2f820e717ce893ad881402d32c35fe35c2d2a7e0e4b8cb701241d069"),
        }
        for airport in self.airports:
            geometry = build_airport_geometry(airport)
            vertices, triangles, digest = expected[airport.icao_id]
            self.assertEqual(geometry["statistics"]["vertices"], vertices)
            self.assertEqual(geometry["statistics"]["triangles"], triangles)
            self.assertEqual(sha256(canonical_json_bytes(geometry)).hexdigest(), digest)

    def test_size_gate_rejects_truncated_archive_before_zip_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            truncated = Path(directory) / NASR_ARCHIVE_NAME
            truncated.write_bytes(ARCHIVE.read_bytes()[:128])
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                verify_nasr_archive(truncated)


if __name__ == "__main__":
    unittest.main()
