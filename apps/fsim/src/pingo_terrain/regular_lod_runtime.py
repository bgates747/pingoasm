"""Host reference contract for the regular hierarchy runtime.

The firmware-side provider can remain small if the host contract makes three
things explicit:

* detailed N=5 cells always use the collision-free slots 0..90;
* hierarchy records are identified by ``(lod, anchor_q, anchor_offset_row)``;
* slots 91..254 are a protected, dynamically allocated pool.

This module is deliberately independent of fixtures and assembly.  It is both
an executable specification for a provider and a source for generated include
tables.  Static phase tables never contain manager slots: those are assigned
only while reconciling a live plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re
import struct
from typing import Iterable, Sequence

from .hex_terrain import HexCell, disk_offsets, validate_cell
from .regular_lod import (
    COARSE_SLOT_COUNT,
    COARSE_SLOT_FIRST,
    FAR_RING,
    HIERARCHY_LEVEL_BY_LOD,
    LEVEL_L8,
    MANAGER_SLOT_COUNT,
    NEAR_RING_MAX,
    HierarchyNode,
    bounded_node_cells,
    offset_row,
    select_hierarchy_nodes,
)


NEAR_SLOT_FIRST = 0
NEAR_SLOT_COUNT = COARSE_SLOT_FIRST
NEAR_SLOT_HASH_Q = 5
NEAR_SLOT_HASH_R = 11
PROVEN_COARSE_PLAN_MAX = 159
UNASSIGNED_SLOT = 0xFF

# A mutable provider record.  The first five bytes are generated and the last
# byte belongs to the runtime allocator.
PLAN_RECORD_LOD = 0
PLAN_RECORD_ANCHOR_Q = 1
PLAN_RECORD_ANCHOR_OFFSET_ROW = 3
PLAN_RECORD_SLOT = 5
PLAN_RECORD_BYTES = 6

# Root alignment completely determines hierarchy selection.  q is modulo 8
# and offset-row is modulo 4, yielding exactly 32 phases.
PHASE_Q_COUNT = LEVEL_L8.width_q
PHASE_OFFSET_ROW_COUNT = LEVEL_L8.height_rows
PHASE_COUNT = PHASE_Q_COUNT * PHASE_OFFSET_ROW_COUNT
PHASE_PLAN_COUNT = (NEAR_RING_MAX + 1) * PHASE_COUNT
PHASE_RECORD_BYTES = 3
PHASE_REFERENCE_Q = 80
PHASE_REFERENCE_OFFSET_ROW = 120

# This order is the executable ABI of ``hex_provider_origin_steps``.  Recipe
# index arithmetic and firmware direction selection must not substitute a
# conventional compass or axial-neighbor order.
TRANSITION_NEAR_RADIUS = 5
TRANSITION_DIRECTION_NAMES = (
    "north",
    "south",
    "northeast",
    "southeast",
    "northwest",
    "southwest",
)
TRANSITION_DIRECTION_STEPS = (
    (0, 1),
    (0, -1),
    (1, 0),
    (1, -1),
    (-1, 1),
    (-1, 0),
)
TRANSITION_DIRECTION_COUNT = len(TRANSITION_DIRECTION_STEPS)
TRANSITION_RECIPE_COUNT = PHASE_COUNT * TRANSITION_DIRECTION_COUNT
TRANSITION_DIRECTORY_POINTER_BYTES = 3
TRANSITION_RECIPE_GROUP_COUNT = 0
TRANSITION_GROUP_RETIRING_COUNT = 0
TRANSITION_GROUP_ENTERING_COUNT = 1
TRANSITION_GROUP_ORDINALS = 2

PROTECTED_MASK_BYTES = (COARSE_SLOT_COUNT + 7) // 8
_ASSEMBLY_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_s16(value: int, field: str) -> None:
    if not -0x8000 <= value <= 0x7FFF:
        raise ValueError(f"{field} lies outside signed 16-bit range: {value}")


def _require_s8(value: int, field: str) -> None:
    if not -0x80 <= value <= 0x7F:
        raise ValueError(f"{field} lies outside signed 8-bit range: {value}")


@dataclass(frozen=True, slots=True)
class CoarsePlanEntry:
    """One absolute hierarchy identity, before a runtime slot is assigned."""

    lod: int
    anchor_q: int
    anchor_offset_row: int

    def __post_init__(self) -> None:
        try:
            level = HIERARCHY_LEVEL_BY_LOD[self.lod]
        except KeyError as error:
            raise ValueError(f"unknown regular hierarchy LOD: {self.lod}") from error
        _require_s16(self.anchor_q, "hierarchy q anchor")
        _require_s16(self.anchor_offset_row, "hierarchy offset-row anchor")
        # HierarchyNode owns the alignment invariant.
        HierarchyNode(level, self.anchor_q, self.anchor_offset_row)

    @classmethod
    def from_node(cls, node: HierarchyNode) -> "CoarsePlanEntry":
        return cls(node.level.lod, node.anchor_q, node.anchor_offset_row)

    @property
    def node(self) -> HierarchyNode:
        return HierarchyNode(
            HIERARCHY_LEVEL_BY_LOD[self.lod],
            self.anchor_q,
            self.anchor_offset_row,
        )

    @property
    def identity(self) -> tuple[int, int, int]:
        return self.lod, self.anchor_q, self.anchor_offset_row


@dataclass(frozen=True, slots=True)
class CoarsePlan:
    """A deterministic ordered hierarchy plan for one regional position."""

    origin_q: int
    origin_r: int
    near_radius: int
    entries: tuple[CoarsePlanEntry, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.near_radius <= NEAR_RING_MAX:
            raise ValueError(
                f"near radius lies outside 0..{NEAR_RING_MAX}: {self.near_radius}"
            )
        _require_s16(self.origin_q, "origin q")
        _require_s16(self.origin_r, "origin r")
        if len(self.entries) > COARSE_SLOT_COUNT:
            raise ValueError(
                f"coarse plan has {len(self.entries)} entries for "
                f"{COARSE_SLOT_COUNT} slots"
            )
        identities = tuple(entry.identity for entry in self.entries)
        if len(set(identities)) != len(identities):
            raise ValueError("coarse plan contains duplicate hierarchy identities")

    @property
    def origin_offset_row(self) -> int:
        return offset_row(self.origin_q, self.origin_r)


@dataclass(frozen=True, slots=True)
class NearPlanEntry:
    """One bounded detailed cell and its globally stable near slot."""

    q: int
    r: int
    slot: int

    def __post_init__(self) -> None:
        _require_s16(self.q, "near q")
        _require_s16(self.r, "near r")
        if not NEAR_SLOT_FIRST <= self.slot < NEAR_SLOT_COUNT:
            raise ValueError(f"near slot lies outside 0..90: {self.slot}")
        if self.slot != near_slot(self.q, self.r):
            raise ValueError("near entry does not use the stable slot hash")


@dataclass(frozen=True, slots=True)
class PhasePlanEntry:
    """One hierarchy identity relative to the live origin."""

    lod: int
    anchor_q_offset: int
    anchor_offset_row_offset: int

    def __post_init__(self) -> None:
        if self.lod not in HIERARCHY_LEVEL_BY_LOD:
            raise ValueError(f"unknown regular hierarchy LOD: {self.lod}")
        _require_s8(self.anchor_q_offset, "phase q offset")
        _require_s8(self.anchor_offset_row_offset, "phase offset-row offset")

    def resolve(self, origin_q: int, origin_offset_row: int) -> CoarsePlanEntry:
        return CoarsePlanEntry(
            self.lod,
            origin_q + self.anchor_q_offset,
            origin_offset_row + self.anchor_offset_row_offset,
        )


@dataclass(frozen=True, slots=True)
class PhasePlan:
    """One translation-independent plan for a radius/alignment phase."""

    near_radius: int
    phase_q: int
    phase_offset_row: int
    entries: tuple[PhasePlanEntry, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.near_radius <= NEAR_RING_MAX:
            raise ValueError("phase plan has an invalid near radius")
        if not 0 <= self.phase_q < PHASE_Q_COUNT:
            raise ValueError("phase q lies outside 0..7")
        if not 0 <= self.phase_offset_row < PHASE_OFFSET_ROW_COUNT:
            raise ValueError("phase offset row lies outside 0..3")
        if len(self.entries) > PROVEN_COARSE_PLAN_MAX:
            raise ValueError("phase plan exceeds the proven 159-entry maximum")

    @property
    def index(self) -> int:
        return phase_table_index(
            self.near_radius,
            self.phase_q,
            self.phase_offset_row,
        )


def near_slot(q: int, r: int) -> int:
    """Return the collision-free detailed slot for any radius-five disk."""

    return (NEAR_SLOT_HASH_Q * q + NEAR_SLOT_HASH_R * r) % NEAR_SLOT_COUNT


def build_near_plan(
    origin_q: int,
    origin_r: int,
    near_radius: int,
    *,
    clip_to_region: bool = True,
) -> tuple[NearPlanEntry, ...]:
    """Build centre/ring-ordered detailed entries in slots 0..90."""

    if not 0 <= near_radius <= NEAR_RING_MAX:
        raise ValueError(
            f"near radius lies outside 0..{NEAR_RING_MAX}: {near_radius}"
        )
    entries: list[NearPlanEntry] = []
    for delta_q, delta_r in disk_offsets(near_radius):
        q, r = origin_q + delta_q, origin_r + delta_r
        if clip_to_region:
            try:
                validate_cell(q, r)
            except ValueError:
                continue
        entries.append(NearPlanEntry(q, r, near_slot(q, r)))
    if len({entry.slot for entry in entries}) != len(entries):
        raise ValueError("near plan's stable slot hash contains a collision")
    return tuple(entries)


def build_coarse_plan(
    origin_q: int,
    origin_r: int,
    near_radius: int,
    *,
    clip_to_region: bool = True,
) -> CoarsePlan:
    """Build an absolute plan using the authoritative hierarchy selector."""

    nodes = select_hierarchy_nodes(origin_q, origin_r, near_radius)
    if clip_to_region:
        nodes = tuple(node for node in nodes if bounded_node_cells(node))
    return CoarsePlan(
        origin_q,
        origin_r,
        near_radius,
        tuple(CoarsePlanEntry.from_node(node) for node in nodes),
    )


def phase_index(phase_q: int, phase_offset_row: int) -> int:
    """Return q-major phase index ``q*4 + offset_row``."""

    if not 0 <= phase_q < PHASE_Q_COUNT:
        raise ValueError("phase q lies outside 0..7")
    if not 0 <= phase_offset_row < PHASE_OFFSET_ROW_COUNT:
        raise ValueError("phase offset row lies outside 0..3")
    return phase_q * PHASE_OFFSET_ROW_COUNT + phase_offset_row


def phase_table_index(
    near_radius: int,
    phase_q: int,
    phase_offset_row: int,
) -> int:
    """Return radius-major index into the complete 192-plan table."""

    if not 0 <= near_radius <= NEAR_RING_MAX:
        raise ValueError("phase table has no such near radius")
    return near_radius * PHASE_COUNT + phase_index(phase_q, phase_offset_row)


@lru_cache(maxsize=None)
def build_phase_plan(
    near_radius: int,
    phase_q: int,
    phase_offset_row: int,
) -> PhasePlan:
    """Generate one of the 6 x 32 translation-independent plans."""

    phase_index(phase_q, phase_offset_row)
    q = PHASE_REFERENCE_Q + phase_q
    row = PHASE_REFERENCE_OFFSET_ROW + phase_offset_row
    absolute = build_coarse_plan(
        q,
        row - q // 2,
        near_radius,
        clip_to_region=False,
    )
    return PhasePlan(
        near_radius,
        phase_q,
        phase_offset_row,
        tuple(
            PhasePlanEntry(
                entry.lod,
                entry.anchor_q - q,
                entry.anchor_offset_row - row,
            )
            for entry in absolute.entries
        ),
    )


def all_phase_plans() -> tuple[PhasePlan, ...]:
    """Return all 192 plans in radius-major, q-major phase order."""

    return tuple(
        build_phase_plan(near_radius, phase_q, phase_row)
        for near_radius in range(NEAR_RING_MAX + 1)
        for phase_q in range(PHASE_Q_COUNT)
        for phase_row in range(PHASE_OFFSET_ROW_COUNT)
    )


def resolve_phase_plan(
    origin_q: int,
    origin_r: int,
    near_radius: int,
    *,
    clip_to_region: bool = True,
) -> CoarsePlan:
    """Resolve the phase table at an arbitrary regional origin."""

    row = offset_row(origin_q, origin_r)
    phase = build_phase_plan(
        near_radius,
        origin_q % PHASE_Q_COUNT,
        row % PHASE_OFFSET_ROW_COUNT,
    )
    entries = tuple(entry.resolve(origin_q, row) for entry in phase.entries)
    if clip_to_region:
        entries = tuple(entry for entry in entries if bounded_node_cells(entry.node))
    return CoarsePlan(origin_q, origin_r, near_radius, entries)


TerrainOwner = NearPlanEntry | CoarsePlanEntry


@dataclass(frozen=True, slots=True)
class TerrainOwnerPlan:
    """Complete near and coarse ownership at one regional position.

    ``NearPlanEntry.slot`` remains the compact endpoint convention used by the
    existing provider, but it is not a staging constraint.  A live transition
    may temporarily place any entering owner in any inactive manager slot and
    publish that slot only when its complete coverage group is ready.
    """

    origin_q: int
    origin_r: int
    near_radius: int
    near_entries: tuple[NearPlanEntry, ...]
    coarse_entries: tuple[CoarsePlanEntry, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.near_radius <= NEAR_RING_MAX:
            raise ValueError(
                f"near radius lies outside 0..{NEAR_RING_MAX}: {self.near_radius}"
            )
        _require_s16(self.origin_q, "origin q")
        _require_s16(self.origin_r, "origin r")
        if len(self.owners) > MANAGER_SLOT_COUNT:
            raise ValueError(
                f"terrain plan has {len(self.owners)} owners for "
                f"{MANAGER_SLOT_COUNT} slots"
            )
        near_cells = tuple((entry.q, entry.r) for entry in self.near_entries)
        if len(set(near_cells)) != len(near_cells):
            raise ValueError("terrain plan contains duplicate near identities")
        coarse_identities = tuple(entry.identity for entry in self.coarse_entries)
        if len(set(coarse_identities)) != len(coarse_identities):
            raise ValueError("terrain plan contains duplicate coarse identities")

    @property
    def owners(self) -> tuple[TerrainOwner, ...]:
        return (*self.near_entries, *self.coarse_entries)

    @property
    def origin_offset_row(self) -> int:
        return offset_row(self.origin_q, self.origin_r)


def build_terrain_owner_plan(
    origin_q: int,
    origin_r: int,
    near_radius: int,
    *,
    clip_to_region: bool = True,
) -> TerrainOwnerPlan:
    """Build the complete slot-independent ownership plan.

    Near and coarse owners intentionally share one capacity domain.  That is
    what permits an incoming detailed cell to stage outside its eventual
    stable near slot while the outgoing owner of that slot remains visible.
    """

    near_entries = build_near_plan(
        origin_q,
        origin_r,
        near_radius,
        clip_to_region=clip_to_region,
    )
    coarse_plan = resolve_phase_plan(
        origin_q,
        origin_r,
        near_radius,
        clip_to_region=clip_to_region,
    )
    return TerrainOwnerPlan(
        origin_q,
        origin_r,
        near_radius,
        near_entries,
        coarse_plan.entries,
    )


def _terrain_owner_sort_key(owner: TerrainOwner) -> tuple[int, ...]:
    if isinstance(owner, NearPlanEntry):
        return 0, owner.q, owner.r
    return 1, owner.lod, owner.anchor_q, owner.anchor_offset_row


@lru_cache(maxsize=None)
def _terrain_owner_coverage(owner: TerrainOwner) -> frozenset[HexCell]:
    """Return the exact bounded L0 cells represented by one owner."""

    if isinstance(owner, NearPlanEntry):
        return frozenset((HexCell(owner.q, owner.r),))
    return _coarse_entry_coverage(owner)


@lru_cache(maxsize=None)
def _coarse_entry_coverage(entry: CoarsePlanEntry) -> frozenset:
    """Return the exact bounded L0 cells owned by one hierarchy identity."""

    return frozenset(bounded_node_cells(entry.node))


@dataclass(frozen=True, slots=True)
class CoarseTransitionGroup:
    """One indivisible old/new coverage component.

    Retiring and entering hierarchy nodes share underlying L0 coverage either
    directly or transitively.  Different groups have no old-to-new coverage
    dependency and can therefore commit at separate render-idle boundaries.
    Empty sides describe terrain leaving or entering the regional view.
    """

    retiring: tuple[CoarsePlanEntry, ...]
    entering: tuple[CoarsePlanEntry, ...]

    def __post_init__(self) -> None:
        if not self.retiring and not self.entering:
            raise ValueError("a transition group cannot be empty")
        if len(set(self.retiring)) != len(self.retiring):
            raise ValueError("a transition group repeats a retiring identity")
        if len(set(self.entering)) != len(self.entering):
            raise ValueError("a transition group repeats an entering identity")
        if set(self.retiring) & set(self.entering):
            raise ValueError("a transition group cannot retire and enter one identity")

    @property
    def retiring_count(self) -> int:
        return len(self.retiring)

    @property
    def entering_count(self) -> int:
        return len(self.entering)

    @property
    def net_slot_cost(self) -> int:
        """Additional occupied slots after this group commits."""

        return self.entering_count - self.retiring_count


@dataclass(frozen=True, slots=True)
class CoarseTransitionStep:
    """Capacity proof for staging and committing one coverage group."""

    group: CoarseTransitionGroup
    free_before: int
    staging_margin: int
    free_after: int

    def __post_init__(self) -> None:
        if self.free_before < self.group.entering_count:
            raise ValueError("transition step cannot stage its entering group")
        if self.staging_margin != self.free_before - self.group.entering_count:
            raise ValueError("transition step has an inconsistent staging margin")
        expected_after = (
            self.free_before
            + self.group.retiring_count
            - self.group.entering_count
        )
        if self.free_after != expected_after:
            raise ValueError("transition step has an inconsistent final capacity")


@dataclass(frozen=True, slots=True)
class CoarseTransitionSchedule:
    """A complete render-idle group handoff within one fixed slot pool."""

    old_plan: CoarsePlan
    new_plan: CoarsePlan
    preserved: tuple[CoarsePlanEntry, ...]
    steps: tuple[CoarseTransitionStep, ...]
    slot_capacity: int
    initial_free_slots: int
    final_free_slots: int
    minimum_staging_margin: int

    def __post_init__(self) -> None:
        old = set(self.old_plan.entries)
        new = set(self.new_plan.entries)
        if set(self.preserved) != old & new:
            raise ValueError("transition schedule changed the preserved identity set")
        retiring = tuple(
            entry for step in self.steps for entry in step.group.retiring
        )
        entering = tuple(
            entry for step in self.steps for entry in step.group.entering
        )
        if set(retiring) != old - new or len(retiring) != len(set(retiring)):
            raise ValueError("transition schedule does not retire the exact old set")
        if set(entering) != new - old or len(entering) != len(set(entering)):
            raise ValueError("transition schedule does not enter the exact new set")
        if self.initial_free_slots != self.slot_capacity - len(old):
            raise ValueError("transition schedule has the wrong initial capacity")
        if self.final_free_slots != self.slot_capacity - len(new):
            raise ValueError("transition schedule has the wrong final capacity")
        margins = tuple(step.staging_margin for step in self.steps)
        expected_margin = min(margins, default=self.initial_free_slots)
        if self.minimum_staging_margin != expected_margin:
            raise ValueError("transition schedule has the wrong minimum margin")


def build_coarse_transition_groups(
    old_plan: CoarsePlan,
    new_plan: CoarsePlan,
) -> tuple[CoarseTransitionGroup, ...]:
    """Partition a hierarchy change by exact underlying L0 overlap.

    The bipartite graph contains one vertex for every retiring or entering
    hierarchy identity and an edge when the pair owns at least one common L0
    cell.  Connected components are the smallest groups whose ownership can be
    switched without separating a parent/child or boundary replacement.
    """

    old_set = set(old_plan.entries)
    new_set = set(new_plan.entries)
    retiring = tuple(entry for entry in old_plan.entries if entry not in new_set)
    entering = tuple(entry for entry in new_plan.entries if entry not in old_set)
    retiring_edges: list[list[int]] = [[] for _ in retiring]
    entering_edges: list[list[int]] = [[] for _ in entering]

    for old_index, old_entry in enumerate(retiring):
        old_coverage = _coarse_entry_coverage(old_entry)
        for new_index, new_entry in enumerate(entering):
            if old_coverage.isdisjoint(_coarse_entry_coverage(new_entry)):
                continue
            retiring_edges[old_index].append(new_index)
            entering_edges[new_index].append(old_index)

    seen_old: set[int] = set()
    seen_new: set[int] = set()
    groups: list[CoarseTransitionGroup] = []
    for first_old in range(len(retiring)):
        if first_old in seen_old:
            continue
        if not retiring_edges[first_old]:
            seen_old.add(first_old)
            groups.append(CoarseTransitionGroup((retiring[first_old],), ()))
            continue

        pending_old = [first_old]
        pending_new: list[int] = []
        component_old: list[int] = []
        component_new: list[int] = []
        seen_old.add(first_old)
        while pending_old or pending_new:
            while pending_old:
                old_index = pending_old.pop()
                component_old.append(old_index)
                for new_index in retiring_edges[old_index]:
                    if new_index in seen_new:
                        continue
                    seen_new.add(new_index)
                    pending_new.append(new_index)
            while pending_new:
                new_index = pending_new.pop()
                component_new.append(new_index)
                for old_index in entering_edges[new_index]:
                    if old_index in seen_old:
                        continue
                    seen_old.add(old_index)
                    pending_old.append(old_index)
        groups.append(
            CoarseTransitionGroup(
                tuple(retiring[index] for index in sorted(component_old)),
                tuple(entering[index] for index in sorted(component_new)),
            )
        )

    for new_index, new_entry in enumerate(entering):
        if new_index not in seen_new:
            groups.append(CoarseTransitionGroup((), (new_entry,)))

    return tuple(groups)


def _transition_group_sort_key(group: CoarseTransitionGroup) -> tuple:
    """Put slot-releasing groups before progressively expanding groups."""

    identities = tuple(
        entry.identity for entry in (*group.retiring, *group.entering)
    )
    return (
        group.net_slot_cost,
        group.entering_count,
        -group.retiring_count,
        identities,
    )


def schedule_coarse_transition(
    old_plan: CoarsePlan,
    new_plan: CoarsePlan,
    *,
    slot_capacity: int = COARSE_SLOT_COUNT,
) -> CoarseTransitionSchedule:
    """Build and prove a shrink-first staged hierarchy handoff.

    All entering meshes in one step are loaded and positioned into inactive
    slots while its retiring owners remain active.  A later render-idle commit
    activates the complete entering group and deactivates the retiring group;
    only then may their old slots be reused.  A ``RuntimeError`` means this
    policy cannot stage the transition within the supplied capacity.
    """

    if slot_capacity < len(old_plan.entries) or slot_capacity < len(new_plan.entries):
        raise RuntimeError("a transition endpoint exceeds the coarse slot pool")
    groups = tuple(
        sorted(
            build_coarse_transition_groups(old_plan, new_plan),
            key=_transition_group_sort_key,
        )
    )
    free = slot_capacity - len(old_plan.entries)
    initial_free = free
    steps: list[CoarseTransitionStep] = []
    for group in groups:
        if free < group.entering_count:
            raise RuntimeError(
                "coarse transition cannot stage a complete coverage group: "
                f"free={free}, entering={group.entering_count}, "
                f"retiring={group.retiring_count}"
            )
        after = free + group.retiring_count - group.entering_count
        steps.append(
            CoarseTransitionStep(
                group,
                free,
                free - group.entering_count,
                after,
            )
        )
        free = after

    old_set = set(old_plan.entries)
    new_set = set(new_plan.entries)
    schedule = CoarseTransitionSchedule(
        old_plan,
        new_plan,
        tuple(entry for entry in old_plan.entries if entry in new_set),
        tuple(steps),
        slot_capacity,
        initial_free,
        free,
        min(
            (step.staging_margin for step in steps),
            default=initial_free,
        ),
    )
    if set(schedule.preserved) != old_set & new_set:
        raise AssertionError("coarse transition lost a preserved identity")
    return schedule


@dataclass(frozen=True, slots=True)
class TerrainTransitionGroup:
    """One indivisible near/coarse ownership replacement component."""

    retiring: tuple[TerrainOwner, ...]
    entering: tuple[TerrainOwner, ...]

    def __post_init__(self) -> None:
        if not self.retiring and not self.entering:
            raise ValueError("a terrain transition group cannot be empty")
        if len(set(self.retiring)) != len(self.retiring):
            raise ValueError("a terrain transition group repeats a retiring owner")
        if len(set(self.entering)) != len(self.entering):
            raise ValueError("a terrain transition group repeats an entering owner")
        if set(self.retiring) & set(self.entering):
            raise ValueError("a terrain transition group cannot replace one owner")

    @property
    def retiring_count(self) -> int:
        return len(self.retiring)

    @property
    def entering_count(self) -> int:
        return len(self.entering)

    @property
    def net_slot_cost(self) -> int:
        return self.entering_count - self.retiring_count


@dataclass(frozen=True, slots=True)
class TerrainTransitionStep:
    """Capacity proof for one staged full-owner group handoff."""

    group: TerrainTransitionGroup
    free_before: int
    staging_margin: int
    free_after: int

    def __post_init__(self) -> None:
        if self.free_before < self.group.entering_count:
            raise ValueError("terrain transition step cannot stage its entering group")
        if self.staging_margin != self.free_before - self.group.entering_count:
            raise ValueError("terrain transition step has an inconsistent margin")
        expected_after = (
            self.free_before
            + self.group.retiring_count
            - self.group.entering_count
        )
        if self.free_after != expected_after:
            raise ValueError("terrain transition step has an inconsistent capacity")


@dataclass(frozen=True, slots=True)
class TerrainTransitionSchedule:
    """A complete near/coarse handoff in the 255-object manager pool."""

    old_plan: TerrainOwnerPlan
    new_plan: TerrainOwnerPlan
    preserved: tuple[TerrainOwner, ...]
    steps: tuple[TerrainTransitionStep, ...]
    slot_capacity: int
    initial_free_slots: int
    final_free_slots: int
    minimum_staging_margin: int

    def __post_init__(self) -> None:
        old = set(self.old_plan.owners)
        new = set(self.new_plan.owners)
        if set(self.preserved) != old & new:
            raise ValueError("terrain schedule changed the preserved owner set")
        retiring = tuple(
            owner for step in self.steps for owner in step.group.retiring
        )
        entering = tuple(
            owner for step in self.steps for owner in step.group.entering
        )
        if set(retiring) != old - new or len(retiring) != len(set(retiring)):
            raise ValueError("terrain schedule does not retire the exact old set")
        if set(entering) != new - old or len(entering) != len(set(entering)):
            raise ValueError("terrain schedule does not enter the exact new set")
        if self.initial_free_slots != self.slot_capacity - len(old):
            raise ValueError("terrain schedule has the wrong initial capacity")
        if self.final_free_slots != self.slot_capacity - len(new):
            raise ValueError("terrain schedule has the wrong final capacity")
        margins = tuple(step.staging_margin for step in self.steps)
        expected_margin = min(margins, default=self.initial_free_slots)
        if self.minimum_staging_margin != expected_margin:
            raise ValueError("terrain schedule has the wrong minimum margin")


def build_terrain_transition_groups(
    old_plan: TerrainOwnerPlan,
    new_plan: TerrainOwnerPlan,
) -> tuple[TerrainTransitionGroup, ...]:
    """Partition a complete plan change by exact L0 ownership overlap.

    Shared owner identities remain active and are removed before graphing.
    Each remaining old/new owner is a vertex; an edge means their bounded L0
    footprints intersect.  Connected components are therefore the smallest
    units that can replace near and coarse coverage without a partial handoff.
    """

    old_owners = old_plan.owners
    new_owners = new_plan.owners
    old_set = set(old_owners)
    new_set = set(new_owners)
    retiring = tuple(owner for owner in old_owners if owner not in new_set)
    entering = tuple(owner for owner in new_owners if owner not in old_set)
    retiring_edges: list[list[int]] = [[] for _ in retiring]
    entering_edges: list[list[int]] = [[] for _ in entering]

    for old_index, old_owner in enumerate(retiring):
        old_coverage = _terrain_owner_coverage(old_owner)
        for new_index, new_owner in enumerate(entering):
            if old_coverage.isdisjoint(_terrain_owner_coverage(new_owner)):
                continue
            retiring_edges[old_index].append(new_index)
            entering_edges[new_index].append(old_index)

    seen_old: set[int] = set()
    seen_new: set[int] = set()
    groups: list[TerrainTransitionGroup] = []
    for first_old in range(len(retiring)):
        if first_old in seen_old:
            continue
        if not retiring_edges[first_old]:
            seen_old.add(first_old)
            groups.append(TerrainTransitionGroup((retiring[first_old],), ()))
            continue

        pending_old = [first_old]
        pending_new: list[int] = []
        component_old: list[int] = []
        component_new: list[int] = []
        seen_old.add(first_old)
        while pending_old or pending_new:
            while pending_old:
                old_index = pending_old.pop()
                component_old.append(old_index)
                for new_index in retiring_edges[old_index]:
                    if new_index in seen_new:
                        continue
                    seen_new.add(new_index)
                    pending_new.append(new_index)
            while pending_new:
                new_index = pending_new.pop()
                component_new.append(new_index)
                for old_index in entering_edges[new_index]:
                    if old_index in seen_old:
                        continue
                    seen_old.add(old_index)
                    pending_old.append(old_index)
        groups.append(
            TerrainTransitionGroup(
                tuple(retiring[index] for index in sorted(component_old)),
                tuple(entering[index] for index in sorted(component_new)),
            )
        )

    for new_index, new_owner in enumerate(entering):
        if new_index not in seen_new:
            groups.append(TerrainTransitionGroup((), (new_owner,)))
    return tuple(groups)


def _terrain_transition_group_sort_key(group: TerrainTransitionGroup) -> tuple:
    identities = tuple(
        _terrain_owner_sort_key(owner)
        for owner in (*group.retiring, *group.entering)
    )
    return (
        group.net_slot_cost,
        group.entering_count,
        -group.retiring_count,
        identities,
    )


def schedule_terrain_transition(
    old_plan: TerrainOwnerPlan,
    new_plan: TerrainOwnerPlan,
    *,
    slot_capacity: int = MANAGER_SLOT_COUNT,
) -> TerrainTransitionSchedule:
    """Prove a failure-atomic, shrink-first full-owner transition.

    For each step, all entering owners stage in inactive slots while all
    retiring owners remain visible.  The complete group swaps at one
    render-idle boundary.  Retired slots become reusable only after that
    commit.  Selection is deterministic and considers only groups which fit
    the current free capacity, preferring the greatest immediate release.
    """

    old_owners = old_plan.owners
    new_owners = new_plan.owners
    if slot_capacity < len(old_owners) or slot_capacity < len(new_owners):
        raise RuntimeError("a terrain transition endpoint exceeds the slot pool")

    pending = list(build_terrain_transition_groups(old_plan, new_plan))
    free = slot_capacity - len(old_owners)
    initial_free = free
    steps: list[TerrainTransitionStep] = []
    while pending:
        feasible = [
            group for group in pending if group.entering_count <= free
        ]
        if not feasible:
            largest_release = max(
                (group.retiring_count - group.entering_count for group in pending),
                default=0,
            )
            raise RuntimeError(
                "terrain transition cannot stage any complete coverage group: "
                f"free={free}, pending={len(pending)}, "
                f"best_release={largest_release}"
            )
        group = min(feasible, key=_terrain_transition_group_sort_key)
        pending.remove(group)
        after = free + group.retiring_count - group.entering_count
        steps.append(
            TerrainTransitionStep(
                group,
                free,
                free - group.entering_count,
                after,
            )
        )
        free = after

    new_set = set(new_owners)
    return TerrainTransitionSchedule(
        old_plan,
        new_plan,
        tuple(owner for owner in old_owners if owner in new_set),
        tuple(steps),
        slot_capacity,
        initial_free,
        free,
        min(
            (step.staging_margin for step in steps),
            default=initial_free,
        ),
    )


@dataclass(frozen=True, slots=True)
class TerrainTransitionRecipe:
    """One canonical radius-five phase/direction transition schedule."""

    phase_q: int
    phase_offset_row: int
    direction_index: int
    schedule: TerrainTransitionSchedule

    def __post_init__(self) -> None:
        phase_index(self.phase_q, self.phase_offset_row)
        if not 0 <= self.direction_index < TRANSITION_DIRECTION_COUNT:
            raise ValueError("transition recipe has an invalid direction")
        old = self.schedule.old_plan
        if old.near_radius != TRANSITION_NEAR_RADIUS:
            raise ValueError("transition recipe is not radius five")
        if old.origin_q % PHASE_Q_COUNT != self.phase_q:
            raise ValueError("transition recipe old q phase is inconsistent")
        if old.origin_offset_row % PHASE_OFFSET_ROW_COUNT != self.phase_offset_row:
            raise ValueError("transition recipe old row phase is inconsistent")
        delta_q, delta_r = TRANSITION_DIRECTION_STEPS[self.direction_index]
        new = self.schedule.new_plan
        if (new.origin_q, new.origin_r) != (
            old.origin_q + delta_q,
            old.origin_r + delta_r,
        ):
            raise ValueError("transition recipe endpoint is not its named neighbor")

    @property
    def index(self) -> int:
        return (
            phase_index(self.phase_q, self.phase_offset_row)
            * TRANSITION_DIRECTION_COUNT
            + self.direction_index
        )

    @property
    def direction_name(self) -> str:
        return TRANSITION_DIRECTION_NAMES[self.direction_index]


@dataclass(frozen=True, slots=True)
class TransitionOrdinalGroup:
    """Decoded recipe group using old-plan and new-plan u8 ordinals."""

    retiring_ordinals: tuple[int, ...]
    entering_ordinals: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.retiring_ordinals and not self.entering_ordinals:
            raise ValueError("an ordinal transition group cannot be empty")
        for name, ordinals in (
            ("retiring", self.retiring_ordinals),
            ("entering", self.entering_ordinals),
        ):
            if len(set(ordinals)) != len(ordinals):
                raise ValueError(f"ordinal group repeats a {name} owner")
            if any(not 0 <= ordinal < MANAGER_SLOT_COUNT for ordinal in ordinals):
                raise ValueError(f"ordinal group has an invalid {name} ordinal")


@lru_cache(maxsize=None)
def build_terrain_transition_recipe(
    phase_q: int,
    phase_offset_row: int,
    direction_index: int,
) -> TerrainTransitionRecipe:
    """Build one translation-independent adjacent-transition recipe."""

    phase_index(phase_q, phase_offset_row)
    if not 0 <= direction_index < TRANSITION_DIRECTION_COUNT:
        raise ValueError("transition direction lies outside 0..5")
    origin_q = PHASE_REFERENCE_Q + phase_q
    origin_row = PHASE_REFERENCE_OFFSET_ROW + phase_offset_row
    origin_r = origin_row - origin_q // 2
    delta_q, delta_r = TRANSITION_DIRECTION_STEPS[direction_index]
    old_plan = build_terrain_owner_plan(
        origin_q,
        origin_r,
        TRANSITION_NEAR_RADIUS,
        clip_to_region=False,
    )
    new_plan = build_terrain_owner_plan(
        origin_q + delta_q,
        origin_r + delta_r,
        TRANSITION_NEAR_RADIUS,
        clip_to_region=False,
    )
    return TerrainTransitionRecipe(
        phase_q,
        phase_offset_row,
        direction_index,
        schedule_terrain_transition(old_plan, new_plan),
    )


def all_terrain_transition_recipes() -> tuple[TerrainTransitionRecipe, ...]:
    """Return all 192 recipes in phase-major, provider-direction order."""

    return tuple(
        build_terrain_transition_recipe(phase_q, phase_row, direction)
        for phase_q in range(PHASE_Q_COUNT)
        for phase_row in range(PHASE_OFFSET_ROW_COUNT)
        for direction in range(TRANSITION_DIRECTION_COUNT)
    )


@dataclass(frozen=True, slots=True)
class ResidentSlot:
    """The retained identity and publication state of one coarse slot."""

    identity: CoarsePlanEntry | None = None
    active: bool = False

    def __post_init__(self) -> None:
        if self.active and self.identity is None:
            raise ValueError("an active coarse slot must have an identity")


@dataclass(frozen=True, slots=True)
class AllocatorSnapshot:
    """All 164 coarse residents, indexed locally from global slot 91."""

    slots: tuple[ResidentSlot, ...]

    def __post_init__(self) -> None:
        if len(self.slots) != COARSE_SLOT_COUNT:
            raise ValueError(
                f"allocator snapshot needs {COARSE_SLOT_COUNT} coarse slots"
            )
        identities = tuple(
            slot.identity for slot in self.slots if slot.identity is not None
        )
        if len(set(identities)) != len(identities):
            raise ValueError("allocator snapshot contains duplicate identities")

    @classmethod
    def empty(cls) -> "AllocatorSnapshot":
        return cls((ResidentSlot(),) * COARSE_SLOT_COUNT)

    @property
    def active_count(self) -> int:
        return sum(slot.active for slot in self.slots)


@dataclass(frozen=True, slots=True)
class AllocatedPlanEntry:
    """One desired hierarchy identity with its live manager slot."""

    identity: CoarsePlanEntry
    slot: int

    def __post_init__(self) -> None:
        if not COARSE_SLOT_FIRST <= self.slot < MANAGER_SLOT_COUNT:
            raise ValueError(f"coarse slot lies outside 91..254: {self.slot}")

    @property
    def lod(self) -> int:
        return self.identity.lod

    @property
    def anchor_q(self) -> int:
        return self.identity.anchor_q

    @property
    def anchor_offset_row(self) -> int:
        return self.identity.anchor_offset_row


@dataclass(frozen=True, slots=True)
class AllocationResult:
    """One atomic plan reconciliation and its proof-oriented bookkeeping."""

    plan: CoarsePlan
    entries: tuple[AllocatedPlanEntry, ...]
    snapshot: AllocatorSnapshot
    protected_mask: bytes
    preserved_slots: tuple[int, ...]
    reactivated_slots: tuple[int, ...]
    loaded_slots: tuple[int, ...]
    deactivated_slots: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.protected_mask) != PROTECTED_MASK_BYTES:
            raise ValueError("protected mask has the wrong byte count")
        if tuple(entry.identity for entry in self.entries) != self.plan.entries:
            raise ValueError("allocated entries changed deterministic plan order")
        if len({entry.slot for entry in self.entries}) != len(self.entries):
            raise ValueError("allocated plan contains duplicate slots")
        if self.snapshot.active_count != len(self.entries):
            raise ValueError("active coarse set does not equal the desired plan")


def _protected_mask(local_slots: Iterable[int]) -> bytes:
    result = bytearray(PROTECTED_MASK_BYTES)
    for local_slot in local_slots:
        if not 0 <= local_slot < COARSE_SLOT_COUNT:
            raise ValueError(f"invalid local coarse slot: {local_slot}")
        result[local_slot // 8] |= 1 << (local_slot % 8)
    return bytes(result)


def protected_mask_contains(mask: bytes, global_slot: int) -> bool:
    """Test a global coarse slot in the allocator's 21-byte mask."""

    if len(mask) != PROTECTED_MASK_BYTES:
        raise ValueError("protected mask has the wrong byte count")
    if not COARSE_SLOT_FIRST <= global_slot < MANAGER_SLOT_COUNT:
        raise ValueError(f"coarse slot lies outside 91..254: {global_slot}")
    local = global_slot - COARSE_SLOT_FIRST
    return bool(mask[local // 8] & (1 << (local % 8)))


def allocate_coarse_plan(
    snapshot: AllocatorSnapshot,
    plan: CoarsePlan,
) -> AllocationResult:
    """Atomically reconcile a plan with protected-slot allocation.

    Pass one protects every desired identity already resident, preserving its
    slot whether it is active or inactive.  Pass two assigns each missing
    identity first to the lowest slot that was already inactive, then (only if
    necessary) to a stale active slot.  The preference matters to the live
    deferred handoff: replacing a mesh in a still-visible fallback slot would
    make the scenery jump before the desired plan converges.  Final snapshot
    state remains the completed desired plan, with stale residents inactive.
    """

    desired = set(plan.entries)
    existing = {
        resident.identity: local
        for local, resident in enumerate(snapshot.slots)
        if resident.identity is not None
    }
    work = list(snapshot.slots)
    active_before = tuple(resident.active for resident in snapshot.slots)
    local_by_identity: dict[CoarsePlanEntry, int] = {}
    protected: set[int] = set()
    preserved: list[int] = []
    reactivated: list[int] = []

    for identity in plan.entries:
        local = existing.get(identity)
        if local is None:
            continue
        local_by_identity[identity] = local
        protected.add(local)
        if work[local].active:
            preserved.append(COARSE_SLOT_FIRST + local)
        else:
            reactivated.append(COARSE_SLOT_FIRST + local)

    deactivated: list[int] = []
    for local, resident in enumerate(work):
        if resident.active and resident.identity not in desired:
            work[local] = ResidentSlot(resident.identity, False)
            deactivated.append(COARSE_SLOT_FIRST + local)

    # Re-publish inactive cache hits only after every reusable slot is known
    # and protected.
    for identity, local in local_by_identity.items():
        work[local] = ResidentSlot(identity, True)

    loaded: list[int] = []
    for identity in plan.entries:
        if identity in local_by_identity:
            continue
        candidates = tuple(
            candidate
            for candidate in range(COARSE_SLOT_COUNT)
            if candidate not in protected
        )
        if not candidates:
            raise RuntimeError("qualified coarse plan exhausted its slot pool")
        local = next(
            (candidate for candidate in candidates if not active_before[candidate]),
            candidates[0],
        )
        if local in protected:
            raise AssertionError("allocator selected a protected slot")
        work[local] = ResidentSlot(identity, True)
        local_by_identity[identity] = local
        protected.add(local)
        loaded.append(COARSE_SLOT_FIRST + local)

    entries = tuple(
        AllocatedPlanEntry(identity, COARSE_SLOT_FIRST + local_by_identity[identity])
        for identity in plan.entries
    )
    result = AllocationResult(
        plan,
        entries,
        AllocatorSnapshot(tuple(work)),
        _protected_mask(protected),
        tuple(preserved),
        tuple(reactivated),
        tuple(loaded),
        tuple(deactivated),
    )
    if any(not protected_mask_contains(result.protected_mask, entry.slot) for entry in entries):
        raise AssertionError("desired coarse slot is absent from protected mask")
    return result


class ProtectedSlotAllocator:
    """Stateful convenience wrapper around :func:`allocate_coarse_plan`."""

    def __init__(self, snapshot: AllocatorSnapshot | None = None) -> None:
        self._snapshot = AllocatorSnapshot.empty() if snapshot is None else snapshot

    @property
    def snapshot(self) -> AllocatorSnapshot:
        return self._snapshot

    def reconcile(self, plan: CoarsePlan) -> AllocationResult:
        result = allocate_coarse_plan(self._snapshot, plan)
        self._snapshot = result.snapshot
        return result


@dataclass(frozen=True, slots=True)
class RuntimePlan:
    """Complete near/coarse desired set for the unchanged 255-slot manager."""

    near_entries: tuple[NearPlanEntry, ...]
    coarse: AllocationResult

    def __post_init__(self) -> None:
        slots = tuple(entry.slot for entry in self.near_entries) + tuple(
            entry.slot for entry in self.coarse.entries
        )
        if len(set(slots)) != len(slots):
            raise ValueError("near and coarse runtime slots overlap")
        if any(not 0 <= slot < MANAGER_SLOT_COUNT for slot in slots):
            raise ValueError("runtime plan contains an invalid manager slot")

    @property
    def active_count(self) -> int:
        return len(self.near_entries) + len(self.coarse.entries)


def build_runtime_plan(
    allocator: ProtectedSlotAllocator,
    origin_q: int,
    origin_r: int,
    near_radius: int,
    *,
    clip_to_region: bool = True,
    use_phase_table: bool = True,
) -> RuntimePlan:
    """Select and allocate one complete manager desired set."""

    near = build_near_plan(
        origin_q,
        origin_r,
        near_radius,
        clip_to_region=clip_to_region,
    )
    builder = resolve_phase_plan if use_phase_table else build_coarse_plan
    coarse = builder(
        origin_q,
        origin_r,
        near_radius,
        clip_to_region=clip_to_region,
    )
    return RuntimePlan(near, allocator.reconcile(coarse))


def encode_plan_template(plan: CoarsePlan) -> bytes:
    """Encode count plus mutable 6-byte provider records.

    Every slot byte is ``0xff``.  Firmware fills those bytes only after its
    protected allocation pass; anchors are signed little-endian 16-bit values.
    """

    result = bytearray((len(plan.entries),))
    for entry in plan.entries:
        result.extend(
            struct.pack(
                "<BhhB",
                entry.lod,
                entry.anchor_q,
                entry.anchor_offset_row,
                UNASSIGNED_SLOT,
            )
        )
    return bytes(result)


def encode_allocated_plan(result: AllocationResult) -> bytes:
    """Encode the same table after runtime slots have been assigned."""

    encoded = bytearray((len(result.entries),))
    for entry in result.entries:
        encoded.extend(
            struct.pack(
                "<BhhB",
                entry.lod,
                entry.anchor_q,
                entry.anchor_offset_row,
                entry.slot,
            )
        )
    return bytes(encoded)


def encode_phase_plan(plan: PhasePlan) -> bytes:
    """Encode count plus compact ``lod,s8 dq,s8 drow`` records."""

    result = bytearray((len(plan.entries),))
    for entry in plan.entries:
        result.extend(
            struct.pack(
                "<Bbb",
                entry.lod,
                entry.anchor_q_offset,
                entry.anchor_offset_row_offset,
            )
        )
    return bytes(result)


def _u24(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFF:
        raise ValueError(f"value lies outside unsigned 24-bit range: {value}")
    return value.to_bytes(3, "little")


def transition_recipe_ordinal_groups(
    recipe: TerrainTransitionRecipe,
) -> tuple[TransitionOrdinalGroup, ...]:
    """Resolve a recipe's owner identities to endpoint-local u8 ordinals."""

    old_ordinals = {
        owner: ordinal
        for ordinal, owner in enumerate(recipe.schedule.old_plan.owners)
    }
    new_ordinals = {
        owner: ordinal
        for ordinal, owner in enumerate(recipe.schedule.new_plan.owners)
    }
    return tuple(
        TransitionOrdinalGroup(
            tuple(old_ordinals[owner] for owner in step.group.retiring),
            tuple(new_ordinals[owner] for owner in step.group.entering),
        )
        for step in recipe.schedule.steps
    )


def encode_transition_recipe(recipe: TerrainTransitionRecipe) -> bytes:
    """Encode one variable-length grouped handoff recipe.

    Schema::

        group_count:u8
        repeat group_count times:
            retiring_count:u8
            entering_count:u8
            old_owner_ordinals[retiring_count]:u8
            new_owner_ordinals[entering_count]:u8
    """

    groups = transition_recipe_ordinal_groups(recipe)
    if len(groups) > 0xFF:
        raise ValueError("transition recipe has too many groups")
    encoded = bytearray((len(groups),))
    for group in groups:
        encoded.extend(
            (len(group.retiring_ordinals), len(group.entering_ordinals))
        )
        encoded.extend(group.retiring_ordinals)
        encoded.extend(group.entering_ordinals)
    return bytes(encoded)


def decode_transition_recipe(payload: bytes) -> tuple[TransitionOrdinalGroup, ...]:
    """Decode one exact recipe payload and reject truncation or trailing data."""

    if not payload:
        raise ValueError("transition recipe payload is empty")
    group_count = payload[TRANSITION_RECIPE_GROUP_COUNT]
    cursor = 1
    groups: list[TransitionOrdinalGroup] = []
    for _ in range(group_count):
        if cursor + TRANSITION_GROUP_ORDINALS > len(payload):
            raise ValueError("transition recipe ends inside a group header")
        retiring_count = payload[cursor + TRANSITION_GROUP_RETIRING_COUNT]
        entering_count = payload[cursor + TRANSITION_GROUP_ENTERING_COUNT]
        cursor += TRANSITION_GROUP_ORDINALS
        end_retiring = cursor + retiring_count
        end_entering = end_retiring + entering_count
        if end_entering > len(payload):
            raise ValueError("transition recipe ends inside an ordinal list")
        groups.append(
            TransitionOrdinalGroup(
                tuple(payload[cursor:end_retiring]),
                tuple(payload[end_retiring:end_entering]),
            )
        )
        cursor = end_entering
    if cursor != len(payload):
        raise ValueError("transition recipe has trailing bytes")
    return tuple(groups)


def resolve_transition_recipe_groups(
    recipe: TerrainTransitionRecipe,
    origin_q: int,
    origin_r: int,
    *,
    clip_to_region: bool = True,
) -> tuple[TerrainTransitionGroup, ...]:
    """Resolve source ordinals at any translation of a recipe's old phase.

    Recipe ordinals are deliberately *not* dense runtime ordinals.  They name
    the unbounded source plans: near ordinals 0..90 follow ``disk_offsets(5)``
    and coarse ordinals continue at 91 in static phase-record order.  At a
    corpus edge, an absent source ordinal is skipped rather than renumbered.
    This makes an interior-generated component a conservative supergroup for
    every clipped translation and prevents a recipe from selecting the wrong
    owner when invalid phase entries disappear.
    """

    if origin_q % PHASE_Q_COUNT != recipe.phase_q:
        raise ValueError("origin q does not match transition recipe phase")
    origin_row = offset_row(origin_q, origin_r)
    if origin_row % PHASE_OFFSET_ROW_COUNT != recipe.phase_offset_row:
        raise ValueError("origin row does not match transition recipe phase")
    delta_q, delta_r = TRANSITION_DIRECTION_STEPS[recipe.direction_index]
    old_source = build_terrain_owner_plan(
        origin_q,
        origin_r,
        TRANSITION_NEAR_RADIUS,
        clip_to_region=False,
    )
    new_source = build_terrain_owner_plan(
        origin_q + delta_q,
        origin_r + delta_r,
        TRANSITION_NEAR_RADIUS,
        clip_to_region=False,
    )
    if clip_to_region:
        old_present = set(
            build_terrain_owner_plan(
                origin_q,
                origin_r,
                TRANSITION_NEAR_RADIUS,
                clip_to_region=True,
            ).owners
        )
        new_present = set(
            build_terrain_owner_plan(
                origin_q + delta_q,
                origin_r + delta_r,
                TRANSITION_NEAR_RADIUS,
                clip_to_region=True,
            ).owners
        )
    else:
        old_present = set(old_source.owners)
        new_present = set(new_source.owners)

    groups: list[TerrainTransitionGroup] = []
    for ordinal_group in transition_recipe_ordinal_groups(recipe):
        retiring = tuple(
            old_source.owners[ordinal]
            for ordinal in ordinal_group.retiring_ordinals
            if old_source.owners[ordinal] in old_present
        )
        entering = tuple(
            new_source.owners[ordinal]
            for ordinal in ordinal_group.entering_ordinals
            if new_source.owners[ordinal] in new_present
        )
        if retiring or entering:
            groups.append(TerrainTransitionGroup(retiring, entering))
    return tuple(groups)


def encode_transition_table(
    recipes: Sequence[TerrainTransitionRecipe] | None = None,
) -> bytes:
    """Encode the 192-entry radius-five adjacent-transition table.

    The directory contains 192 little-endian u24 offsets relative to the
    start of the returned blob.  Payloads follow in phase-major order, with
    the six directions in exact ``hex_provider_origin_steps`` order.
    """

    selected = (
        all_terrain_transition_recipes()
        if recipes is None
        else tuple(recipes)
    )
    if len(selected) != TRANSITION_RECIPE_COUNT:
        raise ValueError(
            f"transition table needs exactly {TRANSITION_RECIPE_COUNT} recipes"
        )
    if tuple(recipe.index for recipe in selected) != tuple(
        range(TRANSITION_RECIPE_COUNT)
    ):
        raise ValueError("transition recipes are not in canonical table order")
    payloads = tuple(encode_transition_recipe(recipe) for recipe in selected)
    cursor = TRANSITION_RECIPE_COUNT * TRANSITION_DIRECTORY_POINTER_BYTES
    directory = bytearray()
    for payload in payloads:
        directory.extend(_u24(cursor))
        cursor += len(payload)
    return bytes(directory) + b"".join(payloads)


def encode_phase_table(plans: Sequence[PhasePlan] | None = None) -> bytes:
    """Encode a random-access table for all 192 plans.

    The first ``192*3`` bytes are little-endian 24-bit offsets from the start
    of the returned blob.  Each target is an :func:`encode_phase_plan` record.
    """

    selected = all_phase_plans() if plans is None else tuple(plans)
    if len(selected) != PHASE_PLAN_COUNT:
        raise ValueError(f"phase table needs exactly {PHASE_PLAN_COUNT} plans")
    if tuple(plan.index for plan in selected) != tuple(range(PHASE_PLAN_COUNT)):
        raise ValueError("phase plans are not in canonical table order")
    payloads = tuple(encode_phase_plan(plan) for plan in selected)
    cursor = PHASE_PLAN_COUNT * 3
    directory = bytearray()
    for payload in payloads:
        directory.extend(_u24(cursor))
        cursor += len(payload)
    return bytes(directory) + b"".join(payloads)


def emit_plan_include(plan: CoarsePlan, prefix: str = "regular_lod_plan") -> str:
    """Emit one assembly-ready mutable plan table.

    The generated slot field deliberately starts at ``0ffh``.  It is not a
    fixed-slot fixture table; the runtime allocator owns that byte.
    """

    if not _ASSEMBLY_IDENTIFIER.fullmatch(prefix):
        raise ValueError(f"invalid assembly label prefix: {prefix!r}")
    lines = [
        "; Generated by pingo_terrain.regular_lod_runtime.emit_plan_include.",
        f"{prefix}_record_lod: equ {PLAN_RECORD_LOD}",
        f"{prefix}_record_anchor_q: equ {PLAN_RECORD_ANCHOR_Q}",
        f"{prefix}_record_anchor_offset_row: equ {PLAN_RECORD_ANCHOR_OFFSET_ROW}",
        f"{prefix}_record_slot: equ {PLAN_RECORD_SLOT}",
        f"{prefix}_record_bytes: equ {PLAN_RECORD_BYTES}",
        f"{prefix}_count:",
        f"    db {len(plan.entries)}",
        f"{prefix}_entries:",
    ]
    for entry in plan.entries:
        lines.extend(
            (
                f"    db {entry.lod}",
                f"    dw {entry.anchor_q},{entry.anchor_offset_row}",
                "    db 0ffh",
            )
        )
    return "\n".join(lines) + "\n"


def emit_phase_include(prefix: str = "regular_lod_phase") -> str:
    """Emit all 192 compact phase profiles as an assembly include.

    ``<prefix>_offsets`` is a directory of 24-bit pointers to count-prefixed
    profiles.  ``<prefix>_payload`` marks the beginning of those profiles.
    Each static record contains only ``lod,s8 dq,s8 drow``; the provider
    resolves the two anchors and copies them into a mutable six-byte plan
    record before protected slot allocation.
    """

    if not _ASSEMBLY_IDENTIFIER.fullmatch(prefix):
        raise ValueError(f"invalid assembly label prefix: {prefix!r}")
    plans = all_phase_plans()
    labels = tuple(
        f"{prefix}_r{plan.near_radius}_q{plan.phase_q}_o{plan.phase_offset_row}"
        for plan in plans
    )
    lines = [
        "; Generated by pingo_terrain.regular_lod_runtime.emit_phase_include.",
        "; Index = near_radius*32 + (origin_q&7)*4 + (origin_offset_row&3).",
        "; Profile: count:u8, followed by count static records.",
        f"{prefix}_near_radius_count: equ {NEAR_RING_MAX + 1}",
        f"{prefix}_q_count: equ {PHASE_Q_COUNT}",
        f"{prefix}_offset_row_count: equ {PHASE_OFFSET_ROW_COUNT}",
        f"{prefix}_count: equ {PHASE_PLAN_COUNT}",
        f"{prefix}_profile_count: equ 0",
        f"{prefix}_profile_entries: equ 1",
        f"{prefix}_record_lod: equ 0",
        f"{prefix}_record_anchor_q_offset: equ 1",
        f"{prefix}_record_anchor_offset_row_offset: equ 2",
        f"{prefix}_record_bytes: equ {PHASE_RECORD_BYTES}",
        f"{prefix}_maximum_records: equ {PROVEN_COARSE_PLAN_MAX}",
        f"{prefix}_offsets:",
    ]
    lines.extend(f"    dl {label}" for label in labels)
    lines.append(f"{prefix}_payload:")
    for plan, label in zip(plans, labels, strict=True):
        lines.extend((f"{label}:", f"    db {len(plan.entries)}"))
        lines.extend(
            f"    db {entry.lod},{entry.anchor_q_offset & 0xFF:02X}h,"
            f"{entry.anchor_offset_row_offset & 0xFF:02X}h"
            for entry in plan.entries
        )
    return "\n".join(lines) + "\n"


def emit_transition_include(prefix: str = "regular_lod_transition") -> str:
    """Emit the canonical full-owner radius-five transition recipes.

    Directory entries are assembly-native 24-bit pointers.  The documented
    hash is over :func:`encode_transition_table`, whose directory instead uses
    blob-relative u24 offsets so the same logical table is host-verifiable
    independently of its eventual assembly address.
    """

    if not _ASSEMBLY_IDENTIFIER.fullmatch(prefix):
        raise ValueError(f"invalid assembly label prefix: {prefix!r}")
    recipes = all_terrain_transition_recipes()
    labels = tuple(
        f"{prefix}_q{recipe.phase_q}_o{recipe.phase_offset_row}_"
        f"{recipe.direction_name}"
        for recipe in recipes
    )
    encoded = encode_transition_table(recipes)
    directory_bytes = (
        TRANSITION_RECIPE_COUNT * TRANSITION_DIRECTORY_POINTER_BYTES
    )
    payload_bytes = len(encoded) - directory_bytes
    digest = hashlib.sha256(encoded).hexdigest()
    maximum_groups = max(len(recipe.schedule.steps) for recipe in recipes)
    maximum_retiring = max(
        step.group.retiring_count
        for recipe in recipes
        for step in recipe.schedule.steps
    )
    maximum_entering = max(
        step.group.entering_count
        for recipe in recipes
        for step in recipe.schedule.steps
    )
    minimum_margin = min(
        recipe.schedule.minimum_staging_margin for recipe in recipes
    )
    lines = [
        "; Generated by pingo_terrain.regular_lod_runtime.emit_transition_include.",
        "; Index = ((origin_q&7)*4 + (origin_offset_row&3))*6 + direction.",
        "; Directions exactly match hex_provider_origin_steps.",
        "; Owner ordinals name the unbounded source plan; absent edge owners",
        "; are 0ffh in the runtime ordinal map and must be skipped, never packed.",
        "; Source plan = 91 near disk entries, then static coarse phase records.",
        "; Recipe: group_count:u8, followed by variable-length groups.",
        "; Group: retiring_count:u8, entering_count:u8, then old source",
        "; ordinals[retiring_count] and new source ordinals[entering_count].",
        f"; Canonical offset-table SHA-256: {digest}",
        f"{prefix}_near_radius: equ {TRANSITION_NEAR_RADIUS}",
        f"{prefix}_q_count: equ {PHASE_Q_COUNT}",
        f"{prefix}_offset_row_count: equ {PHASE_OFFSET_ROW_COUNT}",
        f"{prefix}_direction_count: equ {TRANSITION_DIRECTION_COUNT}",
        f"{prefix}_count: equ {TRANSITION_RECIPE_COUNT}",
        f"{prefix}_directory_pointer_bytes: equ "
        f"{TRANSITION_DIRECTORY_POINTER_BYTES}",
        f"{prefix}_directory_bytes: equ {directory_bytes}",
        f"{prefix}_payload_bytes: equ {payload_bytes}",
        f"{prefix}_table_bytes: equ {len(encoded)}",
        f"{prefix}_maximum_groups: equ {maximum_groups}",
        f"{prefix}_maximum_retiring: equ {maximum_retiring}",
        f"{prefix}_maximum_entering: equ {maximum_entering}",
        f"{prefix}_minimum_staging_margin: equ {minimum_margin}",
        f"{prefix}_recipe_group_count: equ {TRANSITION_RECIPE_GROUP_COUNT}",
        f"{prefix}_group_retiring_count: equ {TRANSITION_GROUP_RETIRING_COUNT}",
        f"{prefix}_group_entering_count: equ {TRANSITION_GROUP_ENTERING_COUNT}",
        f"{prefix}_group_ordinals: equ {TRANSITION_GROUP_ORDINALS}",
    ]
    for index, (name, (delta_q, delta_r)) in enumerate(
        zip(
            TRANSITION_DIRECTION_NAMES,
            TRANSITION_DIRECTION_STEPS,
            strict=True,
        )
    ):
        lines.extend(
            (
                f"{prefix}_direction_{name}: equ {index}",
                f"; direction {index} {name}: dq={delta_q}, dr={delta_r}",
            )
        )
    lines.append(f"{prefix}_offsets:")
    lines.extend(f"    dl {label}" for label in labels)
    lines.append(f"{prefix}_payload:")
    for recipe, label in zip(recipes, labels, strict=True):
        groups = transition_recipe_ordinal_groups(recipe)
        lines.extend((f"{label}:", f"    db {len(groups)}"))
        for group in groups:
            values = (
                len(group.retiring_ordinals),
                len(group.entering_ordinals),
                *group.retiring_ordinals,
                *group.entering_ordinals,
            )
            lines.append("    db " + ",".join(str(value) for value in values))
    return "\n".join(lines) + "\n"


def emit_runtime_include(
    phase_prefix: str = "regular_lod_phase",
    transition_prefix: str = "regular_lod_transition",
) -> str:
    """Emit phase profiles and full-owner handoff recipes as one include."""

    return (
        emit_phase_include(phase_prefix)
        + "\n"
        + emit_transition_include(transition_prefix)
    )
