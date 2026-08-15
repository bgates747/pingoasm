from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

from pingo_terrain.adl_width import audit_paths
from pingo_terrain.aircraft_view import ViewMode, camera_solution
from pingo_terrain.flight_model import axis_matrix_q15
from pingo_terrain.p3dm import parse_container


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/koak-flight-streamed"
SOURCE = FIXTURE / "src"
PROOF = ROOT / "build/p3dm/bay-area-koak-proof"


class KOAKStreamedFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (SOURCE / "koak-flight-streamed.asm").read_text()
        cls.streaming = (SOURCE / "regional-streaming.inc").read_text()
        cls.scene = (SOURCE / "streaming-scene.inc").read_text()
        cls.backdrop = (SOURCE / "flight-backdrop.inc").read_text()

    def test_stable_scene_has_25_terrain_slots_and_paired_airport_slots(self) -> None:
        invocations = re.findall(
            r"^\s*ESTABLISH_TERRAIN_SLOT\s+(\d+)\s*$",
            self.scene,
            flags=re.MULTILINE,
        )
        self.assertEqual([int(value) for value in invocations], list(range(1, 26)))
        airport_invocations = re.findall(
            r"^\s*ESTABLISH_AIRPORT_SLOT\s+(?!SLOT)(\S+)\s*$",
            self.scene,
            flags=re.MULTILINE,
        )
        self.assertEqual(len(airport_invocations), 2)
        self.assertIn("aircraft_mesh_id: equ 201", self.main)
        self.assertIn("active_object_limit", (ROOT / "scripts/build_koak_flight_streamed.py").read_text())

    def test_startup_loads_current_terrain_then_both_airport_components(self) -> None:
        startup = self.streaming.split("streaming_load_startup:", 1)[1].split(
            "streaming_request_airport_pavement:", 1
        )[0]
        sequence = (
            "call streaming_load_desired_terrain",
            "ld hl,koak_pavement_path",
            "call streaming_request_airport_pavement",
            "ld hl,koak_marking_path",
            "call streaming_request_airport_marking",
            "ld (streaming_airport_pair_loaded),a",
            "call streaming_reposition_airport",
        )
        offsets = [startup.index(item) for item in sequence]
        self.assertEqual(offsets, sorted(offsets))
        self.assertNotIn("call pingo_set_object_active", startup)

    def test_service_is_render_idle_and_loads_at_most_one_component(self) -> None:
        loop = self.main.split("@loop:", 1)[1].split("@exit:", 1)[0]
        self.assertLess(loop.index("ld a,(render_in_flight)"), loop.index("call streaming_service_one"))
        self.assertLess(loop.index("call streaming_service_one"), loop.index("call submit_current_render"))
        service = self.streaming.split("streaming_service_one:", 1)[1].split(
            "streaming_compute_direct_slot:", 1
        )[0]
        self.assertEqual(service.count("call streaming_load_desired_terrain"), 1)
        self.assertIn("ret", service.split("call streaming_load_desired_terrain", 1)[1])

    def test_direct_slot_match_requires_active_residency(self) -> None:
        matcher = self.streaming.split("streaming_slot_matches_desired:", 1)[1].split(
            "streaming_load_desired_terrain:", 1
        )[0]
        self.assertIn("streaming_slot_active", matcher)
        self.assertRegex(matcher, r"ld a,\(hl\)\s+cp 1\s+ret")

    def test_z_delta_scratch_preserves_completed_x_transform(self) -> None:
        positioner = self.streaming.split(
            "streaming_position_desired_terrain:", 1
        )[1].split("streaming_delta_to_count:", 1)[0]
        after_x = positioner.split("pop bc", 1)[1]
        before_z_conversion = after_x.split("call streaming_delta_to_count", 1)[0]
        self.assertNotRegex(before_z_conversion, r"ld c\s*,")
        self.assertRegex(
            before_z_conversion,
            r"ld a,\(streaming_coarse_x\)\s+"
            r"ld hl,streaming_desired_x\s+sub \(hl\)",
        )

    def test_canonical_aircraft_reference_produces_exact_28l_camera(self) -> None:
        degrees = -14411 * 360.0 / 32768.0
        flat = axis_matrix_q15("y", degrees)
        orientation = (flat[0:3], flat[3:6], flat[6:9])
        solution = camera_solution(
            ViewMode.COCKPIT,
            aircraft_position=(3088, 44, 2181),
            aircraft_rotation=(0, -14411, 0),
            aircraft_orientation=orientation,
        )
        self.assertEqual(solution.position, (3106, 64, 2226))
        self.assertFalse(solution.aircraft_active)

    def test_backdrop_uses_camera_attitude_and_four_filled_triangles(self) -> None:
        self.assertIn("camera_state+p3d_camera_orientation", self.backdrop)
        self.assertIn("call p3d_asin16", self.backdrop)
        self.assertIn("call p3d_atan2_16", self.backdrop)
        draw = self.backdrop.split("draw_flight_backdrop:", 1)[1].split(
            "backdrop_shift_hl_6:", 1
        )[0]
        self.assertNotIn("p3d_camera_pingo_rotation", draw)
        self.assertNotIn("object_state+p3d_object_pingo_rotation", self.backdrop)
        packet = self.backdrop.split("backdrop_packet:", 1)[1].split(
            "backdrop_packet_end:", 1
        )[0]
        self.assertEqual(packet.count("backdrop_plot_triangle_absolute"), 4)

    def test_new_assembly_has_no_fixed_width_hazard(self) -> None:
        result = audit_paths(
            [
                SOURCE / "koak-flight-streamed.asm",
                SOURCE / "regional-streaming.inc",
                SOURCE / "streaming-vdu.inc",
                SOURCE / "streaming-scene.inc",
                SOURCE / "flight-backdrop.inc",
            ]
        )
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    def test_generated_binary_and_center_container_are_self_consistent(self) -> None:
        report_path = PROOF / "FLIGHT.json"
        if not report_path.is_file():
            self.skipTest("ignored regional proof corpus has not been built")
        report = json.loads(report_path.read_text())
        binary = PROOF / report["binary"]["path"]
        self.assertEqual(binary.stat().st_size, report["binary"]["bytes"])
        self.assertEqual(
            hashlib.sha256(binary.read_bytes()).hexdigest(),
            report["binary"]["sha256"],
        )
        terrain = parse_container((PROOF / "TRN/L0/73/00.AGN").read_bytes())
        self.assertEqual((terrain.meta.tile_x, terrain.meta.tile_y), (94, 146))
        self.assertEqual(report["canonical_camera"]["translation_counts"], [3106, 64, 2226])


if __name__ == "__main__":
    unittest.main()
