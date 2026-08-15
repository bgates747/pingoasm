# Regional terrain build contract

Status: **offline compilers, complete L0 corpora, and first universal-manager
runtime implemented**. The original rectangular corpus remains a reproducible
control. New regional work uses the accepted 50,183-cell N=5 hex profile in
`docs/hexagonal-terrain-cells.md`; its complete loose-L0 corpus now streams
through the manager in `docs/terrain-manager-runtime.md`. Mixed-LOD and physical
hardware qualification remain J1/R1 work, so this document does not mark either
TODO complete.

## Pinned source corpus

The only ordinary-build inputs are the checksum-pinned files in
`data/manifests/bay-area-2026-08-02.json`:

- 42 USGS 3DEP 10 m float32 elevation tiles in EPSG:32610, reported as NAVD88;
- 9 Annual NLCD 2025 30 m categorical tiles in EPSG:5070; and
- the exact request, product, datum, grid, byte-size, and SHA-256 evidence in
  that manifest.

`scripts/build_regional_terrain.py` verifies every source size and SHA-256 by
default, reads TIFF blocks lazily, and performs no network access. It maintains
small per-file block caches rather than expanding the 603 MB source corpus in
memory. One persistent PROJ `cs2cs` process converts sampled UTM points to the
NLCD grid.

## Mandatory Blender review artifact

Every regional terrain-set design and corpus build must have a matching
Blender file for human review. The file is a required build artifact, not an
optional visualization made after the runtime data is accepted. It must cover
the complete regional cell set and preserve enough embedded metadata to audit
the topology profile, cell identities, projected coordinates, source
elevations, material assignments, display scaling, and pinned-input
provenance. A reduced review LOD is permitted only when it identifies itself
unambiguously and does not masquerade as the runtime mesh density.

The current equal-area hex candidate is reviewed at
`build/visualization/bay-area-hex-overview.blend`. The scene contains all
50,183 canonical cell IDs `0..50182` in one shared-vertex mesh. Each cell is
represented by one centre and its six N=5 boundary corners, producing 151,446
vertices and 301,098 flat faces. This one-centre/six-triangle preview is much
lighter than the runtime N=5 triangular lattice; the distinction is recorded
both in scene properties and in the generated `.review.json` receipt.

Every face carries `hex_cell_id`, axial `hex_q`/`hex_r`, preview-sector,
terrain-material, and NLCD-category attributes. Every point carries exact
whole-metre UTM easting/northing plus its sampled NAVD88 elevation. The
`hex_cell_boundary` edge attribute distinguishes cell perimeters from the six
review-only radial edges. Materials use the same restrained 15-color NLCD
vocabulary as terrain generation, sampled at preview-face centroids and kept
flat shaded. DEM heights are bilinear vertex samples, never face-centre
heights.

The ordinary build verifies all 42 DEM and nine NLCD source files against the
pinned manifest before creating the scene. Its default 1:1000 scale is uniform
on all axes with no vertical exaggeration. Any intentionally exaggerated
review must record its multiplier and cannot replace the unexaggerated
artifact when geometry or seam correctness is being accepted.

## Regional integer frame

The world is one exact 512 m grid in EPSG:32610:

| Field | Value |
| --- | ---: |
| southwest integer origin | E 521,728 m, N 4,100,096 m |
| columns × rows | 201 × 252 |
| aligned northeast limit | E 624,640 m, N 4,229,120 m |
| tile coordinate | `tile_x` east, `tile_y` north |
| tile identity | `tile_id = tile_y * 201 + tile_x` |
| terrain path | `TRN/L{lod}/{tile_id >> 8:02X}/{tile_id & 255:02X}.AGN` |

The acquired DEM begins 152 m east and 344 m north of the aligned southwest
corner and ends 150 m west and 180 m south of the aligned northeast corner.
The complete rectangular runtime grid is retained. A lattice sample in that
narrow outer frame clamps to the nearest source pixel, and every affected
record carries explicit DEM and NLCD edge-padding flags. The KOAK proof has no
edge-padded records.

The horizontal floating origin uses the current 512 m cell as its coarse part.
In Pingo translation counts:

```text
object X =  (tile_y - coarse_tile_y) * 8192
object Z = -(tile_x - coarse_tile_x) * 8192
```

Fine X is north and fine Z is west. Crossing a cell changes the coarse index
and fine value by exactly 512 m. Y is absolute and is never horizontally
rebased.

## Normalization and height metadata

Every regional terrain component uses one uniform three-axis model half extent
of 768 m. The vertical origin is 608 m:

```text
model x = (north - tile_center_north) / 768
model y = (NAVD88_elevation - 608) / 768
model z = -(east - tile_center_east) / 768
```

The corresponding object wire scale is Q8.8 `24576`; the absolute terrain Y
translation is `9728` counts. The acquired extrema -114.779747 m through
1335.914551 m map to -722.779747 m through +727.914551 m around the origin,
leaving at least 40 m of headroom. Signed position quantization is about
2.34 cm, far finer than the source DEM.

Each P3DM descriptor stores the mesh minimum elevation in decimetres, including
the downward skirt, and the real terrain-surface maximum in decimetres. The
WORLD record additionally preserves floating surface minimum/maximum values.
The maximum is therefore directly usable for a conservative current/ahead-tile
collision or terrain-clearance rejection without decoding mesh vertices.

FAA airport elevations remain FAA MSL values because the source does not name
a more specific vertical datum; they must not silently be relabelled NAVD88.
`AIRPORTS.json` owns that distinction and the canonical start.

## Lattice, materials, and seams

The three nested hex-offset triangular lattices have horizontal spacings
68.772475637 m, 137.544951273 m, and 275.089902547 m. LOD 1 vertices are a
subset of LOD 0; LOD 2 vertices are a subset of LOD 1. DEM height is bilinearly
sampled at every vertex, never assigned at a face center.

A global lattice phase is used for the entire region. For streaming, each
global triangle is clipped at the exact 512 m tile planes and clipped
intersections are canonicalized to one projected micrometre. This deliberately
differs from the Berkeley fixture's whole-face centroid ownership. Interior
faces retain the aesthetically accepted equilateral topology; only the thin
tile-edge strip contains irregular clipped triangles. Regression tests prove
that every LOD covers exactly 512² m² per tile with no overlap, adjacent equal-
LOD chunks share exact boundary samples, and every surface face points up.

Exact tile planes prevent the broad overlap band that different centroid-owned
LOD lattices would otherwise create. Every boundary also receives an outward-
facing, up-to-64 m downward skirt in the owning face's material. Skirt bottoms
are clamped at -160 m NAVD88, the safe lower normalization plane, and each
record reports the number of clamped boundary vertices. Runtime must limit
adjacent cells to a one-level LOD difference. A 64 m skirt is a provisional
visual bound, not a mathematical guarantee on very steep relief: the Mount
Diablo qualification must compare measured cross-LOD edge error with 64 m. If
that error is larger, regenerate deeper skirts or adopt edge-constrained
variants before claiming crack-free mixed LOD.

Face material is the predominant NLCD category among covered pixel centers,
with a deterministic centroid fallback and lowest-category tie break. The
accepted 15-material natural vocabulary is unchanged. NLCD nodata or an
unknown class at terrain no higher than 3 m becomes open water; other unknown
land becomes the existing developed-high-intensity fallback. Each record
reports actual fallback and nodata-touched face counts. Terrain uses patterned,
scene-lit P3DM policy; airport pavement and markings remain separate solid,
self-lit components.

## Exact storage budgets

The complete aligned region contains 50,652 cells. Storing every LOD for every
cell is technically possible but creates 151,956 FAT files and 450,781,012
container bytes. That cost is not justified for the first runtime experiment.

| Corpus | Tiles | Records | L0 bytes | L1 bytes | L2 bytes | Total bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full aligned world | 50,652 | 151,956 | 269,883,360 | 119,038,920 | 61,858,732 | 450,781,012 |
| KOAK–Berkeley–Mt Diablo corridor | 726 | 2,178 | 3,873,256 | 1,707,192 | 887,040 | 6,467,488 |
| generated KOAK 9×9 proof | 81 | 243 | 433,812 | 191,300 | 98,668 | 723,780 |

The generated KOAK proof has 27,023 vertices and 43,472 triangles including
skirts. Its mean P3DM DATA and UART-only floors at 1.152 Mbaud 8N1 are:

| LOD | Mean DATA bytes | Min–max DATA bytes | UART floor |
| --- | ---: | ---: | ---: |
| 0 | 5,254.96 | 4,888–5,440 | 45.62 ms |
| 1 | 2,261.56 | 2,092–2,464 | 19.63 ms |
| 2 | 1,117.48 | 1,024–1,276 | 9.70 ms |

The skirts make near tiles larger than the earlier unclipped Berkeley records;
an L0 publication no longer fits a 30 Hz tick at the UART floor. The streamer
must request near terrain with multi-tick lookahead and publish at most one
component per foreground service pass. It must not assume all LODs load in one
tick merely because L1/L2 usually do.

## Generated proof and resumability

The shared ignored output root is
`build/p3dm/bay-area-koak-proof`. Terrain owns `TRN/` and `WORLD.json`;
airport generation owns `APT/` and `AIRPORTS.json`. Neither generator deletes
the other's paths.

The proof selects tile X 89..97 and Y 142..150 at all three LODs. Each terrain
record is independently parsed and byte-round-tripped after generation. A
private `.state` record pins the generator/source signature and output hash;
reruns reuse only a file whose state signature, SHA-256, decoded tile, and LOD
all agree. Interrupted generation therefore resumes without trusting a merely
present file.

`WORLD.json` is the authoritative host-side build index and includes all paths,
hashes, counts, material histograms, height bounds, edge flags, grid equations,
normalization witnesses, and a hash reference to `AIRPORTS.json`. A compact
runtime `WORLD.PTI` representation remains owned by J1; this terrain compiler
does not invent a competing on-disk runtime-index format.

The canonical KOAK 28L threshold belongs to coarse cell `(94,146)`, ID 29440,
whose center is E 570,112 m, N 4,175,104 m. The threshold's fine offsets are
+194.105307 m north and -139.094293 m east, yielding Pingo X `3106` and Z
`2226` counts. Surface Y is `40` counts and the accepted 1.5 m initial
clearance starts at absolute Y `64` counts. Heading uses the airport index's
291.677217 degree grid witness rather than conflating grid and true north.

## Commands

```text
.venv/bin/python scripts/build_regional_terrain.py --selection full --budget-only
.venv/bin/python scripts/build_regional_terrain.py --selection koak-proof
.venv/bin/python scripts/build_regional_terrain.py --selection corridor --output <directory>
blender --background --python scripts/build_regional_blender.py -- \
  --output build/visualization/bay-area-hex-overview.blend
```

The default source-hash pass is mandatory for durable output. The explicit
`--skip-source-hash` switch exists only for local development timing.

Building the universal-manager fixture against a full corpus is also a
fail-closed corpus gate. It visits every dense cell ID and verifies the WORLD
path and identity, container length and SHA-256, complete P3DM/CRC/index
contract, DATA length and SHA-256, geometry and material witnesses, and the
aggregate statistics before it assembles or installs the executable. Checking
only the initial runtime neighborhood is not sufficient for a regional set.

Open the generated regional review directly with:

```text
blender build/visualization/bay-area-hex-overview.blend
```
