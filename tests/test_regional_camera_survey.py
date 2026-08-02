from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure
from pingo_terrain.p3dm import LayerKind, parse_container


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/regional-camera-survey"
MAIN = FIXTURE / "src/regional-camera-survey.asm"
STREAMING = FIXTURE / "src/regional-camera-streaming.inc"
SCENE = FIXTURE / "src/regional-camera-scene.inc"
PROGRAM = FIXTURE / "tgt/regional-camera-survey.bin"
CORPUS = ROOT / "build/p3dm/bay-area-full-l0"
RUNTIME = CORPUS / "P3DSURV.BIN"
SURVEY = CORPUS / "SURVEY.json"
WORLD = CORPUS / "WORLD.json"
BUILDER = ROOT / "scripts/build_regional_camera_survey.py"


def normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


def terrain_path(tile_x: int, tile_y: int) -> Path:
    tile_id = tile_y * 201 + tile_x
    return CORPUS / "TRN/L0" / f"{tile_id >> 8:02X}" / f"{tile_id & 255:02X}.AGN"


class RegionalCameraSurveySourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = normalized(MAIN)
        self.streaming = normalized(STREAMING)
        self.scene = normalized(SCENE)

    def test_exact_campanile_start_and_shared_frame_bias(self) -> None:
        for contract in (
            r"regional_start_tile_x\s*:\s*equ\s+85",
            r"regional_start_tile_y\s*:\s*equ\s+179",
            r"regional_frame_z_bias\s*:\s*equ\s+12288",
            r"camera_initial_x\s*:\s*equ\s+-1857",
            r"camera_initial_y\s*:\s*equ\s+3496",
            r"camera_initial_z_canonical\s*:\s*equ\s+3638",
            r"camera_initial_z\s*:\s*equ\s+camera_initial_z_canonical\+regional_frame_z_bias",
        ):
            self.assertRegex(self.main, contract)
        self.assertRegex(
            self.streaming,
            r"ld de\s*,\s*regional_frame_z_bias add\.s hl\s*,\s*de",
        )

    def test_fixture_is_direct_camera_only_with_full_viewport(self) -> None:
        self.assertRegex(self.main, r"viewport_width\s*:\s*equ\s+320")
        self.assertRegex(self.main, r"viewport_height\s*:\s*equ\s+240")
        self.assertIn("camera-survey-input.inc", self.main)
        self.assertIn("flight-backdrop.inc", self.main)
        self.assertNotIn("flight-input.inc", self.main)
        self.assertNotIn("flight_model_step", self.main)
        self.assertNotIn("collision_", self.main)
        self.assertNotIn("aircraft", self.scene)
        self.assertNotIn("airport", self.scene)

    def test_window_uses_all_32_slots_and_collision_free_mapping(self) -> None:
        self.assertRegex(self.streaming, r"terrain_slot_count\s*:\s*equ\s+32")
        established = re.findall(
            r"regional_establish_terrain_slot\s+(\d+)", self.scene
        )
        self.assertEqual([int(item) for item in established], list(range(1, 33)))
        self.assertRegex(
            self.streaming,
            r"and 7 ld c\s*,\s*a ld a\s*,\s*\(regional_desired_y\) and 3 "
            r"add a\s*,\s*a add a\s*,\s*a add a\s*,\s*a add a\s*,\s*c",
        )
        slots = {
            (((179 + dy) & 3) * 8 + ((85 + dx) & 7))
            for dy in range(-2, 2)
            for dx in range(-2, 6)
        }
        self.assertEqual(slots, set(range(32)))

    def test_streamer_covers_full_grid_and_rebases_camera_not_flight(self) -> None:
        self.assertRegex(self.streaming, r"regional_grid_columns\s*:\s*equ\s+201")
        self.assertRegex(self.streaming, r"regional_grid_rows\s*:\s*equ\s+252")
        self.assertIn("regional_streaming_rebase_camera:", self.streaming)
        self.assertIn("regional_z_low: equ regional_frame_z_bias-regional_half_cell_counts", self.streaming)
        self.assertIn("regional_z_high: equ regional_frame_z_bias+regional_half_cell_counts", self.streaming)
        self.assertNotIn("streaming_rebase_flight", self.streaming)
        self.assertRegex(
            self.main,
            r"call simulate_camera_step call regional_streaming_rebase_camera",
        )

    def test_one_component_is_published_only_between_completed_renders(self) -> None:
        idle = self.main.split("; disk i/o and mesh publication", 1)[1]
        self.assertRegex(
            idle,
            r"call regional_streaming_service_one call sync_camera_state "
            r"call submit_current_render",
        )
        service = self.streaming.split("regional_streaming_service_one:", 1)[1].split(
            "regional_compute_direct_slot:", 1
        )[0]
        self.assertEqual(service.count("jp regional_load_desired_terrain"), 1)
        self.assertIn("call p3dm_load_component", self.streaming)

    def test_z_delta_scratch_does_not_corrupt_completed_x_transform(self) -> None:
        positioner = self.streaming.split(
            "regional_position_desired_terrain:", 1
        )[1].split("regional_delta_to_count:", 1)[0]
        after_x = positioner.split("pop bc", 1)[1]
        before_z_conversion = after_x.split("call regional_delta_to_count", 1)[0]
        self.assertNotRegex(before_z_conversion, r"ld c\s*,")
        self.assertRegex(
            before_z_conversion,
            r"ld a\s*,\s*\(regional_coarse_x\) "
            r"ld hl\s*,\s*regional_desired_x sub \(hl\)",
        )

    def test_include_closure_is_adl_width_clean(self) -> None:
        result = audit_paths(include_closure([MAIN]))
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)


class RegionalCameraSurveyCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        if not WORLD.is_file():
            self.skipTest("ignored full-region L0 corpus has not been built")

    def test_full_corpus_and_start_window_are_present(self) -> None:
        world = json.loads(WORLD.read_text(encoding="utf-8"))
        self.assertEqual(world["selection"], "full")
        self.assertEqual(world["world_grid"]["columns"], 201)
        self.assertEqual(world["world_grid"]["rows"], 252)
        self.assertEqual(world["statistics"]["records"], 50652)
        self.assertEqual(world["statistics"]["container_bytes"], 269883360)
        paths = [
            terrain_path(85 + dx, 179 + dy)
            for dy in range(-2, 2)
            for dx in range(-2, 6)
        ]
        self.assertEqual(len(paths), 32)
        self.assertTrue(all(path.is_file() for path in paths))
        for path in (paths[0], terrain_path(85, 179), paths[-1]):
            tile = parse_container(path.read_bytes())
            self.assertIs(tile.meta.layer_kind, LayerKind.TERRAIN)
            self.assertEqual(tile.meta.lod, 0)

    def test_runtime_manifest_and_binary_match_fixture_artifacts(self) -> None:
        report = json.loads(SURVEY.read_text(encoding="utf-8"))
        self.assertEqual(report["corpus"]["records"], 50652)
        self.assertEqual(report["window"]["slots"], 32)
        self.assertEqual(report["camera"]["canonical_fine_counts"], [-1857, 3496, 3638])
        self.assertEqual(report["camera"]["render_frame_position_counts"], [-1857, 3496, 15926])
        self.assertEqual(PROGRAM.read_bytes(), RUNTIME.read_bytes())
        payload = PROGRAM.read_bytes()
        self.assertEqual(payload[:4], bytes((0xC3, 0x45, 0, 4)))
        self.assertEqual(payload[0x40:0x45], b"MOS\0\1")

    def test_builder_is_fail_closed_around_corpus_and_adl_audit(self) -> None:
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn("bay-area-full-l0-2026-08-02.json", source)
        self.assertIn("50652", source)
        self.assertIn("269883360", source)
        self.assertIn("full-corpus component hash changed", source)
        self.assertIn("verified_records", source)
        self.assertIn("audit_adl_width.py", source)
        self.assertIn("--fail-review", source)
        self.assertIn("P3DSURV.BIN", source)

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_fixture_reassembles_byte_identically(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            scratch = Path(directory)
            shutil.copytree(ROOT / "fixtures", scratch / "fixtures")
            copied_main = scratch / MAIN.relative_to(ROOT)
            output = scratch / "regional-camera-survey.bin"
            completed = subprocess.run(
                ["ez80asm", copied_main.name, str(output), "-c"],
                cwd=copied_main.parent,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(output.read_bytes(), PROGRAM.read_bytes())


if __name__ == "__main__":
    unittest.main()
