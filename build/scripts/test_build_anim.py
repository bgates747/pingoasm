#!/usr/bin/env python3
"""Regression tests for the rigid Lara animation application."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import tempfile
import unittest
from pathlib import Path

import build_anim as anim


MAIN_SOURCE = anim.SOURCE_DIR / anim.ASSEMBLY_FILENAME
NOVEL_SOURCE = anim.SOURCE_DIR / "lara-animation.inc"
MESH_SOURCE = anim.SOURCE_DIR / anim.MESH_INCLUDE
POSE_SOURCE = anim.SOURCE_DIR / anim.POSE_INCLUDE


def executable_source(source: str) -> str:
    return "\n".join(line.split(";", 1)[0] for line in source.splitlines())


def global_block(source: str, label: str) -> str:
    """Return one global assembly routine, including all of its local labels."""

    match = re.search(
        rf"(?ms)^{re.escape(label)}:\s*\n.*?"
        rf"(?=^[A-Za-z_][A-Za-z0-9_]*:\s*$|\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"assembly label not found: {label}")
    return match.group(0)


def pose_records(source: str) -> list[tuple[int, ...]]:
    table = source.split("lara_pose_samples:\n", 1)[1]
    records = []
    for line in table.splitlines():
        code = line.split(";", 1)[0].strip()
        if code:
            records.append(tuple(int(value) for value in code[3:].split(",")))
    return records


def rotate_pingo_vector(
    vector: tuple[float, float, float],
    angle_words: tuple[int, ...],
) -> tuple[float, float, float]:
    """Apply Pingo's qualified Rz * Ry * Rx Euler construction."""

    x, y, z = vector
    rx, ry, rz = (
        value * (2.0 * math.pi) / 32767.0 for value in angle_words
    )
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return x, y, z


class AnimProfileTests(unittest.TestCase):
    def test_profile_names_the_canonical_animation_sources(self) -> None:
        profile = anim.load_profile()
        self.assertEqual(
            profile["source_blend"],
            "blender/anim/bandai_namco/run_normal_001/output/"
            "lara_running_normal_001.blend",
        )
        self.assertEqual(
            profile["source_texture"],
            "blender/anim/bandai_namco/run_normal_001/source/Lara.png",
        )
        self.assertEqual(
            profile["rest_blend"],
            "blender/anim/bandai_namco/run_normal_001/output/lara_rest.blend",
        )
        self.assertEqual(profile["scene"], "RUNNING_NORMAL_001")
        self.assertEqual(profile["rest_scene"], "REST_POSE")
        self.assertEqual(profile["qualified_blender_version"], "4.0.2")
        self.assertEqual(profile["frames"], [1, 23])
        self.assertEqual(profile["loop_successor_frame"], 24)
        self.assertEqual(profile["source_rate_hz"], 30)
        self.assertEqual(profile["object_scale"], 1280)
        self.assertEqual(profile["camera_offset"], [0, 0, 3200])
        self.assertEqual(profile["default_root_mode"], "controlled")
        self.assertTrue(profile["preserves_root_motion"])
        self.assertTrue(profile["loopable"])

        for key in anim.QUALIFIED_SOURCE_KEYS:
            source = anim.project_path(profile[key])
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                profile["source_sha256"][key],
            )

    def test_profile_has_stable_tracks_and_distinct_global_ids(self) -> None:
        profile = anim.load_profile()
        tracks = profile["tracks"]
        self.assertEqual(len(tracks), 15)
        expected = [
            ("pelvis_bundle", ["pelvis", "holster.l", "holster.r"], "pelvis"),
            ("torso", ["torso"], "torso"),
            ("head", ["head"], "head"),
            ("arm_l", ["arm.l"], "arm.l"),
            ("forearm_l", ["forearm.l"], "forearm.l"),
            ("hand_l", ["hand.l"], "hand.l"),
            ("arm_r", ["arm.r"], "arm.r"),
            ("forearm_r", ["forearm.r"], "forearm.r"),
            ("hand_r", ["hand.r"], "hand.r"),
            ("thigh_l", ["thigh.l"], "thigh.l"),
            ("leg_l", ["leg.l"], "leg.l"),
            ("foot_l", ["foot.l"], "foot.l"),
            ("thigh_r", ["thigh.r"], "thigh.r"),
            ("leg_r", ["leg.r"], "leg.r"),
            ("foot_r", ["foot.r"], "foot.r"),
        ]
        self.assertEqual(
            [(track["name"], track["sources"], track["driver"]) for track in tracks],
            expected,
        )
        sources = [source for track in tracks for source in track["sources"]]
        self.assertEqual(len(sources), 17)
        self.assertEqual(len(sources), len(set(sources)))
        semantic = profile["semantic_meshes"]
        self.assertEqual([item["name"] for item in semantic], sources)
        self.assertEqual(sum(item["vertices"] for item in semantic), 300)
        self.assertEqual(sum(item["triangles"] for item in semantic), 526)
        global_ids = {
            profile["control_id"],
            profile["texture_bitmap_id"],
            profile["target_bitmap_id"],
        }
        self.assertEqual(len(global_ids), 3)


class GeneratedAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = json.loads(anim.METADATA_PATH.read_text(encoding="utf-8"))
        cls.mesh_source = MESH_SOURCE.read_text(encoding="utf-8")
        cls.pose_source = POSE_SOURCE.read_text(encoding="utf-8")

    def test_inventory_and_pose_contract_are_exact(self) -> None:
        contract = self.metadata["contract"]
        geometry = self.metadata["geometry"]
        self.assertEqual(contract["frame_count"], 23)
        self.assertEqual(contract["track_count"], 15)
        self.assertEqual(contract["pose_record_bytes"], 12)
        self.assertEqual(contract["pose_table_bytes"], 4_140)
        self.assertEqual(contract["loop_successor_frame"], 24)
        self.assertEqual(contract["loop_closure_start"], 15)
        self.assertEqual(contract["loop_closure_order"], "discrete C1")
        self.assertEqual(contract["loop_forward_step_command_units"], 77)
        self.assertEqual(contract["cycle_forward_command_units"], 2_131)
        self.assertEqual(contract["nominal_forward_step_command_units"], 93)
        self.assertTrue(contract["preserves_root_motion"])
        self.assertTrue(contract["loopable"])
        self.assertEqual(geometry["semantic_parts"], 17)
        self.assertEqual(geometry["runtime_meshes"], 15)
        self.assertEqual(geometry["positions"], 300)
        self.assertEqual(geometry["triangles"], 526)

    def test_transitive_provenance_and_semantic_meshes_are_pinned(self) -> None:
        profile = anim.load_profile()
        source = self.metadata["source"]
        self.assertEqual(source["blender_version"], profile["qualified_blender_version"])
        self.assertEqual(
            source["profile"]["sha256"],
            hashlib.sha256(anim.PROFILE_PATH.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            source["exporter_sha256"],
            hashlib.sha256(anim.EXPORTER.read_bytes()).hexdigest(),
        )
        for key in anim.QUALIFIED_SOURCE_KEYS:
            self.assertEqual(
                source["inputs"][key],
                {"path": profile[key], "sha256": profile["source_sha256"][key]},
            )

        expected = {item["name"]: item for item in profile["semantic_meshes"]}
        actual = [
            item
            for track in self.metadata["geometry"]["tracks"]
            for item in track["source_counts"]
        ]
        self.assertEqual(len(actual), 17)
        for item in actual:
            semantic = expected[item["name"]]
            self.assertEqual(item["positions"], semantic["vertices"])
            self.assertEqual(item["triangles"], semantic["triangles"])
            self.assertEqual(item["driver"], semantic["driver"])
            self.assertEqual(
                item["rest_geometry_sha256"], semantic["geometry_sha256"]
            )
            self.assertEqual(
                item["run_geometry_sha256"], semantic["geometry_sha256"]
            )

    def test_generated_hashes_and_banners_match(self) -> None:
        profile = anim.load_profile()
        for filename, path in (
            (anim.MESH_INCLUDE, MESH_SOURCE),
            (anim.POSE_INCLUDE, POSE_SOURCE),
        ):
            with self.subTest(filename=filename):
                source = path.read_text(encoding="utf-8")
                self.assertIn("AUTO-GENERATED FILE - DO NOT EDIT", source)
                self.assertIn(
                    "Generated from: blender/anim/bandai_namco/"
                    "run_normal_001/output/lara_running_normal_001.blend",
                    source,
                )
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    self.metadata["outputs"][filename],
                )
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    profile["qualified_output_sha256"][filename],
                )

    def test_pose_table_contains_exactly_345_six_word_records(self) -> None:
        records = pose_records(self.pose_source)
        for record in records:
            self.assertEqual(len(record), 6)
            self.assertTrue(all(-32768 <= value <= 32767 for value in record))
        self.assertEqual(len(records), 23 * 15)
        self.assertEqual(len(records) * 12, 4_140)

    def test_loop_keeps_the_preclosure_opening_byte_identical(self) -> None:
        records = pose_records(self.pose_source)[: 15 * 15]
        payload = b"".join(struct.pack("<6h", *record) for record in records)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "403b2a9f892d4301ae9e6117d6bfc0632d1a91dfd69a420a2a3b5ac9d79ef83c",
        )

    def test_pelvis_root_motion_has_the_qualified_forward_deltas(self) -> None:
        pelvis = pose_records(POSE_SOURCE.read_text(encoding="utf-8"))[::15]
        self.assertEqual(pelvis[0][:3], (0, 0, 0))
        self.assertEqual(pelvis[-1][:3], (1, -17, 2054))
        deltas = [right[2] - left[2] for left, right in zip(pelvis, pelvis[1:])]
        self.assertEqual(len(deltas), 22)
        self.assertTrue(all(delta > 0 for delta in deltas))
        self.assertEqual(sum(deltas), 2054)
        self.assertEqual((min(deltas), max(deltas)), (74, 118))
        self.assertEqual(sum(deltas) + 77, 2131)
        self.assertEqual(round(2131 / 23), 93)

    def test_pelvis_and_boot_motion_bases_face_their_anatomical_directions(self) -> None:
        records = pose_records(self.pose_source)

        # Lara's local anatomical +Y front becomes local -Z in Pingo. The
        # corrected pelvis must carry that front along the capture's +Z run.
        pelvis_front_z = [
            rotate_pingo_vector((0.0, 0.0, -1.0), records[frame * 15][3:])[2]
            for frame in range(23)
        ]
        self.assertGreater(min(pelvis_front_z), 0.9)
        self.assertGreater(sum(pelvis_front_z) / len(pelvis_front_z), 0.92)

        # Both lace rectangles have this outward local normal after the
        # qualified Blender-to-Pingo basis conversion. At each foot's ten
        # lowest/contact frames it must retain a positive world-up component.
        lace_normal = (0.0, 0.759, -0.651)
        contact_frames = {
            11: (1, 21, 22, 23),         # foot_l
            14: (10, 11, 12, 13, 14),    # foot_r
        }
        for track, frames in contact_frames.items():
            with self.subTest(track=track):
                lace_up = [
                    rotate_pingo_vector(
                        lace_normal,
                        records[(frame - 1) * 15 + track][3:],
                    )[1]
                    for frame in frames
                ]
                self.assertGreater(min(lace_up), 0.45)

    def test_mesh_counts_and_index_contract_match_metadata(self) -> None:
        vertex_counts = [
            int(value)
            for value in re.findall(
                r"(?m)^lara_[a-z0-9_]+_vertices_n:\s*equ\s+(\d+)\s*$",
                self.mesh_source,
            )
        ]
        index_counts = [
            int(value)
            for value in re.findall(
                r"(?m)^lara_[a-z0-9_]+_indices_n:\s*equ\s+(\d+)\s*$",
                self.mesh_source,
            )
        ]
        self.assertEqual(len(vertex_counts), 15)
        self.assertEqual(len(index_counts), 15)
        self.assertEqual(sum(vertex_counts), 300)
        self.assertEqual(sum(index_counts), 526 * 3)
        self.assertTrue(all(value % 3 == 0 for value in index_counts))

    def test_export_validation_metrics_remain_inside_gates(self) -> None:
        validation = self.metadata["validation"]
        self.assertEqual(validation["pelvis_holster_matrix_error_max"], 0.0)
        self.assertLess(validation["scale_deviation_max"], 5.0e-5)
        self.assertLess(validation["decomposition_coefficient_error_max"], 5.0e-5)
        self.assertLess(validation["quantized_rotation_coefficient_error_max"], 0.001)
        self.assertLess(validation["quantized_transformed_vertex_error_max"], 0.01)
        self.assertLess(max(validation["adjacent_euler_step_degrees_max"]), 45.0)
        self.assertGreater(validation["root_delta_command_units"][2], 15.0)
        self.assertLessEqual(validation["loop_endpoint_translation_word_error_max"], 1.0)
        self.assertLessEqual(validation["loop_endpoint_rotation_degrees_max"], 0.01)
        self.assertLessEqual(validation["loop_velocity_translation_word_error_max"], 24.0)
        self.assertLessEqual(validation["loop_velocity_rotation_degrees_max"], 2.0)


class AssemblyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = MAIN_SOURCE.read_text(encoding="utf-8")
        cls.novel = NOVEL_SOURCE.read_text(encoding="utf-8")
        cls.code = executable_source(cls.main + "\n" + cls.novel)

    def test_source_is_self_contained_and_novel_code_is_isolated(self) -> None:
        includes = re.findall(r'(?im)^\s*include\s+"([^"]+)"', self.main)
        self.assertTrue(includes)
        for include in includes:
            with self.subTest(include=include):
                self.assertNotIn("..", Path(include).parts)
                self.assertTrue((anim.SOURCE_DIR / include).is_file())
        self.assertIn("Novel apps/anim assembly", self.novel)
        self.assertNotIn("p3d_object_step16", self.code)

    def test_uses_existing_absolute_pose_and_async_contract(self) -> None:
        self.assertIn("call p3d_object_init16", self.code)
        self.assertIn("call p3d_object_sync16", self.code)
        self.assertIn("or p3d_object_dirty_pose", self.code)
        self.assertRegex(
            self.code,
            r"(?s)call lara_sync_scene\s+call submit_current_render",
        )
        self.assertRegex(
            self.code,
            r"(?s)call wait_for_setup_barrier.*?call install_render_callback"
            r".*?call enable_render_notifications.*?call submit_current_render",
        )
        self.assertRegex(
            self.code,
            r"(?s)call waitKeypress\s+call lara_wait_for_keys_released",
        )
        self.assertRegex(
            self.code,
            r"(?s)lara_restart:.*?ld \(simulation_accumulator\),hl"
            r".*?ld \(lara_restart_pending\),a",
        )
        self.assertRegex(
            self.code,
            r"(?s)lara_animation_step:.*?ld a,\(lara_restart_pending\)"
            r"\s+or a\s+jr nz,@track_camera",
        )
        self.assertRegex(
            self.code,
            r"(?s)call nz,consume_render_completion\s+ld a,\(render_in_flight\)"
            r"\s+or a\s+jr nz,mainloop.*?call lara_scene_dirty\s+or a"
            r"\s+jr z,mainloop\s+call lara_sync_scene"
            r"\s+call submit_current_render",
        )
        sync = global_block(self.code, "lara_sync_scene")
        self.assertLess(sync.index("call lara_sync_objects"), sync.index("call lara_sync_view"))
        self.assertEqual(
            len(re.findall(r"call submit_current_render\s+call lara_render_submitted", self.code)),
            2,
        )

    def test_uses_scene_yaw_translation_and_no_retired_command_42(self) -> None:
        self.assertRegex(
            self.code,
            r"(?s)lara_set_scene_rotation_y:.*?db\s+49h\s*,\s*33",
        )
        self.assertRegex(
            self.code,
            r"(?s)lara_set_scene_translation:.*?db\s+49h\s*,\s*37",
        )
        self.assertNotRegex(self.code, r"(?i)db\s+(?:\$|0x)?49h?\s*,\s*42\b")
        render_source = (anim.SOURCE_DIR / "render-async.inc").read_text(
            encoding="utf-8"
        )
        profile = anim.load_profile()
        self.assertIn(
            f"render_notify_token: equ 0{profile['render_notification_token']:04X}h",
            render_source,
        )

    def test_configures_camera_side_light_with_clockwise_offset(self) -> None:
        self.assertIn("lara_light_direction_x: equ 8481", self.novel)
        self.assertIn("lara_light_direction_y: equ 0", self.novel)
        self.assertIn("lara_light_direction_z: equ 31650", self.novel)
        self.assertRegex(
            self.code,
            r"(?s)lara_animation_initialize:.*?call lara_configure_lighting"
            r".*?lara_configure_lighting:\s+ld bc,lara_light_direction_x"
            r"\s+ld de,lara_light_direction_y"
            r"\s+ld iy,lara_light_direction_z"
            r"\s+jp pingo_set_light_direction",
        )

    def test_playback_uses_real_deltas_and_a_safe_forward_seam(self) -> None:
        self.assertRegex(
            self.code,
            r"(?s)lara_advance_pose:.*?inc a\s+cp lara_pose_frame_count"
            r"\s+jr c,@advance\s+ld hl,lara_loop_forward_step"
            r".*?xor a\s+ld hl,lara_pose_samples\s+jr @install"
            r".*?@advance:.*?sbc\.s hl,de"
            r".*?LARA_STORE_HL16 lara_motion_step"
            r".*?@install:\s+ld \(lara_current_frame\),a"
            r"\s+ld \(lara_pose_pointer\),hl\s+jp lara_apply_current_pose",
        )

    def test_wolf_keyboard_matrix_and_no_reverse_binding(self) -> None:
        step = global_block(self.code, "lara_animation_step")
        turn = global_block(self.code, "lara_apply_turn_controls")
        movement = global_block(self.code, "lara_apply_locomotion_controls")

        self.assertIn("bit 1,(ix+4)", movement)   # W
        self.assertIn("bit 1,(ix+8)", movement)   # A
        self.assertIn("bit 2,(ix+6)", movement)   # D
        self.assertNotIn("bit 1,(ix+10)", movement)  # S
        self.assertIn("bit 1,(ix+3)", turn)       # Left
        self.assertIn("bit 1,(ix+15)", turn)      # Right
        self.assertRegex(
            turn,
            r"(?s)bit 1,\(ix\+3\).*?bit 1,\(ix\+15\)\s+ret nz",
        )
        self.assertRegex(
            movement,
            r"(?s)bit 1,\(ix\+8\).*?bit 2,\(ix\+6\)\s+jr nz,@ready",
        )
        self.assertRegex(
            turn,
            r"(?s)bit 1,\(ix\+3\).*?LARA_LOAD_HL16 lara_scene_heading"
            r"\s+ld de,lara_turn_step.*?@right_only:.*?"
            r"LARA_LOAD_HL16 lara_scene_heading\s+ld de,-lara_turn_step",
        )
        self.assertLess(step.index("call lara_apply_turn_controls"), step.index("call nz,lara_advance_pose"))
        self.assertLess(step.index("call nz,lara_advance_pose"), step.index("call lara_apply_locomotion_controls"))
        self.assertNotIn("keyboard_masks", global_block(self.code, "lara_advance_pose"))

    def test_pause_and_reset_are_edge_triggered_clip_controls(self) -> None:
        controls = global_block(self.code, "lara_handle_edge_controls")
        restart = global_block(self.code, "lara_restart")
        self.assertIn("bit 3,(ix+6)", controls)  # R
        self.assertIn("bit 7,(ix+6)", controls)  # P
        self.assertIn("set 0,b", controls)
        self.assertIn("res 0,b", controls)
        self.assertIn("set 1,b", controls)
        self.assertIn("res 1,b", controls)
        self.assertRegex(controls, r"ld a,\(lara_playing\)\s+xor 1")
        self.assertNotIn("bit 2,(ix+12)", self.novel)  # retired Space binding
        self.assertNotIn("bit 5,(ix+12)", self.novel)  # retired M binding
        for retained_state in (
            "lara_world_position",
            "lara_scene_heading",
            "lara_camera_height",
        ):
            self.assertNotIn(retained_state, restart)
        self.assertRegex(
            restart,
            r"(?s)xor a\s+ld \(lara_current_frame\),a.*?"
            r"ld hl,lara_pose_samples\s+ld \(lara_pose_pointer\),hl",
        )
        self.assertRegex(restart, r"xor a\s+ld \(lara_playing\),a")

    def test_page_keys_drive_only_the_retained_camera_height(self) -> None:
        controls = global_block(self.code, "lara_apply_camera_height_controls")
        position = global_block(self.code, "lara_build_look_at_camera_position")
        camera_sync = global_block(self.code, "lara_sync_camera_state")
        self.assertIn("bit 7,(ix+7)", controls)
        self.assertIn("bit 6,(ix+9)", controls)
        self.assertRegex(
            controls,
            r"(?s)bit 7,\(ix\+7\).*?bit 6,\(ix\+9\)\s+ret nz",
        )
        self.assertIn("call lara_camera_height_up", controls)
        self.assertIn("call lara_camera_height_down", controls)
        self.assertIn("LARA_LOAD_HL16 lara_camera_height", position)
        self.assertIn("ld de,lara_camera_offset_y", position)
        self.assertNotIn("lara_world_position", position)
        self.assertNotIn("p3d_vec3_rotate_y16", position)
        self.assertIn("call p3d_camera_init16", self.code)
        self.assertIn("call p3d_camera_aim_at_point16", self.code)
        self.assertIn("ld a,p3d_camera_roll_upright", self.code)
        self.assertIn("call scdabs", camera_sync)
        self.assertIn("call scrabs", camera_sync)
        self.assertEqual(self.novel.count("call scdabs"), 1)
        self.assertEqual(self.novel.count("call scrabs"), 1)
        self.assertNotIn("rst.lil", global_block(self.code, "lara_update_camera_tracking"))
        self.assertRegex(self.code, r"lara_camera_state:\s+ds p3d_camera_size")

    def test_runtime_removes_only_progressive_root_z(self) -> None:
        apply_pose = global_block(self.code, "lara_apply_current_pose")
        self.assertIn("LARA_STORE_HL16 lara_pose_root_z", apply_pose)
        self.assertRegex(
            apply_pose,
            r"(?s)p3d_object_pingo_translation\+p3d_vec3_z.*?"
            r"LARA_LOAD_DE16 lara_pose_root_z\s+or a\s+sbc\.s hl,de.*?"
            r"p3d_object_pingo_translation\+p3d_vec3_z",
        )
        self.assertNotRegex(apply_pose, r"sbc\.s.*p3d_vec3_[xy]")

        pelvis = pose_records(POSE_SOURCE.read_text(encoding="utf-8"))[::15]
        final_frame = pelvis[-1]
        self.assertEqual(
            (final_frame[0], final_frame[1], final_frame[2] - final_frame[2]),
            (1, -17, 0),
        )
        controller_z = sum(
            right[2] - left[2] for left, right in zip(pelvis, pelvis[1:])
        )
        self.assertEqual(controller_z, pelvis[-1][2])
        controller_z += 77
        self.assertEqual(controller_z, 2131)

    def test_fixture_rebases_controller_and_camera_together(self) -> None:
        rebase = global_block(self.code, "lara_rebase_world_if_needed")
        camera_position = global_block(self.code, "lara_build_chase_camera_position")
        self.assertIn("lara_world_recenter_limit:  equ 24000", self.novel)
        self.assertIn("lara_camera_offset_z", camera_position)
        self.assertLess(24_000 + 3_200, 32_768)
        self.assertRegex(
            rebase,
            r"ld a,\(lara_camera_mode\)\s+cp lara_camera_mode_chase\s+ret nz",
        )
        self.assertIn("LARA_STORE_HL16 lara_world_position+p3d_vec3_x", rebase)
        self.assertIn("LARA_STORE_HL16 lara_world_position+p3d_vec3_z", rebase)
        for retained_state in (
            "lara_current_frame",
            "lara_scene_heading",
            "lara_camera_height",
            "lara_playing",
        ):
            self.assertNotIn(retained_state, rebase)

    def test_default_is_fixed_look_at_and_chase_code_is_retained(self) -> None:
        dispatcher = global_block(self.code, "lara_build_camera_position")
        look_at = global_block(self.code, "lara_build_look_at_camera_position")
        chase = global_block(self.code, "lara_build_chase_camera_position")
        target = global_block(self.code, "lara_build_camera_target")
        self.assertRegex(
            self.code,
            r"lara_camera_mode:\s+db lara_camera_mode_look_at",
        )
        self.assertIn("cp lara_camera_mode_chase", dispatcher)
        self.assertIn("jp z,lara_build_chase_camera_position", dispatcher)
        self.assertIn("jp lara_build_look_at_camera_position", dispatcher)
        self.assertNotIn("lara_world_position", look_at)
        self.assertIn("lara_world_position+p3d_vec3_x", chase)
        self.assertIn("lara_world_position+p3d_vec3_z", chase)
        self.assertIn("ld iy,lara_world_position", target)

    def test_exit_releases_control_and_global_buffers_behind_barrier(self) -> None:
        self.assertRegex(
            self.code,
            r"(?s)main_end:\s+call disable_render_notifications\s+"
            r"call lara_release_resources\s+call wait_for_setup_barrier\s+"
            r"call remove_render_callback",
        )
        self.assertRegex(
            self.code,
            r"(?s)lara_release_resources:.*?dw sid\s+db 49h\s*,\s*39"
            r".*?dw tgtbmid\s+db 2"
            r".*?dw lara_texture_bmid\s+db 2",
        )

    def test_target_payload_and_staging_window_are_exact(self) -> None:
        target_files = {path.name for path in anim.TARGET_DIR.iterdir() if path.is_file()}
        self.assertEqual(target_files, {"anim.bin", "Lara.rgba2"})
        executable = anim.TARGET_DIR / "anim.bin"
        texture = anim.TARGET_DIR / "Lara.rgba2"
        self.assertLess(
            executable.stat().st_size + texture.stat().st_size,
            anim.EZ80_APPLICATION_WINDOW,
        )
        self.assertEqual(texture.stat().st_size, 256 * 184)
        build_outputs = json.loads(anim.METADATA_PATH.read_text(encoding="utf-8"))[
            "build"
        ]["outputs"]
        for path in (executable, texture):
            self.assertEqual(build_outputs[path.name]["bytes"], path.stat().st_size)
            self.assertEqual(
                build_outputs[path.name]["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )

    def test_metadata_hashes_every_assembly_input(self) -> None:
        metadata = json.loads(anim.METADATA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            metadata["build"]["builder_sha256"],
            hashlib.sha256(Path(anim.__file__).resolve().read_bytes()).hexdigest(),
        )
        self.assertEqual(metadata["build"]["assembler"], anim.assembler_identity())
        recorded = metadata["build"]["assembly_inputs"]
        expected_paths = sorted(
            path for path in anim.SOURCE_DIR.rglob("*") if path.is_file()
        )
        self.assertEqual(
            sorted(recorded),
            [path.relative_to(anim.SOURCE_DIR).as_posix() for path in expected_paths],
        )
        for path in expected_paths:
            relative = path.relative_to(anim.SOURCE_DIR).as_posix()
            self.assertEqual(recorded[relative]["bytes"], path.stat().st_size)
            self.assertEqual(
                recorded[relative]["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )

    def test_staging_window_guard_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "anim.bin"
            texture = root / "Lara.rgba2"
            executable.write_bytes(b"x" * (anim.EZ80_APPLICATION_WINDOW - 9))
            texture.write_bytes(b"x" * 9)
            with self.assertRaisesRegex(ValueError, "application window"):
                anim.validate_staging_window(executable, texture)


if __name__ == "__main__":
    unittest.main()
