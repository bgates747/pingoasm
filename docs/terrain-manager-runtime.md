# Universal terrain-manager runtime contract

Status: **implemented for first hex-native qualification; emulator and hardware
acceptance pending**. The reusable ADL eZ80 core is
`runtime/ez80/terrain-manager.inc`. Its first client is
`fixtures/terrain-manager-survey`; topology and corpus policy live in that
fixture's hex provider rather than in the manager.

## Ownership boundary

The manager owns residency state, stable slots, bounded work scheduling,
failure/backoff state, object activation, render-idle publication order,
floating-origin coordination, status reporting, and teardown. It contains no
hex, square, path, P3DM-family, camera-control, flight-dynamics, collision, or
fixture-entry assumptions.

The application owns render synchronization and calls the two mutating service
routines only while no render is in flight. It also creates the configured
placeholder meshes/objects, loads shared material resources, supplies an
authoritative position state, and synchronizes any non-terrain world state.
The provider owns topology, desired-set enumeration, corpus bounds and paths,
component validation/publication, exact placement, and position normalization.

## Compile-time configuration

One inclusion supplies these symbols before the manager source:

| Symbol | Contract |
| --- | --- |
| `terrain_manager_slot_count` | `1..255`; current manager slot indices and counts are deliberately `u8` |
| `terrain_manager_max_ring` | largest provider policy index accepted at runtime |
| `terrain_manager_initial_ring` | initial policy index, no larger than the maximum |
| `terrain_manager_mesh_id_base` | first exact `u16` Pingo mesh ID |
| `terrain_manager_object_id_base` | first exact `u16` Pingo object ID |

Both inclusive ID ranges are checked against `0..65535`; ID arithmetic is
never truncated to a byte. The 255-slot manager-profile ceiling is not a Pingo
firmware object limit. Pingo now traverses the complete 16-bit object registry;
a future manager profile can widen slot ordinals independently if a measured
scene needs more than 255 simultaneously managed terrain objects.

The core uses nine bytes per slot: signed `q` and `r`, flags, LOD, last error,
failure count, and retry countdown. The 91-slot radius-five hex binding uses
819 bytes.

## Public lifecycle

Unless noted otherwise, success returns carry clear; failure returns carry set
with `A` equal to the error code.

1. `terrain_manager_initialize` validates compile-time bounds and clears all
   manager-owned state.
2. `terrain_manager_submit_origin` accepts signed axial or provider-defined
   coordinates in `BC=q`, `DE=r`. Changing an established origin schedules one
   atomic active-set rebase. The provider must accept desired ordinal zero at a
   valid origin; a clipped centre is reported as `error_origin`.
3. `terrain_manager_update_position` accepts `IX` as an opaque mutable
   application position-state pointer. It delegates normalization to the
   provider and returns `A=0` when unchanged or `A=1` when rebased. Carry is
   reserved for an actual error. The provider updates the local position and
   proposed regional origin as one CPU-side transaction.
4. `terrain_manager_set_ring` accepts `A=0..max_ring`, resets convergence, and
   does no I/O.
5. `terrain_manager_service_idle` is called only between completed renders. It
   performs at most one ordinary load, cached activation, or deactivation, or
   one atomic all-active origin-rebase transaction. On success, `A` is the
   operation code.
6. `terrain_manager_query` returns `IX` pointing to the stable 19-byte status
   block.
7. `terrain_manager_shutdown_idle` is called only between renders. It
   deactivates every active manager object, clears residency/error state, and
   moves the lifecycle to `shutdown`.

The application may call position and ring updates while a render is in
flight because those calls emit no VDP traffic. It must delay `service_idle`
and `shutdown_idle` until the render-completion barrier.

## Provider hooks

The linked provider implements these exact hooks:

| Hook | Inputs and outputs |
| --- | --- |
| `terrain_provider_ring_count` | `A=ring` to `A=nominal desired count`, within the configured slot pool |
| `terrain_provider_desired_at` | `A=ordinal`; writes candidate signed `q/r`, stable slot, and LOD; carry means this non-centre request is clipped by corpus bounds |
| `terrain_provider_load_candidate` | reads candidate and work mesh ID; validates and atomically publishes one complete component; `A=0` success, nonzero error |
| `terrain_provider_position_candidate` | reads candidate, current origin, and work object ID; emits the complete object transform; `A=0` success, nonzero error |
| `terrain_provider_candidate_is_desired` | zero if the resident candidate belongs to the current desired set, nonzero otherwise |
| `terrain_provider_normalize_position` | normalizes the opaque `IX` position, writes proposed origin, and returns carry iff the origin changed |

Provider slot assignment must be injective over every possible desired set and
stable for a given world component. The first hex provider satisfies this with
`(5*q + 11*r) mod 91`, a perfect map for every radius-five disk.

The load hook is the transaction boundary for geometry: a failure must leave
the old mesh and object untouched. On success the manager orders publication
as load, exact transform, activation, then residency commit. A later transform
failure cannot roll command 50 back, so the affected slot is invalidated and
deactivated. Cached-activation transform failure is different: no mesh changed,
so the validated inactive resident and both counts remain intact.

## Rebase and eviction semantics

When the provider normalizes a position into a new regional origin, the
manager defers all VDP work to the next idle barrier. That service pass examines
every active resident against the new desired set. Stale old-edge cells are
deactivated before placement, while overlapping cells receive their exact new
transform. This is intentionally one atomic idle transaction: the next render
cannot observe a mixture of old- and new-origin placements.

Inactive residents retain validated meshes as a small opportunistic cache.
Reactivation reissues placement before activation. Ordinary convergence loads
or activates a desired component first; only after a complete desired scan does
it deactivate at most one stale object per idle call. Load failures use a
bounded exponential visit countdown, preserve the previous complete resident,
and remain observable per slot and in the public status.

## Status ABI

`terrain_manager_query` returns this stable little-endian block:

| Offset | Size | Field |
| ---: | ---: | --- |
| 0 | 1 | lifecycle state |
| 1 | 1 | current ring/policy index |
| 2 | 1 | nominal desired count |
| 3 | 1 | validated resident count |
| 4 | 1 | active count |
| 5 | 1 | convergence flag |
| 6 | 1 | last operation |
| 7 | 1 | last error |
| 8 | 2 | signed current origin `q` |
| 10 | 2 | signed current origin `r` |
| 12 | 1 | last affected slot, or `0xFF` initially |
| 13 | 2 | signed last component `q` |
| 15 | 2 | signed last component `r` |
| 17 | 2 | successful-operation generation counter |

Lifecycle states are uninitialized, ready, error, and shutdown. Operation
codes are none, load, activate, deactivate, rebase, and shutdown. Manager error
codes distinguish configuration, ring, origin, provider, position, and slot
failures; component-loader error values pass through unchanged.

## First qualified binding

The Bay Area provider binds the generic core to the 50,183-cell flat-top N=5
hex corpus. It enumerates complete radius `0..5` disks of `1, 7, 19, 37, 61,
91` cells, uses exact signed-16 axial identities, resolves
`TRH/L0/HH/LL.AGN`, publishes P3DM L0 terrain through command 50, and places
objects with signed-24 command 52 translations. Its camera-only fixture starts
at the Campanile in cell `(90,121)` and exposes the six ring choices on the
top-row number keys.

The hex provider's N=5 perimeter has six straight five-edge sides. Rebase
normalization retains the current origin through a 16 m (256-count) outward
band on every side. Exact outer ties retain; the first count beyond the band
selects a neighbor, with deterministic vertical-before-sloped corner order.
Placement is bounded to the desired radius-five domain; the manager therefore
retires stale old-ring residents before asking the provider to place the
overlap. Exhaustive host checks cover all corpus IDs and paths, disk order,
slot injectivity, basis signs, straight boundaries, the expanded half-planes,
six-side and corner no-chatter behavior, ADL memory widths, and deterministic
assembly. Visual emulator and physical-hardware acceptance remain separate
gates.
