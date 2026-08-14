# Bay Area landmark source reconnaissance

Date: 2026-08-02  
Status: L1 source pass complete; no landmark has yet been promoted into a
runtime fixture

## Recommendation

The useful surprise is that the [FlightGear scenery database](https://scenery.flightgear.org/)
already contains five current Bay Area donors suitable for an offline Pingo
conversion pass:

- Golden Gate Bridge;
- the Bay Bridge west span;
- Coit Tower;
- Sutro Tower; and
- the Transamerica Pyramid.

They are compact textual AC3D, authored by Frederic Bouvier, and the database
labels its model data GPL-2.0-or-later. Their embedded AC3D materials already
carry usable RGB values, so their bitmap textures are not required to recover
a restrained flat-material vocabulary. More importantly, their FlightGear XML
wrappers expose deliberate `Bare` LOD roots that are often almost exactly the
mesh budget Pingo needs.

Do not vendor those files yet. The dated source manifest pins their raw URLs,
sizes, and hashes while keeping normal builds offline. Before distributing a
derived P3DM corpus, make the GPL data-package boundary and attribution bundle
explicit; do not assume that converting a mesh to a binary container removes
its source license.

Build the Campanile, Salesforce Tower, the current Bay Bridge east span, and
the Mount Diablo summit structure procedurally from authoritative dimensions
and open reference material. No redistributable donor found for those targets
was both trustworthy and useful.

The pinned machine-readable record is
[`data/manifests/bay-area-landmarks-2026-08-02.json`](../data/manifests/bay-area-landmarks-2026-08-02.json).

## Coordinate and scale control

Coordinates below are exact values from the named source, but they do not all
mean the same thing. FlightGear coordinates are model-local placement anchors,
the DataSF Salesforce value is an official address point, and the GNIS value is
a summit point. Conversion must preserve that semantic label. In every case,
use the regional terrain corpus for final ground elevation rather than mixing
the donor's elevation datum into NAVD88 terrain.

| Landmark | Horizontal placement | Authoritative physical control | Initial geometry decision |
|---|---:|---|---|
| Golden Gate Bridge | 37.81953555, -122.4785758; FlightGear model anchor, heading 84.2° | Official district: 8,981 ft / 2,737.41 m end-to-end, 4,200 ft / 1,280.16 m main span, 90 ft / 27.43 m wide, towers 746 ft / 227.38 m above water | FlightGear `Bare`, one component initially, 308 vertices / 388 triangles |
| Bay Bridge west span | 37.79833333, -122.3770588; FlightGear model anchor, heading 40° | MTC: complete crossing 8.4 mi / 13.52 km including approaches, 220 ft / 67.06 m clearance, 1,400 ft / 426.72 m channel span | FlightGear `Bare`, mandatory three-way spatial split, roughly 1,100 triangles total after line handling |
| Bay Bridge current east span | derive from current Caltrans/MTC engineering alignment; do not reuse model 77's origin as geometry truth | MTC: self-anchored suspension plus skyway, 525 ft / 160.02 m SAS tower, opened 2013 | New procedural silhouette, approximately three streamed components / 900 triangles total |
| Coit Tower | 37.80241406, -122.4058707; FlightGear anchor | National Register amendment: 182 ft / 55.47 m architectural height; DataSF lidar difference at the footprint is 55.05 m | FlightGear `Bare`, scale Y by about 0.6925, one component / 192 triangles |
| Campanile / Sather Tower | 37.872332, -122.257964 from the UC Berkeley map link | UC Berkeley: 307 ft / 93.57 m tall; clock hands 17 ft / 5.18 m | New procedural model, one component / about 320 triangles |
| Transamerica Pyramid | 37.79521298, -122.4027781; FlightGear anchor, heading 80° | USGS: 853 ft / 260.0 m tall and 174 ft / 53.04 m square plan | FlightGear `Bare`, 48 vertices / 78 triangles; preserve Y and calibrate X/Z |
| Salesforce Tower | 37.78993419, -122.397097479; official DataSF address point for 415 Mission, parcel 3720009 | California Geological Survey: up to 167×167 ft / 50.90×50.90 m floor plate, 901 ft / 274.62 m top occupied floor, 1,070 ft / 326.14 m crown; SF Planning calls the roof approximately 912 ft | New rounded-square/tapered procedural model, one component / about 160 triangles |
| Sutro Tower | 37.75640048, -122.452998; FlightGear anchor. FCC ASR 1001289 reports 37°45'19.0" N, 122°27'10.0" W NAD83 | Official site/FCC: 977 ft / 297.79 m overall AGL, base 834 ft / 254.20 m AMSL, top 1,811 ft / about 552.0 m AMSL | FlightGear solids, one component / about 450 triangles after converting only critical line members |
| Mount Diablo Summit Building | GNIS summit 37.881702, -121.914268; drape building to terrain | California State Parks: summit 3,849 ft / 1,173.18 m; historic sandstone summit building, rotunda, deck, and aviation beacon | New procedural close-range accent, one component / about 180 triangles |
| Treasure/Yerba Buena Island group | derive each structure from island GIS/engineering control when built | HABS/HAER provides measured and historical documentation for the bridge and surviving exposition buildings | Bridge/tunnel portals first; later simplified Buildings 1, 2, and 3/111 only if object budget permits |

Dimension sources:

- Golden Gate Bridge District [facts and figures](https://www.goldengate.org/exhibits/facts-and-figures-about-the-bridge/)
  and NPS [main-span explanation](https://www.nps.gov/places/000/how-long-is-the-golden-gate-bridge.htm).
- MTC [Bay Bridge overview and current-span facts](https://mtc.ca.gov/operations/programs-projects/bridges/san-francisco-oakland-bay-bridge)
  and [525-foot east tower fact](https://mtc.ca.gov/news/test-your-knowledge-bay-bridge-fun-facts).
- NPS [Coit Tower National Register amendment](https://npgallery.nps.gov/NRHP/GetAsset/5b02a09a-bc9f-404c-b635-da88f5a1cd8b).
- UC Berkeley [Campanile map](https://www.berkeley.edu/map/campanile-sather-tower/)
  and [tower history](https://visit.berkeley.edu/campus-attractions/campanile-sather-tower/history-campanile/about).
- USGS [strong-motion building report](https://pubs.usgs.gov/of/1989/0568/report.pdf)
  for the Transamerica plan and height.
- Salesforce Tower [official facts](https://salesforcetower.com/about/),
  California Geological Survey [SMIP18 proceedings](https://www.conservation.ca.gov/cgs/documents/program-smi/seminar/SMIP18-Proceedings.pdf),
  and [SF Planning case 2012.0257](https://commissions.sfplanning.org/cpcpackets/2012.0257.pdf).
- Sutro Tower [official dimensions](https://www.sutrotower.com/about) and the
  current [FCC ASR 1001289 mirror](https://www.fccinfo.com/CMDProASRLookup.php?sASR=1001289&tabSearchType=ASR+Search).
- California State Parks [Mount Diablo overview](https://www.parks.ca.gov/?page_id=517)
  and [CCC summit-building history](https://www.parks.ca.gov/?page_id=25059),
  with USGS [GNIS semantics](https://www.usgs.gov/us-board-on-geographic-names/what-geographic-names-information-system-gnis).

## Inspected FlightGear donors

The files were downloaded only to `/tmp`, inspected with
`scripts/inspect_landmark_ac3d.py`, and not added to the repository. The raw
counts include alternate LODs and light billboards; they are not proposed
runtime counts.

| Donor | Raw bytes | Raw objects/materials | Raw vertices | Raw fan triangles | Chosen root | Chosen geometry |
|---|---:|---:|---:|---:|---|---:|
| Golden Gate, model 78 | 177,241 | 181 / 9 | 2,550 | 3,140 | `Bare` | 308 vertices / 388 triangles |
| Bay Bridge west, model 75 | 404,926 | 102 / 6 | 6,042 | 7,216 plus 107 line surfaces | `Bare` | 752 vertices / 842 triangles plus 15 line surfaces |
| Coit Tower, model 79 | 52,138 | 31 / 4 | 877 | 850 | `Bare` | 121 vertices / 192 triangles |
| Sutro Tower, model 76 | 36,845 | 52 / 4 | 477 | 380 plus 78 line surfaces | selected structural objects | about 300 existing solid triangles before critical-line conversion |
| Transamerica, model 160 | 10,770 | 3 / 2 | 96 | 156 | `Bare` | 48 vertices / 78 triangles |

All five AC files are already flattened: no `loc` or `rot` object directives
occur. They use metres and their raw vertical extents provide strong scale
checks. Exact byte sizes and SHA-256 values are in the manifest.

There are two traps worth preserving in the design:

1. Importing the AC file as one undifferentiated mesh is wrong. The XML wrapper
   selects `Detailed`, `Rough`, or `Bare` by range; several donors also carry
   separate day/night variants. Naive import draws duplicate coincident
   geometry.
2. Billboard lamps, cable lights, and Sutro's line surfaces are FlightGear
   rendering devices, not ordinary Pingo triangles. Discard billboard lights.
   Convert only recognition-critical line work to narrow crossed ribbons or
   triangular prisms after measuring its screen-space value.

The checked-in inspector intentionally reports raw file facts rather than
silently interpreting FlightGear's XML scene graph:

```text
.venv/bin/python scripts/inspect_landmark_ac3d.py path/to/model.ac
```

The eventual converter must add hierarchy-aware root selection as a separate,
tested stage.

## Offline conversion prototype

The first implementation should remain a deterministic host pipeline and emit
the existing AGNB/P3DM landmark layer. A useful stage boundary is:

1. Acquire only the manifest URL requested by an explicit command. Verify byte
   size and SHA-256 before parsing. Ordinary builds never access the network.
2. Parse the AC3D hierarchy and select one named LOD root. Fail if the named
   root is missing or duplicated unexpectedly.
3. Remove billboard/light helper objects, texture references, degenerate
   surfaces, and unsupported points/lines. Emit a report naming every removal.
4. Apply any object transforms before merging. The currently pinned files have
   none, but treating that as an assertion prevents a later donor change from
   silently moving parts.
5. Triangulate polygons deterministically while retaining AC3D material index
   per output triangle. Do not select a face color from a now-discarded texture
   when the donor's named material already expresses the intended structure.
6. Calibrate against authoritative dimensions. Record non-uniform scale when
   required, notably Transamerica X/Z and Coit Y.
7. Recenter each output component and partition any component whose integer
   model half extent exceeds 2,047 m. The Bay Bridge west donor necessarily
   partitions; the Golden Gate `Bare` root fits one object.
8. Weld only within a component. Preserve exact shared endpoint coordinates
   where adjacent bridge components meet so quantisation cannot open visible
   joints.
9. Collapse materials to the vocabulary below, generate normals from final
   winding, quantise to P3DM, and validate the container round trip and DATA
   CRC before publication.
10. Produce a Blender comparison scene and a Pingo object-count report before
    any fixture integration.

The initial material vocabulary should be small and semantic:

| Group | Initial face materials |
|---|---|
| Golden Gate | international-orange steel, brighter tower face, pale concrete, dark asphalt, muted ground/fort |
| Bay Bridge | medium steel gray, bright sun-facing steel, pale concrete, dark asphalt, cable gray |
| Coit/Campanile | warm pale stone, shadow stone, dark openings, clock face, roof/spire accent |
| Transamerica | warm off-white concrete, shadow off-white, dark window/wing accent |
| Salesforce | cool pale glass, shadow blue-gray, bright crown, dark base |
| Sutro | safety red, pale gray/white, dark red shadow, optional self-lit obstruction accent |
| Diablo summit | warm sandstone, shadow sandstone, dark opening, metal beacon |

Landmarks begin as scene-illuminated `SOLID_FLAT` P3DM objects with a native
solid palette. Their source textures are never shipped. Patterned landmark
materials can be evaluated later, but they are not required to prove L1 and
must not consume the terrain pattern contract by accident.

## Streaming and renderer budget

The current combined-flight budget is 25 terrain objects, two KOAK hard-surface
objects, and at most one aircraft: 28 active renderables. Landmark streaming
must never treat the remaining four slots as a permanent entitlement.

- A single tower or the one-object Golden Gate raises the scene to 29.
- The three-part Bay Bridge west span raises it to 31.
- A complete west-plus-east Bay Bridge cannot remain resident beside the full
  radius-two terrain ring. Bridge pieces must replace terrain slots or stream
  by aircraft-relative segment.
- Do not load a tiny tower merely because its region is resident. Use projected
  importance/distance thresholds: major bridges can appear tens of kilometres
  away, skyline towers at roughly 10–15 km, the Campanile and Coit at shorter
  range, and the Mount Diablo summit building only close to the peak. Mount
  Diablo itself is terrain and remains visible independently.
- Landmark publication follows the same transactional rule as terrain: import
  into staging, validate, transform, and then replace a stable slot only when no
  render is in flight. A failed donor leaves the previous object unchanged.

This is why a spectacularly detailed city model is the wrong source even if it
were freely licensed. Recognisable silhouettes, authoritative scale, small
component counts, and whole-object culling matter more than facade detail.

## Explicitly rejected sources

The following are not fallback donors:

- FlightGear model 77, “San Francisco East Bay Bridge,” is a useful historical
  artifact but was last updated in 2010. MTC confirms the replacement east span
  opened in September 2013; using model 77 would recreate the demolished span.
- Sketchfab's exact [Campanile model](https://sketchfab.com/3d-models/campanile-uc-berkeley-3e8163996296487ba208a8172dfde24d)
  is unlicensed, non-downloadable, texture-dependent, and 810,317 faces.
- The remarkably economical [3D Warehouse Campanile](https://embed-3dwarehouse-classic.sketchup.com/model/e86d2c2bac08770486ed0f2c6244a512/Model-of-the-Sather-Tower)
  has only 305 polygons, but the 3D Warehouse General Model License is not an
  open stand-alone redistribution license. It needs direct author permission
  before it can become project data.
- The only plausible Salesforce Sketchfab result is a photogrammetric Einstein
  sculpture near the tower, not the building, and is CC BY-NC-SA.
- The Esri [San Francisco 3D Buildings scene layer](https://www.arcgis.com/home/item.html?id=d3344ba99c3f4efaa909ccfbcc052ed5)
  is Precision Light Works/Pictometry material under the Esri Master License.
  It is a visual reference, not an open donor corpus.
- Google Earth, Google Maps, and Apple Maps geometry, textures, or models
  reconstructed from screenshots are rejected. A downstream uploader's CC
  label cannot cure missing rights in the upstream imagery.
- Untextured Sketchfab uploads with vague authorship, AI-generated descriptions,
  uncertain scale, or no clear current-span identity are rejected even when a
  platform field says CC BY. License metadata is necessary, not sufficient,
  provenance.

## Open reference material that is not a donor mesh

Government records can validate a new model without becoming its runtime
texture:

- Library of Congress [Golden Gate Bridge HAER CA-31](https://www.loc.gov/pictures/item/ca1355/)
  and [Bay Bridge HAER CA-32](https://www.loc.gov/item/ca1352/) include measured
  drawings and extensive engineering documentation. The rights notice says
  government-made images have no known restrictions, while copied third-party
  images may remain restricted; select sheets individually.
- HABS documents [Treasure Island Buildings 3 and 111](https://www.loc.gov/pictures/item/ca3381/)
  and the [Treasure Island Administration Building](https://tile.loc.gov/storage-services/master/pnp/habshaer/ca/ca3400/ca3486/data/ca3486data.pdf).
- UC Berkeley's Environmental Design Archives holds original [Sather Tower
  construction and maintenance drawings](https://public.ucbeda.aspace.cdlib.org/repositories/2/archival_objects/40993).
  The collection is open for research, but that is not itself a redistribution
  license; request digital access and permission before copying drawings.
- DataSF's [Building Footprints](https://data.sfgov.org/Geographic-Locations-and-Boundaries/Building-Footprints/ynuv-fyni)
  are PDDL/public-domain data and are excellent dimensional cross-checks. They
  derive from 2010 massing, so they accurately corroborate Coit and
  Transamerica but cannot contain Salesforce Tower.

## L1 next acceptance slice

The lowest-risk visual proof is Transamerica plus Coit: both use one tiny named
`Bare` root, have authoritative scale controls, and fit one Pingo object each.
The next bridge proof should use the Golden Gate `Bare` root because it already
fits one object and retains a strongly recognisable silhouette. Bay Bridge work
should wait for the hierarchy-aware splitter and a current procedural east
span; importing only the west donor would be correct but incomplete.

L1 remains open. This pass completed source, license, scale, rejection, and
conversion reconnaissance; it did not add a landmark fixture or claim visual
acceptance.
