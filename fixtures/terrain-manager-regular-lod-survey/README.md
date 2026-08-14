# Terrain-manager regular-LOD hierarchy survey

This sibling fixture exercises the position-driven Bay Area terrain hierarchy
without changing the accepted universal manager or the earlier mixed-distance
control. It starts over the Berkeley Marina with the same reviewed camera,
lighting, three-colour terrain presentation, and Pingo far plane of 65,535.

The fixture reserves all 255 manager slots. Slots 0 through 90 retain the
qualified radius-five hash for detailed `TRH/L0` cells. The generated runtime
plan assigns disjoint coarse `RGL/L8`, `RGL/L4`, `RGL/L2`, and `RGL/L1` nodes
to slots 91 through 254, preserving the slot of every resident node that
survives a plan change. The hierarchy is an aligned partition in
`(q, offset_row)` space; a parent and any of its children are never members of
the same target plan.

Top-row keys `0` through `5` select the detailed near radius. Arrow keys look,
WASD translate in the horizontal plane, Page Up/Page Down move vertically,
minus/equals change translation speed, and Escape returns to the launcher.

Runtime files expected beside the appliance are:

- `P3DRGL.BIN`
- `MATID.RG2`, `PATTERN.RG2`, and `PATLUT.BIN`
- the accepted detailed `TRH/L0` tree
- the generated regular hierarchy under `RGL/L8`, `RGL/L4`, `RGL/L2`, and
  `RGL/L1`

The generated `tgt/regular-lod-runtime.inc` is part of the fixture contract.
It is not a hand-edited topology table.
