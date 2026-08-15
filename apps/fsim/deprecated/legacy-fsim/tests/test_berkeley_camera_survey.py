from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/berkeley-flight-triangular-dither"
MAIN = FIXTURE / "src/berkeley-camera-survey.asm"
CONTROL = FIXTURE / "src/camera-survey-input.inc"
BASE = FIXTURE / "src/berkeley-flight-triangular-dither.asm"
BINARY = FIXTURE / "tgt/berkeley-camera-survey.bin"
BUILDER = ROOT / "scripts/build_berkeley_camera_survey.py"


def normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


class BerkeleyCameraSurveyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = MAIN.read_text(encoding="utf-8")
        self.control = CONTROL.read_text(encoding="utf-8")
        self.normalized_main = normalized(MAIN)
        self.normalized_control = normalized(CONTROL)

    def test_scene_and_initial_pose_are_the_exact_fixture_three_control(self) -> None:
        for definition in (
            r"sid\s*:\s*equ\s+1731",
            r"viewport_width\s*:\s*equ\s+320",
            r"viewport_height\s*:\s*equ\s+240",
            r"camera_initial_x\s*:\s*equ\s+0",
            r"camera_initial_y\s*:\s*equ\s+-1144",
            r"camera_initial_z\s*:\s*equ\s+16384",
            r"simulation_step_ticks\s*:\s*equ\s+4",
        ):
            self.assertRegex(self.normalized_main, definition)
        self.assertRegex(
            self.normalized_main,
            r"ld bc\s*,\s*0 ld de\s*,\s*16384 ld iy\s*,\s*-28377 "
            r"call pingo_set_light_direction",
        )
        self.assertRegex(
            self.normalized_main,
            r"ld a\s*,\s*95 call pingo_set_ambient_light",
        )
        self.assertIn('include "terrain-scene.inc"', self.normalized_main)
        self.assertIn('db "terrain-patterns.rgba2",0', self.normalized_main)
        self.assertIn('db "terrain-pattern-lookup.bin",0', self.normalized_main)
        self.assertIn('db "terrain-material-ids.rgba2",0', self.normalized_main)

    def test_fixture_is_camera_only_and_keeps_the_shared_async_loop(self) -> None:
        self.assertNotIn('include "flight-input.inc"', self.normalized_main)
        self.assertNotIn("object_state:", self.normalized_main)
        self.assertNotIn("p3d_object_step16", self.normalized_control)
        self.assertNotIn("flight_state", self.normalized_main)
        self.assertNotIn("collision_", self.normalized_main)
        self.assertIn("call simulate_camera_step", self.normalized_main)
        self.assertIn("call submit_current_render", self.normalized_main)
        self.assertIn("call nz,consume_render_completion", self.normalized_main)

    def test_requested_keyboard_matrix_is_exact(self) -> None:
        for instruction, meaning in (
            (r"bit 1\s*,\s*\(ix\+7\)", "Arrow Up"),
            (r"bit 1\s*,\s*\(ix\+5\)", "Arrow Down"),
            (r"bit 1\s*,\s*\(ix\+3\)", "Arrow Left"),
            (r"bit 1\s*,\s*\(ix\+15\)", "Arrow Right"),
            (r"bit 7\s*,\s*\(ix\+7\)", "Page Up"),
            (r"bit 6\s*,\s*\(ix\+9\)", "Page Down"),
            (r"bit 1\s*,\s*\(ix\+4\)", "W"),
            (r"bit 1\s*,\s*\(ix\+10\)", "S"),
            (r"bit 1\s*,\s*\(ix\+8\)", "A"),
            (r"bit 2\s*,\s*\(ix\+6\)", "D"),
            (r"bit 7\s*,\s*\(ix\+2\)", "Minus"),
            (r"bit 5\s*,\s*\(ix\+11\)", "Equals"),
        ):
            with self.subTest(key=meaning):
                self.assertRegex(self.normalized_control, instruction)
        self.assertNotRegex(
            self.normalized_control,
            r"bit 6\s*,\s*\(ix\+11\)",
            "MOS maps Equals to BBC key 94: byte 11 bit 5, not bit 6",
        )

    def test_translation_is_yaw_only_and_vertical_is_world_y(self) -> None:
        translation = self.normalized_control.split(
            "survey_update_translation:", 1
        )[1]
        self.assertEqual(translation.count("call p3d_vec3_rotate_y16"), 1)
        self.assertNotIn("p3d_vec3_rotate_x16", translation)
        self.assertNotIn("p3d_vec3_rotate_xyz16", translation)
        self.assertRegex(
            translation,
            r"survey_load_hl camera_state\+p3d_camera_pingo_rotation\+p3d_vec3_y "
            r"ld ix\s*,\s*survey_translation_delta call p3d_vec3_rotate_y16",
        )
        rotate_at = translation.index("call p3d_vec3_rotate_y16")
        page_at = translation.index("; page up")
        self.assertLess(rotate_at, page_at, "world-Y command must be appended after yaw")
        self.assertIn("call p3d_vec3_translate16", translation)

    def test_rotation_is_absolute_upright_bounded_and_constant_rate(self) -> None:
        self.assertRegex(
            self.normalized_main,
            r"survey_angular_rate_128\s*:\s*equ\s+4864",
        )
        self.assertRegex(
            self.normalized_main,
            r"survey_angular_step\s*:\s*equ\s+survey_angular_rate_128\s*>>\s*5",
        )
        self.assertRegex(
            self.normalized_main,
            r"survey_pitch_limit\s*:\s*equ\s+8191",
        )
        self.assertIn("call p3d_camera_mat3_from_euler_fine16", self.control)
        self.assertRegex(
            self.normalized_control,
            r"ld \(camera_state\+p3d_camera_pingo_rotation\+p3d_vec3_z\)\s*,\s*a "
            r"ld \(camera_state\+p3d_camera_pingo_rotation\+p3d_vec3_z\+1\)\s*,\s*a",
        )

    def test_rotation_signs_and_pitch_limits_follow_the_visual_controls(self) -> None:
        blocks = {
            name: self.normalized_control.split(f"{name}:", 1)[1].split(
                " ret", 1
            )[0]
            for name in (
                "survey_pitch_up",
                "survey_pitch_down",
                "survey_yaw_left",
                "survey_yaw_right",
            )
        }
        self.assertRegex(
            blocks["survey_pitch_up"], r"ld de\s*,\s*-survey_angular_step"
        )
        self.assertRegex(
            blocks["survey_pitch_down"], r"ld de\s*,\s*survey_angular_step"
        )
        self.assertRegex(
            blocks["survey_yaw_left"], r"ld de\s*,\s*survey_angular_step"
        )
        self.assertRegex(
            blocks["survey_yaw_right"], r"ld de\s*,\s*-survey_angular_step"
        )

        # These sign guards make the two saturation comparisons signed.  In
        # their absence, reversing from either side of zero snaps directly to
        # the opposite near-vertical limit.
        self.assertRegex(
            blocks["survey_pitch_up"],
            r"bit 7\s*,\s*h jr z\s*,\s*@store .* "
            r"sbc\.s hl\s*,\s*de .* jr nc\s*,\s*@store",
        )
        self.assertRegex(
            blocks["survey_pitch_down"],
            r"bit 7\s*,\s*h jr nz\s*,\s*@store .* "
            r"sbc\.s hl\s*,\s*de .* jr c\s*,\s*@store",
        )

    def test_speed_ladder_is_perceptible_bounded_and_rising_edge_only(self) -> None:
        for definition in (
            r"survey_translation_rate_min\s*:\s*equ\s+8",
            r"survey_translation_rate_initial\s*:\s*equ\s+32",
            r"survey_translation_rate_max\s*:\s*equ\s+256",
        ):
            self.assertRegex(self.normalized_main, definition)
        speed = self.normalized_control.split(
            "survey_update_translation_rate:", 1
        )[1].split("survey_update_rotation:", 1)[0]
        self.assertIn("survey_speed_keys_down", speed)
        self.assertRegex(speed, r"cpl and b")
        self.assertRegex(speed, r"srl h rr l")
        self.assertRegex(speed, r"add\.s hl\s*,\s*hl")

    def test_new_include_closure_is_adl_width_clean(self) -> None:
        result = audit_paths(include_closure([MAIN]))
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    def test_builder_reuses_scene_by_default_and_can_regenerate_explicitly(self) -> None:
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn("--regenerate-scene", source)
        self.assertIn("build_berkeley_flight_triangular_dither.py", source)
        self.assertIn("audit_adl_width.py", source)
        self.assertIn("berkeley-camera-survey.bin", source)


class BerkeleyCameraSurveyBinaryTests(unittest.TestCase):
    def test_checked_in_binary_has_the_common_fixture_entry(self) -> None:
        payload = BINARY.read_bytes()
        self.assertGreater(len(payload), 69)
        self.assertEqual(payload[:4], bytes((0xC3, 0x45, 0x00, 0x04)))
        self.assertEqual(payload[0x40:0x45], b"MOS\0\1")

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_fixture_assembles_to_an_isolated_output(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            scratch = Path(directory)
            source = scratch / "src"
            shutil.copytree(MAIN.parent, source)
            output = scratch / "survey.bin"
            completed = subprocess.run(
                ["ez80asm", MAIN.name, str(output), "-c"],
                cwd=source,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(output.read_bytes(), BINARY.read_bytes())


if __name__ == "__main__":
    unittest.main()
