from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from pingo_terrain.p3dm import LayerKind, ShadingMode, parse_container


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/p3dm-loader-probe"
MAIN = FIXTURE / "src/p3dm-loader-probe.asm"
LOADER = FIXTURE / "src/p3dm-loader.inc"
TARGET = FIXTURE / "tgt"


class P3DMLoaderFixtureTests(unittest.TestCase):
    def test_runtime_path_is_fixed_and_83_safe(self):
        source = LOADER.read_text(encoding="utf-8")
        self.assertIn('db "TRN/L0/00/0C.AGN",0', source)
        self.assertIn("p3dm_filename_capacity: equ 64", source)
        self.assertIn("p3dm_filename_buffer:", source)
        self.assertIn("p3dm_filename_pointer: dl p3dm_filename_buffer", source)
        for component in "TRN/L0/00/0C.AGN".split("/"):
            stem, dot, suffix = component.partition(".")
            self.assertLessEqual(len(stem), 8)
            if dot:
                self.assertLessEqual(len(suffix), 3)

    def test_probe_container_matches_fixed_terrain_slot(self):
        path = TARGET / "TRN/L0/00/0C.AGN"
        tile = parse_container(path.read_bytes())
        self.assertEqual(tile.stage_buffer_id, 0x7400)
        self.assertEqual(tile.meta.layer_kind, LayerKind.TERRAIN)
        self.assertEqual(tile.meta.shading_mode, ShadingMode.FLAT_PATTERN)
        self.assertEqual((tile.meta.tile_x, tile.meta.tile_y), (4, 1))
        report = json.loads((TARGET / "probe.json").read_text())
        self.assertEqual(report["container_bytes"], path.stat().st_size)
        self.assertEqual(report["vertices"], len(tile.positions))
        self.assertEqual(report["triangles"], len(tile.position_indices) // 3)

    def test_read_close_validate_publish_order_is_fail_closed(self):
        source = LOADER.read_text(encoding="utf-8")
        top = source.split("p3dm_load_component:", 1)[1].split(
            "; Open/read/close", 1
        )[0]
        sequence = [
            "call p3dm_read_container",
            "call p3dm_validate_container",
            "call p3dm_upload_data",
            "call pingo_replace_mesh_from_buffer",
        ]
        offsets = [top.index(item) for item in sequence]
        self.assertEqual(offsets, sorted(offsets))
        self.assertGreaterEqual(top.count("ret nz"), 3)
        reader = source.split("p3dm_read_container:", 1)[1].split(
            "p3dm_bad_open:", 1
        )[0]
        self.assertIn("FFSCALL ffs_fopen", reader)
        self.assertIn("FFSCALL ffs_fclose", reader)

    def test_loader_checks_structure_policy_crc_and_indices(self):
        source = LOADER.read_text(encoding="utf-8")
        for required in (
            "p3dm_validate_padding",
            "p3dm_validate_position_indices",
            "p3dm_validate_uv_indices",
            "p3dm_validate_crc32",
            "6V+2I+4U+2T",
            "p3dm_bad_policy",
            "p3dm_bad_bounds",
            "p3dm_bad_counts",
            "p3dm_bad_crc32",
            "p3dm_bad_indices",
        ):
            self.assertIn(required, source)
        self.assertIn("xor 0EDh", source)
        self.assertIn("xor 0B8h", source)
        self.assertIn("xor 083h", source)
        self.assertIn("xor 020h", source)

    def test_publication_helpers_encode_commands_50_and_51(self):
        source = LOADER.read_text(encoding="utf-8")
        cmd50 = source.split("pingo_replace_mesh_from_buffer:", 1)[1].split(
            "; Pingo subcommand 51", 1
        )[0]
        cmd51 = source.split("pingo_set_object_active:", 1)[1].split(
            "p3dm_bad_structure:", 1
        )[0]
        self.assertRegex(cmd50, r"db\s+049h,50")
        self.assertRegex(cmd51, r"db\s+049h,51")
        self.assertIn("dw p3dm_stage_buffer_id", cmd50)
        self.assertIn("ld a,(p3dm_target_mesh_id)", cmd50)
        self.assertIn("ld (@mesh_id),a", cmd50)
        self.assertRegex(cmd50, r"@mesh_id:\s+dw 0")

    def test_request_policy_is_caller_selected(self):
        source = LOADER.read_text(encoding="utf-8")
        for field in (
            "p3dm_target_mesh_id",
            "p3dm_expected_layer",
            "p3dm_expected_lod",
            "p3dm_expected_shading",
            "p3dm_expected_illumination",
            "p3dm_expected_material_set",
            "p3dm_expected_tile_x",
            "p3dm_expected_tile_y",
        ):
            self.assertIn(field, source)
        policy = source.split("; Layout 1", 1)[1].split(
            "; Signed minimum elevation", 1
        )[0]
        for field in (
            "p3dm_expected_layer",
            "p3dm_expected_lod",
            "p3dm_expected_shading",
            "p3dm_expected_illumination",
            "p3dm_expected_material_set",
            "p3dm_expected_tile_x",
            "p3dm_expected_tile_y",
        ):
            self.assertIn(field, policy)

    def test_validated_descriptor_results_are_retained_exact_width(self):
        source = LOADER.read_text(encoding="utf-8")
        retain = source.split("p3dm_retain_descriptor:", 1)[1].split(
            "p3dm_validate_padding:", 1
        )[0]
        for field in (
            "p3dm_tile_x",
            "p3dm_tile_y",
            "p3dm_center_east_m",
            "p3dm_center_north_m",
            "p3dm_minimum_elevation_dm",
            "p3dm_maximum_elevation_dm",
            "p3dm_model_half_extent_m",
        ):
            self.assertIn(field, retain)
        self.assertIn("ld de,2048", source)
        self.assertIn("jp nc,p3dm_bad_policy", source)

    def test_complete_file_window_admits_dense_airport_markings(self):
        source = LOADER.read_text(encoding="utf-8")
        self.assertIn("p3dm_max_file_bytes: equ 16384", source)

    def test_only_data_payload_is_selected_for_vdp_upload(self):
        source = LOADER.read_text(encoding="utf-8")
        upload = source.split("p3dm_upload_data:", 1)[1].split(
            "; Pingo subcommand 50", 1
        )[0]
        self.assertIn("ld hl,p3dm_file_buffer+p3dm_data_offset", upload)
        self.assertNotIn("ld hl,p3dm_file_buffer\n", upload)

    def test_main_binds_stable_slot_before_disk_load_and_activates_after(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertLess(
            source.index("CO sid,probe_object_id"),
            source.index("call p3dm_load_component"),
        )
        self.assertLess(
            source.index("call p3dm_load_component"),
            source.rindex("call pingo_set_object_active"),
        )
        self.assertIn("call apply_probe_descriptor_transform", source)

    def test_fixture_coordinator_derives_transform_from_validated_result(self):
        source = MAIN.read_text(encoding="utf-8")
        transform = source.split("apply_probe_descriptor_transform:", 1)[1].split(
            "; A -> two uppercase", 1
        )[0]
        self.assertIn("p3dm_center_east_m", transform)
        self.assertIn("p3dm_center_north_m", transform)
        self.assertIn("P3DM_LD_U16_HL p3dm_model_half_extent_m", transform)
        self.assertGreaterEqual(transform.count("add hl,hl"), 13)
        self.assertRegex(transform, r"db\s+49h,9")
        self.assertRegex(transform, r"db\s+49h,17")

    def test_main_initializes_generic_request_before_loading(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertLess(
            source.index("call initialize_p3dm_request"),
            source.index("call p3dm_load_component"),
        )
        initializer = source.split("initialize_p3dm_request:", 1)[1].split(
            "; A -> two uppercase", 1
        )[0]
        for field in (
            "p3dm_filename_pointer",
            "p3dm_target_mesh_id",
            "p3dm_expected_layer",
            "p3dm_expected_lod",
            "p3dm_expected_shading",
            "p3dm_expected_illumination",
            "p3dm_expected_material_set",
            "p3dm_expected_tile_x",
            "p3dm_expected_tile_y",
        ):
            self.assertIn(field, initializer)

    def test_no_direct_wide_store_targets_normalized_u16_state(self):
        source = LOADER.read_text(encoding="utf-8")
        fields = "|".join(
            re.escape(name)
            for name in (
                "p3dm_file_size",
                "p3dm_data_size",
                "p3dm_vertex_count",
                "p3dm_position_index_count",
                "p3dm_uv_count",
                "p3dm_uv_index_count",
            )
        )
        self.assertNotRegex(
            source,
            rf"ld\s+\((?:{fields})\),\s*(?:bc|de|hl|ix|iy)",
        )


if __name__ == "__main__":
    unittest.main()
