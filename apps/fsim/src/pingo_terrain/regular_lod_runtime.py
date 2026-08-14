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
import re
import struct
from typing import Iterable, Sequence

from .hex_terrain import disk_offsets, validate_cell
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
    slot whether it is active or inactive.  Stale active residents are then
    deactivated.  Pass two assigns each missing identity to the lowest slot
    that is both inactive and unprotected.  The proven 159-entry maximum
    leaves at least five spare slots, so a qualified plan cannot exhaust the
    164-slot pool.
    """

    desired = set(plan.entries)
    existing = {
        resident.identity: local
        for local, resident in enumerate(snapshot.slots)
        if resident.identity is not None
    }
    work = list(snapshot.slots)
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
        try:
            local = next(
                candidate
                for candidate, resident in enumerate(work)
                if not resident.active and candidate not in protected
            )
        except StopIteration as error:
            raise RuntimeError("qualified coarse plan exhausted its slot pool") from error
        # This is the central allocator invariant: assignment never overwrites
        # an active or protected resident.
        if work[local].active or local in protected:
            raise AssertionError("allocator selected an active/protected slot")
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
