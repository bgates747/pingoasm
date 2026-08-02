from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
import unittest

from pingo_terrain.landmark_p3dm import (
    LANDMARK_SELECTORS,
    LANDMARK_SPECS,
    REGIONAL_VERTICAL_ORIGIN_M,
    SOLID_PALETTE,
    add_buried_foundation_skirt,
    build_campanile_mesh,
    build_landmark_p3dm_corpus,
    build_landmark_tile,
    build_mount_diablo_mesh,
    build_salesforce_mesh,
    build_transamerica_mesh,
    resolve_solid_palette_uv,
    solid_palette_uv,
    validate_procedural_mesh,
    validate_source_controls,
)
from pingo_terrain.p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    ShadingMode,
    parse_container,
)


ROOT = Path(__file__).resolve().parents[1]
REGIONAL_MANIFEST = ROOT / "data/manifests/bay-area-2026-08-02.json"
LANDMARK_MANIFEST = (
    ROOT / "data/manifests/bay-area-landmarks-2026-08-02.json"
)
DEM_WITNESSES = (
    ROOT / "data/downloads/bay-area/usgs-3dep-10m-utm10n/dem-r01-c02.tif",
    ROOT / "data/downloads/bay-area/usgs-3dep-10m-utm10n/dem-r01-c04.tif",
    ROOT / "data/downloads/bay-area/usgs-3dep-10m-utm10n/dem-r02-c01.tif",
    ROOT / "data/downloads/bay-area/usgs-3dep-10m-utm10n/dem-r02-c02.tif",
)
SOURCES_INSTALLED = (
    REGIONAL_MANIFEST.is_file()
    and LANDMARK_MANIFEST.is_file()
    and all(path.is_file() for path in DEM_WITNESSES)
)

BUILDERS = {
    "campanile": build_campanile_mesh,
    "mount_diablo": build_mount_diablo_mesh,
    "salesforce": build_salesforce_mesh,
    "transamerica": build_transamerica_mesh,
}


def _cross(first, second, third):
    ab = tuple(second[axis] - first[axis] for axis in range(3))
    ac = tuple(third[axis] - first[axis] for axis in range(3))
    return (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )


class ProceduralLandmarkGeometryTests(unittest.TestCase):
    def test_pinned_nominal_controls_and_triangle_budgets(self) -> None:
        meshes = {identifier: builder() for identifier, builder in BUILDERS.items()}
        expected_counts = {
            "campanile": (252, 122),
            "mount_diablo": (212, 94),
            "salesforce": (228, 108),
            "transamerica": (108, 50),
        }
        for spec in LANDMARK_SPECS:
            mesh = meshes[spec.landmark_id]
            self.assertEqual(
                (len(mesh.vertices), len(mesh.triangles)),
                expected_counts[spec.landmark_id],
            )
            self.assertLessEqual(len(mesh.triangles), spec.triangle_budget)
            validate_procedural_mesh(mesh)

        self.assertEqual(
            max(vertex[1] for vertex in meshes["campanile"].vertices),
            93.5736,
        )
        salesforce = meshes["salesforce"]
        self.assertEqual(max(vertex[1] for vertex in salesforce.vertices), 326.136)
        self.assertIn(277.9776, {vertex[1] for vertex in salesforce.vertices})
        self.assertEqual(
            (min(vertex[0] for vertex in salesforce.vertices),
             max(vertex[0] for vertex in salesforce.vertices)),
            (-25.4508, 25.4508),
        )
        transamerica = meshes["transamerica"]
        self.assertEqual(max(vertex[1] for vertex in transamerica.vertices), 260.0)
        self.assertEqual(
            (min(vertex[0] for vertex in transamerica.vertices),
             max(vertex[0] for vertex in transamerica.vertices)),
            (-26.5176, 26.5176),
        )

    def test_transamerica_wings_remain_embedded_through_their_full_height(self) -> None:
        mesh = build_transamerica_mesh()
        wing_selector = LANDMARK_SELECTORS["dark_opening"]
        wing_vertices = {
            mesh.vertices[index]
            for triangle in mesh.triangles if triangle[3] == wing_selector
            for index in triangle[:3]
        }
        self.assertEqual(
            (min(vertex[1] for vertex in wing_vertices),
             max(vertex[1] for vertex in wing_vertices)),
            (70.0, 120.0),
        )
        self.assertEqual(max(abs(vertex[0]) for vertex in wing_vertices), 26.5176)
        inner_edge = min(abs(vertex[0]) for vertex in wing_vertices)
        self.assertEqual(inner_edge, 14.0)
        pyramid_half_at_wing_top = 26.5176 + (2.0 - 26.5176) * (
            (120.0 - 12.0) / (250.0 - 12.0)
        )
        self.assertLess(inner_edge, pyramid_half_at_wing_top)
        inner_faces = []
        downward_caps = []
        for triangle in mesh.triangles:
            if triangle[3] != wing_selector:
                continue
            vertices = [mesh.vertices[index] for index in triangle[:3]]
            normal = _cross(*vertices)
            if len({vertex[0] for vertex in vertices}) == 1 and abs(
                vertices[0][0]
            ) == inner_edge:
                inner_faces.append(vertices)
            if normal[1] < 0.0:
                downward_caps.append(vertices)
        self.assertEqual(len(inner_faces), 4)
        self.assertTrue(
            all(
                {vertex[1] for vertex in vertices} == {70.0, 120.0}
                for vertices in inner_faces
            )
        )
        self.assertEqual(len(downward_caps), 4)
        self.assertTrue(
            all(
                {vertex[1] for vertex in vertices} == {70.0}
                for vertices in downward_caps
            )
        )

    def test_buried_foundation_vertical_faces_wind_outward(self) -> None:
        selector = LANDMARK_SELECTORS["stone_shadow"]
        for builder in BUILDERS.values():
            recognition = builder()
            mesh = add_buried_foundation_skirt(
                recognition, depth_m=9, selector=selector
            )
            self.assertEqual(len(mesh.vertices) - len(recognition.vertices), 16)
            self.assertEqual(len(mesh.triangles) - len(recognition.triangles), 8)
            for triangle in mesh.triangles[-8:]:
                vertices = [mesh.vertices[index] for index in triangle[:3]]
                normal = _cross(*vertices)
                self.assertAlmostEqual(normal[1], 0.0)
                centroid_x = sum(vertex[0] for vertex in vertices) / 3.0
                centroid_z = sum(vertex[2] for vertex in vertices) / 3.0
                self.assertGreater(
                    normal[0] * centroid_x + normal[2] * centroid_z,
                    0.0,
                )

    def test_all_triangles_are_valid_and_exterior_faces_wind_outward(self) -> None:
        for identifier, builder in BUILDERS.items():
            mesh = builder()
            for triangle in mesh.triangles:
                vertices = [mesh.vertices[index] for index in triangle[:3]]
                normal = _cross(*vertices)
                self.assertGreater(sum(value * value for value in normal), 1e-16)
                if abs(normal[0]) < 1e-10 and abs(normal[2]) < 1e-10:
                    is_wing_underside = (
                        identifier == "transamerica"
                        and triangle[3] == LANDMARK_SELECTORS["dark_opening"]
                        and {vertex[1] for vertex in vertices} == {70.0}
                    )
                    if is_wing_underside:
                        self.assertLess(normal[1], 0.0)
                    else:
                        self.assertGreater(normal[1], 0.0)
                # Sloped central silhouettes must face away from their axis;
                # vertical box faces are already fixed by the primitive order.
                if abs(normal[1]) > 1e-10:
                    centroid_x = sum(vertex[0] for vertex in vertices) / 3.0
                    centroid_z = sum(vertex[2] for vertex in vertices) / 3.0
                    radial_dot = normal[0] * centroid_x + normal[2] * centroid_z
                    self.assertGreaterEqual(radial_dot, 0.0)

    def test_native_palette_uvs_round_trip_for_restrained_vocabulary(self) -> None:
        self.assertEqual(len(SOLID_PALETTE), 64)
        self.assertEqual(
            sha256(SOLID_PALETTE).hexdigest(),
            "47f7e1441be49b5e4701d19e2af2c31a5ee056914c03bd8d6249bdb085bb374d",
        )
        self.assertEqual(len(LANDMARK_SELECTORS), 8)
        self.assertEqual(len(set(LANDMARK_SELECTORS.values())), 8)
        for selector in LANDMARK_SELECTORS.values():
            self.assertEqual(resolve_solid_palette_uv(solid_palette_uv(selector)), selector)

    def test_shared_vertical_origin_quantization_preserves_every_winding(self) -> None:
        representative_ground = {
            "campanile": 98.180879,
            "mount_diablo": 1171.894986,
            "salesforce": 4.318805,
            "transamerica": 5.441588,
        }
        for spec in LANDMARK_SPECS:
            tile, frame, witness = build_landmark_tile(
                spec,
                BUILDERS[spec.landmark_id](),
                representative_ground[spec.landmark_id],
            )
            self.assertEqual(tile.meta.layer_kind, LayerKind.LANDMARK)
            self.assertLessEqual(frame.model_half_extent_m, 2_047)
            self.assertEqual(witness["source_degenerate_triangles"], 0)
            self.assertEqual(witness["encoded_degenerate_triangles"], 0)
            self.assertEqual(witness["winding_changes_after_quantization"], 0)
            self.assertLessEqual(
                witness["maximum_decode_error_m"],
                witness["theoretical_decode_error_bound_m"] + 1e-9,
            )

    def test_manifest_controls_are_an_executable_build_gate(self) -> None:
        manifest = json.loads(LANDMARK_MANIFEST.read_text())
        validate_source_controls(manifest)
        changed = json.loads(json.dumps(manifest))
        campanile = next(
            item for item in changed["procedural_landmarks"]
            if item["landmark"] == "Sather Tower / the Campanile"
        )
        campanile["authoritative_height_m"] = 94.0
        with self.assertRaisesRegex(ValueError, "Campanile source controls changed"):
            validate_source_controls(changed)


@unittest.skipUnless(SOURCES_INSTALLED, "pinned regional DEM sources are not installed")
class LandmarkP3DMCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name)
        cls.index = build_landmark_p3dm_corpus(
            cls.output,
            source_root=ROOT,
            regional_manifest_path=REGIONAL_MANIFEST,
            landmark_manifest_path=LANDMARK_MANIFEST,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_corpus_bytes_are_deterministic(self) -> None:
        index_bytes = (self.output / "LANDMARK.json").read_bytes()
        self.assertEqual(
            sha256(index_bytes).hexdigest(),
            "822f3e3eb5b1f4be0dfc44805d362a4e9bfa7ced1e153c32228c1283bae43317",
        )
        self.assertEqual(json.loads(index_bytes), self.index)
        self.assertEqual(
            {
                record["id"]: record["component"]["sha256"]
                for record in self.index["landmarks"]
            },
            {
                "campanile": "7c434d711cfe16d62636c307da9c71142fd3538d28fe2c0e2f4ac27e4ce96864",
                "mount_diablo": "4f00c75dbfe1995122a42f9158c6cdd00d11ece2fce9c87f3fc4c7d1d816edf4",
                "salesforce": "1fb17ee422cbf759322fa2f489eb396bb982fab5c9d8bbeec44c94f2337c3479",
                "transamerica": "c9435dd03cf19e9528488e14752ce76744531e8cca2a8ce224a73c8f5d4df239",
            },
        )

    def test_components_round_trip_with_scene_lit_solid_policy(self) -> None:
        for record in self.index["landmarks"]:
            component = record["component"]
            tile = parse_container((self.output / component["path"]).read_bytes())
            self.assertEqual(tile.meta.layer_kind, LayerKind.LANDMARK)
            self.assertEqual(tile.meta.shading_mode, ShadingMode.SOLID_FLAT)
            self.assertEqual(tile.meta.illumination, IlluminationPolicy.SCENE)
            self.assertEqual(tile.meta.material_set, MaterialSet.NATIVE_SOLID_PALETTE)
            self.assertEqual(
                [resolve_solid_palette_uv(uv) for uv in tile.uvs],
                component["selectors"],
            )
            self.assertTrue(set(component["selectors"]).issubset(LANDMARK_SELECTORS.values()))
            for offset in range(0, len(tile.uv_indices), 3):
                self.assertEqual(len(set(tile.uv_indices[offset : offset + 3])), 1)
            witness = component["normalization_witness"]
            self.assertEqual(witness["encoded_degenerate_triangles"], 0)
            self.assertEqual(witness["winding_changes_after_quantization"], 0)
            self.assertEqual(
                component["object_transform"]["origin_absolute_m"]["elevation"],
                REGIONAL_VERTICAL_ORIGIN_M,
            )

    def test_rendered_contact_provenance_and_activation_radii_are_explicit(self) -> None:
        records = {record["id"]: record for record in self.index["landmarks"]}
        self.assertEqual(
            [tile["id"] for tile in self.index["source"]["ground_dataset"]["sampled_tiles"]],
            ["r01-c02", "r01-c04", "r02-c01", "r02-c02"],
        )
        expected = {
            "campanile": {
                "raw": 98.180879,
                "base": 97.321074,
                "depth": 7,
                "keys": ["N06", "D1", "D2"],
                "ranges": [
                    [96.586236, 98.055913],
                    [96.377623, 97.198263],
                    [91.976395, 92.98478],
                ],
            },
            "mount_diablo": {
                "raw": 1171.894986,
                "base": 1166.177314,
                "depth": 10,
                "keys": ["N02", "D1", "D2"],
                "ranges": [
                    [1160.796093, 1167.582294],
                    [1157.590104, 1166.441954],
                    [1157.934862, 1166.441954],
                ],
            },
            "salesforce": {
                "raw": 4.318805,
                "base": 5.21235,
                "depth": 2,
                "keys": ["N02", "D1", "D2"],
                "ranges": [
                    [4.561231, 5.778779],
                    [4.652821, 5.284699],
                    [4.565052, 5.122215],
                ],
            },
            "transamerica": {
                "raw": 5.441588,
                "base": 5.267444,
                "depth": 3,
                "keys": ["N04", "D1", "D2"],
                "ranges": [
                    [5.009545, 5.520367],
                    [3.82857, 5.247815],
                    [6.054453, 7.83456],
                ],
            },
        }
        for identifier, values in expected.items():
            record = records[identifier]
            drape = record["ground_drape"]
            contact = record["terrain_contact"]
            foundation = record["foundation_skirt"]
            self.assertEqual(drape["raw_dem_elevation_m_navd88"], values["raw"])
            self.assertEqual(drape["elevation_m_navd88"], values["base"])
            self.assertEqual(contact["model_base_elevation_m_navd88"], values["base"])
            self.assertEqual(foundation["depth_m"], values["depth"])
            self.assertEqual(foundation["vertices"], 16)
            self.assertEqual(foundation["triangles"], 8)
            self.assertGreaterEqual(
                contact["minimum_foundation_burial_clearance_m"], 1.0
            )
            foundation_bottom = contact[
                "foundation_bottom_elevation_m_navd88"
            ]
            self.assertEqual(
                record["procedural_local_bounds_m"]["y_agl"][0],
                -values["depth"],
            )
            self.assertEqual(record["recognition_local_bounds_m"]["y_agl"][0], 0.0)
            for label, key, expected_range in zip(
                ("L0", "L1", "L2"),
                values["keys"],
                values["ranges"],
                strict=True,
            ):
                rendered = contact["rendered_lods"][label]
                self.assertEqual(rendered["component_key"], key)
                self.assertEqual(
                    rendered["footprint_elevation_range_m_navd88"],
                    expected_range,
                )
                self.assertGreaterEqual(expected_range[0] - foundation_bottom, 1.0)
                self.assertLessEqual(
                    abs(
                        rendered["anchor_minus_raw_dem_m"]
                        - (
                            rendered["anchor_elevation_m_navd88"]
                            - values["raw"]
                        )
                    ),
                    1.1e-6,
                )
                for recorded_delta, elevation in zip(
                    rendered["footprint_range_minus_l0_model_base_m"],
                    expected_range,
                    strict=True,
                ):
                    self.assertLessEqual(
                        abs(recorded_delta - (elevation - values["base"])),
                        1.1e-6,
                    )
            self.assertEqual(
                contact["rendered_lods"]["L0"]["anchor_elevation_m_navd88"],
                values["base"],
            )
            self.assertEqual(
                contact["rendered_lods"]["L0"]["anchor_minus_l0_model_base_m"],
                0.0,
            )
        self.assertEqual(
            records["mount_diablo"]["summit_control_comparison"][
                "raw_dem_minus_official_m"
            ],
            -1.280214,
        )
        self.assertEqual(
            records["mount_diablo"]["summit_control_comparison"][
                "rendered_l0_minus_official_m"
            ],
            -6.997886,
        )
        self.assertEqual(
            {identifier: record["activation_circle"]["load_radius_m"]
             for identifier, record in records.items()},
            {
                "campanile": 8_000,
                "mount_diablo": 3_000,
                "salesforce": 15_000,
                "transamerica": 15_000,
            },
        )
        for record in records.values():
            self.assertEqual(
                record["activation_circle"]["retain_radius_m"],
                record["activation_circle"]["load_radius_m"] + 512,
            )
            self.assertIn("not survey", record["approximation_status"])
            self.assertTrue(record["approximations"])
            self.assertTrue(record["dimension_sources"])
            self.assertTrue(record["nominal_source_controls"])

    def test_corpus_has_no_bitmap_or_donor_mesh_dependency(self) -> None:
        self.assertIn("no donor mesh", self.index["source"]["geometry"])
        self.assertIn(
            "no image-derived", self.index["solid_selector_palette"]["texture_policy"]
        )
        self.assertEqual(self.index["solid_selector_palette"]["bytes"], 64)
        self.assertEqual(
            self.index["statistics"],
            {
                "landmarks": 4,
                "components": 4,
                "vertices": 864,
                "triangles": 406,
                "container_bytes": 10520,
                "selected_palette_cells": 8,
            },
        )
        self.assertFalse(any(path.suffix.lower() in {".png", ".jpg", ".ac"}
                             for path in self.output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
