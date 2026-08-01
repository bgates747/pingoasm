#!/usr/bin/env python3
"""Regression tests for shared Earth Party camera controls."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EDITIONS = ("earth-party-flat", "earth-party-tex")


def source(edition: str, filename: str) -> str:
    return (
        PROJECT_ROOT / "apps" / edition / "src" / filename
    ).read_text(encoding="utf-8")


class EarthPartyCameraControlTests(unittest.TestCase):
    def test_both_editions_share_one_camera_implementation(self) -> None:
        self.assertEqual(
            source("earth-party-flat", "camera-follow.inc"),
            source("earth-party-tex", "camera-follow.inc"),
        )

    def test_fixed_step_calls_camera_before_jet_look_at(self) -> None:
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                assembly = source(edition, "earth-party.asm")
                self.assertRegex(
                    assembly,
                    r"(?ims)^run_simulation_batch:.*?"
                    r"call\s+simulate_object_step\s*"
                    r"call\s+simulate_party_step\s*"
                    r"call\s+simulate_camera_step\s*"
                    r"call\s+update_camera_tracking",
                )

    def test_requested_keyboard_matrix_contract_is_pinned(self) -> None:
        camera = source("earth-party-flat", "camera-follow.inc")
        controls = re.search(
            r"(?ims)^simulate_camera_step:.*?^camera_world_y_up:", camera
        ).group(0)
        for instruction, meaning in (
            (r"bit\s+7\s*,\s*\(ix\+7\)", "Page Up"),
            (r"bit\s+6\s*,\s*\(ix\+9\)", "Page Down"),
            (r"bit\s+6\s*,\s*\(ix\+7\)", "Home"),
            (r"bit\s+1\s*,\s*\(ix\+13\)", "End"),
            (r"bit\s+5\s*,\s*\(ix\+7\)", "Insert"),
            (r"bit\s+1\s*,\s*\(ix\+11\)", "Delete"),
        ):
            with self.subTest(key=meaning):
                self.assertRegex(controls, instruction)

        for routine in (
            "camera_world_y_up",
            "camera_world_y_down",
            "camera_radial_in",
            "camera_radial_out",
            "camera_sweep_increase",
            "camera_sweep_decrease",
        ):
            self.assertRegex(controls, rf"(?im)call\s+{routine}\s*$")

    def test_cylindrical_position_is_regenerated_without_sweep_drift(self) -> None:
        camera = source("earth-party-flat", "camera-follow.inc")
        rebuild = re.search(
            r"(?ims)^rebuild_camera_position:.*?"
            r"^update_camera_tracking:", camera
        ).group(0)
        self.assertRegex(rebuild, r"call\s+p3d_sincos16")
        self.assertEqual(len(re.findall(r"call\s+p3d_smul_norm16", rebuild)), 2)
        self.assertRegex(
            rebuild,
            r"(?ims)camera_sweep_sine.*?p3d_vec3_x.*?"
            r"camera_world_y.*?p3d_vec3_y.*?"
            r"camera_sweep_cosine.*?ld\s+de\s*,\s*earth_z.*?p3d_vec3_z",
        )

        assembly = source("earth-party-flat", "earth-party.asm")
        for definition in (
            r"camera_initial_horizontal_radius:\s*equ\s+-earth_z\+camera_initial_radius_extension",
            r"camera_horizontal_radius_min:\s*equ\s+256",
            r"camera_horizontal_radius_max:\s*equ\s+28000",
            r"camera_world_y_step:\s*equ\s+32",
            r"camera_sweep_step:\s*equ\s+128",
        ):
            self.assertRegex(assembly, rf"(?im)^{definition}\s*$")

    def test_earth_is_position_reference_but_jet_is_only_aim_target(self) -> None:
        camera = source("earth-party-flat", "camera-follow.inc")
        aim = re.search(
            r"(?ims)^aim_camera_at_object:.*?^sync_camera_state:", camera
        ).group(0)
        self.assertRegex(aim, r"ld\s+iy\s*,\s*object_state")
        self.assertRegex(aim, r"call\s+p3d_camera_aim_at_object16")
        self.assertNotIn("earth_state", aim)

    def test_both_editions_use_darkest_nonblack_blue_background(self) -> None:
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                assembly = source(edition, "earth-party.asm")
                self.assertRegex(
                    assembly,
                    r"(?ims)^@display_setup:.*?"
                    r"db\s+17\s*,\s*16\+128.*?"
                    r"db\s+18\s*,\s*0\s*,\s*16\+128",
                )

    def test_camera_scalars_never_use_short_mode_memory_access(self) -> None:
        camera = source("earth-party-flat", "camera-follow.inc")
        self.assertNotRegex(camera, r"(?im)\bld\.s\s+[^\n]*\(")
        self.assertIn("ADL warning: LD.S changes", camera)

    def test_loading_control_card_waits_before_graphics_mode(self) -> None:
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                assembly = source(edition, "earth-party.asm")
                self.assertRegex(
                    assembly,
                    r"(?ims)Loading scene assets\.\.\..*?"
                    r"Ready\. Press any key to begin\..*?"
                    r"call\s+waitKeypress.*?call\s+vdu_set_screen_mode",
                )


if __name__ == "__main__":
    unittest.main()
