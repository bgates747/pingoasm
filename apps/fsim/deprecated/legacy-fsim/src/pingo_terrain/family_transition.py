"""Exact two-family runtime plan for the first mixed-LOD flight proof.

This module turns :func:`regional_lod.active_plan` into stable Pingo object
slots and exact nested-AGNB requests.  It deliberately models one cardinal
west transition from KOAK's family ``(23, 36)`` to ``(22, 36)``.  The narrow
scope keeps the first target fixture auditable while exercising every runtime
mechanism needed by a general coordinator: two L0 banks, staged D1 repair, a
staged D2 replacement, and one render-idle activation transaction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .nested_agnb import RecordIdentity
from .p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    ShadingMode,
)
from .regional_lod import (
    ActiveComponent,
    ActiveTerrainPlan,
    SuperTileGrid,
    active_plan,
    component_specs,
)


PINGO_COUNTS_PER_METRE = 16
PINGO_SCALE_Q8_PER_METRE = 32
REGIONAL_VERTICAL_ORIGIN_M = 608
KOAK_CURRENT_FAMILY = (23, 36)
KOAK_NEXT_WEST_FAMILY = (22, 36)


@dataclass(frozen=True, slots=True)
class ComponentWireRequest:
    component: ActiveComponent
    family_id: int
    path: PurePosixPath
    record_index: int
    expected: RecordIdentity
    center_east_m: int
    center_north_m: int
    center_east_counts: int
    center_north_counts: int
    scale_q8_8: int


@dataclass(frozen=True, slots=True)
class FamilyLoadEntry:
    phase: str
    slot: int
    request: ComponentWireRequest
    activate_after_load: bool


@dataclass(frozen=True, slots=True)
class ActivationTransaction:
    """Command-51 order inside one render-idle transaction."""

    deactivate_distant: tuple[int, ...]
    deactivate_transition: tuple[int, ...]
    deactivate_near: tuple[int, ...]
    activate_near: tuple[int, ...]
    activate_transition: tuple[int, ...]
    activate_distant: tuple[int, ...]

    @property
    def deactivations(self) -> tuple[int, ...]:
        return (
            self.deactivate_distant
            + self.deactivate_transition
            + self.deactivate_near
        )

    @property
    def activations(self) -> tuple[int, ...]:
        return (
            self.activate_near
            + self.activate_transition
            + self.activate_distant
        )


@dataclass(frozen=True, slots=True)
class FixedWestTransition:
    current_plan: ActiveTerrainPlan
    next_plan: ActiveTerrainPlan
    boot_near: tuple[FamilyLoadEntry, ...]
    reconcile_transition: tuple[FamilyLoadEntry, ...]
    reconcile_distant: tuple[FamilyLoadEntry, ...]
    preload_next_near: tuple[FamilyLoadEntry, ...]
    preload_plan_delta: tuple[FamilyLoadEntry, ...]
    swap: ActivationTransaction

    @property
    def load_entries(self) -> tuple[FamilyLoadEntry, ...]:
        return (
            self.boot_near
            + self.reconcile_transition
            + self.reconcile_distant
            + self.preload_next_near
            + self.preload_plan_delta
        )

    @property
    def required_families(self) -> tuple[tuple[int, int], ...]:
        families = {
            (entry.request.component.super_x, entry.request.component.super_y)
            for entry in self.load_entries
        }
        return tuple(sorted(families, key=lambda item: (item[1], item[0])))

    def to_json_record(self) -> dict[str, object]:
        def entry_record(entry: FamilyLoadEntry) -> dict[str, object]:
            request = entry.request
            return {
                "phase": entry.phase,
                "slot": entry.slot,
                "activate_after_load": entry.activate_after_load,
                "component": asdict(request.component),
                "family_id": request.family_id,
                "path": request.path.as_posix(),
                "record_index": request.record_index,
                "expected": asdict(request.expected),
                "center_counts": [
                    request.center_east_counts,
                    request.center_north_counts,
                ],
                "scale_q8_8": request.scale_q8_8,
            }

        return {
            "schema": "pingo-terrain-fixed-west-family-transition-v1",
            "current_family": list(KOAK_CURRENT_FAMILY),
            "next_family": list(KOAK_NEXT_WEST_FAMILY),
            "required_families": [list(item) for item in self.required_families],
            "loads": [entry_record(item) for item in self.load_entries],
            "swap": {
                key: list(value)
                for key, value in asdict(self.swap).items()
            },
        }


class FixedTransitionRuntime:
    """Transactional host oracle for the target fixture's one-load service.

    The model intentionally separates planning from successful publication.
    A failed nested read therefore cannot advance the cursor, claim residency,
    activate a partial bank, or disturb the already displayed plan.
    """

    def __init__(self, plan: FixedWestTransition):
        self.plan = plan
        self._cursor = 0
        self._pending: FamilyLoadEntry | None = None
        self._resident: dict[int, ActiveComponent] = {}
        self._active: set[int] = set()
        self.error_hold = False
        self.swapped = False

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def resident(self) -> dict[int, ActiveComponent]:
        return dict(self._resident)

    @property
    def active_slots(self) -> frozenset[int]:
        return frozenset(self._active)

    @property
    def active_components(self) -> frozenset[ActiveComponent]:
        return frozenset(self._resident[slot] for slot in self._active)

    @property
    def armed(self) -> bool:
        return (
            not self.error_hold
            and self._pending is None
            and self._cursor == len(self.plan.load_entries)
        )

    def plan_one_load(self) -> FamilyLoadEntry | None:
        if self._pending is not None:
            raise RuntimeError("a family load is already pending")
        if self.error_hold or self._cursor == len(self.plan.load_entries):
            return None
        self._pending = self.plan.load_entries[self._cursor]
        return self._pending

    def commit_load(self, entry: FamilyLoadEntry) -> None:
        if entry != self._pending:
            raise ValueError("family load commit does not match the pending entry")
        if entry.slot in self._active:
            raise AssertionError("scheduler attempted to replace an active mesh")
        self._resident[entry.slot] = entry.request.component
        if entry.activate_after_load:
            self._active.add(entry.slot)
        self._cursor += 1
        self._pending = None
        self._check_active_budget()

    def abort_load(self, entry: FamilyLoadEntry) -> None:
        if entry != self._pending:
            raise ValueError("family load abort does not match the pending entry")
        self._pending = None
        self.error_hold = True

    def swap_if_crossed(self, coarse_tile_x: int) -> bool:
        """Apply the complete command-51 group at the west family boundary."""

        if self.swapped or coarse_tile_x >= 92:
            return False
        if not self.armed:
            return False
        before = set(self._active)
        for slot in self.plan.swap.deactivations:
            if slot not in self._active:
                raise AssertionError(f"swap deactivates inactive slot {slot}")
            self._active.remove(slot)
        for slot in self.plan.swap.activations:
            if slot in self._active or slot not in self._resident:
                raise AssertionError(f"swap activates invalid slot {slot}")
            self._active.add(slot)
        self._check_active_budget()
        if len(before) != len(self._active):
            raise AssertionError("family swap changed the steady terrain count")
        expected = frozenset(
            self.plan.next_plan.near
            + self.plan.next_plan.transition
            + self.plan.next_plan.distant
        )
        if self.active_components != expected:
            raise AssertionError("family swap did not publish the exact next plan")
        self.swapped = True
        return True

    def _check_active_budget(self) -> None:
        if len(self._active) > 24:
            raise AssertionError("family runtime exceeded 24 active terrain objects")


def assembly_include(plan: FixedWestTransition) -> str:
    """Emit the compact, byte-width-explicit table consumed by the eZ80."""

    lines = [
        "; Generated by pingo_terrain.family_transition; do not hand edit.",
        "family_plan_entry_size: equ 17",
        f"family_plan_boot_count: equ {len(plan.boot_near)}",
        "family_plan_steady_count: equ 24",
        f"family_plan_total_count: equ {len(plan.load_entries)}",
        "family_plan_table:",
    ]
    for entry in plan.load_entries:
        request = entry.request
        expected = request.expected
        lines.extend(
            (
                f"    ; {entry.phase} slot {entry.slot}: "
                f"{request.component.tier} "
                f"({request.component.super_x},{request.component.super_y}) "
                f"{request.component.component_key}",
                f"    db {entry.slot}",
                f"    dw {request.family_id}",
                f"    db {expected.lod}",
                f"    dw {expected.tile_x},{expected.tile_y}",
                f"    dl {request.center_east_counts}",
                f"    dl {request.center_north_counts}",
                f"    dw {request.scale_q8_8}",
                f"    db {1 if entry.activate_after_load else 0}",
            )
        )
    lines.extend(
        (
            "family_swap_deactivate_count: equ "
            f"{len(plan.swap.deactivations)}",
            "family_swap_deactivate_ids:",
            "    db " + ",".join(str(value) for value in plan.swap.deactivations),
            "family_swap_activate_count: equ "
            f"{len(plan.swap.activations)}",
            "family_swap_activate_ids:",
            "    db " + ",".join(str(value) for value in plan.swap.activations),
            "",
        )
    )
    return "\n".join(lines)


def component_wire_request(
    grid: SuperTileGrid, component: ActiveComponent
) -> ComponentWireRequest:
    """Resolve one active-plan component to its exact disk/wire transform."""

    supertile = grid.supertile(component.super_x, component.super_y)
    specs = component_specs(supertile)
    try:
        record_index, spec = next(
            (index, candidate)
            for index, candidate in enumerate(specs)
            if candidate.key == component.component_key
        )
    except StopIteration as error:
        raise ValueError(f"component key is absent from family: {component}") from error
    if spec.tier != component.tier:
        raise ValueError(
            f"component tier/key mismatch: {component.tier}/{component.component_key}"
        )

    west, south, east, north = spec.rectangle.bounds(grid.base)
    center_east = round((west + east) / 2.0 - grid.base.origin_east_m)
    center_north = round((south + north) / 2.0 - grid.base.origin_north_m)
    return ComponentWireRequest(
        component=component,
        family_id=supertile.super_id,
        path=grid.path(component.super_x, component.super_y),
        record_index=record_index,
        expected=RecordIdentity(
            int(LayerKind.TERRAIN),
            spec.lod,
            int(ShadingMode.FLAT_PATTERN),
            int(IlluminationPolicy.SCENE),
            int(MaterialSet.TERRAIN_SELECTOR_4X4),
            spec.rectangle.tile_x,
            spec.rectangle.tile_y,
        ),
        center_east_m=center_east,
        center_north_m=center_north,
        center_east_counts=center_east * PINGO_COUNTS_PER_METRE,
        center_north_counts=center_north * PINGO_COUNTS_PER_METRE,
        scale_q8_8=spec.model_half_extent_m * PINGO_SCALE_Q8_PER_METRE,
    )


def _entries(
    grid: SuperTileGrid,
    phase: str,
    slots: tuple[int, ...],
    components: tuple[ActiveComponent, ...],
    *,
    activate: bool,
) -> tuple[FamilyLoadEntry, ...]:
    if len(slots) != len(components):
        raise ValueError(f"{phase} slot/component count mismatch")
    return tuple(
        FamilyLoadEntry(
            phase,
            slot,
            component_wire_request(grid, component),
            activate,
        )
        for slot, component in zip(slots, components, strict=True)
    )


def build_fixed_west_transition(
    grid: SuperTileGrid = SuperTileGrid(),
) -> FixedWestTransition:
    """Build the exact KOAK cardinal-west two-bank transition witness."""

    current = active_plan(
        grid,
        *KOAK_CURRENT_FAMILY,
        heading_east=-1.0,
        heading_north=0.0,
    )
    following = active_plan(
        grid,
        *KOAK_NEXT_WEST_FAMILY,
        heading_east=-1.0,
        heading_north=0.0,
    )
    if (len(current.near), len(current.transition), len(current.distant)) != (
        8,
        8,
        8,
    ):
        raise AssertionError("KOAK current family no longer has an 8/8/8 plan")

    boot_near = _entries(
        grid, "BOOT_L0", tuple(range(1, 9)), current.near, activate=True
    )
    reconcile_transition = _entries(
        grid,
        "RECONCILE_D1",
        tuple(range(17, 25)),
        current.transition,
        activate=True,
    )
    reconcile_distant = _entries(
        grid,
        "RECONCILE_D2",
        tuple(range(29, 37)),
        current.distant,
        activate=True,
    )
    preload_next_near = _entries(
        grid,
        "PRELOAD_NEXT_L0",
        tuple(range(9, 17)),
        following.near,
        activate=False,
    )

    current_transition_slots = {
        entry.request.component: entry.slot for entry in reconcile_transition
    }
    missing_transition = tuple(
        component
        for component in following.transition
        if component not in current_transition_slots
    )
    current_distant_slots = {
        entry.request.component: entry.slot for entry in reconcile_distant
    }
    missing_distant = tuple(
        component
        for component in following.distant
        if component not in current_distant_slots
    )
    if len(missing_transition) != 4 or len(missing_distant) != 1:
        raise AssertionError(
            "fixed west staging delta changed: "
            f"D1={len(missing_transition)} D2={len(missing_distant)}"
        )
    preload_plan_delta = (
        _entries(
            grid,
            "PRELOAD_PLAN_DELTA",
            tuple(range(25, 29)),
            missing_transition,
            activate=False,
        )
        + _entries(
            grid,
            "PRELOAD_PLAN_DELTA",
            (37,),
            missing_distant,
            activate=False,
        )
    )

    staged_transition_slots = {
        entry.request.component: entry.slot
        for entry in preload_plan_delta
        if entry.request.component.tier == "transition"
    }
    staged_distant_slots = {
        entry.request.component: entry.slot
        for entry in preload_plan_delta
        if entry.request.component.tier == "distant"
    }
    outgoing_transition = tuple(
        current_transition_slots[component]
        for component in current.transition
        if component not in set(following.transition)
    )
    outgoing_distant = tuple(
        current_distant_slots[component]
        for component in current.distant
        if component not in set(following.distant)
    )
    swap = ActivationTransaction(
        deactivate_distant=outgoing_distant,
        deactivate_transition=outgoing_transition,
        deactivate_near=tuple(range(1, 9)),
        activate_near=tuple(range(9, 17)),
        activate_transition=tuple(
            staged_transition_slots[component] for component in missing_transition
        ),
        activate_distant=tuple(
            staged_distant_slots[component] for component in missing_distant
        ),
    )
    return FixedWestTransition(
        current,
        following,
        boot_near,
        reconcile_transition,
        reconcile_distant,
        preload_next_near,
        preload_plan_delta,
        swap,
    )
