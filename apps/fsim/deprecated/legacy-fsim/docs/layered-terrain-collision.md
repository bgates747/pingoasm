# Layered terrain collision

Status: **executable C1 host reference; not yet in the KOAK eZ80 fixture**.
`src/pingo_terrain/collision.py` and `tests/test_collision.py` define the first
fixed-point policy. The accepted F2 force model and active assembly fixture are
unchanged.

## Scope

The first collision system answers a deliberately smaller question than a
general rigid-body solver: may one already-integrated 30 Hz aircraft step be
published, is the aircraft still supported by a known runway, or must the step
be held/reported because terrain or an airport object might have been touched?
It does not yet model crash damage, wheel suspension, bouncing, building
shapes, or a response after contact.

The policy has five possible dispositions:

| Disposition | Meaning for the later eZ80 caller |
| --- | --- |
| `CLEAR` | Commit the candidate step. |
| `AHEAD_WARNING` | Commit this step, prioritize the named ahead tile, and retain the warning. |
| `RUNWAY_SUPPORTED` | Commit horizontal/attitude state while applying F2's existing support-plane rule. |
| `HOLD_FOR_DATA` | Do not publish the candidate pose; retain the previous safe state while required immediate detail is obtained. |
| `CONTACT` | Do not publish the penetrating pose; emit the terrain, runway, or airport contact event. |

`HOLD_FOR_DATA` is intentionally different from collision. A missing current
tile or missing narrow-phase data is not silently interpreted as empty space,
and an unloaded ahead tile is not prematurely interpreted as a crash.

## Fixed-point contract

The policy reuses existing J1/F2 domains rather than introducing metres in the
simulation loop.

| Quantity | Fixed domain | Required range in the first port |
| --- | --- | --- |
| east/north position | signed 32-bit Q8 translation counts relative to the regional south-west origin | complete 201x252 world fits below 2^29 |
| altitude | signed 32-bit Q8 translation counts | absolute MSL-like altitude |
| velocity | signed 16-bit Q8 translation counts per 30 Hz tick | F2 currently clamps to +/-8192 |
| acceleration reach bound | unsigned velocity-Q8 change per tick | horizontal 160, downward 192 |
| P3DM elevation extrema | signed i16 decimetres | descriptor values retained unchanged |
| P3DM normalization extent | unsigned integer metres | Bay Area terrain is uniformly 768 m |
| aircraft proxy extents | nonnegative position-Q8 | must contain the complete continuous start-to-end body sweep |
| runway axis | signed Q15 unit east/north vector | dot products use local signed-16 translation counts and signed-32 products |

There are 16 translation counts per metre and 256 fractional units per count,
so one metre is exactly 4096 position-Q8 units. A 512 m cell is `0x200000`.
The conversion from J1 coarse/fine state is exact:

```text
east_q8  = tile_x * 0x200000 + 0x100000 + fine_east_q8
north_q8 = tile_y * 0x200000 + 0x100000 + fine_north_q8
```

P3DM descriptor maxima are already rounded upward to decimetres, but collision
conversion rounds outward again. For example, +0.1 m becomes lower/upper
position-Q8 values 409/410, while -0.1 m becomes -410/-409. The broad bounds
also expand by twice the outward-rounded P3DM half-quantization error plus one
Q8 unit. One half-error covers a decoded vertex beyond the descriptor's source
extremum; the second dominates the source-recovery expansion used by the narrow
box. This matters when a source vertex lies exactly on a decimetre boundary.
No conversion may round an upper terrain bound downward or a lower bound upward.

The host API accepts the aircraft proxy rather than guessing it from the
rendered Jet. Its no-false-negative claim is conditional on that proxy
containing the model for the whole step. A target implementation can obtain a
tight proxy by multiplying local model half extents by the absolute Q15
orientation rows and rounding every world extent upward. It must use the
larger start/end result plus an angular-sweep margin. A single
orientation-independent bounding sphere is also safe, but the Jet's roughly
9.5 m radius would cause conspicuous low-altitude false contacts.

## Staged policy

The order is normative because it keeps detailed geometry off the common
high-altitude path.

1. Build one closed aircraft AABB around the exact previous and candidate
   positions. Equality at a boundary remains possible contact.
2. Test explicit runway support against an oriented runway/graded-safe
   rectangle. Existing support is retained only while the complete horizontal
   proxy remains inside and has no accepted positive takeoff velocity. A real
   downward crossing at no more than 512 velocity-Q8 (3.75 m/s) acquires
   support only when the proxy is contained at both sweep endpoints; convexity
   then contains the path between them. A deeper, faster, or partially covered
   crossing reports runway contact. An unsupported aircraft already below the
   plane, including one moving upward through it, is contact rather than a
   synthetic touchdown. After support releases, the runway masks underlying
   terrain under that same whole-sweep containment rule.
3. Test airport-group broad AABBs. Detailed airport obstacle boxes are read
   only for a group whose broad box intersects the immediate aircraft sweep.
   Airport obstacle contact overrides runway support.
4. Enumerate only 512 m terrain cells touched by the immediate closed sweep.
   A missing descriptor produces `HOLD_FOR_DATA`. If the aircraft bottom is
   strictly above the outward-rounded tile maximum, that tile is rejected
   without touching mesh data. If the complete aircraft is at or below the
   descriptor minimum, it is certainly buried beneath the terrain surface and
   contact is reported without a narrow phase.
5. For the remaining probable current tiles, test conservative AABBs of upward
   surface triangles. Boundary skirts are excluded. Horizontal overlap plus an
   aircraft bottom at or below the triangle-box maximum is terrain contact,
   because terrain is treated as solid below its surface. Missing current
   surface boxes produces `HOLD_FOR_DATA`, not `CLEAR`.
6. After the immediate step is clear, project a 30-tick reach rectangle. It
   includes end velocity and constant acceleration margins
   `a*n*(n+1)/2`, using 160 horizontally in either direction and 192 downward.
   A tile outside this rectangle is rejected without a square root or divide.
   A reachable missing tile or a reachable aircraft-bottom envelope at or
   below its P3DM maximum produces `AHEAD_WARNING`; the narrow phase is never
   opened merely for a warning.

The acceleration constants are bounds on the current F2 equations, not flight
tuning. Current maximum lift is 80, full-throttle thrust 28, per-axis drag 32,
and gravity 45 velocity-Q8 per tick. The executable test imports those current
F2 values and proves loose component sums of 140 horizontal and 185 downward,
leaving margins beneath 160/192. Any force-model change must re-prove these two
collision bounds.

## P3DM detail source

`TerrainEnvelope.from_p3dm` extracts the descriptor fields needed by the cheap
phase. A later target needs only four additional bytes of min/max state per
resident terrain slot beyond the tile identity already retained by J1; the
Bay Area terrain half extent is the world-wide constant 768 m. A generic
multi-extent corpus would also retain the descriptor's two-byte extent.

`terrain_surface_boxes_from_p3dm` is the executable narrow-phase reference. It
walks indexed faces, keeps only faces with a positive encoded Y normal, decodes
Pingo X as regional north and negative Pingo Z as regional east, and rounds
each face minimum down and maximum up. It then expands all six planes by the
outward-rounded half-quantization bound
`model_half_extent / (2 * 32767)`, so the pre-encoding source surface cannot
escape a decoded box. Horizontal expansions clamp to the declared tile square,
because the source lattice is clipped to that exact ownership boundary; this
prevents a box from leaking into a neighboring tile that would not load its
owner. The KOAK L0 centre proof tile yields 186 surface boxes from its 322
triangles; the remaining 136 triangles are boundary skirts and do not become
terrain tops.

The eZ80 does not need to retain thousands of boxes for all 25 render slots.
When the broad phase first admits probable contact, it can re-read the named
terrain P3DM into the existing 16 KiB staging window and stream these same box
tests directly from positions and indices. The last collision tile identity
may remain cached until terrain publication needs the window. If that read is
not ready for the candidate step, `HOLD_FOR_DATA` preserves the prior safe
state. A compact per-cell maximum sidecar remains a possible optimization, not
part of this first format.

P3DM terrain `minimum_elevation_dm` includes the 64 m boundary skirts, whereas
its maximum is the real surface maximum. The minimum is therefore useful only
as a corruption/definitely-buried bound; it must never be treated as the local
ground height. Per-face boxes similarly use their top maximum, not a hollow
three-dimensional shell, because terrain below the surface is solid.

## Runway and airport boundary

Runway support is not general collision. Each FAA-derived runway supplies a
centre, Q15 along vector, half length, half width, and an aircraft-reference
support altitude. The rectangle must describe pavement plus any explicitly
accepted graded-safe margin; it may not assume unspecified surroundings are
flat. Projection drops the fractional count bits before the Q15 dot products,
preserving 1/16 m horizontal precision. Because truncation plus Q15 rounding
can err by less than two counts, overlap tests expand by two counts and full-
containment tests shrink by two. A point test includes exact rectangle edges,
but a nonzero proxy cannot use an edge to prove containment. The current KOAK
start uses aircraft reference altitude
44 translation counts (2.75 m) above the regional zero, corresponding to the
existing four-count clearance over the FAA 2.49936 m runway surface.

While supported, or while the released aircraft's complete horizontal proxy is
contained for the whole sweep by a valid runway region, the hard surface is
authoritative and suppresses terrain beneath it after airport obstacle boxes
have cleared. A reference point on the runway edge cannot mask terrain for a
proxy extending past that edge. This makes the
FAA-feet-MSL versus terrain-NAVD88 mismatch explicit rather than silently
averaging two datums. Pavement and paint are not airport obstacles. Later
hangars, towers, and landmark solids can supply ordinary closed airport boxes;
those boxes conservatively include empty space but cannot be skipped by runway
support.

## False-positive and false-negative boundaries

The policy deliberately chooses its comparison boundaries in one direction:

- descriptor clear requires `aircraft_bottom > terrain_max`; equality proceeds
  to the narrow phase;
- tile/triangle/airport boxes are closed, so touching faces or edges overlap;
- terrain contact requires `aircraft_bottom <= surface_box_max`; equality is
  contact;
- runway length and width edges are included; and
- immediate missing data holds, while ahead missing data warns.

Expected false positives are bounded but not eliminated. A triangle's AABB
contains horizontal corners outside the triangle, and its maximum height is
used across that complete rectangle. Grouping several triangles in one box
would enlarge both errors. The aircraft proxy may also contain empty space,
and a runway crossing beyond the allowed descent rate is categorized as hard
contact without wheel dynamics. These are acceptable first-policy errors and
can only make collision earlier.

There are no geometric false negatives under six explicit assumptions:

1. the aircraft proxy contains the complete body throughout the integrated
   step;
2. current and ahead P3DM descriptor extrema and normalization extent were
   validated and retained for the correct tile identities;
3. every upward terrain surface triangle is included in the narrow scan with
   outward-rounded bounds;
4. the actual per-tick acceleration remains inside the stated reach bounds;
   and
5. every solid airport object is contained by both its group broad box and one
   tested detail box;
6. every runway support rectangle used for masking is itself a verified
   pavement/graded-safe region containing the complete proxy sweep.

Breaking an assumption invalidates the no-false-negative claim. Missing data
therefore never satisfies an assumption and cannot return `CLEAR`. The policy
still has temporal limits: it encloses one supplied candidate step, so the F2
caller must evaluate before publication and must not advance multiple physics
steps through an unresolved hold. Contact response and human qualification of
the chosen aircraft proxy remain C1 integration work.

## Executable evidence

The focused host suite covers signed outward decimetre conversion, exact J1
coordinate conversion, P3DM surface/skirt classification, current F2
acceleration bounds, maximum-height rejection without detail access,
distance-based rejection of a far mountain, fail-closed current data, ahead
warnings, definite burial, closed equality contact, runway retention/takeoff/
touchdown/below-plane/hard/edge contact, fractional projection margins,
whole-sweep runway masking, and airport broad/detail ordering. It also applies
the
P3DM box generator to the generated KOAK centre tile as a development witness;
the committed test itself uses a deterministic synthetic tile and does not
depend on ignored build products.
