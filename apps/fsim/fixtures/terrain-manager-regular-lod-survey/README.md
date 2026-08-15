# Terrain-manager regular-LOD hierarchy survey

This sibling fixture exercises the position-driven Bay Area terrain hierarchy
without changing the accepted universal manager or the earlier mixed-distance
control. It starts over the Berkeley Marina, level and facing north, with the
three-colour terrain presentation and Pingo far plane of 65,535. Scene
illumination is disabled at runtime, so each terrain face uses its exact solid
Agon base colour without illumination-selected dithering. Transparent pixels
in the Pingo target reveal one full-frame blue clear; there is no synthetic
ground plane or attitude-derived horizon.

The accepted disk corpus predates this fixture and stores the reflected basis
`X=north, Y=up, Z=-east`. This made a genuinely north-facing view put west on
screen-right. The regular fixture corrects every validated record at its one
loader boundary: vertex Z is negated and position/UV triangle winding is
reversed before command 50. Object translations, the initial camera Z, and
floating-origin steps use `Z=+east`. The published world is therefore
right-handed: facing north places east on the right and west on the left. The
on-disk corpus remains immutable and checksum-verifiable.

The fixture reserves all 255 manager slots. A cold plan assigns its detailed
`TRH/L0` disk through the qualified 91-slot radius-five hash and fills coarse
`RGL/L8`, `RGL/L4`, `RGL/L2`, and `RGL/L1` owners from slot 91 upward. After
the first moving-origin handoff, that split is no longer authoritative: one
unified owner-to-slot map preserves every shared detailed or coarse identity
in its actual slot, and incoming owners may occupy any inactive slot. The
hierarchy remains an aligned partition in `(q, offset_row)` space; a parent and
any of its children are never members of the same target plan.

Each adjacent radius-five move uses one of 192 generated full-owner recipes.
Coverage-overlap components stage all entering meshes, still inactive, while
their retiring predecessors remain visible. At a render-idle boundary the
manager first deactivates the complete retiring set and then activates the
complete entering set without an intervening render. Edge clipping retains
source-plan ordinals and dynamically reorders only feasible groups. Exhaustive
host qualification covers all 299,306 directed bounded neighbor moves: 4,176
canonical groups, at most 14 owners on either side, at most 15 activation-state
changes in one commit, and at least four free staging slots. Ordinary mesh
publication remains limited to one load per idle pass.

Top-row keys `0` through `5` select the detailed near radius by a deliberate
render-idle cold restart at the current regional origin. This creates a visible
sky-only incremental refill and safely discards any arbitrary unified slot
mapping. Only radius five has adjacent-move recipes; radii zero through four
are stationary review modes and do not normalize regional travel. Arrow keys look,
WASD translate in the horizontal plane, Page Up/Page Down move vertically,
minus/equals change translation speed, and Escape returns to the launcher.

Runtime files expected beside the appliance are:

- `P3DRGL.BIN`
- `MATID.RG2`, `PATTERN.RG2`, and `PATLUT.BIN`
- the accepted detailed `TRH/L0` tree
- the generated regular hierarchy under `RGL/L8`, `RGL/L4`, `RGL/L2`, and
  `RGL/L1`

The generated `tgt/regular-lod-runtime.inc` and separate
`tgt/regular-lod-transitions.inc` are part of the fixture contract. Neither is
a hand-edited topology table.
