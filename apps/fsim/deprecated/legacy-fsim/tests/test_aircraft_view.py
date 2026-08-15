from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pingo_terrain.adl_width import audit_paths
from pingo_terrain.aircraft_asset import (
    OUTPUT_INCLUDE,
    OUTPUT_MANIFEST,
    OUTPUT_TEXTURE,
    build,
    load_vendor,
)
from pingo_terrain.aircraft_view import (
    CHASE_CAMERA_LOCAL,
    CHASE_TARGET_LOCAL,
    COCKPIT_EYE_LOCAL,
    JET_MODEL_HALF_EXTENT_METRES,
    JET_OBJECT_SCALE_Q8_8,
    Q15_ONE,
    SCENE_RENDERABLE_LIMIT,
    VIEW_KEY_BIT,
    VIEW_KEY_BYTE,
    CameraSolution,
    ViewMode,
    ViewToggleState,
    active_renderables,
    advance_view_toggle,
    camera_solution,
    scale_half_extent_metres,
    transform_local_q15,
)
from pingo_terrain.paths import PROJECT_ROOT


IDENTITY = (
    (Q15_ONE, 0, 0),
    (0, Q15_ONE, 0),
    (0, 0, Q15_ONE),
)


class AircraftAssetTests(unittest.TestCase):
    def test_vendored_flat_jet_is_hash_pinned_and_face_constant(self) -> None:
        asset = load_vendor()
        self.assertEqual(len(asset["positions"]), 370)
        self.assertEqual(len(asset["position_indices"]), 2_208)
        self.assertEqual(len(asset["position_indices"]) // 3, 736)
        self.assertEqual(len(asset["uvs"]), 64)
        self.assertEqual(len(asset["texture"]), 64)
        self.assertEqual(
            hashlib.sha256(asset["texture"]).hexdigest(),
            "858b708a30584790b8255450819ffdca148a60150a31ba35be3ff8f70f92f130",
        )
        for offset in range(0, len(asset["uv_indices"]), 3):
            self.assertEqual(len(set(asset["uv_indices"][offset : offset + 3])), 1)

    def test_project_builder_is_byte_deterministic_and_compact(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as first_directory:
            with tempfile.TemporaryDirectory(dir="/tmp") as second_directory:
                first = Path(first_directory)
                second = Path(second_directory)
                first_manifest = build(first)
                second_manifest = build(second)
                self.assertEqual(first_manifest, second_manifest)
                for filename in (OUTPUT_INCLUDE, OUTPUT_TEXTURE, OUTPUT_MANIFEST):
                    self.assertEqual(
                        (first / filename).read_bytes(),
                        (second / filename).read_bytes(),
                    )
                include = (first / OUTPUT_INCLUDE).read_bytes()
                self.assertEqual(len(include), 26_353)
                self.assertEqual(
                    hashlib.sha256(include).hexdigest(),
                    "8ec547558a6dc3532704a4d351bd311f6af868afacb071a4a30ed38b477823ad",
                )
                self.assertNotIn(b"aircraft_jet_normals", include)

    def test_small_aircraft_scale_is_exact_q8_8_and_far_from_limit(self) -> None:
        self.assertEqual(JET_OBJECT_SCALE_Q8_8, 240)
        self.assertEqual(
            scale_half_extent_metres(JET_OBJECT_SCALE_Q8_8),
            JET_MODEL_HALF_EXTENT_METRES,
        )
        self.assertLess(JET_OBJECT_SCALE_Q8_8, 0x100)
        self.assertLess(JET_OBJECT_SCALE_Q8_8, 0xFFFF)


class AircraftCameraTests(unittest.TestCase):
    def solution(self, mode: ViewMode, orientation=IDENTITY) -> CameraSolution:
        return camera_solution(
            mode,
            aircraft_position=(1_000, 200, -3_000),
            aircraft_rotation=(100, -200, 300),
            aircraft_orientation=orientation,
        )

    def test_cockpit_uses_local_eye_and_direct_aircraft_rotation(self) -> None:
        solution = self.solution(ViewMode.COCKPIT)
        self.assertEqual(COCKPIT_EYE_LOCAL, (0, 20, -48))
        self.assertEqual(solution.position, (1_000, 220, -3_048))
        self.assertEqual(solution.direct_rotation, (100, -200, 300))
        self.assertIsNone(solution.aim_target)
        self.assertFalse(solution.aircraft_active)

    def test_chase_is_behind_up_and_aims_ahead_through_look_at_input(self) -> None:
        solution = self.solution(ViewMode.CHASE)
        self.assertEqual(CHASE_CAMERA_LOCAL, (0, 80, 288))
        self.assertEqual(CHASE_TARGET_LOCAL, (0, 16, -48))
        self.assertEqual(solution.position, (1_000, 280, -2_712))
        self.assertEqual(solution.aim_target, (1_000, 216, -3_048))
        self.assertIsNone(solution.direct_rotation)
        self.assertTrue(solution.aircraft_active)

    def test_local_offsets_follow_full_q15_aircraft_orientation(self) -> None:
        # Exact quarter-turn witness: (x,y,z) -> (z,y,-x).
        quarter_turn = (
            (0, 0, Q15_ONE),
            (0, Q15_ONE, 0),
            (-Q15_ONE, 0, 0),
        )
        self.assertEqual(transform_local_q15(CHASE_CAMERA_LOCAL, quarter_turn), (288, 80, 0))
        solution = self.solution(ViewMode.CHASE, quarter_turn)
        self.assertEqual(solution.position, (1_288, 280, -3_000))
        self.assertEqual(solution.aim_target, (952, 216, -3_000))

    def test_q15_transform_rounds_nearest_like_p3d(self) -> None:
        matrix = (
            (16_384, 0, 0),
            (0, 16_383, 0),
            (0, 0, -16_384),
        )
        self.assertEqual(transform_local_q15((1, 1, 1), matrix), (1, 0, -1))

    def test_v_key_toggle_is_rising_edge_only(self) -> None:
        self.assertEqual((VIEW_KEY_BYTE, VIEW_KEY_BIT), (12, 3))
        state = ViewToggleState()
        observed: list[tuple[ViewMode, bool, bool]] = []
        for key_down in (False, True, True, True, False, False, True, True):
            state, changed = advance_view_toggle(state, view_key_down=key_down)
            observed.append((state.mode, state.key_latched, changed))
        self.assertEqual(
            observed,
            [
                (ViewMode.COCKPIT, False, False),
                (ViewMode.CHASE, True, True),
                (ViewMode.CHASE, True, False),
                (ViewMode.CHASE, True, False),
                (ViewMode.CHASE, False, False),
                (ViewMode.CHASE, False, False),
                (ViewMode.COCKPIT, True, True),
                (ViewMode.COCKPIT, True, False),
            ],
        )

    def test_scene_budget_counts_only_active_aircraft(self) -> None:
        self.assertEqual(active_renderables(ViewMode.COCKPIT), 27)
        self.assertEqual(active_renderables(ViewMode.CHASE), 28)
        self.assertLessEqual(active_renderables(ViewMode.CHASE), SCENE_RENDERABLE_LIMIT)


class AircraftViewAssemblyTests(unittest.TestCase):
    def test_include_uses_proven_p3d_paths_and_is_adl_clean(self) -> None:
        include = PROJECT_ROOT / "fixtures/_common/aircraft-view.inc"
        source = include.read_text(encoding="utf-8")
        self.assertIn("call p3d_mat3_mul_vec3_16", source)
        self.assertIn("jp p3d_camera_aim_at_point16", source)
        self.assertIn("bit 3,(ix+12)", source)
        result = audit_paths([include])
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    def test_include_assembles_in_an_adl_harness(self) -> None:
        assembler = shutil.which("ez80asm")
        self.assertIsNotNone(assembler)
        harness = PROJECT_ROOT / "tests/aircraft_view_harness.asm"
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            temporary_tests = root / "tests"
            temporary_common = root / "fixtures/_common"
            temporary_tests.mkdir(parents=True)
            temporary_common.mkdir(parents=True)
            temporary_harness = temporary_tests / harness.name
            shutil.copy2(harness, temporary_harness)
            shutil.copy2(
                PROJECT_ROOT / "fixtures/_common/aircraft-view.inc",
                temporary_common / "aircraft-view.inc",
            )
            output = root / "airview.bin"
            subprocess.run(
                [assembler, temporary_harness.name, str(output)],
                cwd=temporary_tests,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
