import unittest

from pingo_terrain.flight_model import (
    CRUISE_THROTTLE,
    CRUISE_THRUST_Q8,
    FlightState,
    IDENTITY_Q15,
    INITIAL_SPEED_Q8,
    MAX_THRUST_Q8,
    POSITION_COUNT_METRES,
    TAKEOFF_SPEED_Q8,
    axis_matrix_q15,
    backdrop_attitude_words,
    backdrop_ground_quad,
    coordinated_yaw_step,
    damp_rate,
    lift_q8,
    thrust_q8,
    update_rate,
)


class FlightModelTests(unittest.TestCase):
    def test_level_cruise_throttle_preserves_exact_integer_trim(self):
        state = FlightState(position_q8=[0, 12345, 0])
        for _ in range(30 * 60):
            state.step()
        self.assertEqual(state.throttle, CRUISE_THROTTLE)
        self.assertEqual(state.thrust_q8, CRUISE_THRUST_Q8)
        self.assertEqual(state.velocity_q8, [0, 0, -INITIAL_SPEED_Q8])
        self.assertEqual(state.position_q8[1], 12345)
        self.assertEqual(state.force_q8, [0, 0, 0])
        self.assertEqual(state.acceleration_q8, [0, 0, 0])
        self.assertAlmostEqual(state.airspeed_mps, 33.75)

    def test_idle_aircraft_loses_speed_then_lift_and_descends(self):
        state = FlightState(throttle=0, position_q8=[0, 500000, 0])
        initial_altitude = state.position_q8[1]
        for _ in range(180):
            state.step()
        self.assertLess(state.airspeed_q8, INITIAL_SPEED_Q8)
        self.assertLess(state.position_q8[1], initial_altitude)
        self.assertLess(state.velocity_q8[1], 0)

    def test_high_angle_of_attack_reduces_lift(self):
        normal = lift_q8(INITIAL_SPEED_Q8, 0)
        half = lift_q8(INITIAL_SPEED_Q8, INITIAL_SPEED_Q8 // 2)
        quarter = lift_q8(INITIAL_SPEED_Q8, INITIAL_SPEED_Q8)
        self.assertEqual((normal, half, quarter), (45, 22, 11))

    def test_runway_support_is_not_general_collision(self):
        held = FlightState(
            velocity_q8=[0, -100, -1000],
            throttle=0,
            on_ground=True,
            ground_y_q8=77,
        )
        held.step()
        self.assertTrue(held.on_ground)
        self.assertEqual(held.velocity_q8[1], 0)
        self.assertEqual(held.position_q8[1], 77)

        released = FlightState(
            velocity_q8=[0, 100, -INITIAL_SPEED_Q8],
            on_ground=True,
            ground_y_q8=77,
            orientation_q15=axis_matrix_q15("x", 12.0),
        )
        released.step()
        self.assertFalse(released.on_ground)
        self.assertGreater(released.position_q8[1], 77)

    def test_rate_damping_and_moments_are_bounded(self):
        self.assertEqual(damp_rate(1), 0)
        self.assertEqual(damp_rate(-1), 0)
        self.assertEqual(damp_rate(160), 150)
        self.assertEqual(damp_rate(-160), -150)
        rate = 0
        for _ in range(1000):
            rate = update_rate(rate, 1, 24)
        self.assertLessEqual(rate, 512)
        for _ in range(1000):
            rate = update_rate(rate, 0, 24)
        self.assertEqual(rate, 0)

    def test_coordinated_yaw_uses_continuous_matrix_bank_proxy(self):
        self.assertEqual(
            coordinated_yaw_step(TAKEOFF_SPEED_Q8 - 1, axis_matrix_q15("z", 45)),
            0,
        )
        self.assertEqual(
            coordinated_yaw_step(TAKEOFF_SPEED_Q8, axis_matrix_q15("x", 8)),
            0,
        )
        self.assertEqual(
            coordinated_yaw_step(TAKEOFF_SPEED_Q8, axis_matrix_q15("y", -158)),
            0,
        )
        self.assertGreater(
            coordinated_yaw_step(TAKEOFF_SPEED_Q8, axis_matrix_q15("z", 45)),
            0,
        )
        self.assertLess(
            coordinated_yaw_step(TAKEOFF_SPEED_Q8, axis_matrix_q15("z", -45)),
            0,
        )

    def test_throttle_mapping_retains_trim_and_adds_full_power_reserve(self):
        self.assertEqual(thrust_q8(0), 0)
        self.assertEqual(thrust_q8(CRUISE_THROTTLE), CRUISE_THRUST_Q8)
        self.assertEqual(thrust_q8(255), MAX_THRUST_Q8)
        values = [thrust_q8(throttle) for throttle in range(256)]
        self.assertEqual(values, sorted(values))

    def test_w_ramp_and_modest_rotation_release_stationary_runway_start(self):
        state = FlightState(
            position_q8=[0, 0, 0],
            velocity_q8=[0, 0, 0],
            orientation_q15=IDENTITY_Q15,
            throttle=0,
            on_ground=True,
            ground_y_q8=0,
            airspeed_q8=0,
            lift_q8=0,
            thrust_q8=0,
        )
        rotation_tick = None
        release_tick = None
        for tick in range(1, 600):
            state.throttle = min(255, state.throttle + 4)
            if rotation_tick is None and state.airspeed_q8 >= TAKEOFF_SPEED_Q8:
                rotation_tick = tick
                state.orientation_q15 = axis_matrix_q15("x", 8.0)
            state.step()
            if not state.on_ground:
                release_tick = tick
                break

        self.assertEqual(rotation_tick, 190)
        self.assertEqual(release_tick, 393)
        self.assertEqual(state.throttle, 255)
        self.assertEqual(state.thrust_q8, MAX_THRUST_Q8)
        self.assertEqual(state.airspeed_q8, 4480)
        self.assertEqual(state.lift_q8, 43)
        self.assertEqual(state.force_q8, [0, 1, -4])
        self.assertEqual(state.velocity_q8, [0, 1, -4528])
        self.assertEqual(state.position_q8, [0, 1, -1098405])
        self.assertAlmostEqual(
            -state.position_q8[2] * POSITION_COUNT_METRES / 256.0,
            268.165283203125,
        )

    def test_level_backdrop_covers_far_beyond_viewport(self):
        h0, h1, g1, g0 = backdrop_ground_quad(0, 0)
        self.assertEqual((h0[1], h1[1]), (74, 74))
        self.assertLess(h0[0], 0)
        self.assertGreater(h1[0], 319)
        self.assertGreater(g0[1], 147)
        self.assertGreater(g1[1], 147)

    def test_pitch_and_roll_change_fallback_horizon(self):
        level = backdrop_ground_quad(0, 0)
        pitched = backdrop_ground_quad(2048, 0)
        rolled = backdrop_ground_quad(0, 4096)
        self.assertEqual(pitched[0][1] - level[0][1], 32)
        self.assertNotEqual(rolled[0][1], rolled[1][1])

    def test_backdrop_attitude_comes_from_matrix_world_up_row(self):
        self.assertEqual(backdrop_attitude_words(IDENTITY_Q15), (0, 0))
        self.assertEqual(
            backdrop_attitude_words(axis_matrix_q15("y", 137.0)),
            (0, 0),
        )
        self.assertEqual(
            backdrop_attitude_words(axis_matrix_q15("x", 8.0)),
            (768, 0),
        )
        self.assertEqual(
            backdrop_attitude_words(axis_matrix_q15("z", 45.0)),
            (0, 4096),
        )


if __name__ == "__main__":
    unittest.main()
