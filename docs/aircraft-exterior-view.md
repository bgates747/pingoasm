# Aircraft asset and exterior-view contract

Status: **implemented reusable component; streamed-fixture visual integration
pending under F2**.

This document fixes the small-aircraft asset, cockpit/chase transforms, view
input semantics, and active-scene budget for the regional light-flight fixture.
It does not modify the accepted Berkeley fixtures.

## Vendored Jet snapshot

The exterior model is the visually and mechanically proven flat-palette Jet
from PingoASM commit
`1030581011710b30b7e9496fe1c6cdca003865e8`. The project-local snapshot is:

- `assets/aircraft/pingoasm-jet/jet-flat.inc`: 61,054 bytes, SHA-256
  `4713e15ab315f7ca03017499a6676df30253105313622b035175aff769181140`;
- `assets/aircraft/pingoasm-jet/jet-flat.rgba2`: 64 bytes, SHA-256
  `858b708a30584790b8255450819ffdca148a60150a31ba35be3ff8f70f92f130`;
  and
- `assets/aircraft/pingoasm-jet/provenance.json`: donor commit, paths,
  generator hashes, source hashes, bounds, and rights status.

The model has 370 vertices and 736 triangles. PingoASM's offline predominant-
color pass has reduced every source-image triangle to one of 64 UV selectors;
each triangle repeats a single selector for all three corners. The 8x8 texture
is PingoASM's visually ordered Agon color cube, not the airport corpus's raw
selector-order palette. The two resources cannot silently share one bitmap
ID merely because both contain 64 pixels.

The original Jet creator, source URL, and redistribution license are not
recorded in PingoASM. Git history establishes that the asset entered that
repository in commit `87d598702659ccbca647c84b8b98669c47a41af7`, but not where
it came from. This local experimental copy is therefore useful for the
Author's fixture but is not a redistribution-cleared asset. Promotion or
release must resolve that provenance or replace the model.

Build the portable payload offline with:

```bash
.venv/bin/python scripts/build_aircraft_asset.py
```

The default ignored output is `build/aircraft/pingoasm-jet/`. The generator
revalidates both vendored hashes, counts, signed-word ranges, indices, and the
one-selector-per-face invariant. It removes unused normal tables while leaving
all Pingo-consumed bytes unchanged. Current deterministic outputs are:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `jet-view.inc` | 26,353 | `8ec547558a6dc3532704a4d351bd311f6af868afacb071a4a30ed38b477823ad` |
| `JET64.RG2` | 64 | `858b708a30584790b8255450819ffdca148a60150a31ba35be3ff8f70f92f130` |
| `AIRCRAFT.json` | 1,025 | `4bf3e2811749f1a2d247eabf4cfee800a38d161bd7423d357f8a277e0641f412` |

The actual Pingo mesh payload represented by the compact include is 11,308
bytes: 2,220 position bytes, 4,416 position-index bytes, 256 UV bytes, and
4,416 UV-index bytes. It is a static startup asset, not a terrain-streaming
slot.

## Physical scale and axes

The donor OBJ is treated as metres. Its bounds are X
`[-6.062263,+6.062263]`, Y `[-0.871043,+2.498260]`, and Z
`[-7.419411,+6.403551]`. Local `-Z` is forward and local `+Y` is up.

The normalized mesh uses the largest absolute source coordinate, 7.419411 m.
The runtime deliberately rounds that to a 7.5 m physical half extent. Under
the accepted 8 m Pingo world unit this is exact unsigned Q8.8:

```text
object_scale = 7.5 m / 8 m * 256 = 240
```

The resulting dimensions are approximately 12.256 m span, 3.406 m height,
and 13.973 m length. That is a plausible small-jet scale and only 1.086 percent
larger than the source's assumed metre dimensions. Scale 240 is below unity
and nowhere near Pingo's `65535` word limit; no aircraft partition is needed.
The Jet remains solid-flat mode 1 with ordinary scene illumination, matching
the proven Earth Party treatment.

## Camera transforms

`src/pingo_terrain/aircraft_view.py` is the executable host reference. All
positions below are exact 1/16-metre Pingo translation counts. `M` is the
aircraft's retained signed-Q15 local-to-world orientation matrix:

```text
world_point = aircraft_position + round_nearest(M * local_point / 32767)
```

Cockpit mode uses local eye `(0,+20,-48)`, or `(0,+1.25,-3.00)` metres. It
submits the aircraft's Pingo Euler rotation directly and keeps the exterior
object inactive. The small physical offset moves the eye from the force-model
reference point without inventing a second aircraft state.

Chase mode uses local camera `(0,+80,+288)`, or `(0,+5,+18)` metres. Because
forward is `-Z`, positive local Z is behind the aircraft. Its aim point is
local `(0,+16,-48)`, or `(0,+1,-3)` metres, slightly above and ahead of the
reference point. Both points follow the complete aircraft orientation, not
just compass yaw.

The eZ80 component then passes the transformed chase target to the qualified
`p3d_camera_aim_at_point16` path with `p3d_camera_roll_upright`. The look-at
solver, rather than new approximate trigonometry, owns pitch/yaw signs, pole
hysteresis, and Euler-branch selection. A coincident target retains the last
valid frame through the existing P3D contract.

The frame fallback must derive its horizon from
`camera_state+p3d_camera_pingo_rotation` in both modes. In cockpit that equals
aircraft attitude. In chase the look-at camera has an upright roll even while
the aircraft banks; using aircraft roll for the backdrop would visibly
contradict the rendered terrain horizon.

## View key and publication semantics

Physical `V` selects the view. MOS's BBC key map assigns it virtual key 100,
which is byte 12, bit 3 in the 16-byte map. The transition is a conventional
rising-edge latch:

| Previous latch | V now | Effect |
| --- | --- | --- |
| clear | down | toggle once and set latch |
| set | down | no change |
| either | up | clear latch; do not toggle |

The toggle is sampled once per deterministic physics quantum, after the live
MOS map is latched. A held key cannot oscillate between modes during catch-up
steps. Entering chase invalidates old camera look-at branch memory so the first
aim is canonical.

`fixtures/_common/aircraft-view.inc` implements these semantics and the exact
camera transforms. It requires the combined fixture to expose
`object_state`, `camera_state`, and `keyboard_masks` and to include the
qualified P3D library. It has no firmware dependency beyond the already
proposed object-active command.

The stable aircraft object is created once. Before the first cockpit render it
is inactive. At a cockpit-to-chase transition, the render-idle publisher must
submit the newest aircraft pose, submit the camera, activate the aircraft, and
only then start the next render. A chase-to-cockpit transition deactivates the
aircraft before the next render. Inactive objects retain their stable ID and
mesh binding but do not consume a scene-renderable slot.

The initial active counts are therefore 27 in cockpit and 28 in chase:

```text
25 terrain + 2 KOAK P00/M00 + 0 or 1 aircraft = 27 or 28
```

This leaves four renderable slots below Pingo's hard limit of 32. The aircraft
does not justify activating more airport groups or a 33rd object.

The static 320x92 panel and 320x148 viewport remain in both modes for the first
integration. This keeps performance and display composition comparable while
the exterior behavior is qualified; removing the panel in chase can be a
later presentation choice rather than a second rendering architecture.

## Qualification

`tests/test_aircraft_view.py` covers donor hashes, counts, flat-face selectors,
byte-deterministic generation, exact Q8.8 scale, identity and quarter-turn
camera witnesses, Q15 rounding, V-key edge sequences, and active-object
budgets. A small ADL harness assembles the reusable include. The fixed-width
audit reports no hazards and no indirect accesses requiring review. Human
visual qualification remains part of F2 when this component is combined with
KOAK terrain, hard surfaces, physics, backdrop, and asynchronous rendering.
