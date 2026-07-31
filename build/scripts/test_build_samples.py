#!/usr/bin/env python3
"""Unit tests for source-preserving assembly application builds."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_samples


LOCAL_APPS = {
    "moveobj-local": "inputobj-local.inc",
    "moveair-local": "inputair-local.inc",
}


def executable_source(source: str) -> str:
    return "\n".join(line.split(";", 1)[0] for line in source.splitlines())


class LocalTransformSourceTests(unittest.TestCase):
    def test_jet_uses_fixed_simulation_and_tunable_viewport(self) -> None:
        for app_name, control_filename in LOCAL_APPS.items():
            with self.subTest(app=app_name):
                source = (
                    build_samples.APPS_ROOT / app_name / "src" / "jet.asm"
                ).read_text(encoding="utf-8")
                code = executable_source(source)

                self.assertRegex(
                    code,
                    r'(?im)^\s*include\s+"jet\.inc"\s*$',
                )
                self.assertRegex(
                    code,
                    r'(?im)^\s*include\s+"render-async\.inc"\s*$',
                )
                self.assertRegex(
                    code,
                    rf'(?im)^\s*include\s+"{re.escape(control_filename)}"\s*$',
                )
                self.assertNotRegex(
                    code,
                    r'(?im)^\s*include\s+"cube\.inc"\s*$',
                )
                self.assertRegex(
                    code,
                    r"(?im)^simulation_step_ticks:\s*equ\s+4\s*$",
                )
                self.assertRegex(
                    code,
                    r"(?im)^simulation_rate_basis_ticks:\s*equ\s+128\s*$",
                )
                self.assertRegex(
                    code,
                    r"(?im)^object_linear_rate_128:\s*equ\s+352\s*$",
                )
                self.assertRegex(
                    code,
                    r"(?im)^object_angular_rate_128:\s*equ\s+4864\s*$",
                )
                self.assertRegex(
                    code,
                    (
                        r"(?im)^object_linear_step:\s*equ\s+"
                        r"object_linear_rate_128\s*>>\s*5\s*$"
                    ),
                )
                self.assertRegex(
                    code,
                    (
                        r"(?im)^object_angular_step:\s*equ\s+"
                        r"object_angular_rate_128\s*>>\s*5\s*$"
                    ),
                )
                self.assertRegex(
                    code,
                    r"(?im)^viewport_width:\s*equ\s+320\s*$",
                )
                self.assertRegex(
                    code,
                    r"(?im)^viewport_height:\s*equ\s+240\s*$",
                )
                self.assertRegex(
                    code,
                    (
                        r"(?ims)^run_simulation_batch:\s*.*?"
                        r"call\s+take_simulation_step\s*.*?"
                        r"call\s+simulate_object_step\s*.*?"
                        r"call\s+reset_keys\s*.*?"
                        r"call\s+set_keys"
                    ),
                )

    def test_vdu_helper_contains_only_current_pingo_commands(self) -> None:
        for app_name, control_filename in LOCAL_APPS.items():
            with self.subTest(app=app_name):
                source_dir = build_samples.APPS_ROOT / app_name / "src"
                sources = "\n".join(
                    (source_dir / filename).read_text(encoding="utf-8")
                    for filename in (
                        "jet.asm",
                        control_filename,
                        "vdu_pingo.inc",
                        "render-async.inc",
                    )
                )
                commands = {
                    int(match)
                    for match in re.findall(
                        r"db\s+(?:\$49|49h)\s*,\s*(\d+)",
                        sources,
                        flags=re.IGNORECASE,
                    )
                }
                self.assertEqual(
                    commands,
                    {0, 1, 2, 3, 4, 5, 9, 13, 17, 21, 25, 38, 41},
                )
                self.assertNotIn("sodrel:", sources)
                self.assertNotIn("sorrel:", sources)
                self.assertNotIn("vdu_set_dither:", sources)
                self.assertNotRegex(
                    executable_source(sources),
                    r"(?i)\b(?:call|jp)\s+cto\b",
                )

    def test_render_notification_packets_match_current_contract(self) -> None:
        for app_name in LOCAL_APPS:
            with self.subTest(app=app_name):
                source = (
                    build_samples.APPS_ROOT
                    / app_name
                    / "src"
                    / "render-async.inc"
                ).read_text(encoding="utf-8")
                code = executable_source(source)

                self.assertRegex(
                    code,
                    (
                        r"(?ims)^enable_render_notifications:\s*.*?"
                        r"^@command:\s*\n"
                        r"\s*db\s+23\s*,\s*0\s*,\s*0A0h\s*\n"
                        r"\s*dw\s+sid\s*\n"
                        r"\s*db\s+49h\s*,\s*41\s*,\s*1\s*\n"
                        r"\s*dw\s+render_notify_token\s*\n"
                        r"^@end:"
                    ),
                )
                self.assertRegex(
                    code,
                    (
                        r"(?ims)^disable_render_notifications:\s*.*?"
                        r"^@command:\s*\n"
                        r"\s*db\s+23\s*,\s*0\s*,\s*0A0h\s*\n"
                        r"\s*dw\s+sid\s*\n"
                        r"\s*db\s+49h\s*,\s*41\s*,\s*0\s*\n"
                        r"\s*dw\s+0\s*\n"
                        r"^@end:"
                    ),
                )
                self.assertRegex(
                    code,
                    r"(?im)^render_notify_token:\s*equ\s+0C35Ah\s*$",
                )
                self.assertRegex(
                    code,
                    (
                        r"(?ims)^submit_current_render:\s*.*?"
                        r"ld\s+a\s*,\s*1\s*\n"
                        r"\s*ld\s+\(\s*render_in_flight\s*\)\s*,\s*a\s*\n"
                        r"\s*RENDBMP\s+sid\s*,\s*tgtbmid"
                    ),
                )

    def test_space_dither_binding_is_not_executable(self) -> None:
        for app_name, control_filename in LOCAL_APPS.items():
            with self.subTest(app=app_name):
                source = (
                    build_samples.APPS_ROOT
                    / app_name
                    / "src"
                    / control_filename
                ).read_text(encoding="utf-8")
                code = executable_source(source)
                self.assertNotRegex(
                    code,
                    r"(?i)\bbit\s+2\s*,\s*\(\s*ix\s*\+\s*12\s*\)",
                )
                self.assertNotRegex(
                    code,
                    r"(?i)\bcall\s+nz\s*,\s*cycle_dithering\b",
                )

    def test_render_async_layer_is_identical_between_local_apps(self) -> None:
        moveobj = (
            build_samples.APPS_ROOT
            / "moveobj-local"
            / "src"
            / "render-async.inc"
        ).read_bytes()
        moveair = (
            build_samples.APPS_ROOT
            / "moveair-local"
            / "src"
            / "render-async.inc"
        ).read_bytes()
        self.assertEqual(moveair, moveobj)

    def test_moveair_preserves_z_velocity_and_steps_while_coasting(self) -> None:
        source = (
            build_samples.APPS_ROOT
            / "moveair-local"
            / "src"
            / "inputair-local.inc"
        ).read_text(encoding="utf-8")
        jet_source = (
            build_samples.APPS_ROOT
            / "moveair-local"
            / "src"
            / "jet.asm"
        ).read_text(encoding="utf-8")
        code = executable_source(source)
        jet_code = executable_source(jet_source)
        simulation = code.split("simulate_object_step:", 1)[1]
        transient_clear = simulation.split("ld ix,keyboard_masks", 1)[0]

        self.assertNotIn("p3d_vec3_z", transient_clear)
        self.assertRegex(
            simulation,
            (
                r"(?ims)ld\s+a\s*,\s*\(\s*iy\+"
                r"p3d_object_local_linear_velocity\+p3d_vec3_z\s*\)\s*"
                r"or\s+\(\s*iy\+p3d_object_local_linear_velocity\+"
                r"p3d_vec3_z\+1\s*\).*?"
                r"ret\s+z\s*.*?ld\s+ix\s*,\s*object_state\s*.*?"
                r"jp\s+p3d_object_step16"
            ),
        )
        self.assertRegex(
            jet_code,
            r"(?im)^object_air_speed_limit:\s*equ\s+255\s*$",
        )
        self.assertIn("dec.s hl", simulation)
        self.assertIn("inc.s hl", simulation)

    def test_moveair_tracks_object_with_ez80_camera_state(self) -> None:
        source_dir = build_samples.APPS_ROOT / "moveair-local" / "src"
        jet = executable_source(
            (source_dir / "jet.asm").read_text(encoding="utf-8")
        )
        tracking = executable_source(
            (source_dir / "camera-follow.inc").read_text(encoding="utf-8")
        )

        self.assertRegex(
            jet,
            r'(?im)^\s*include\s+"camera-follow\.inc"\s*$',
        )
        self.assertRegex(
            jet,
            (
                r"(?im)^camera_tracking_roll_policy:\s*equ\s+"
                r"p3d_camera_roll_upright\s*$"
            ),
        )
        self.assertRegex(
            jet,
            (
                r"(?ims)call\s+init_object_state\s*"
                r"call\s+init_camera_tracking"
            ),
        )
        self.assertRegex(
            jet,
            (
                r"(?ims)^run_simulation_batch:\s*.*?"
                r"call\s+simulate_object_step\s*"
                r"call\s+update_camera_tracking"
            ),
        )
        self.assertRegex(
            jet,
            (
                r"(?ims)ld\s+ix\s*,\s*camera_state\s*.*?"
                r"and\s+p3d_camera_dirty_all\s*.*?"
                r"call\s+p3d_object_sync16\s*"
                r"call\s+sync_camera_state\s*"
                r"call\s+submit_current_render"
            ),
        )
        self.assertRegex(
            tracking,
            (
                r"(?ims)^init_camera_tracking:\s*.*?"
                r"call\s+p3d_camera_init16\s*.*?"
                r"call\s+aim_camera_at_object\s*.*?"
                r"jp\s+sync_camera_state"
            ),
        )
        self.assertRegex(
            tracking,
            (
                r"(?ims)^update_camera_tracking:\s*.*?"
                r"bit\s+0\s*,\s*\(\s*ix\+p3d_object_dirty\s*\)\s*"
                r"ret\s+z\s*.*?"
                r"call\s+p3d_camera_aim_at_object16"
            ),
        )
        self.assertRegex(
            tracking,
            (
                r"(?ims)^sync_camera_state:\s*.*?"
                r"call\s+scdabs\s*.*?"
                r"res\s+0\s*,\s*a\s*.*?"
                r"call\s+scrabs\s*.*?"
                r"res\s+1\s*,\s*a"
            ),
        )
        self.assertRegex(
            jet,
            r"(?ims)^camera_initial_position:\s*dw\s+0\s*,\s*0\s*,\s*0",
        )
        self.assertRegex(
            jet,
            r"(?ims)^camera_state:\s*ds\s+p3d_camera_size",
        )


class StaticApplicationBuildTests(unittest.TestCase):
    def test_static_app_manifest_selects_both_local_jets(self) -> None:
        self.assertEqual(
            build_samples.STATIC_APPS,
            {
                "moveobj-local": ("jet.asm", ("jet.rgba2",)),
                "moveair-local": ("jet.asm", ("jet.rgba2",)),
            },
        )

    def test_assemble_uses_short_relative_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "apps" / "moveobj-local" / "src"
            output = root / "apps" / "moveobj-local" / "tgt" / "jet.bin"
            source_dir.mkdir(parents=True)

            with mock.patch.object(build_samples.subprocess, "run") as run:
                build_samples.assemble(source_dir, "jet.asm", output)

            run.assert_called_once_with(
                ["ez80asm", "jet.asm", "../tgt/jet.bin"],
                cwd=source_dir,
                check=True,
            )

    def test_build_static_app_replaces_only_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            apps_root = root / "apps"
            models_root = root / "models"
            source_dir = apps_root / "moveobj-local" / "src"
            target_dir = apps_root / "moveobj-local" / "tgt"
            source_dir.mkdir(parents=True)
            target_dir.mkdir()
            models_root.mkdir()

            source_marker = source_dir / "agon" / "3d.inc"
            source_marker.parent.mkdir()
            source_marker.write_text("canonical local source\n", encoding="utf-8")
            (source_dir / "jet.asm").write_text("assembly source\n", encoding="utf-8")
            (target_dir / "stale.bin").write_bytes(b"stale")
            (models_root / "jet.rgba2").write_bytes(b"texture")

            def fake_assemble(
                actual_source_dir: Path,
                asm_filename: str,
                output: Path,
            ) -> None:
                self.assertEqual(actual_source_dir, source_dir)
                self.assertEqual(asm_filename, "jet.asm")
                output.write_bytes(b"binary")

            with (
                mock.patch.object(build_samples, "APPS_ROOT", apps_root),
                mock.patch.object(build_samples, "MODELS_ROOT", models_root),
                mock.patch.object(build_samples, "assemble", fake_assemble),
            ):
                output = build_samples.build_static_app(
                    "moveobj-local",
                    "jet.asm",
                    ("jet.rgba2",),
                )

            self.assertEqual(output, target_dir / "jet.bin")
            self.assertEqual(source_marker.read_text(encoding="utf-8"), "canonical local source\n")
            self.assertFalse((target_dir / "stale.bin").exists())
            self.assertEqual((target_dir / "jet.bin").read_bytes(), b"binary")
            self.assertEqual(
                (target_dir / "jet.rgba2").read_bytes(),
                b"texture",
            )


if __name__ == "__main__":
    unittest.main()
