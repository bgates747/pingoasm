from __future__ import annotations

import importlib.util
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure
from pingo_terrain.p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    ShadingMode,
    parse_container,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/campanile-p3dm-probe"
MAIN = FIXTURE / "src/campanile-p3dm-probe.asm"
TARGET = FIXTURE / "tgt"
MANIFEST = TARGET / "probe.json"
BUILD_SCRIPT = ROOT / "scripts/build_campanile_p3dm_probe.py"
CAPTURE_SCRIPT = ROOT / "scripts/capture_campanile_p3dm_probe.py"
GENERATED = FIXTURE / "src/generated/campanile-probe.inc"
P3D_NORM_MAX = 32_767


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_capture_module():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    specification = importlib.util.spec_from_file_location(
        "capture_campanile_p3dm_probe", CAPTURE_SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class CampanileP3DMProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.component = TARGET / cls.manifest["component"]["runtime_name"]
        cls.palette = TARGET / cls.manifest["palette"]["runtime_name"]
        cls.tile = parse_container(cls.component.read_bytes())

    def test_component_is_exact_scene_lit_solid_flat_landmark(self) -> None:
        self.assertEqual(self.tile.meta.layer_kind, LayerKind.LANDMARK)
        self.assertEqual(self.tile.meta.shading_mode, ShadingMode.SOLID_FLAT)
        self.assertEqual(self.tile.meta.illumination, IlluminationPolicy.SCENE)
        self.assertEqual(
            self.tile.meta.material_set, MaterialSet.NATIVE_SOLID_PALETTE
        )
        self.assertEqual(file_sha256(self.component), self.manifest["component"]["sha256"])
        self.assertEqual(len(self.tile.positions), self.manifest["component"]["vertices"])
        self.assertEqual(
            len(self.tile.position_indices) // 3,
            self.manifest["component"]["triangles"],
        )

    def test_native_palette_is_exact_raw_8x8_cube(self) -> None:
        self.assertEqual(self.palette.read_bytes(), bytes(range(0xC0, 0x100)))
        self.assertEqual(file_sha256(self.palette), self.manifest["palette"]["sha256"])
        self.assertEqual(self.manifest["palette"]["dimensions"], [8, 8])
        self.assertTrue(set(self.manifest["palette"]["selectors"]).issubset(range(64)))

    def test_local_placement_preserves_mesh_scale_and_contacts_ground(self) -> None:
        placement = self.manifest["local_placement"]
        self.assertTrue(placement["preserves_component_scale_and_mesh"])
        self.assertEqual(
            placement["scale_q8_8"], self.tile.meta.model_half_extent_m * 32
        )
        self.assertEqual((placement["translation_x"], placement["translation_z"]), (0, 0))
        minimum_y = min(position[1] for position in self.tile.positions)
        maximum_y = max(position[1] for position in self.tile.positions)
        half = self.tile.meta.model_half_extent_m
        translation_y = placement["translation_y"]
        base_m = (translation_y * 2048 + minimum_y * half) / P3D_NORM_MAX
        top_m = (translation_y * 2048 + maximum_y * half) / P3D_NORM_MAX
        self.assertEqual(placement["minimum_encoded_y"], minimum_y)
        self.assertEqual(placement["maximum_encoded_y"], maximum_y)
        self.assertAlmostEqual(placement["base_residual_m"], base_m, places=12)
        self.assertAlmostEqual(placement["decoded_top_m"], top_m, places=12)
        self.assertLessEqual(abs(base_m), 1024 / P3D_NORM_MAX)
        self.assertGreater(top_m, 90.0)

        generated = {
            key: int(value)
            for key, value in re.findall(
                r"^(campanile_[a-z0-9_]+): equ (-?\d+)$",
                GENERATED.read_text(encoding="ascii"),
                flags=re.MULTILINE,
            )
        }
        self.assertEqual(generated["campanile_scale_q8_8"], placement["scale_q8_8"])
        self.assertEqual(
            generated["campanile_local_translation_y"], translation_y
        )
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn("SO sid,probe_object_id,campanile_scale_q8_8", source)
        self.assertIn("ld de,campanile_local_translation_y", source)
        self.assertIn("call sodabs", source)

    def test_runtime_assets_are_83_safe_and_match_canonical_corpus(self) -> None:
        for name in ("CAMPANIL.AGN", "SOLID64.RG2", "CAMPTEST.BIN"):
            stem, extension = name.split(".")
            self.assertLessEqual(len(stem), 8)
            self.assertLessEqual(len(extension), 3)
            self.assertTrue((TARGET / name).is_file())
        canonical = ROOT / self.manifest["canonical_landmark_index"]["path"]
        index = json.loads(canonical.read_text(encoding="utf-8"))
        record = next(item for item in index["landmarks"] if item["id"] == "campanile")
        self.assertEqual(record["component"]["sha256"], file_sha256(self.component))
        self.assertEqual(
            file_sha256(canonical),
            self.manifest["canonical_landmark_index"]["sha256"],
        )

    def test_scene_establishes_stable_slot_then_loads_and_activates(self) -> None:
        source = MAIN.read_text(encoding="utf-8")
        self.assertLess(
            source.index("CO sid,probe_object_id"),
            source.index("call p3dm_load_component"),
        )
        self.assertLess(
            source.index("call p3dm_load_component"),
            source.rindex("call pingo_set_object_active"),
        )
        self.assertIn("pingo_shading_flat_palette", source)
        self.assertIn("pingo_mesh_illumination_scene", source)
        self.assertNotIn("pingo_bind_flat_pattern_library", source)
        self.assertNotIn("pingo_shading_flat_pattern", source)

    def test_oblique_camera_uses_qualified_integer_look_at(self) -> None:
        source = MAIN.read_text(encoding="utf-8")
        camera = source.split("initialize_probe_camera:", 1)[1].split(
            "sync_camera_state:", 1
        )[0]
        self.assertIn("call p3d_camera_init16", camera)
        self.assertIn("call p3d_camera_look_at_point16", camera)
        self.assertIn("p3d_camera_roll_upright", camera)
        self.assertEqual(
            self.manifest["camera"]["position_translation_counts"],
            [-2304, 1152, 2304],
        )

    def test_builder_regenerates_before_copy_and_audits_include_closure(self) -> None:
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertLess(
            source.index("scripts/build_landmark_p3dm.py"),
            source.index("CANONICAL_INDEX.read_text"),
        )
        self.assertIn("scripts/audit_adl_width.py", source)
        self.assertIn('"--follow-includes"', source)
        self.assertIn('"--fail-review"', source)
        generic_capture = (ROOT / "scripts/capture_p3dm_loader_probe.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('f"load {PROGRAM.name}', generic_capture)
        closure = self.manifest["assembly"]["include_closure"]
        for record in closure:
            self.assertEqual(file_sha256(ROOT / record["path"]), record["sha256"])

    def test_complete_include_closure_is_adl_clean_and_assembles(self) -> None:
        closure = include_closure([MAIN])
        result = audit_paths(closure)
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)
        if not shutil.which("ez80asm"):
            self.skipTest("ez80asm is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            for source in closure:
                destination = scratch / source.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            copied_main = scratch / MAIN.relative_to(ROOT)
            output = scratch / "CAMPTEST.BIN"
            completed = subprocess.run(
                ["ez80asm", copied_main.name, str(output)],
                cwd=copied_main.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(file_sha256(output), self.manifest["assembly"]["sha256"])

    def test_capture_requires_exact_mesh_publication_and_activation(self) -> None:
        capture_module = load_capture_module()
        component = self.manifest["component"]
        valid = (
            "PINGO_STREAM mesh_replace=ok stage=29696 mid=1 "
            f"bytes={component['data_bytes']} v={component['vertices']} "
            f"i={component['position_indices']} u={component['uvs']} "
            f"t={component['uv_indices']} us=42\n"
            "PINGO_STREAM object_active=ok oid=1 active=1\n"
        )
        capture_module.validate_stream_log(valid, self.manifest)
        with self.assertRaisesRegex(SystemExit, "command-50"):
            capture_module.validate_stream_log("PINGO_DUMP status=ok", self.manifest)

    def test_capture_hash_binds_every_staged_runtime_asset(self) -> None:
        capture_module = load_capture_module()
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory)
            for name in capture_module.expected_assets(self.manifest):
                shutil.copy2(TARGET / name, staged / name)
            witnessed = capture_module.verify_assets(staged, self.manifest)
            self.assertEqual(
                witnessed["CAMPTEST.BIN"]["sha256"],
                self.manifest["assembly"]["sha256"],
            )
            palette = staged / "SOLID64.RG2"
            palette.write_bytes(bytes([0]) + palette.read_bytes()[1:])
            with self.assertRaisesRegex(SystemExit, "disagrees with probe.json"):
                capture_module.verify_assets(staged, self.manifest)

    def test_capture_rejects_a_nonrecognition_pixel_witness(self) -> None:
        capture_module = load_capture_module()
        raw = bytearray(320 * 240)
        raw[120 * 320 + 160] = 0xFF
        with self.assertRaisesRegex(SystemExit, "too small"):
            capture_module.analyze_silhouette(bytes(raw))


if __name__ == "__main__":
    unittest.main()
