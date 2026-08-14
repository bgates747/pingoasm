"""Deterministic host reference for cockpit and local-offset chase views.

Pingo translation words are treated as exact 1/16-metre counts.  Aircraft
orientation is the retained P3D signed-Q15 local-to-world matrix; the eZ80
integration uses the same ``p3d_mat3_mul_vec3_16`` primitive.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


Vec3 = tuple[int, int, int]
Mat3 = tuple[Vec3, Vec3, Vec3]

Q15_ONE = 32_767
PINGO_COUNTS_PER_METRE = 16
PINGO_WORLD_UNIT_METRES = 8
Q8_8_ONE = 256

# The donor OBJ's largest absolute coordinate is 7.419411 m.  Rounding the
# physical half extent to 7.5 m gives an exactly representable Q8.8 scale and
# changes the donor dimensions by only 1.086 percent.
JET_MODEL_HALF_EXTENT_METRES = 7.5
JET_OBJECT_SCALE_Q8_8 = 240

# Local -Z is forward.  All offsets are exact Pingo translation counts.
COCKPIT_EYE_LOCAL: Vec3 = (0, 20, -48)       # 0, +1.25, -3.00 m
CHASE_CAMERA_LOCAL: Vec3 = (0, 80, 288)      # 0, +5.00, +18.00 m
CHASE_TARGET_LOCAL: Vec3 = (0, 16, -48)      # 0, +1.00, -3.00 m

# MOS maps physical V to BBC virtual key 100: byte (100-1)//8, bit (100-1)%8.
VIEW_KEY_VKEYCODE = 100
VIEW_KEY_BYTE = 12
VIEW_KEY_BIT = 3

SCENE_RENDERABLE_LIMIT = 32
DEFAULT_TERRAIN_ACTIVE = 25
DEFAULT_KOAK_ACTIVE = 2


class ViewMode(IntEnum):
    COCKPIT = 0
    CHASE = 1


@dataclass(frozen=True)
class ViewToggleState:
    """One rising-edge latch for the V view key."""

    mode: ViewMode = ViewMode.COCKPIT
    key_latched: bool = False


@dataclass(frozen=True)
class CameraSolution:
    """Camera data before the qualified P3D look-at solver runs.

    Cockpit mode submits ``direct_rotation`` exactly from the aircraft pose.
    Chase mode submits ``aim_target`` to ``p3d_camera_aim_at_point16`` with
    upright-roll policy.  Exactly one of those fields is populated.
    """

    mode: ViewMode
    position: Vec3
    direct_rotation: Vec3 | None
    aim_target: Vec3 | None
    aircraft_active: bool


def _checked_i16(value: int, *, name: str) -> int:
    if not isinstance(value, int) or not -32_768 <= value <= 32_767:
        raise OverflowError(f"{name} is outside signed 16-bit range: {value!r}")
    return value


def _checked_vec3(value: Vec3, *, name: str) -> Vec3:
    if len(value) != 3:
        raise ValueError(f"{name} needs exactly three components")
    return tuple(
        _checked_i16(component, name=f"{name} component {axis}")
        for axis, component in enumerate(value)
    )  # type: ignore[return-value]


def _round_q15(total: int) -> int:
    """Match P3D's nearest-integer signed division by 32767."""

    magnitude = abs(total)
    result = (magnitude + 16_383) // Q15_ONE
    if total < 0:
        result = -result
    return _checked_i16(result, name="normalized dot product")


def transform_local_q15(vector: Vec3, orientation: Mat3) -> Vec3:
    """Transform one local translation-count vector into world axes."""

    vector = _checked_vec3(vector, name="local vector")
    if len(orientation) != 3:
        raise ValueError("an orientation needs exactly three matrix rows")
    transformed: list[int] = []
    for row in orientation:
        if len(row) != 3:
            raise ValueError("every orientation row needs three coefficients")
        for coefficient in row:
            if not -Q15_ONE <= coefficient <= Q15_ONE:
                raise ValueError(f"invalid signed-Q15 coefficient: {coefficient}")
        transformed.append(
            _round_q15(sum(value * coefficient for value, coefficient in zip(vector, row)))
        )
    return tuple(transformed)  # type: ignore[return-value]


def add_translation(left: Vec3, right: Vec3) -> Vec3:
    """Add two signed Pingo vec3 values, rejecting packet overflow."""

    left = _checked_vec3(left, name="left translation")
    right = _checked_vec3(right, name="right translation")
    return tuple(
        _checked_i16(a + b, name=f"world component {axis}")
        for axis, (a, b) in enumerate(zip(left, right))
    )  # type: ignore[return-value]


def camera_solution(
    mode: ViewMode,
    *,
    aircraft_position: Vec3,
    aircraft_rotation: Vec3,
    aircraft_orientation: Mat3,
) -> CameraSolution:
    """Build the exact camera position and orientation/aim submission."""

    aircraft_position = _checked_vec3(
        aircraft_position, name="aircraft position"
    )
    aircraft_rotation = _checked_vec3(
        aircraft_rotation, name="aircraft rotation"
    )

    if mode is ViewMode.COCKPIT:
        position = add_translation(
            aircraft_position,
            transform_local_q15(COCKPIT_EYE_LOCAL, aircraft_orientation),
        )
        return CameraSolution(
            mode=mode,
            position=position,
            direct_rotation=aircraft_rotation,
            aim_target=None,
            aircraft_active=False,
        )
    if mode is ViewMode.CHASE:
        position = add_translation(
            aircraft_position,
            transform_local_q15(CHASE_CAMERA_LOCAL, aircraft_orientation),
        )
        target = add_translation(
            aircraft_position,
            transform_local_q15(CHASE_TARGET_LOCAL, aircraft_orientation),
        )
        return CameraSolution(
            mode=mode,
            position=position,
            direct_rotation=None,
            aim_target=target,
            aircraft_active=True,
        )
    raise ValueError(f"unsupported view mode: {mode!r}")


def advance_view_toggle(
    state: ViewToggleState, *, view_key_down: bool
) -> tuple[ViewToggleState, bool]:
    """Apply one simulation quantum of rising-edge view-toggle input."""

    if not view_key_down:
        return ViewToggleState(mode=state.mode, key_latched=False), False
    if state.key_latched:
        return state, False
    mode = ViewMode.CHASE if state.mode is ViewMode.COCKPIT else ViewMode.COCKPIT
    return ViewToggleState(mode=mode, key_latched=True), True


def active_renderables(
    mode: ViewMode,
    *,
    terrain: int = DEFAULT_TERRAIN_ACTIVE,
    airport: int = DEFAULT_KOAK_ACTIVE,
) -> int:
    """Return the active scene count for the accepted streamed-flight budget."""

    if mode not in (ViewMode.COCKPIT, ViewMode.CHASE):
        raise ValueError(f"unsupported view mode: {mode!r}")
    if terrain < 0 or airport < 0:
        raise ValueError("active component counts cannot be negative")
    return terrain + airport + int(mode is ViewMode.CHASE)


def scale_half_extent_metres(scale_q8_8: int) -> float:
    """Decode Pingo object scale into a normalized mesh's half extent."""

    if not 0 <= scale_q8_8 <= 0xFFFF:
        raise ValueError("Pingo object scale must be an unsigned word")
    return scale_q8_8 / Q8_8_ONE * PINGO_WORLD_UNIT_METRES
