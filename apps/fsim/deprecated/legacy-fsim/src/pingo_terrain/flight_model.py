"""Integer reference contract for the first eZ80 light-flight model.

The assembly implementation lives in ``fixtures/berkeley-flight-fdm``.  This
module mirrors its force and integration arithmetic so constants, trim, stall
behavior, runway support, and horizon geometry can be tested without a GUI.
P3D remains authoritative for target-side trigonometric lookup and attitude
matrix maintenance; tests here use explicit Q15 matrices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, atan2, cos, pi, sin


Q15_ONE = 32767
GRAVITY_STEP_Q8 = -45
VELOCITY_LIMIT_Q8 = 8192
TAKEOFF_SPEED_Q8 = 3200
INITIAL_SPEED_Q8 = 4608
CRUISE_THROTTLE = 160
CRUISE_THRUST_Q8 = 18
MAX_THRUST_Q8 = 28
POSITION_COUNT_METRES = 0.0625
TICKS_PER_SECOND = 30

Vec3 = tuple[int, int, int]
Mat3 = tuple[int, int, int, int, int, int, int, int, int]
IDENTITY_Q15: Mat3 = (
    Q15_ONE,
    0,
    0,
    0,
    Q15_ONE,
    0,
    0,
    0,
    Q15_ONE,
)


def clamp(value: int, lower: int, upper: int) -> int:
    return min(upper, max(lower, value))


def round_div_q15(value: int) -> int:
    """Round a signed integer divided by 32767, away from neither side."""

    magnitude = abs(value)
    result = (magnitude + (Q15_ONE // 2)) // Q15_ONE
    return -result if value < 0 else result


def mat_vec_q15(matrix: Mat3, vector: Vec3) -> Vec3:
    return tuple(
        round_div_q15(sum(matrix[row * 3 + column] * vector[column] for column in range(3)))
        for row in range(3)
    )  # type: ignore[return-value]


def transpose(matrix: Mat3) -> Mat3:
    return tuple(matrix[column * 3 + row] for row in range(3) for column in range(3))  # type: ignore[return-value]


def axis_matrix_q15(axis: str, degrees: float) -> Mat3:
    """Construct a host-only explicit Q15 axis matrix for invariant tests."""

    angle = degrees * pi / 180.0
    c = round(cos(angle) * Q15_ONE)
    s = round(sin(angle) * Q15_ONE)
    if axis == "x":
        return (Q15_ONE, 0, 0, 0, c, -s, 0, s, c)
    if axis == "y":
        return (c, 0, s, 0, Q15_ONE, 0, -s, 0, c)
    if axis == "z":
        return (c, -s, 0, s, c, 0, 0, 0, Q15_ONE)
    raise ValueError(f"unknown axis: {axis}")


def damp_rate(rate: int) -> int:
    """Mirror the assembly's 1/16 decay with a one-count minimum."""

    if rate == 0:
        return 0
    decay = max(1, abs(rate) >> 4)
    return rate - decay if rate > 0 else rate + decay


def update_rate(rate: int, demand: int, moment: int, limit: int = 512) -> int:
    if demand not in (-1, 0, 1):
        raise ValueError("control demand must be -1, 0, or 1")
    return clamp(damp_rate(rate) + demand * moment, -limit, limit)


def coordinated_yaw_step(airspeed_q8: int, orientation_q15: Mat3) -> int:
    """Return the target's continuous bank-to-yaw feedback contribution."""

    if airspeed_q8 < TAKEOFF_SPEED_Q8:
        return 0
    # Row 1, column 0 is world-Y in the aircraft's local-right basis vector.
    # Unlike an exported Euler branch, it stays continuous through yawed pitch.
    return orientation_q15[3] >> 12


def _coarse_angle_word(radians: float) -> int:
    """Mirror P3D's nearest 1/256-turn inverse-trig result domain."""

    exact = radians * 32768.0 / (2.0 * pi)
    magnitude = int((abs(exact) + 64.0) // 128.0) * 128
    quantized = -magnitude if exact < 0.0 else magnitude
    return ((quantized + 16384) % 32768) - 16384


def backdrop_attitude_words(orientation_q15: Mat3) -> tuple[int, int]:
    """Return branch-free pitch/roll words for the 2D fallback horizon."""

    up_right = orientation_q15[3]
    up_up = orientation_q15[4]
    up_forward = orientation_q15[5]
    pitch_sine = clamp(-up_forward, -Q15_ONE, Q15_ONE) / Q15_ONE
    pitch = _coarse_angle_word(asin(pitch_sine))
    roll = _coarse_angle_word(atan2(up_right, up_up))
    return pitch, roll


def thrust_q8(throttle: int) -> int:
    if throttle not in range(256):
        raise ValueError("throttle must be in 0..255")
    return (throttle >> 3) - (throttle >> 6)


def lift_q8(forward_speed_q8: int, body_vertical_q8: int) -> int:
    speed = clamp(forward_speed_q8, 0, VELOCITY_LIMIT_Q8)
    lift = (speed >> 7) + (speed >> 9)
    vertical = abs(body_vertical_q8)
    if vertical >= speed:
        return lift >> 2
    if vertical >= (speed >> 1):
        return lift >> 1
    return lift


@dataclass(slots=True)
class FlightState:
    """First-model position/velocity state in the target integer domains."""

    position_q8: list[int] = field(default_factory=lambda: [0, 0, 0])
    velocity_q8: list[int] = field(
        default_factory=lambda: [0, 0, -INITIAL_SPEED_Q8]
    )
    orientation_q15: Mat3 = IDENTITY_Q15
    throttle: int = CRUISE_THROTTLE
    on_ground: bool = False
    ground_y_q8: int = 0
    force_q8: list[int] = field(default_factory=lambda: [0, 0, 0])
    acceleration_q8: list[int] = field(default_factory=lambda: [0, 0, 0])
    airspeed_q8: int = INITIAL_SPEED_Q8
    lift_q8: int = 45
    thrust_q8: int = CRUISE_THRUST_Q8

    def step(self) -> None:
        body_velocity = mat_vec_q15(
            transpose(self.orientation_q15), tuple(self.velocity_q8)
        )
        self.airspeed_q8 = clamp(-body_velocity[2], 0, VELOCITY_LIMIT_Q8)
        self.lift_q8 = lift_q8(self.airspeed_q8, body_velocity[1])
        self.thrust_q8 = thrust_q8(self.throttle)

        local_force = (0, self.lift_q8, -self.thrust_q8)
        aero = mat_vec_q15(self.orientation_q15, local_force)
        force = [
            aero[index] - (self.velocity_q8[index] >> 8)
            for index in range(3)
        ]
        force[1] += GRAVITY_STEP_Q8
        self.force_q8[:] = force
        # The first aircraft uses normalized unit mass.  Retain this separate
        # vector so a later reciprocal-mass step does not change integration.
        self.acceleration_q8[:] = force
        self.velocity_q8[:] = [
            clamp(
                self.velocity_q8[index] + self.acceleration_q8[index],
                -VELOCITY_LIMIT_Q8,
                VELOCITY_LIMIT_Q8,
            )
            for index in range(3)
        ]

        if self.on_ground:
            if self.velocity_q8[1] > 0 and self.airspeed_q8 >= TAKEOFF_SPEED_Q8:
                self.on_ground = False
            else:
                self.velocity_q8[1] = 0

        for index in (0, 2):
            self.position_q8[index] += self.velocity_q8[index]
        if self.on_ground:
            self.position_q8[1] = self.ground_y_q8
        else:
            self.position_q8[1] += self.velocity_q8[1]

    @property
    def airspeed_mps(self) -> float:
        raw_counts_per_tick = self.airspeed_q8 / 256.0
        return raw_counts_per_tick * POSITION_COUNT_METRES * TICKS_PER_SECOND


def backdrop_ground_quad(
    pitch_word: int,
    roll_word: int,
    *,
    width: int = 320,
    height: int = 148,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Mirror the eZ80's deliberately oversized clipped ground quadrilateral."""

    angle = roll_word * 2.0 * pi / Q15_ONE
    sin_r512 = round(sin(angle) * Q15_ONE) >> 6
    cos_r512 = round(cos(angle) * Q15_ONE) >> 6
    horizon_y = height // 2 + (pitch_word >> 6)
    h0 = (width // 2 - cos_r512, horizon_y - sin_r512)
    h1 = (width // 2 + cos_r512, horizon_y + sin_r512)
    down = (-2 * sin_r512, 2 * cos_r512)
    g0 = (h0[0] + down[0], h0[1] + down[1])
    g1 = (h1[0] + down[0], h1[1] + down[1])
    return h0, h1, g1, g0
