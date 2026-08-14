# Regional airport P3DM corpus

Status: **deterministic proof corpus** for A1. The generated files are under
`build/p3dm/bay-area-koak-proof/APT/`; the regional developer index is
`build/p3dm/bay-area-koak-proof/AIRPORTS.json`. Generated build products are
ignored. Rebuild them offline from the checksum-qualified FAA archive with:

```sh
.venv/bin/python scripts/build_airport_p3dm.py
```

## Coordinate and datum contract

The airport compiler uses the regional terrain grid without overstating the
source accuracy:

- horizontal model CRS: WGS 84 / UTM zone 10N, EPSG:32610;
- integer regional origin: E 521,728 m, N 4,100,096 m;
- grid: 201 by 252 cells, 512 m each;
- Pingo axes: X is grid north, Y is up, Z is negative grid east;
- shared vertical model origin: 608.0 m; and
- physical scale: 8 m per Pingo internal unit.

FAA APT horizontal coordinates are NAD83 latitude/longitude. The dependency-
free compiler treats those angular coordinates as numerically coincident with
WGS84 and applies a deterministic zone-10 UTM series. This agrees with PROJ
9.4's available ballpark operation at the KOAK witness to substantially less
than a millimetre, but PROJ reports unknown accuracy and no realization/grid
shift is applied. This is adequate for the 10 m terrain proof, not an
authoritative survey transformation.

FAA runway and field elevations are feet MSL, converted exactly at 0.3048
m/ft. The consumed NASR fields do not identify a more specific vertical datum.
Terrain is USGS 3DEP NAVD88. The index explicitly records this unresolved datum
relationship; airport MSL is never relabelled or asserted to be NAVD88.

## Normalization and object transform

Each pavement/marking pair shares one integer-metre origin and one uniform
model half extent. For every source axis:

```text
i16 = symmetric_round((axis_m - component_origin_axis_m)
                      * 32767 / model_half_extent_m)
axis_m = component_origin_axis_m
       + i16 * model_half_extent_m / 32767
```

Horizontal component origins are rounded projected metres. The vertical
component origin is always 608.0 m. The P3DM `model_half_extent_m` is therefore
an exact decode and scale witness, not merely a culling hint. `AIRPORTS.json`
records the source bounds, encoded bounds, theoretical half-quantum error,
observed maximum error, exact object origin, and Q8.8 object scale for every
component. Every paired group also carries its own geometry/load/retention
activation circle, so KOAK's spatially separate second group need not be made
resident merely because the first group is visible.

Pingo's maximum unsigned Q8.8 object scale represents slightly less than
2,048 m at 8 m/unit. The generator restricts the integer witness to at most
2,047 m (`65504` wire). It greedily preserves FAA runway order while forming
the fewest in-order groups that satisfy that scale. All airports fit in one
paired group except KOAK:

| Airport/group | Runways | Half extent |
| --- | --- | ---: |
| KSFO/0 | 01L/19R, 01R/19L, 10L/28R, 10R/28L | 1,620 m |
| KOAK/0 | 10L/28R, 10R/28L, 12/30 | 1,658 m |
| KOAK/1 | 15/33 | 608 m |
| KHWD/0 | 10L/28R, 10R/28L | 768 m |
| KSQL/0 | 12/30 | 607 m |
| KCCR/0 | 01L/19R, 01R/19L, 14L/32R, 14R/32L | 819 m |

Files are paired as `APT/<ICAO>/Pnn.AGN` pavement and
`APT/<ICAO>/Mnn.AGN` markings. Both layers are mode-1 solid-flat,
self-illuminated, non-dithered, upward-wound meshes. A group cannot separate a
runway's pavement from its markings.

These files are the accepted placement, palette, grouping, and startup proof,
but their independent overlay geometry is not the final terrain-integration
method. The next airport compiler must add a pinned property polygon and emit a
constrained replacement patch: clip intersected terrain faces, share canonical
perimeter vertices, grade the property interior, and partition airport base,
pavement, and markings into non-overlapping faces. Until that stitched corpus
is qualified, the present proof may demonstrate airport identity but does not
close the z-fighting or terrain/airport ownership requirement.

## Native solid palette

`APT/SOLID64.RG2` is the 8 by 8 raw opaque RGBA2222 color cube. Row-major cell
`i` contains byte `0xC0 | i`; this is deliberately different from a historical
MOS-first palette ordering. Every face repeats one interior UV selector three
times:

| Role | Selector | RGBA2222 |
| --- | ---: | ---: |
| runway/taxiway dark gray | 21 (`0x15`) | `0xD5` |
| ramp/apron light gray | 42 (`0x2a`) | `0xEA` |
| residual property green | 25 (`0x19`) | `0xD9` |
| marking pure white | 63 (`0x3f`) | `0xFF` |

The current proof emits runway pavement and white only. The stitched successor
uses light gray only for source-identified ramps/aprons and fills every other
airport-property ground face with the muted `(1,2,1)` green. All markings are
white by default.

Mapping-derived terminal and airport-building footprints may later produce
separate simplified wall-and-roof components. Their fixed self-lit 4×4 pattern
contains thirteen `0xD5` pixels and three nonadjacent `0xEA` pixels, averaging
about 101/255 per channel. Explicit mapped height wins, followed by a documented
levels conversion and then a pinned conservative default for unambiguous
airport structures. The provider emits nothing without a footprint and does
not infer detailed architecture.

## KOAK 28L startup barrier

The canonical start comes directly from FAA runway 10R/28L end 28L:

- threshold NAD83: 37.72227386, -122.20600930;
- projected proof position: E 569,972.905707 m, N 4,175,298.105307 m;
- FAA elevation: 8.2 ft MSL = 2.49936 m;
- FAA true alignment: 292 degrees (nearest degree);
- derived true centerline heading: 292.163062 degrees;
- projected grid heading: 291.677217 degrees; and
- regional terrain tile: `(94,146)`.

The start index orders `APT/KOAK/P00.AGN` before `APT/KOAK/M00.AGN` and
requires both publications to complete before the first KOAK scene render.
This prevents a cockpit start on an unmarked or absent runway.

The index also supplies an exact first-frame wire witness. Tile `(94,146)` has
coarse center E 570,112 m, N 4,175,104 m. Rounding at 16 translation counts
per metre gives camera `(X,Y,Z) = (3106,64,2226)`: X/Z are fine north/west
offsets from that cell center, while camera Y is absolute FAA altitude plus
1.5 m clearance. The useful model-coordinate vector whose Y is
`altitude-608 m` is retained separately and labelled so it cannot be copied
into the camera packet.

KOAK group 0 has object origin E 568,436 m, N 4,174,593 m, elevation 608 m.
Relative to the same coarse cell it emits `(X,Y,Z) = (-8176,9728,26816)` and
uniform scale `53056`; P00 and M00 share this transform. Airport model axes
are already grid north/up/west, so the object Euler words are identity
`(0,0,0)`.

For the cockpit direction, the proven Pingo helper documents upright camera
yaw as `atan2(-dx,-dz)` and one binary turn as 32768 words. Applying that
formula to the projected 28L centerline produces -158.322783 degrees,
-14410.891506 words, and symmetric-nearest wire yaw `-14411` (`0xC7B5`).
Initial camera Euler words are therefore `(pitch,yaw,roll) = (0,-14411,0)`.

## Current size evidence

The proof contains five airports, six paired groups, 12 P3DM components, 2,816
vertices, 1,408 triangles, and 35,040 container bytes. The developer index
SHA-256 is
`0653fb8cfe5b0f09bd47951cb4ed150202dd25bb681ed9412db03f60092f9503`;
the raw palette SHA-256 is
`47f7e1441be49b5e4701d19e2af2c31a5ee056914c03bd8d6249bdb085bb374d`.

KSFO markings are the largest single component at 14,120 container bytes.
This is intentionally recorded rather than hidden: airport activation must
begin early and publish at most one component per service pass. If measured
hardware latency makes that unacceptable, split by runway while retaining the
same paired/publication contract; do not weaken CRC validation or partially
publish a mesh.
