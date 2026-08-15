# Universal terrain-manager runtime contract

Status: **implemented and emulator-qualified for the regular radius-five
coverage-group client; physical-hardware acceptance remains open**. The reusable ADL eZ80 core is
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
| `terrain_manager_defer_stale_rebase` | retain (`1`) or retire (`0`) stale owners during the ordinary origin rebase |
| `terrain_manager_group_staging` | compile staged-inactive load and atomic coverage-group commit support when `1`; historical clients use `0` |

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
   coordinates in `BC=q`, `DE=r`. Historical clients may change an established
   origin to schedule an active-set rebase. Group-staged clients reject that
   direct mutation: adjacent moves use `update_position`, while a teleport or
   radius restart uses shutdown, initialize, and a new first submit. The
   provider must accept desired ordinal zero at a valid origin; a clipped centre
   is reported as `error_origin`.
3. `terrain_manager_update_position` accepts `IX` as an opaque mutable
   application position-state pointer. It delegates normalization to the
   provider and returns `A=0` when unchanged or `A=1` when rebased. Carry is
   reserved for an actual error. The provider updates the local position and
   proposed regional origin as one CPU-side transaction.
4. `terrain_manager_set_ring` accepts `A=0..max_ring`, resets convergence, and
   does no I/O. A group provider may reject an in-place policy change after its
   slot ownership becomes unified; the regular fixture implements number-key
   changes as a render-idle cold restart at the same regional origin.
5. `terrain_manager_service_idle` is called only between completed renders. It
   performs at most one ordinary load, cached activation, or deactivation, or
   one atomic all-active origin-rebase transaction. On success, `A` is the
   operation code.
6. `terrain_manager_stage_candidate` loads and positions one candidate in an
   inactive slot without activating it. `terrain_manager_commit_staged_group`
   accepts exact retiring and entering slot arrays and swaps the complete group
   synchronously. These exist only when group staging is compiled.
7. `terrain_manager_query` returns `IX` pointing to the stable 19-byte status
   block.
8. `terrain_manager_shutdown_idle` is called only between renders. It
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
| `terrain_provider_transition_busy` | group profile: nonzero while the provider owns idle service for one transition |
| `terrain_provider_ring_change_allowed` | group profile: nonzero rejects an unsafe in-place ring change |
| `terrain_provider_service_transition` | group profile: stage or atomically commit one selected coverage group at render idle |

The regular client additionally exposes
`terrain_provider_reset_for_cold_restart`. It clears provider-private plan,
unified-slot, and transition state only after the manager has deactivated and
forgotten every slot; the fixture then initializes and resubmits the saved
origin before rebuilding the requested radius.

With `terrain_manager_group_staging=1`, the provider also exposes a busy flag,
a ring-change guard, and a render-idle transition dispatcher. The manager's
`terrain_manager_stage_candidate` publishes and positions one mesh only in an
inactive slot and marks it staged without activation. After a complete group
has staged, `terrain_manager_commit_staged_group` preflights exact, distinct
resident/active retiring slots and resident/staged entering slots, deactivates
the whole retiring set, then activates the whole entering set synchronously.
No render can interleave within that commit. A partial stage or failed
preflight leaves the old visible coverage intact.

An ordinary provider's slot assignment must be injective over every desired set
and stable for a given world component. The first hex provider satisfies this
with `(5*q + 11*r) mod 91`, a perfect map for every radius-five disk. A group
provider may instead publish an authoritative live owner-to-slot map: preserved
owners keep their actual slots, entering owners acquire staged inactive slots,
and every later desired/stale query must use that map rather than recomputing a
historical hash.

The load hook is the transaction boundary for geometry: a failure must leave
the old mesh and object untouched. On success the manager orders publication
as load, exact transform, activation, then residency commit. A later transform
failure cannot roll command 50 back, so the affected slot is invalidated and
deactivated. Cached-activation transform failure is different: no mesh changed,
so the validated inactive resident and both counts remain intact.

## Rebase and eviction semantics

When the provider normalizes a position into a new regional origin, the
manager defers all VDP work to the next idle barrier. The provider selects one
of two compile-time policies. The historical policy deactivates stale old-edge
cells before positioning the overlap. A provider with a proven placement
fringe may instead reposition every active resident and retain stale owners as
fallback scenery. In either case the rebase itself is one atomic idle
transaction: the next render cannot observe a mixture of old- and new-origin
coordinate frames.

Inactive residents retain validated meshes as a small opportunistic cache.
Reactivation reissues placement before activation. Ordinary convergence loads
or activates a desired component first; only after a complete desired scan does
it deactivate at most one stale object per idle call. Under deferred stale
rebase, this ordering keeps the preceding scene visible until the complete new
desired plan is active. A dynamic provider must not confuse an unclaimed slot
with an inactive slot during that interval: command 50 on an active stale slot
replaces the mesh beneath visible fallback scenery.

The promoted regular provider instead treats detailed and coarse owners as one
slot domain. Its radius-five recipes partition old/new coverage overlap into
components, stage every entering component only in inactive capacity, and swap
the complete component atomically. Shared identities retain their actual slots;
after the first handoff a detailed cell may legally occupy a former coarse
slot. Runtime edge filtering preserves source-plan ordinals and selects the
best currently feasible shrink-first group. The generated 192-recipe table and
complete 299,306-edge host audit prove a maximum 14 owners on either side, 15
activation changes in one commit, and at least four free staging slots.

Load failures use a bounded exponential visit countdown, preserve the previous
complete resident, and remain observable per slot and in the public status.

The regular hierarchy fixture additionally adapts the immutable legacy terrain
payload at the loader boundary. After disk CRC and index validation but before
VDP upload, it negates every vertex Z and reverses each position/UV triangle.
Together with east-positive command-52, camera, and rebase translations, this
publishes a right-handed `X=north, Y=up, Z=east` world without modifying or
duplicating the checksum-bound 133,476-record source corpus. Other bindings
compile the adapter out.

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
codes are none, load, activate, deactivate, rebase, shutdown, stage, and group
commit. Manager error codes distinguish configuration, ring, origin, provider,
position, slot, and group
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

## Experimental natural-surface binding

`fixtures/terrain-manager-natural-survey` demonstrates that the same manager
can drive irregular physical components cut only after one natural master
surface is complete. Its logical provider still uses the canonical axial
coordinates, ring order, stable 91-slot map, transforms, and hysteresis of the
straight-hex control. Its geometry does not: each `NAT` record owns whole
triangles routed along existing master-mesh edges, and neighboring components
duplicate those irregular boundary vertices exactly.

The original proof corpus was a radius-five disk around Campanile cell
`(90,121)`. It remains preserved as historical evidence. The current regional
profile exposes all 50,183 `NAT` records and applies only the true alternating
235/234-row Bay Area bounds. It starts over the Berkeley Marina in containing
cell `(80,125)` at its maximum accepted radius five. The same 91-slot manager
therefore bounds live VDP residency while aircraft/camera motion may select any
regional record.

The complete records contain 842,903 component-local vertices and 992,477
triangles in 25,251,544 container bytes. They have no skirts. Post-container
validation proves 294,948 selected-to-selected seam edges, 3,105 corpus edges,
128,259 physical component pairs, 78,271 boundary vertices shared by at least
three components, at most seven owners at one vertex, and zero ideal-world
integer reconstruction mismatches. A compact 25,237,845-byte fixed-record
source bridge keeps the full Blender extraction deterministic without a
hundreds-of-megabytes JSON intermediate.

Pingo command 53 sets the control's far plane to the maximum unsigned value
65,535 after control creation; this does not enlarge the resident ring or
generate distant LOD. A silent emulator trace publishes all 91 initial meshes,
observes every exact command-52 transform, reports `far=65535`, traverses all
91 objects, rasterizes the complete frame, and shuts down cleanly. The logical
provider still uses ideal axial containment even though the artifact records a
noncanonical physical adjacency graph. Explicit physical containment, mixed
LOD, indexed hardware bundles, human regional movement/presentation, and
physical-hardware behavior remain acceptance gates.
