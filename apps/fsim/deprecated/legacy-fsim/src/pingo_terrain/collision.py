"""Layered fixed-point terrain and airport collision reference.

This module is deliberately independent of the active eZ80 flight fixture.  It
defines the conservative broad/narrow-phase contract that a later C1 target
port can mirror:

* closed fixed-point aircraft sweeps reject distant tiles without division;
* outward-rounded P3DM elevation extrema reject aircraft certainly above a
  tile and identify aircraft certainly buried beneath its mesh envelope;
* detailed terrain or airport boxes are consulted only after those cheap
  tests admit possible contact; and
* an explicit oriented runway region can retain or acquire support without
  turning every low-altitude state into generic terrain collision.

Horizontal coordinates are signed Q8 *translation counts* relative to the
regional south-west origin.  There are 16 translation counts per metre and
256 fractions per count, hence 4096 units per metre.  Altitude and velocity
use the existing F2 position-Q8 and velocity-Q8 domains respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .p3dm import LayerKind, P3DMTile, validate_tile
from .streaming import (
    DEFAULT_TILE_SIZE_M,
    POSITION_Q8_PER_METRE,
    RegionalGrid,
    FloatingOriginPosition,
)


Q15_ONE = 32_767
REGIONAL_VERTICAL_ORIGIN_Q8 = 608 * POSITION_Q8_PER_METRE
DEFAULT_LOOKAHEAD_TICKS = 30
RUNWAY_PROJECTION_ERROR_COUNTS = 2

# These are proven upper envelopes for the current F2 force laws, not new
# aerodynamic constants.  A deliberately loose component-wise bound is 140
# velocity-Q8/tick horizontally and 185 downward after gravity, transformed
# lift/thrust, drag, and Q15 rounding.  Rounded margins keep the later target
# arithmetic simple.  They must be revisited if F2 force construction changes.
MAX_HORIZONTAL_ACCEL_Q8 = 160
MAX_DOWNWARD_ACCEL_Q8 = 192

I16_MIN = -0x8000
I16_MAX = 0x7FFF
I32_MIN = -0x80000000
I32_MAX = 0x7FFFFFFF


def _require_int(name: str, value: int, low: int, high: int) -> None:
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}: {value!r}")


def _floor_fraction(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("fixed-point denominator must be positive")
    return numerator // denominator


def _ceil_fraction(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("fixed-point denominator must be positive")
    return -((-numerator) // denominator)


def elevation_dm_floor_q8(elevation_dm: int) -> int:
    """Round a descriptor lower bound down into position-Q8 units."""

    _require_int("elevation_dm", elevation_dm, I16_MIN, I16_MAX)
    return _floor_fraction(elevation_dm * POSITION_Q8_PER_METRE, 10)


def elevation_dm_ceil_q8(elevation_dm: int) -> int:
    """Round a descriptor upper bound up into position-Q8 units."""

    _require_int("elevation_dm", elevation_dm, I16_MIN, I16_MAX)
    return _ceil_fraction(elevation_dm * POSITION_Q8_PER_METRE, 10)


@dataclass(frozen=True, slots=True)
class CollisionPose:
    """One aircraft reference position in regional position-Q8 coordinates."""

    east_q8: int
    north_q8: int
    altitude_q8: int

    def __post_init__(self) -> None:
        for name in ("east_q8", "north_q8", "altitude_q8"):
            _require_int(name, getattr(self, name), I32_MIN, I32_MAX)

    @classmethod
    def from_floating_origin(
        cls,
        grid: RegionalGrid,
        position: FloatingOriginPosition,
        altitude_q8: int,
    ) -> "CollisionPose":
        """Convert J1 coarse/fine state without introducing a new world axis."""

        if not position.is_canonical(grid):
            raise ValueError("collision input must use a canonical floating origin")
        half_tile_q8 = grid.half_tile_position_q8
        return cls(
            east_q8=position.tile_x * grid.tile_position_q8
            + half_tile_q8
            + position.east_q8,
            north_q8=position.tile_y * grid.tile_position_q8
            + half_tile_q8
            + position.north_q8,
            altitude_q8=altitude_q8,
        )


@dataclass(frozen=True, slots=True)
class AircraftProxy:
    """Closed axis-aligned proxy guaranteed to contain the aircraft body."""

    half_east_q8: int
    half_north_q8: int
    below_reference_q8: int
    above_reference_q8: int

    def __post_init__(self) -> None:
        for name in (
            "half_east_q8",
            "half_north_q8",
            "below_reference_q8",
            "above_reference_q8",
        ):
            _require_int(name, getattr(self, name), 0, I32_MAX)


@dataclass(frozen=True, slots=True)
class AircraftSweep:
    """One already-integrated simulation step plus retained end velocity."""

    start: CollisionPose
    end: CollisionPose
    proxy: AircraftProxy
    velocity_east_q8: int = 0
    velocity_north_q8: int = 0
    velocity_up_q8: int = 0
    was_runway_supported: bool = False

    def __post_init__(self) -> None:
        for name in (
            "velocity_east_q8",
            "velocity_north_q8",
            "velocity_up_q8",
        ):
            _require_int(name, getattr(self, name), I16_MIN, I16_MAX)


@dataclass(frozen=True, slots=True)
class ClosedAABB:
    """A closed regional east/north/altitude box in position-Q8 units."""

    minimum_east_q8: int
    minimum_north_q8: int
    minimum_altitude_q8: int
    maximum_east_q8: int
    maximum_north_q8: int
    maximum_altitude_q8: int

    def __post_init__(self) -> None:
        values = (
            self.minimum_east_q8,
            self.minimum_north_q8,
            self.minimum_altitude_q8,
            self.maximum_east_q8,
            self.maximum_north_q8,
            self.maximum_altitude_q8,
        )
        if any(not isinstance(value, int) for value in values):
            raise TypeError("collision box coordinates must be integers")
        if self.minimum_east_q8 > self.maximum_east_q8:
            raise ValueError("collision box east bounds are inverted")
        if self.minimum_north_q8 > self.maximum_north_q8:
            raise ValueError("collision box north bounds are inverted")
        if self.minimum_altitude_q8 > self.maximum_altitude_q8:
            raise ValueError("collision box altitude bounds are inverted")
        for index, value in enumerate(values):
            _require_int(f"collision_box[{index}]", value, I32_MIN, I32_MAX)

    def intersects(self, other: "ClosedAABB") -> bool:
        """Return closed intersection: equality is possible contact."""

        return not (
            self.maximum_east_q8 < other.minimum_east_q8
            or other.maximum_east_q8 < self.minimum_east_q8
            or self.maximum_north_q8 < other.minimum_north_q8
            or other.maximum_north_q8 < self.minimum_north_q8
            or self.maximum_altitude_q8 < other.minimum_altitude_q8
            or other.maximum_altitude_q8 < self.minimum_altitude_q8
        )

    def intersects_horizontally(self, other: "ClosedAABB") -> bool:
        return not (
            self.maximum_east_q8 < other.minimum_east_q8
            or other.maximum_east_q8 < self.minimum_east_q8
            or self.maximum_north_q8 < other.minimum_north_q8
            or other.maximum_north_q8 < self.minimum_north_q8
        )


@dataclass(frozen=True, slots=True)
class TerrainEnvelope:
    """Cheap fixed descriptor data retained with a resident P3DM terrain tile."""

    tile_x: int
    tile_y: int
    minimum_elevation_dm: int
    maximum_elevation_dm: int
    model_half_extent_m: int

    def __post_init__(self) -> None:
        _require_int("tile_x", self.tile_x, 0, I16_MAX)
        _require_int("tile_y", self.tile_y, 0, I16_MAX)
        _require_int(
            "minimum_elevation_dm", self.minimum_elevation_dm, I16_MIN, I16_MAX
        )
        _require_int(
            "maximum_elevation_dm", self.maximum_elevation_dm, I16_MIN, I16_MAX
        )
        if self.minimum_elevation_dm > self.maximum_elevation_dm:
            raise ValueError("terrain envelope minimum exceeds maximum")
        _require_int("model_half_extent_m", self.model_half_extent_m, 1, 0xFFFF)

    @classmethod
    def from_p3dm(cls, tile: P3DMTile) -> "TerrainEnvelope":
        validate_tile(tile)
        if tile.meta.layer_kind is not LayerKind.TERRAIN:
            raise ValueError("terrain envelope requires a terrain P3DM tile")
        return cls(
            tile.meta.tile_x,
            tile.meta.tile_y,
            tile.meta.minimum_elevation_dm,
            tile.meta.maximum_elevation_dm,
            tile.meta.model_half_extent_m,
        )

    @property
    def decode_error_q8(self) -> int:
        return _ceil_fraction(
            self.model_half_extent_m * POSITION_Q8_PER_METRE,
            2 * Q15_ONE,
        )

    @property
    def collision_slack_q8(self) -> int:
        # A decoded vertex can lie one half-error beyond the descriptor's
        # source extremum, and the narrow box expands once more to recover the
        # source position.  One final Q8 quantum covers nested ceil operations.
        return 2 * self.decode_error_q8 + 1

    @property
    def minimum_altitude_q8(self) -> int:
        return elevation_dm_floor_q8(self.minimum_elevation_dm) - self.collision_slack_q8

    @property
    def maximum_altitude_q8(self) -> int:
        return elevation_dm_ceil_q8(self.maximum_elevation_dm) + self.collision_slack_q8


@dataclass(frozen=True, slots=True)
class TerrainSurfaceBox:
    """Conservative AABB for one or more upward terrain surface triangles."""

    identifier: int
    bounds: ClosedAABB


@dataclass(frozen=True, slots=True)
class AirportEnvelope:
    """Cheap airport-group broad-phase bounds; detail lives in a separate map."""

    identifier: str
    bounds: ClosedAABB

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("airport envelope identifier cannot be empty")


@dataclass(frozen=True, slots=True)
class AirportContactBox:
    identifier: str
    bounds: ClosedAABB

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("airport contact identifier cannot be empty")


@dataclass(frozen=True, slots=True)
class RunwaySupportRegion:
    """One oriented runway rectangle and the aircraft-reference support plane.

    The horizontal centre is regional position-Q8, but projection first drops
    the low eight fractional-count bits.  Its Q15 dot products therefore use
    signed 16-bit translation-count operands inside an activated airport and a
    signed 32-bit product/accumulator on eZ80.
    """

    identifier: str
    center_east_q8: int
    center_north_q8: int
    along_east_q15: int
    along_north_q15: int
    half_length_counts: int
    half_width_counts: int
    reference_altitude_q8: int
    retain_above_q8: int = POSITION_Q8_PER_METRE // 2
    penetration_q8: int = POSITION_Q8_PER_METRE // 2
    maximum_touchdown_descent_q8: int = 512

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("runway identifier cannot be empty")
        for name in ("center_east_q8", "center_north_q8", "reference_altitude_q8"):
            _require_int(name, getattr(self, name), I32_MIN, I32_MAX)
        for name in ("along_east_q15", "along_north_q15"):
            _require_int(name, getattr(self, name), -Q15_ONE, Q15_ONE)
        norm_squared = self.along_east_q15**2 + self.along_north_q15**2
        if abs(norm_squared - Q15_ONE**2) > Q15_ONE * 4:
            raise ValueError("runway along axis must be unit length within Q15 rounding")
        for name in ("half_length_counts", "half_width_counts"):
            _require_int(name, getattr(self, name), 1, I16_MAX)
        for name in (
            "retain_above_q8",
            "penetration_q8",
            "maximum_touchdown_descent_q8",
        ):
            _require_int(name, getattr(self, name), 0, I16_MAX)


class CollisionDisposition(str, Enum):
    CLEAR = "clear"
    AHEAD_WARNING = "ahead_warning"
    RUNWAY_SUPPORTED = "runway_supported"
    HOLD_FOR_DATA = "hold_for_data"
    CONTACT = "contact"


class ContactKind(str, Enum):
    NONE = "none"
    TERRAIN = "terrain"
    AIRPORT = "airport"
    RUNWAY = "runway"


@dataclass(frozen=True, slots=True)
class CollisionDecision:
    disposition: CollisionDisposition
    contact_kind: ContactKind
    subject: str | None
    reason: str
    terrain_box_tests: int = 0
    airport_box_tests: int = 0


def aircraft_sweep_box(sweep: AircraftSweep) -> ClosedAABB:
    proxy = sweep.proxy
    return ClosedAABB(
        min(sweep.start.east_q8, sweep.end.east_q8) - proxy.half_east_q8,
        min(sweep.start.north_q8, sweep.end.north_q8) - proxy.half_north_q8,
        min(sweep.start.altitude_q8, sweep.end.altitude_q8)
        - proxy.below_reference_q8,
        max(sweep.start.east_q8, sweep.end.east_q8) + proxy.half_east_q8,
        max(sweep.start.north_q8, sweep.end.north_q8) + proxy.half_north_q8,
        max(sweep.start.altitude_q8, sweep.end.altitude_q8)
        + proxy.above_reference_q8,
    )


def _round_div_q15(value: int) -> int:
    magnitude = abs(value)
    result = (magnitude + Q15_ONE // 2) // Q15_ONE
    return -result if value < 0 else result


def _runway_coordinates(
    region: RunwaySupportRegion, pose: CollisionPose
) -> tuple[int, int] | None:
    delta_east_counts = (pose.east_q8 - region.center_east_q8) >> 8
    delta_north_counts = (pose.north_q8 - region.center_north_q8) >> 8
    # Active airport groups are already distance culled.  Retaining this guard
    # makes the target multiplication domain explicit instead of truncating.
    if not (
        I16_MIN <= delta_east_counts <= I16_MAX
        and I16_MIN <= delta_north_counts <= I16_MAX
    ):
        return None
    along = _round_div_q15(
        delta_east_counts * region.along_east_q15
        + delta_north_counts * region.along_north_q15
    )
    across = _round_div_q15(
        -delta_east_counts * region.along_north_q15
        + delta_north_counts * region.along_east_q15
    )
    return along, across


def runway_contains(region: RunwaySupportRegion, pose: CollisionPose) -> bool:
    """Test the aircraft reference against one closed oriented rectangle."""

    coordinates = _runway_coordinates(region, pose)
    if coordinates is None:
        return False
    along, across = coordinates
    return (
        abs(along) <= region.half_length_counts
        and abs(across) <= region.half_width_counts
    )


def runway_contains_proxy(
    region: RunwaySupportRegion,
    pose: CollisionPose,
    proxy: AircraftProxy,
) -> bool:
    """Return whether the complete horizontal aircraft proxy is on pavement."""

    coordinates = _runway_coordinates(region, pose)
    if coordinates is None:
        return False
    along, across = coordinates
    along_radius, across_radius = _runway_proxy_radii(region, proxy)
    return (
        abs(along) + along_radius + RUNWAY_PROJECTION_ERROR_COUNTS
        <= region.half_length_counts
        and abs(across) + across_radius + RUNWAY_PROJECTION_ERROR_COUNTS
        <= region.half_width_counts
    )


def _runway_proxy_radii(
    region: RunwaySupportRegion, proxy: AircraftProxy
) -> tuple[int, int]:
    half_east_counts = (proxy.half_east_q8 + 255) >> 8
    half_north_counts = (proxy.half_north_q8 + 255) >> 8
    along_radius = _ceil_fraction(
        half_east_counts * abs(region.along_east_q15)
        + half_north_counts * abs(region.along_north_q15),
        Q15_ONE,
    )
    across_radius = _ceil_fraction(
        half_east_counts * abs(region.along_north_q15)
        + half_north_counts * abs(region.along_east_q15),
        Q15_ONE,
    )
    return along_radius, across_radius


def runway_sweep_overlaps(
    region: RunwaySupportRegion, sweep: AircraftSweep
) -> bool:
    """Conservatively test a swept horizontal aircraft proxy against pavement."""

    start = _runway_coordinates(region, sweep.start)
    end = _runway_coordinates(region, sweep.end)
    if start is None or end is None:
        return False
    along_radius, across_radius = _runway_proxy_radii(region, sweep.proxy)
    along_radius += RUNWAY_PROJECTION_ERROR_COUNTS
    across_radius += RUNWAY_PROJECTION_ERROR_COUNTS
    minimum_along = min(start[0], end[0]) - along_radius
    maximum_along = max(start[0], end[0]) + along_radius
    minimum_across = min(start[1], end[1]) - across_radius
    maximum_across = max(start[1], end[1]) + across_radius
    return (
        maximum_along >= -region.half_length_counts
        and minimum_along <= region.half_length_counts
        and maximum_across >= -region.half_width_counts
        and minimum_across <= region.half_width_counts
    )


def _runway_decision(
    sweep: AircraftSweep,
    regions: Sequence[RunwaySupportRegion],
) -> CollisionDecision | None:
    for region in regions:
        end_inside = runway_contains(region, sweep.end)
        sweep_overlaps = runway_sweep_overlaps(region, sweep)
        sweep_inside = runway_contains_proxy(
            region, sweep.start, sweep.proxy
        ) and runway_contains_proxy(region, sweep.end, sweep.proxy)
        support_y = region.reference_altitude_q8
        if sweep.was_runway_supported:
            if (
                sweep_overlaps
                and sweep.end.altitude_q8 < support_y - region.penetration_q8
            ):
                return CollisionDecision(
                    CollisionDisposition.CONTACT,
                    ContactKind.RUNWAY,
                    region.identifier,
                    "supported aircraft penetrated below the runway tolerance",
                )
            # F2 has already suppressed a low-speed upward blip before this
            # call.  A retained positive vertical velocity is therefore the
            # accepted takeoff transition and must not be captured again.
            if (
                end_inside
                and sweep_inside
                and sweep.velocity_up_q8 <= 0
                and sweep.end.altitude_q8 <= support_y + region.retain_above_q8
            ):
                return CollisionDecision(
                    CollisionDisposition.RUNWAY_SUPPORTED,
                    ContactKind.RUNWAY,
                    region.identifier,
                    "explicit runway support remains inside its oriented region",
                )
            continue

        if not sweep_overlaps:
            continue
        penetrated = sweep.end.altitude_q8 < support_y - region.penetration_q8
        crossed_downward = (
            sweep.start.altitude_q8 >= support_y
            and sweep.end.altitude_q8 <= support_y
            and sweep.velocity_up_q8 <= 0
        )
        below_without_downward_crossing = (
            min(sweep.start.altitude_q8, sweep.end.altitude_q8) < support_y
            and not crossed_downward
        )
        if below_without_downward_crossing:
            return CollisionDecision(
                CollisionDisposition.CONTACT,
                ContactKind.RUNWAY,
                region.identifier,
                "unsupported aircraft traverses or remains below the runway plane",
            )
        if not crossed_downward:
            continue
        if (
            penetrated
            or not end_inside
            or not sweep_inside
            or -sweep.velocity_up_q8 > region.maximum_touchdown_descent_q8
        ):
            return CollisionDecision(
                CollisionDisposition.CONTACT,
                ContactKind.RUNWAY,
                region.identifier,
                "runway crossing exceeds penetration or descent-speed tolerance",
            )
        return CollisionDecision(
            CollisionDisposition.RUNWAY_SUPPORTED,
            ContactKind.RUNWAY,
            region.identifier,
            "descending aircraft acquired the runway support plane",
        )
    return None


def _future_reachable_box(
    sweep: AircraftSweep,
    ticks: int,
    horizontal_accel_q8: int,
    downward_accel_q8: int,
) -> ClosedAABB:
    immediate = aircraft_sweep_box(sweep)
    horizontal_margin = horizontal_accel_q8 * ticks * (ticks + 1) // 2
    downward_margin = downward_accel_q8 * ticks * (ticks + 1) // 2
    projected_east = sweep.end.east_q8 + sweep.velocity_east_q8 * ticks
    projected_north = sweep.end.north_q8 + sweep.velocity_north_q8 * ticks
    projected_altitude = sweep.end.altitude_q8 + sweep.velocity_up_q8 * ticks
    proxy = sweep.proxy
    return ClosedAABB(
        min(immediate.minimum_east_q8, projected_east - proxy.half_east_q8)
        - horizontal_margin,
        min(immediate.minimum_north_q8, projected_north - proxy.half_north_q8)
        - horizontal_margin,
        min(
            immediate.minimum_altitude_q8,
            projected_altitude - proxy.below_reference_q8 - downward_margin,
        ),
        max(immediate.maximum_east_q8, projected_east + proxy.half_east_q8)
        + horizontal_margin,
        max(immediate.maximum_north_q8, projected_north + proxy.half_north_q8)
        + horizontal_margin,
        max(
            immediate.maximum_altitude_q8,
            projected_altitude + proxy.above_reference_q8,
        ),
    )


def _tiles_for_closed_box(
    grid: RegionalGrid, bounds: ClosedAABB
) -> tuple[tuple[tuple[int, int], ...], bool]:
    span = grid.tile_position_q8
    # Closed intervals touch both tiles at an exact shared edge.  Subtracting
    # one integer quantum from the lower bound admits the south/west neighbor.
    minimum_x = (bounds.minimum_east_q8 - 1) // span
    maximum_x = bounds.maximum_east_q8 // span
    minimum_y = (bounds.minimum_north_q8 - 1) // span
    maximum_y = bounds.maximum_north_q8 // span
    outside = (
        minimum_x < 0
        or minimum_y < 0
        or maximum_x >= grid.columns
        or maximum_y >= grid.rows
    )
    tiles = tuple(
        (tile_x, tile_y)
        for tile_y in range(max(0, minimum_y), min(grid.rows - 1, maximum_y) + 1)
        for tile_x in range(max(0, minimum_x), min(grid.columns - 1, maximum_x) + 1)
    )
    return tiles, outside


def _decoded_axis_bounds(raw_values: Sequence[int], half_extent_m: int) -> tuple[int, int]:
    numerator = half_extent_m * POSITION_Q8_PER_METRE
    products = tuple(value * numerator for value in raw_values)
    return (
        _floor_fraction(min(products), Q15_ONE),
        _ceil_fraction(max(products), Q15_ONE),
    )


def terrain_surface_boxes_from_p3dm(
    tile: P3DMTile,
    *,
    vertical_origin_q8: int = REGIONAL_VERTICAL_ORIGIN_Q8,
) -> tuple[TerrainSurfaceBox, ...]:
    """Build conservative per-face boxes for upward terrain faces.

    Boundary skirts have horizontal normals and are excluded.  Every decoded
    minimum rounds down and maximum rounds up; all planes then expand by the
    half-quantization bound so the source surface cannot escape its host box.
    """

    validate_tile(tile)
    if tile.meta.layer_kind is not LayerKind.TERRAIN:
        raise ValueError("terrain contact boxes require a terrain P3DM tile")
    _require_int("vertical_origin_q8", vertical_origin_q8, I32_MIN, I32_MAX)
    centre_east_q8 = tile.meta.center_east_m * POSITION_Q8_PER_METRE
    centre_north_q8 = tile.meta.center_north_m * POSITION_Q8_PER_METRE
    expected_centre_east_m = tile.meta.tile_x * DEFAULT_TILE_SIZE_M + (
        DEFAULT_TILE_SIZE_M // 2
    )
    expected_centre_north_m = tile.meta.tile_y * DEFAULT_TILE_SIZE_M + (
        DEFAULT_TILE_SIZE_M // 2
    )
    if (
        tile.meta.center_east_m != expected_centre_east_m
        or tile.meta.center_north_m != expected_centre_north_m
    ):
        raise ValueError("terrain P3DM centre does not match its 512-metre tile")
    tile_west_q8 = tile.meta.tile_x * DEFAULT_TILE_SIZE_M * POSITION_Q8_PER_METRE
    tile_south_q8 = tile.meta.tile_y * DEFAULT_TILE_SIZE_M * POSITION_Q8_PER_METRE
    tile_east_q8 = tile_west_q8 + DEFAULT_TILE_SIZE_M * POSITION_Q8_PER_METRE
    tile_north_q8 = tile_south_q8 + DEFAULT_TILE_SIZE_M * POSITION_Q8_PER_METRE
    decode_error_q8 = _ceil_fraction(
        tile.meta.model_half_extent_m * POSITION_Q8_PER_METRE,
        2 * Q15_ONE,
    )
    boxes: list[TerrainSurfaceBox] = []
    for face_index, offset in enumerate(range(0, len(tile.position_indices), 3)):
        vertices = tuple(
            tile.positions[tile.position_indices[offset + index]] for index in range(3)
        )
        first, second, third = vertices
        ab_x = second[0] - first[0]
        ab_z = second[2] - first[2]
        ac_x = third[0] - first[0]
        ac_z = third[2] - first[2]
        normal_y = ab_z * ac_x - ab_x * ac_z
        if normal_y <= 0:
            continue
        north_min, north_max = _decoded_axis_bounds(
            tuple(vertex[0] for vertex in vertices), tile.meta.model_half_extent_m
        )
        elevation_min, elevation_max = _decoded_axis_bounds(
            tuple(vertex[1] for vertex in vertices), tile.meta.model_half_extent_m
        )
        # Pingo Z points west, so regional east is the negated encoded Z axis.
        east_min, east_max = _decoded_axis_bounds(
            tuple(-vertex[2] for vertex in vertices), tile.meta.model_half_extent_m
        )
        minimum_east_q8 = max(
            tile_west_q8, centre_east_q8 + east_min - decode_error_q8
        )
        minimum_north_q8 = max(
            tile_south_q8, centre_north_q8 + north_min - decode_error_q8
        )
        maximum_east_q8 = min(
            tile_east_q8, centre_east_q8 + east_max + decode_error_q8
        )
        maximum_north_q8 = min(
            tile_north_q8, centre_north_q8 + north_max + decode_error_q8
        )
        if (
            minimum_east_q8 > maximum_east_q8
            or minimum_north_q8 > maximum_north_q8
        ):
            raise ValueError("terrain surface face lies outside its declared tile")
        boxes.append(
            TerrainSurfaceBox(
                face_index,
                ClosedAABB(
                    minimum_east_q8,
                    minimum_north_q8,
                    vertical_origin_q8 + elevation_min - decode_error_q8,
                    maximum_east_q8,
                    maximum_north_q8,
                    vertical_origin_q8 + elevation_max + decode_error_q8,
                ),
            )
        )
    if not boxes:
        raise ValueError("terrain P3DM contains no upward surface triangles")
    return tuple(boxes)


def evaluate_collision(
    sweep: AircraftSweep,
    *,
    grid: RegionalGrid,
    terrain_envelopes: Mapping[tuple[int, int], TerrainEnvelope],
    terrain_surface_boxes: Mapping[
        tuple[int, int], Sequence[TerrainSurfaceBox]
    ],
    runway_regions: Sequence[RunwaySupportRegion] = (),
    airport_envelopes: Sequence[AirportEnvelope] = (),
    airport_contact_boxes: Mapping[str, Sequence[AirportContactBox]] | None = None,
    lookahead_ticks: int = DEFAULT_LOOKAHEAD_TICKS,
    maximum_horizontal_accel_q8: int = MAX_HORIZONTAL_ACCEL_Q8,
    maximum_downward_accel_q8: int = MAX_DOWNWARD_ACCEL_Q8,
) -> CollisionDecision:
    """Evaluate one candidate F2 step with conservative staged rejection.

    The caller must not publish an end pose after ``HOLD_FOR_DATA``.  An
    ``AHEAD_WARNING`` is not current contact; it requests prefetch/attention
    while the already-tested step may proceed.
    """

    if grid.tile_size_m != DEFAULT_TILE_SIZE_M:
        raise ValueError("the first C1 policy is fixed to 512-metre P3DM cells")
    _require_int("lookahead_ticks", lookahead_ticks, 0, 255)
    _require_int(
        "maximum_horizontal_accel_q8", maximum_horizontal_accel_q8, 0, I16_MAX
    )
    _require_int(
        "maximum_downward_accel_q8", maximum_downward_accel_q8, 0, I16_MAX
    )
    if airport_contact_boxes is None:
        airport_contact_boxes = {}

    immediate = aircraft_sweep_box(sweep)
    runway = _runway_decision(sweep, runway_regions)
    runway_cover = next(
        (
            region
            for region in runway_regions
            if sweep.end.altitude_q8 >= region.reference_altitude_q8
            and runway_contains_proxy(region, sweep.start, sweep.proxy)
            and runway_contains_proxy(region, sweep.end, sweep.proxy)
        ),
        None,
    )
    if runway is not None and runway.disposition is CollisionDisposition.CONTACT:
        return runway

    airport_tests = 0
    for envelope in airport_envelopes:
        if not immediate.intersects(envelope.bounds):
            continue
        if envelope.identifier not in airport_contact_boxes:
            return CollisionDecision(
                CollisionDisposition.HOLD_FOR_DATA,
                ContactKind.AIRPORT,
                envelope.identifier,
                "probable airport contact has no retained detail boxes",
                airport_box_tests=airport_tests,
            )
        for contact in airport_contact_boxes[envelope.identifier]:
            airport_tests += 1
            if immediate.intersects(contact.bounds):
                return CollisionDecision(
                    CollisionDisposition.CONTACT,
                    ContactKind.AIRPORT,
                    contact.identifier,
                    "closed aircraft sweep intersects an airport obstacle box",
                    airport_box_tests=airport_tests,
                )

    if runway is not None:
        return CollisionDecision(
            runway.disposition,
            runway.contact_kind,
            runway.subject,
            runway.reason,
            airport_box_tests=airport_tests,
        )
    if runway_cover is not None:
        return CollisionDecision(
            CollisionDisposition.CLEAR,
            ContactKind.NONE,
            runway_cover.identifier,
            "aircraft proxy is wholly above the runway hard-surface region",
            airport_box_tests=airport_tests,
        )

    immediate_tiles, immediate_outside = _tiles_for_closed_box(grid, immediate)
    if immediate_outside:
        return CollisionDecision(
            CollisionDisposition.HOLD_FOR_DATA,
            ContactKind.TERRAIN,
            None,
            "aircraft sweep reaches outside the pinned terrain world",
            airport_box_tests=airport_tests,
        )

    terrain_tests = 0
    for key in immediate_tiles:
        envelope = terrain_envelopes.get(key)
        if envelope is None:
            return CollisionDecision(
                CollisionDisposition.HOLD_FOR_DATA,
                ContactKind.TERRAIN,
                f"{key[0]},{key[1]}",
                "immediate swept tile has no validated P3DM elevation envelope",
                terrain_box_tests=terrain_tests,
                airport_box_tests=airport_tests,
            )
        if (envelope.tile_x, envelope.tile_y) != key:
            raise ValueError(f"terrain envelope key {key} does not match descriptor")
        if immediate.minimum_altitude_q8 > envelope.maximum_altitude_q8:
            continue
        if immediate.maximum_altitude_q8 <= envelope.minimum_altitude_q8:
            return CollisionDecision(
                CollisionDisposition.CONTACT,
                ContactKind.TERRAIN,
                f"{key[0]},{key[1]}",
                "aircraft is entirely below the tile mesh lower envelope",
                terrain_box_tests=terrain_tests,
                airport_box_tests=airport_tests,
            )
        if key not in terrain_surface_boxes:
            return CollisionDecision(
                CollisionDisposition.HOLD_FOR_DATA,
                ContactKind.TERRAIN,
                f"{key[0]},{key[1]}",
                "probable terrain contact has no retained surface boxes",
                terrain_box_tests=terrain_tests,
                airport_box_tests=airport_tests,
            )
        boxes = terrain_surface_boxes[key]
        if not boxes:
            return CollisionDecision(
                CollisionDisposition.HOLD_FOR_DATA,
                ContactKind.TERRAIN,
                f"{key[0]},{key[1]}",
                "terrain detail set is present but contains no surface boxes",
                terrain_box_tests=terrain_tests,
                airport_box_tests=airport_tests,
            )
        for contact in boxes:
            terrain_tests += 1
            if (
                immediate.intersects_horizontally(contact.bounds)
                and immediate.minimum_altitude_q8
                <= contact.bounds.maximum_altitude_q8
            ):
                return CollisionDecision(
                    CollisionDisposition.CONTACT,
                    ContactKind.TERRAIN,
                    f"{key[0]},{key[1]}:{contact.identifier}",
                    "aircraft sweep overlaps a conservative terrain surface box",
                    terrain_box_tests=terrain_tests,
                    airport_box_tests=airport_tests,
                )

    if lookahead_ticks == 0:
        return CollisionDecision(
            CollisionDisposition.CLEAR,
            ContactKind.NONE,
            None,
            "immediate closed sweep is clear",
            terrain_box_tests=terrain_tests,
            airport_box_tests=airport_tests,
        )

    future = _future_reachable_box(
        sweep,
        lookahead_ticks,
        maximum_horizontal_accel_q8,
        maximum_downward_accel_q8,
    )
    ahead_tiles, ahead_outside = _tiles_for_closed_box(grid, future)
    if ahead_outside:
        return CollisionDecision(
            CollisionDisposition.AHEAD_WARNING,
            ContactKind.TERRAIN,
            None,
            "look-ahead reach extends outside the pinned terrain world",
            terrain_box_tests=terrain_tests,
            airport_box_tests=airport_tests,
        )
    for key in ahead_tiles:
        envelope = terrain_envelopes.get(key)
        if envelope is None:
            return CollisionDecision(
                CollisionDisposition.AHEAD_WARNING,
                ContactKind.TERRAIN,
                f"{key[0]},{key[1]}",
                "reachable ahead tile needs its P3DM elevation envelope",
                terrain_box_tests=terrain_tests,
                airport_box_tests=airport_tests,
            )
        if future.minimum_altitude_q8 <= envelope.maximum_altitude_q8:
            return CollisionDecision(
                CollisionDisposition.AHEAD_WARNING,
                ContactKind.TERRAIN,
                f"{key[0]},{key[1]}",
                "conservative descent envelope reaches terrain maximum",
                terrain_box_tests=terrain_tests,
                airport_box_tests=airport_tests,
            )
    return CollisionDecision(
        CollisionDisposition.CLEAR,
        ContactKind.NONE,
        None,
        "current and reachable ahead terrain are vertically separated",
        terrain_box_tests=terrain_tests,
        airport_box_tests=airport_tests,
    )
