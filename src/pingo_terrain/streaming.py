"""Deterministic terrain residency and floating-origin reference model.

Pingo's public transforms are signed 16-bit Q8 values.  Under the accepted
terrain scale, one integer translation count is 1/16 metre, so a single fixed
origin spans only about four kilometres.  Regional flight therefore keeps an
integer 512-metre coarse cell plus a high-resolution offset from that cell's
centre.  The eZ80 implementation can mirror this module without division: one
cell is exactly 8192 translation counts, or 0x200000 position-Q8 units.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Sequence


TRANSLATION_COUNTS_PER_METRE = 16
POSITION_FRACTION_BITS = 8
POSITION_FRACTION_SCALE = 1 << POSITION_FRACTION_BITS
POSITION_Q8_PER_METRE = TRANSLATION_COUNTS_PER_METRE * POSITION_FRACTION_SCALE
DEFAULT_TILE_SIZE_M = 512
DEFAULT_TERRAIN_SLOTS = 25
DEFAULT_TERRAIN_RING_SIDE = 5
PINGO_I16_MIN = -0x8000
PINGO_I16_MAX = 0x7FFF
PINGO_MAX_SCENE_RENDERABLES = 32


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


@dataclass(frozen=True)
class RegionalGrid:
    """Pinned rectangular terrain grid in an integer metric projection."""

    origin_east_m: int
    origin_north_m: int
    columns: int
    rows: int
    tile_size_m: int = DEFAULT_TILE_SIZE_M

    def __post_init__(self) -> None:
        for name in ("origin_east_m", "origin_north_m"):
            if not isinstance(getattr(self, name), int):
                raise TypeError(f"{name} must be an integer metre coordinate")
        if self.columns <= 0 or self.rows <= 0:
            raise ValueError("regional grid dimensions must be positive")
        if self.tile_size_m <= 0:
            raise ValueError("tile size must be positive")

    @property
    def tile_counts(self) -> int:
        return self.tile_size_m * TRANSLATION_COUNTS_PER_METRE

    @property
    def tile_position_q8(self) -> int:
        return self.tile_counts * POSITION_FRACTION_SCALE

    @property
    def half_tile_position_q8(self) -> int:
        if self.tile_position_q8 & 1:
            raise ValueError("floating-origin cells require an even Q8 span")
        return self.tile_position_q8 // 2

    def contains(self, tile_x: int, tile_y: int) -> bool:
        return 0 <= tile_x < self.columns and 0 <= tile_y < self.rows

    def require_tile(self, tile_x: int, tile_y: int) -> None:
        if not self.contains(tile_x, tile_y):
            raise ValueError(f"tile ({tile_x},{tile_y}) is outside the world")

    def tile_id(self, tile_x: int, tile_y: int) -> int:
        self.require_tile(tile_x, tile_y)
        return tile_y * self.columns + tile_x

    def terrain_path(self, lod: int, tile_x: int, tile_y: int) -> PurePosixPath:
        if not 0 <= lod <= 9:
            raise ValueError("8.3 terrain paths reserve one decimal LOD digit")
        tile_id = self.tile_id(tile_x, tile_y)
        return PurePosixPath(
            "TRN", f"L{lod}", f"{tile_id >> 8:02X}", f"{tile_id & 0xFF:02X}.AGN"
        )


@dataclass(frozen=True)
class FloatingOriginPosition:
    """Coarse terrain cell plus metric east/north offsets from its centre.

    ``east_q8`` and ``north_q8`` are Q8 translation counts, not Q8 metres.
    Their canonical interval is ``[-half_cell, half_cell)``.  Pingo's local
    axes are X=north and Z=-east.
    """

    tile_x: int
    tile_y: int
    east_q8: int
    north_q8: int

    def is_canonical(self, grid: RegionalGrid) -> bool:
        half = grid.half_tile_position_q8
        return (
            -half <= self.east_q8 < half
            and -half <= self.north_q8 < half
        )

    def rebase(self, grid: RegionalGrid) -> tuple["FloatingOriginPosition", tuple[int, int]]:
        """Normalize both fine axes and return the coarse-cell displacement."""

        span = grid.tile_position_q8
        half = grid.half_tile_position_q8
        east_shift = (self.east_q8 + half) // span
        north_shift = (self.north_q8 + half) // span
        normalized = FloatingOriginPosition(
            tile_x=self.tile_x + east_shift,
            tile_y=self.tile_y + north_shift,
            east_q8=self.east_q8 - east_shift * span,
            north_q8=self.north_q8 - north_shift * span,
        )
        if not normalized.is_canonical(grid):
            raise AssertionError("floating-origin normalization failed")
        return normalized, (east_shift, north_shift)

    def integrate_pingo_q8(
        self, grid: RegionalGrid, delta_x_q8: int, delta_z_q8: int
    ) -> tuple["FloatingOriginPosition", tuple[int, int]]:
        """Integrate Pingo-local X/Z motion, then perform a whole-cell rebase."""

        candidate = FloatingOriginPosition(
            self.tile_x,
            self.tile_y,
            self.east_q8 - delta_z_q8,
            self.north_q8 + delta_x_q8,
        )
        return candidate.rebase(grid)

    @property
    def pingo_x_q8(self) -> int:
        return self.north_q8

    @property
    def pingo_z_q8(self) -> int:
        return -self.east_q8

    @staticmethod
    def _render_word(position_q8: int) -> int:
        return position_q8 >> POSITION_FRACTION_BITS

    @property
    def pingo_x_count(self) -> int:
        return self._render_word(self.pingo_x_q8)

    @property
    def pingo_z_count(self) -> int:
        return self._render_word(self.pingo_z_q8)

    def absolute_q8(self, grid: RegionalGrid) -> tuple[int, int]:
        """Return absolute easting/northing as Q8 translation counts."""

        if not self.is_canonical(grid):
            raise ValueError("position must be rebased before reconstruction")
        half_tile_m = grid.tile_size_m // 2
        if grid.tile_size_m & 1:
            raise ValueError("absolute reconstruction requires an even tile size")
        east_m = grid.origin_east_m + self.tile_x * grid.tile_size_m + half_tile_m
        north_m = (
            grid.origin_north_m + self.tile_y * grid.tile_size_m + half_tile_m
        )
        return (
            east_m * POSITION_Q8_PER_METRE + self.east_q8,
            north_m * POSITION_Q8_PER_METRE + self.north_q8,
        )


def locate_absolute_q8(
    grid: RegionalGrid, absolute_east_q8: int, absolute_north_q8: int
) -> FloatingOriginPosition:
    """Convert absolute projected Q8 coordinates to the canonical frame."""

    origin_east_q8 = grid.origin_east_m * POSITION_Q8_PER_METRE
    origin_north_q8 = grid.origin_north_m * POSITION_Q8_PER_METRE
    span = grid.tile_position_q8
    tile_x = (absolute_east_q8 - origin_east_q8) // span
    tile_y = (absolute_north_q8 - origin_north_q8) // span
    grid.require_tile(tile_x, tile_y)
    half = grid.half_tile_position_q8
    position = FloatingOriginPosition(
        tile_x=tile_x,
        tile_y=tile_y,
        east_q8=absolute_east_q8 - origin_east_q8 - tile_x * span - half,
        north_q8=absolute_north_q8 - origin_north_q8 - tile_y * span - half,
    )
    if not position.is_canonical(grid):
        raise AssertionError("absolute-to-floating conversion is not canonical")
    return position


def tile_center_pingo_translation(
    grid: RegionalGrid,
    position: FloatingOriginPosition,
    tile_x: int,
    tile_y: int,
) -> tuple[int, int]:
    """Return a resident tile centre's signed Pingo X/Z translation words."""

    grid.require_tile(tile_x, tile_y)
    x_count = (tile_y - position.tile_y) * grid.tile_counts
    z_count = -(tile_x - position.tile_x) * grid.tile_counts
    if not (
        PINGO_I16_MIN <= x_count <= PINGO_I16_MAX
        and PINGO_I16_MIN <= z_count <= PINGO_I16_MAX
    ):
        raise OverflowError("resident tile lies outside Pingo's transform window")
    return x_count, z_count


def desired_tile_order(
    grid: RegionalGrid,
    position: FloatingOriginPosition,
    *,
    velocity_east_q8: int = 0,
    velocity_north_q8: int = 0,
    radius: int = 2,
    limit: int = DEFAULT_TERRAIN_SLOTS,
) -> tuple[tuple[int, int], ...]:
    """Return a deterministic near-first, motion-biased square neighborhood."""

    if radius < 0 or limit < 0:
        raise ValueError("radius and limit must be nonnegative")
    east_sign = _sign(velocity_east_q8)
    north_sign = _sign(velocity_north_q8)
    predicted = (position.tile_x + east_sign, position.tile_y + north_sign)
    candidates = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tile = (position.tile_x + dx, position.tile_y + dy)
            if not grid.contains(*tile):
                continue
            chebyshev = max(abs(dx), abs(dy))
            manhattan = abs(dx) + abs(dy)
            forward = dx * east_sign + dy * north_sign
            category = 0 if (dx, dy) == (0, 0) else 1 if tile == predicted else 2
            candidates.append(
                ((category, chebyshev, -forward, manhattan, grid.tile_id(*tile)), tile)
            )
    candidates.sort()
    return tuple(tile for _, tile in candidates[:limit])


@dataclass(frozen=True)
class TerrainSlotPlan:
    slot: int
    tile: tuple[int, int] | None
    evicted_tile: tuple[int, int] | None

    @property
    def is_load(self) -> bool:
        return self.tile is not None


class TerrainResidentSet:
    """Transactional stable-slot model for the foreground J1 service pass."""

    def __init__(self, slot_count: int = DEFAULT_TERRAIN_SLOTS):
        if slot_count <= 0:
            raise ValueError("terrain slot count must be positive")
        self._slots: list[tuple[int, int] | None] = [None] * slot_count
        self._pending: TerrainSlotPlan | None = None

    @property
    def slots(self) -> tuple[tuple[int, int] | None, ...]:
        return tuple(self._slots)

    @property
    def pending(self) -> TerrainSlotPlan | None:
        return self._pending

    def plan_one(self, desired: Sequence[tuple[int, int]]) -> TerrainSlotPlan | None:
        """Choose one load/replacement/deactivation without mutating slots."""

        if self._pending is not None:
            raise RuntimeError("a terrain publication is already pending")
        if len(set(desired)) != len(desired):
            raise ValueError("desired terrain order contains duplicates")
        resident = {tile for tile in self._slots if tile is not None}
        missing = next((tile for tile in desired if tile not in resident), None)
        if missing is None:
            desired_set = set(desired)
            extras = [
                index
                for index, tile in enumerate(self._slots)
                if tile is not None and tile not in desired_set
            ]
            if not extras:
                return None
            slot = extras[0]
            plan = TerrainSlotPlan(slot, None, self._slots[slot])
            self._pending = plan
            return plan

        try:
            slot = self._slots.index(None)
        except ValueError:
            desired_set = set(desired)
            victims = [
                index
                for index, tile in enumerate(self._slots)
                if tile not in desired_set
            ]
            if not victims:
                raise RuntimeError("desired set exceeds the stable terrain-slot pool")
            # A stable, low-slot-first victim rule makes traces reproducible.
            slot = victims[0]
        plan = TerrainSlotPlan(slot, missing, self._slots[slot])
        self._pending = plan
        return plan

    def commit(self, plan: TerrainSlotPlan) -> None:
        """Publish a successfully validated/uploaded replacement atomically."""

        if plan != self._pending:
            raise ValueError("terrain commit does not match the pending plan")
        self._slots[plan.slot] = plan.tile
        self._pending = None

    def abort(self, plan: TerrainSlotPlan) -> None:
        """Discard a failed read/upload while retaining the old slot exactly."""

        if plan != self._pending:
            raise ValueError("terrain abort does not match the pending plan")
        self._pending = None

    def resident_tiles(self) -> frozenset[tuple[int, int]]:
        return frozenset(tile for tile in self._slots if tile is not None)


def direct_mapped_terrain_slot(
    tile_x: int,
    tile_y: int,
    *,
    side: int = DEFAULT_TERRAIN_RING_SIDE,
) -> int:
    """Map one nonnegative world tile into a square toroidal slot ring.

    A complete ``side`` by ``side`` neighborhood contains exactly one tile for
    every residue pair, so this map is collision-free for the runtime's 5x5
    desired set.  It replaces a general cache-victim search with two small
    remainders and one multiply on the eZ80.
    """

    if side <= 0:
        raise ValueError("direct-mapped ring side must be positive")
    if tile_x < 0 or tile_y < 0:
        raise ValueError("regional terrain tile coordinates must be nonnegative")
    return (tile_y % side) * side + (tile_x % side)


class DirectMappedTerrainRing:
    """Transactional reference for the initial 5x5 eZ80 terrain ring.

    ``plan_one`` follows the already priority-sorted desired sequence.  A
    replacement never changes the retained map until ``commit``; ``abort``
    therefore preserves the complete previous resident exactly.  Once every
    desired tile is resident, an obsolete edge tile is deactivated one slot per
    service pass.
    """

    def __init__(self, side: int = DEFAULT_TERRAIN_RING_SIDE):
        if side <= 0:
            raise ValueError("direct-mapped ring side must be positive")
        self.side = side
        self._slots: list[tuple[int, int] | None] = [None] * (side * side)
        self._pending: TerrainSlotPlan | None = None

    @property
    def slots(self) -> tuple[tuple[int, int] | None, ...]:
        return tuple(self._slots)

    @property
    def pending(self) -> TerrainSlotPlan | None:
        return self._pending

    def plan_one(self, desired: Sequence[tuple[int, int]]) -> TerrainSlotPlan | None:
        if self._pending is not None:
            raise RuntimeError("a terrain publication is already pending")
        if len(set(desired)) != len(desired):
            raise ValueError("desired terrain order contains duplicates")

        desired_slots: dict[int, tuple[int, int]] = {}
        for tile in desired:
            slot = direct_mapped_terrain_slot(*tile, side=self.side)
            previous = desired_slots.get(slot)
            if previous is not None and previous != tile:
                raise ValueError(
                    f"desired tiles {previous} and {tile} collide in slot {slot}"
                )
            desired_slots[slot] = tile
            if self._slots[slot] != tile:
                plan = TerrainSlotPlan(slot, tile, self._slots[slot])
                self._pending = plan
                return plan

        for slot, resident in enumerate(self._slots):
            if resident is not None and slot not in desired_slots:
                plan = TerrainSlotPlan(slot, None, resident)
                self._pending = plan
                return plan
        return None

    def commit(self, plan: TerrainSlotPlan) -> None:
        if plan != self._pending:
            raise ValueError("terrain commit does not match the pending plan")
        self._slots[plan.slot] = plan.tile
        self._pending = None

    def abort(self, plan: TerrainSlotPlan) -> None:
        if plan != self._pending:
            raise ValueError("terrain abort does not match the pending plan")
        self._pending = None

    def resident_tiles(self) -> frozenset[tuple[int, int]]:
        return frozenset(tile for tile in self._slots if tile is not None)


def assert_scene_budget(
    terrain_slots: int,
    airport_objects: int,
    aircraft_objects: int = 1,
    landmark_objects: int = 0,
) -> None:
    """Fail before a configuration can overflow Pingo's 32-object scene."""

    values: Iterable[int] = (
        terrain_slots,
        airport_objects,
        aircraft_objects,
        landmark_objects,
    )
    if any(value < 0 for value in values):
        raise ValueError("scene object counts cannot be negative")
    total = terrain_slots + airport_objects + aircraft_objects + landmark_objects
    if total > PINGO_MAX_SCENE_RENDERABLES:
        raise ValueError(
            f"active scene needs {total} objects; Pingo permits "
            f"{PINGO_MAX_SCENE_RENDERABLES}"
        )
