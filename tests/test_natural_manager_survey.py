from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure
from pingo_terrain.hex_terrain import HexCell, disk_offsets, hex_distance


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = ROOT / "fixtures/terrain-manager-survey/src"
MAIN = SOURCE_DIRECTORY / "terrain-manager-natural-survey.asm"
CONTROL_MAIN = SOURCE_DIRECTORY / "terrain-manager-survey.asm"
PROVIDER = SOURCE_DIRECTORY / "terrain-manager-hex-provider.inc"
RUNTIME_MANAGER = ROOT / "runtime/ez80/terrain-manager.inc"
PROGRAM = (
    ROOT
    / "fixtures/terrain-manager-natural-survey/tgt"
    / "terrain-manager-natural-survey.bin"
)

sys.path.insert(0, str(ROOT / "scripts"))

import build_natural_terrain_manager_survey as builder  # noqa: E402
import export_natural_runtime_subset_blender as extractor  # noqa: E402


class NaturalManagerSurveyTests(unittest.TestCase):
    def test_selection_and_nat_record_paths_match_manager_ring_order(self) -> None:
        cells = builder.expected_cells()
        self.assertEqual(len(cells), 91)
        self.assertEqual((cells[0].q, cells[0].r), (90, 121))
        self.assertEqual(
            [(cell.q - 90, cell.r - 121) for cell in cells],
            list(disk_offsets(5)),
        )
        self.assertEqual(
            builder.record_path(HexCell(90, 121)),
            Path("NAT/L0/53/17.AGN"),
        )
        self.assertEqual(builder.RADIUS_COUNTS, (1, 7, 19, 37, 61, 91))

    def test_extractor_is_pinned_to_the_accepted_master(self) -> None:
        self.assertEqual(extractor.SELECTION_CENTER, builder.START_CELL)
        self.assertEqual(extractor.SELECTION_RADIUS, builder.SELECTION_RADIUS)
        self.assertEqual(
            extractor.SOURCE_BLEND_SHA256,
            builder.SOURCE_BLEND_SHA256,
        )
        self.assertEqual(
            extractor.SOURCE_TOPOLOGY_SHA256,
            builder.SOURCE_TOPOLOGY_SHA256,
        )
        self.assertEqual(
            builder.EXPECTED_SOURCE_SEMANTIC_SHA256,
            "10758c3e4633e199af85c2829af3313923220db65267ec999e033d780227be88",
        )

    def test_historical_bounded_source_disk_remains_well_formed(self) -> None:
        desired = {
            (90 + dq, 121 + dr) for dq, dr in disk_offsets(5)
        }
        self.assertEqual(len(desired), 91)
        for q in range(84, 97):
            for r in range(115, 128):
                admitted = hex_distance((q, r), (90, 121)) <= 5
                self.assertEqual((q, r) in desired, admitted)
        self.assertTrue(
            all(
                hex_distance((90 + dq, 121 + dr), (90, 121)) == 6
                for dq, dr in disk_offsets(6)[-36:]
            )
        )

    def test_natural_and_control_profiles_share_only_provider_policy(self) -> None:
        natural = MAIN.read_text(encoding="utf-8").lower()
        control = CONTROL_MAIN.read_text(encoding="utf-8").lower()
        provider = PROVIDER.read_text(encoding="utf-8").lower()
        self.assertIn("hex_provider_fixture_bounds_enabled: equ 0", natural)
        self.assertIn("hex_provider_natural_namespace: equ 1", natural)
        self.assertIn("hex_provider_fixture_bounds_enabled: equ 0", control)
        self.assertIn("hex_provider_natural_namespace: equ 0", control)
        self.assertIn("hex_provider_validate_fixture_bounds", provider)
        self.assertIn("ld (p3dm_filename_buffer+0),a", provider)
        self.assertIn("ld (p3dm_filename_buffer+1),a", provider)
        self.assertIn("ld (p3dm_filename_buffer+2),a", provider)
        for required in (
            'include "../../../runtime/ez80/terrain-manager.inc"',
            "call terrain_manager_initialize",
            "call terrain_manager_service_idle",
            "call terrain_manager_shutdown_idle",
            "call init_camera_survey",
            'include "../../../fixtures/_common/pingo-projection.inc"',
            "ld hl,manager_survey_projection_far_units",
            "call pingo_set_projection_far_units",
        ):
            self.assertIn(required, natural)
            if "projection" not in required and "manager_survey_projection" not in required:
                self.assertIn(required, control)

        self.assertIn("terrain_manager_initial_ring: equ 5", natural)
        self.assertIn("manager_survey_projection_far_units: equ 65535", natural)
        self.assertIn("manager_survey_start_q: equ 80", natural)
        self.assertIn("manager_survey_start_r: equ 125", natural)
        self.assertIn("camera_initial_x: equ 4275", natural)
        self.assertIn("camera_initial_y: equ 8000", natural)
        self.assertIn("camera_initial_z: equ 466", natural)

    def test_committed_binary_has_common_entry_and_expected_identity(self) -> None:
        payload = PROGRAM.read_bytes()
        self.assertEqual(payload[:4], builder.FIXTURE_STUB)
        self.assertEqual(payload[0x40:0x45], builder.MOS_ADL_HEADER)
        self.assertEqual(len(payload), 37_531)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "cbf183d043e2a53b10e3ca355e2e9ec998782f07cb86780c62d10547202a1a96",
        )

    def test_natural_include_closure_is_adl_width_clean(self) -> None:
        result = audit_paths(include_closure([MAIN]))
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_fixture_assembles_deterministically(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            scratch = Path(directory)
            shutil.copytree(ROOT / "fixtures", scratch / "fixtures")
            shutil.copytree(ROOT / "runtime", scratch / "runtime")
            copied_main = scratch / MAIN.relative_to(ROOT)
            outputs = (scratch / "first.bin", scratch / "second.bin")
            for output in outputs:
                completed = subprocess.run(
                    ["ez80asm", copied_main.name, str(output), "-c"],
                    cwd=copied_main.parent,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    completed.returncode, 0, completed.stdout + completed.stderr
                )
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            self.assertEqual(outputs[0].read_bytes(), PROGRAM.read_bytes())


if __name__ == "__main__":
    unittest.main()
