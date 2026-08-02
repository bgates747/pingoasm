# Procedural Bay Area landmark P3DM corpus

Status: **deterministic offline proof corpus for L1**. The build does not
modify or enter the live KOAK fixture. Generated files are ignored under
`build/p3dm/bay-area-koak-proof/LMK/`; the developer index is
`build/p3dm/bay-area-koak-proof/LANDMARK.json`.

```sh
.venv/bin/python scripts/build_landmark_p3dm.py
```

The generator performs no network access and consumes no donor mesh, imagery,
or texture bitmap. It builds four original, low-poly recognition silhouettes
from pinned public positions and nominal scale controls. Every dimension not
supplied by a pinned control is labelled as an approximation in the generated
index. These models are not survey, navigation, facade, or collision geometry.

## Proof set

The Campanile and Mount Diablo summit building are the priority witnesses.
Salesforce Tower and the Transamerica Pyramid add useful tall-city silhouettes.

| ID / path | Horizontal anchor | Raw 3DEP sample / rendered L0 base (m NAVD88) | Pinned nominal control | Final vertices / triangles | Load / retain radius |
| --- | --- | ---: | --- | ---: | ---: |
| Campanile / `LMK/CAMPANIL.AGN` | UC Berkeley map point, E 565,262.013 m, N 4,191,909.590 m | 98.180879 / 97.321074 | 93.5736 m reported architectural height | 268 / 130 | 8,000 / 8,512 m |
| Diablo / `LMK/DIABLO.AGN` | USGS GNIS summit point, E 595,478.713 m, N 4,193,245.261 m | 1,171.894986 / 1,166.177314 | 1,173.1752 m reported summit; building dimensions approximate | 228 / 102 | 3,000 / 3,512 m |
| Salesforce / `LMK/SALESFRC.AGN` | official DataSF address/parcel point, E 553,084.113 m, N 4,182,679.344 m | 4.318805 / 5.212350 | reported 50.9016 m plan, 277.9776 m roof, and 326.136 m crown | 244 / 116 | 15,000 / 15,512 m |
| Transamerica / `LMK/TRANSPYR.AGN` | pinned FlightGear placement anchor, E 552,580.202 m, N 4,183,261.814 m | 5.441588 / 5.267444 | reported 53.0352 m square plan and 260.0 m height | 124 / 58 | 15,000 / 15,512 m |

“Pinned nominal” is intentional: the cited values control deterministic model
scale but do not turn a recognition mesh into measured geometry. In particular,
Mount Diablo’s reported 3,849 ft summit control is 1.280214 m above the raw
bilinear DEM sample and 6.997886 m above the decoded L0 surface at the GNIS
point. The index retains both comparisons without relabelling either source.

## Rendered-terrain contact contract

Placing a landmark on the raw GeoTIFF sample is insufficient. The regional
mesh samples a triangular lattice and then quantizes it into signed 16-bit
P3DM coordinates; L0, L1, and L2 can therefore differ at both the anchor and
across a building footprint. The landmark build now reproduces that rendered
path:

1. Project the pinned WGS84 anchor into the regional EPSG:32610 frame.
2. Select the same L0 strip, L1 family component, and L2 family component used
   by `regional_lod`.
3. Build each surface with `rectangular_topology()` and `build_component()`
   from the pinned DEM samples, then decode its P3DM signed-16 coordinates.
4. Interpolate the anchor on the decoded triangles. Model local `y=0` is the
   decoded L0 anchor elevation.
5. Clip decoded triangles against the landmark’s axis-aligned footprint and
   record the minimum and maximum contact elevation at all three LODs.

The generated `terrain_contact` record includes each component key and
rectangle, decoded anchor elevation, anchor-minus-raw delta, footprint range,
and footprint-minus-L0-base delta. The current witnesses are:

| Landmark | L0 footprint range | L1 footprint range | L2 footprint range | Foundation depth / bottom / minimum burial clearance |
| --- | ---: | ---: | ---: | ---: |
| Campanile | 96.586236–98.055913 | 96.377623–97.198263 | 91.976395–92.984780 | 7 m / 90.321074 m / 1.655321 m |
| Diablo | 1,160.796093–1,167.582294 | 1,157.590104–1,166.441954 | 1,157.934862–1,166.441954 | 10 m / 1,156.177314 m / 1.412789 m |
| Salesforce | 4.561231–5.778779 | 4.652821–5.284699 | 4.565052–5.122215 | 2 m / 3.212350 m / 1.348881 m |
| Transamerica | 5.009545–5.520367 | 3.828570–5.247815 | 6.054453–7.834560 | 3 m / 2.267444 m / 1.561126 m |

Each recognition mesh receives a rectangular foundation skirt from local
`y=0` down to an integer-metre buried bottom. Its depth is

```text
max(1, ceil(max(0, L0_anchor - minimum_L0_L1_L2_footprint) + 1 m))
```

The skirt has four outward-wound vertical walls and no horizontal caps. Its
open bottom is at least one metre below every witnessed footprint surface, so
terrain hides it despite local relief and LOD changes. The index keeps the
recognition bounds separate from the final procedural bounds and records the
16 added vertices and eight added triangles explicitly.

## Recognition geometry and approximation labels

The Campanile is a square shaft, clock stage, dark-backed open belfry, four
corner piers, cornice, lantern, and pyramidal cap. Its reported 93.5736 m
height is a pinned nominal control. The clock medallions are two layers of
flat geometry, not an image; plan widths, stage divisions, medallion size, and
facade alignment are visual estimates. The reported 5.1816 m clock-hand fact
is retained as a nominal source control but is not presented as face diameter.

The Diablo component is a low sandstone plinth and summit house, octagonal
rotunda, mast, and faceted beacon. All structure dimensions are estimates
because the source pass found no reusable donor or measured public plan. Its
small 3 km activation range reflects that the mountain is the primary distant
landmark; this building is a close-range accent.

Salesforce uses a 12-sided rounded-square superellipse. Its reported maximum
plan, roof, and crown dimensions are pinned nominal controls; taper start,
intermediate widths, curve exponent, address-point centering, and facade
alignment remain approximations.

Transamerica uses the reported square plan and height around a simplified
podium, taper, tip, and two recognition-scale wings. Each wing spans local
`y=70..120 m`, with its inner edge at `|x|=14 m` and outer edge at the nominal
plan limit `|x|=26.5176 m`. The taper still encloses the inner edge at 120 m,
so the wing remains attached throughout its height. Each partially exposed
`y=70 m` underside is explicitly capped with downward exterior winding. The
procedural model consumes none of the GPL FlightGear donor geometry; that
record contributes only the pinned horizontal anchor.

No model reaches its reconnaissance triangle ceiling: the four final
components use 406 triangles including foundation skirts. Every emitted face
is triangulated before P3DM serialization. Source triangles are nondegenerate,
roof surfaces wind upward, Transamerica wing undersides wind downward,
foundation walls wind outward, and post-quantization checks reject any
degenerate triangle or winding reversal.

## Regional transform and quantization

The corpus uses the terrain and airport frame unchanged:

- WGS 84 / UTM zone 10N, EPSG:32610;
- regional origin E 521,728 m, N 4,100,096 m;
- Pingo X grid north, Y up, Z negative grid east;
- shared 608.0 m vertical model origin; and
- 8 physical metres per Pingo internal unit.

Each component anchor is projected, rounded to an integer-metre horizontal
object origin, and normalized uniformly around that horizontal origin and the
shared 608 m vertical origin:

```text
i16 = symmetric_round((axis_m - component_origin_axis_m)
                      * 32767 / model_half_extent_m)
```

The resulting model half extents are 518 m for the Campanile, 574 m for
Diablo, 605 m for Salesforce, and 606 m for Transamerica. The generous values
are deliberate: a shared vertical origin lets the existing P3DM loader place
terrain, airports, and landmarks through one transform contract. Observed
maximum decode error is at most 0.009214321 m, within every component’s
half-quantum witness. Object rotation words are identity; geometry is
regional-grid aligned rather than asserting an unpinned facade bearing.

The P3DM descriptor supplies the anchor tile, integer regional center, actual
absolute elevation bounds in decimetres, and uniform half extent. Runtime X/Z
translation follows the existing floating-origin formula. Load ranges are
recognition and projected-importance thresholds, not collision extents;
retention adds one 512 m cell of hysteresis.

## Flat material contract

Landmarks are mode-1 `SOLID_FLAT`, scene illuminated, and non-dithered. They
reuse the native 8 by 8 raw opaque RGBA2222 cube as `LMK/SOLID64.RG2`. The
complete lookup is 64 bytes and is a selector table, not a bitmap facade.
Faces use eight semantic cells:

| Role | Cell | RGB levels (0–3) | Raw RGBA2222 |
| --- | ---: | --- | ---: |
| warm stone | 47 | 3, 3, 2 | `0xEF` |
| stone shadow | 26 | 2, 2, 1 | `0xDA` |
| dark opening | 5 | 1, 1, 0 | `0xC5` |
| clock face | 63 | 3, 3, 3 | `0xFF` |
| metal gray | 42 | 2, 2, 2 | `0xEA` |
| cool glass | 58 | 2, 2, 3 | `0xFA` |
| glass shadow | 37 | 1, 1, 2 | `0xE5` |
| crown light | 62 | 2, 3, 3 | `0xFE` |

Every triangle repeats one interior UV selector three times. There is no
texture interpolation, image-derived predominant color, alpha billboard, or
runtime dither-pattern dependency.

## Source and deterministic evidence

The build pins both control inputs:

- regional manifest SHA-256
  `a996c9f8af597eefea677a8cb987c78b645598a070d99e30055785ba78b493b5`;
- landmark-control manifest SHA-256
  `c4597b0045d7b26d616133f6a928dedf715e1edf30ce321db12f0e59b27ebea0`.

Dimension controls remain attributable to UC Berkeley’s
[Campanile history](https://visit.berkeley.edu/campus-attractions/campanile-sather-tower/history-campanile/about),
California State Parks’ [Mount Diablo overview](https://www.parks.ca.gov/?page_id=517)
and [summit-building history](https://www.parks.ca.gov/?page_id=25059), the
California Geological Survey [Salesforce structural report](https://www.conservation.ca.gov/cgs/documents/program-smi/seminar/SMIP18-Proceedings.pdf),
the [SF Planning case record](https://commissions.sfplanning.org/cpcpackets/2012.0257.pdf),
and the USGS [Transamerica strong-motion report](https://pubs.usgs.gov/of/1989/0568/report.pdf).
The machine index repeats the applicable URLs on each landmark.

Rendered contact uses four DEM source files because the regional LOD topology
around the anchors reaches into an additional tile. Ordinary builds validate
their byte sizes and hashes before sampling:

| Tile | SHA-256 |
| --- | --- |
| `r01-c02` | `2642211cb2a6700182c66fba79666e2ecc6a523f4bd4499deaa5b8384bdaf545` |
| `r01-c04` | `6dbfc409f9cd616dc20edfd68fd8c5faa03ca186d1ecf3fd76de198008a98445` |
| `r02-c01` | `0291c6f74917bcf5178409ab7ca3e8105cd8ebf9d137fb8ef81b8d54f03ec8c5` |
| `r02-c02` | `446ba274e258b887eff35194da5e9e2d2458c9cc44bc281f7f4867068de38e36` |

The corpus contains 864 vertices, 406 triangles, and 10,520 container bytes.
The palette SHA-256 is
`47f7e1441be49b5e4701d19e2af2c31a5ee056914c03bd8d6249bdb085bb374d`.

| Component | SHA-256 |
| --- | --- |
| Campanile | `7c434d711cfe16d62636c307da9c71142fd3538d28fe2c0e2f4ac27e4ce96864` |
| Diablo | `4f00c75dbfe1995122a42f9158c6cdd00d11ece2fce9c87f3fc4c7d1d816edf4` |
| Salesforce | `1fb17ee422cbf759322fa2f489eb396bb982fab5c9d8bbeec44c94f2337c3479` |
| Transamerica | `c9435dd03cf19e9528488e14752ce76744531e8cca2a8ce224a73c8f5d4df239` |

`LANDMARK.json` SHA-256 is
`822f3e3eb5b1f4be0dfc44805d362a4e9bfa7ced1e153c32228c1283bae43317`.
The focused tests reconstruct every mesh, enforce the pinned nominal controls,
reject changed manifests, validate wing attachment and exposed undersides,
check foundation winding and per-LOD burial, round-trip each P3DM component,
verify source provenance, and pin these bytes.

This proof still stops before a live fixture or slot-scheduler change.
Landmark publication must occur at the render-idle transaction barrier, obey
the 32-object scene budget, and receive a visual range/silhouette comparison
before L1 can be considered complete.
