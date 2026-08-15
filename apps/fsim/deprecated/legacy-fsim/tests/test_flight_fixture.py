from __future__ import annotations

import hashlib
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/berkeley-flight-fdm"
ACCEPTED = ROOT / "fixtures/berkeley-flight-triangular-dither"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FlightFixtureSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (FIXTURE / "src/berkeley-flight-fdm.asm").read_text()
        cls.model = (FIXTURE / "src/flight-input.inc").read_text()
        cls.backdrop = (FIXTURE / "src/flight-backdrop.inc").read_text()
        cls.render = (FIXTURE / "src/render-async.inc").read_text()

    def test_accepted_terrain_geometry_is_preserved_byte_for_byte(self):
        accepted = sorted((ACCEPTED / "src/generated").glob("terrain_*.inc"))
        derived = sorted((FIXTURE / "src/generated").glob("terrain_*.inc"))
        self.assertEqual(len(accepted), 32)
        self.assertEqual([path.name for path in accepted], [path.name for path in derived])
        self.assertEqual([sha256(path) for path in accepted], [sha256(path) for path in derived])
        for name in (
            "terrain-material-ids.rgba2",
            "terrain-pattern-lookup.bin",
            "terrain-patterns.rgba2",
        ):
            self.assertEqual(
                sha256(ACCEPTED / "tgt" / name), sha256(FIXTURE / "tgt" / name)
            )

    def test_model_uses_force_inertia_and_proven_p3d_primitives(self):
        for required in (
            "flight_velocity_q8",
            "flight_force_q8",
            "flight_acceleration_q8",
            "flight_angular_acceleration",
            "call p3d_object_step16",
            "call p3d_mat3_mul_vec3_16",
            "call p3d_vec3_translate16",
            "flight_gravity_step_q8: equ -45",
            "flight_flag_on_ground",
        ):
            self.assertIn(required, self.model)

    def test_target_thrust_map_preserves_cruise_trim_and_full_power_reserve(self):
        for required in (
            "flight_cruise_throttle: equ 160",
            "flight_cruise_thrust_q8: equ 18",
            "flight_max_thrust_q8: equ 28",
            "ld a,flight_cruise_throttle",
            "(throttle>>3)-(throttle>>6)",
        ):
            self.assertIn(required, self.model)
        thrust = self.model.split("@thrust:", 1)[1].split(
            "flight_half_lift:", 1
        )[0]
        self.assertEqual(thrust.count("srl a"), 9)
        self.assertIn("sub b", thrust)

    def test_coordinated_turn_uses_matrix_bank_not_ambiguous_euler_branch(self):
        yaw = self.model.split("; A restrained bank-to-yaw", 1)[1].split(
            "@store_yaw:", 1
        )[0]
        self.assertIn("p3d_object_orientation+p3d_mat3_r1c0", yaw)
        self.assertNotIn("p3d_object_pingo_rotation", yaw)
        self.assertIn("ld a,12", yaw)

    def test_positions_are_exact_24_bit_and_wide_accesses_are_confined(self):
        for axis in "xyz":
            self.assertRegex(self.model, rf"flight_position_{axis}_q8:\s+dl 0")
        wide_targets = re.findall(
            r"ld\s+(?:hl,\(([^)]+)\)|\(([^)]+)\),hl)", self.model
        )
        flattened = [left or right for left, right in wide_targets]
        self.assertTrue(flattened)
        self.assertTrue(
            all(
                target.startswith("flight_position_")
                or target.startswith("flight_ground_y_q8")
                for target in flattened
            )
        )

    def test_backdrop_uses_four_filled_triangles_and_byte_patching(self):
        packet = self.backdrop.split("backdrop_packet:", 1)[1].split(
            "backdrop_packet_end:", 1
        )[0]
        self.assertEqual(packet.count("backdrop_plot_triangle_absolute"), 4)
        self.assertNotRegex(self.backdrop, r"ld\s+\(backdrop_t[^)]+\),\s*(?:hl|de|bc)")
        self.assertRegex(
            self.render,
            r"call draw_flight_backdrop\s+DISPBMP tgtbmid,viewport_x,viewport_y",
        )

    def test_backdrop_uses_branch_free_matrix_attitude(self):
        extractor = self.backdrop.split("backdrop_extract_attitude:", 1)[1].split(
            "draw_flight_backdrop:", 1
        )[0]
        for element in ("p3d_mat3_r1c0", "p3d_mat3_r1c1", "p3d_mat3_r1c2"):
            self.assertIn(element, extractor)
        self.assertIn("call p3d_asin16", extractor)
        self.assertIn("call p3d_atan2_16", extractor)
        draw = self.backdrop.split("draw_flight_backdrop:", 1)[1].split(
            "backdrop_shift_hl_6:", 1
        )[0]
        self.assertNotIn("p3d_object_pingo_rotation", draw)

    def test_cockpit_owns_lower_92_rows(self):
        self.assertIn("viewport_height: equ 148", self.main)
        cockpit = (FIXTURE / "src/cockpit.inc").read_text()
        self.assertIn("cockpit_height: equ 92", cockpit)
        self.assertIn("cockpit_y: equ 148", cockpit)
        self.assertIn("DISPBMP cockpit_bmid,cockpit_x,cockpit_y", cockpit)

    def test_authored_panel_checksum_is_pinned(self):
        panel = ROOT / "assets/cockpit/fsimpanel.png"
        self.assertEqual(
            sha256(panel),
            "4beb8066ea7baa53914d0c02e67e53b41519f7bdd1da89f30903349527bd7b36",
        )


if __name__ == "__main__":
    unittest.main()
