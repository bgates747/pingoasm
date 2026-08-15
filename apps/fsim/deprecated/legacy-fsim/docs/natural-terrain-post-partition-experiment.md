# Natural terrain first, streaming partitions second

Status: **accepted experimental design choice; not yet a runtime corpus
contract**, 2026-08-03.

This document records a deliberate inversion of the first hex-terrain build:

> Generate one feature- and error-driven terrain surface over an extended
> source domain. Only after that surface is complete, partition its existing
> faces into bounded, roughly hexagonal streaming components.

Logical hexagons continue to provide stable addresses, approximate locality,
ring selection, and workload targets. They no longer dictate six perfectly
straight physical sides or the topology of the terrain inside them.

The existing 50,183-cell N=5 corpus remains the accepted runtime control. This
experiment uses different artifact names and may not replace that corpus until
its topology, manager, LOD, collision, culling, visual, and hardware evidence
is accepted explicitly.

## Motivation

The regular triangular lattice removed the repeated diagonal bias of the
earliest square terrain, but it still spends equal geometric attention on
unlike terrain. A featureless plain receives the same sampling rhythm as a
sharp ridge, a meandering stream, a recognizable shoreline, or a small island.
Conversely, a categorical feature that falls between lattice samples can be
reduced to an artificial triangle even where its plan-view shape matters.

Adding special feature patches to independently generated cells can recover
shape, but it makes cell boundaries responsible for reconciling unrelated
local triangulations. The Lake Anza experiment demonstrated the more useful
construction: overbuild a common surface, impose meaningful constraints, and
cut the result only afterward. Shared boundaries are then selected from one
authoritative mesh rather than negotiated between two generators.

## Experimental hypothesis

A terrain mesh with detail allocated by source-space structure and projected
error will provide better recognizable geography per transformed triangle than
a uniform lattice. Partitioning that completed mesh along its own edges will
produce independently streamable components without forcing artificial
geometry back into the terrain.

The hypothesis has three separable claims:

1. protected categorical and geometric features improve recognition;
2. adaptive interiors remove unnecessary vertices from homogeneous regions
   without exceeding declared elevation, boundary, horizon, or material error;
   and
3. post-triangulation partitioning can meet bounded streaming and exact-seam
   requirements without requiring geometrically perfect hexagons.

Each claim requires its own evidence. A visually attractive full-region
Blender file is a review artifact, not proof of runtime suitability.

## Authoritative source fields

The generator consumes only pinned, checksum-bound fields and profiles:

1. elevation raster, CRS, vertical datum, nodata policy, and affine grid;
2. categorical land-cover and water rasters;
3. attributable vector features when a later profile accepts them;
4. projection and target viewport parameters used by projected-error tests;
5. logical cell seed lattice and regional coverage;
6. deterministic feature, triangulation, partition, and quantization
   parameters; and
7. exact material vocabulary and categorical mappings.

Named geographic features remain human review witnesses. Lake Anza, Mount
Diablo, the Bay shoreline, and other recognizable places do not enter the
compiler as hand-maintained exceptions.

## Build domains and overbuild

The natural surface must be computed on substantially more source area than is
retained. A cut line must not influence feature detection, sample retention, or
triangulation near the retained boundary.

For a bounded experiment, one master domain may cover the complete requested
region plus an apron. A production build divides a very large corpus into
deterministic generation supertiles:

```text
generation domain = owned supertile + declared overlap apron
emitted domain     = owned supertile only
```

The apron is at least as wide as the largest support stencil, contour-cleanup
radius, triangulation influence distance, and partition-routing search band.
Neighboring supertiles read identical pinned data in their overlap. A
canonical ownership rule selects which result survives; scheduling cannot
change the retained mesh.

The first full-region Blender experiment is explicitly permitted to retain
outer-corpus edge effects. That permission applies only to the visualization
boundary. It does not waive internal feature, topology, partition, or seam
checks and does not establish the later runtime edge policy.

## Pass one: protected feature graph

The first pass builds a graph of source features that ordinary simplification
may not cross or erase casually. Candidate graph elements include:

- vector and categorical shorelines;
- water components, islands, holes, and channels;
- streams and rivers;
- airport property boundaries;
- DEM residual extrema;
- high gradient or surface-normal changes;
- curvature ridges and valleys;
- protected horizon contributors; and
- the outer retained-corpus boundary.

Categorical labels use connected components and class-transition contours, not
intensity-gradient filters on arbitrary class numbers. DEM-derived edges use
declared numerical stencils and thresholds. Every graph edge records its
source, class pair or geometric metric, quantized coordinates, strength,
topological role, and permitted LOD transformations.

The graph may be simplified only within source-resolution, projected-boundary,
minimum-width, and topology constraints. An island or channel cannot vanish
because its polygon has few vertices; omission or merging requires an explicit
LOD rule.

## Pass two: adaptive natural triangulation

The feature graph becomes mandatory input to an adaptive constrained
triangulation. Remaining samples are retained according to a deterministic
priority that may include:

1. projected horizon-envelope error;
2. projected ordinary height error;
3. protected feature membership;
4. local plane-fit height residual;
5. gradient, normal-change, or curvature magnitude;
6. material-boundary error;
7. triangle-quality repair; and
8. one canonical global sample key for ties.

This is the sense in which angles matter. Sharp ridges and abrupt changes in
surface normal receive detail because a coarse interpolant changes their shape
or silhouette. Angles alone are insufficient: a flat shoreline or river may
have no vertical relief, so its plan-view categorical or vector constraint
must remain authoritative.

Homogeneous interiors are allowed to become substantially coarser. Refinement
continues until all accepted error and triangle-quality bounds pass or the
profile's hard safety ceiling aborts the build. A far tier is generated from
the pinned sources and constraints, not recursively from a decimated near
mesh.

## Post-triangulation partitioning

The complete natural triangulation is authoritative. Partitioning assigns each
existing triangle to exactly one streaming component and chooses component
boundaries only along existing mesh edges. It does not slice arbitrary faces
or introduce a new regular perimeter into the terrain.

Logical axial hex cells supply target seeds and approximate equal-area regions.
The physical boundary between neighboring seeds is routed through the master
mesh near the corresponding ideal Voronoi/hex boundary. A candidate route has
a deterministic cost such as:

```text
route cost =
    distance from ideal logical boundary
  + boundary edge count and encoded bytes
  + compactness penalty
  + component-area imbalance
  + narrow-neck or disconnected-region penalty
  + penalty for cutting protected feature continuity
  + penalty for poor culling bounds
```

All terms, units, fixed-point quantization, weights or lexicographic ordering,
and ties belong to the build profile. The selected routes form one planar
partition graph. Pairwise routing is insufficient if independently selected
paths can cross, leave holes, or disagree at three-component junctions.

## Physical component requirements

A physical component may look only approximately hexagonal. It must still
satisfy all of the following:

1. one stable logical cell identity and one connected surface region;
2. an explicit ordered neighbor list;
3. bounded area, maximum diameter, vertex count, triangle count, encoded size,
   and conservative elevation range;
4. every source triangle assigned to exactly one owner;
5. complete coverage with no gaps, overlaps, duplicate coplanar faces, or
   unowned edges;
6. shared partition paths selected once and duplicated into both component
   records;
7. byte-identical shared vertex positions after final P3DM quantization;
8. consistent winding and material ownership at every shared edge;
9. deterministic three-or-more-component junction keys; and
10. conservative bounds suitable for frustum culling and collision broad
    phase.

The partitioner should prefer roughly equal work rather than merely equal
plan-view area. Triangle count, protected-edge complexity, expected visible
work, and encoded size may be better balancing signals than square metres.

## Logical addressing and runtime containment

The universal terrain manager remains topology-neutral. A provider may retain
axial coordinates for stable IDs, neighborhood requests, and approximate ring
selection while supplying explicit physical adjacency and containment data.

Aircraft containment begins with the ideal logical-hex estimate, then tests
that component and a small explicit neighbor set against their physical
polygons. The previous owner remains eligible inside the declared hysteresis
band. A bounded point-in-polygon test is acceptable; a full-region search is
not. A build fails if the physical partition lets a point belong to no owner or
to several owners outside an exact shared boundary tie.

Ring radius continues to describe logical neighborhood depth. Because physical
components are compact perturbations of their logical seeds, it remains a
useful loading control, but the provider must use the explicit adjacency graph
where a perfect six-neighbor assumption is false.

## Seam construction

Post-partition seams are consequences of the master mesh:

1. select one ordered master-edge path;
2. quantize every path vertex once in a canonical regional domain;
3. duplicate that exact ordered sequence into both component payloads;
4. validate decoded world positions, incident faces, winding, and materials;
   and
5. validate every multi-component junction independently.

This removes the same-LOD problem of reconciling two separately generated
surfaces. It does not remove mixed-LOD work. LOD tiers require a compatible
partition skeleton, nested boundary key sets, common refinements, or explicit
transition meshes under the mathematical distant-terrain contract.

## Collision and culling

Each irregular component records a conservative horizontal bounding box or
sphere, minimum and maximum elevation, and optionally a simplified containment
polygon. Frustum culling may be less tight than for a perfect regular cell if a
route wanders excessively; the partition cost and maximum-diameter bound keep
that loss measurable.

Collision broad phase uses explicit bounds and adjacency rather than deriving
coverage solely from axial geometry. Narrow-phase terrain remains the owned
piecewise-linear surface. Runtime collision does not use visual skirts or
assume a straight cell edge.

## First complete-region Blender experiment

The next review artifact covers the already pinned complete Bay Area region.
It must:

1. retain the accepted terrain material colors;
2. build a natural/adaptive master surface before assigning logical cells;
3. expose the master surface, logical seed layout, physical partition identity,
   protected-feature classes, and corpus edge as inspectable Blender data;
4. preserve every face exactly once in the retained region;
5. report source hashes, feature counts, vertices, faces, materials, partition
   balance, topology, build time, and peak host memory;
6. use a different filename from the accepted regular-hex overview; and
7. keep the currently unavoidable outer-region edge effects visible rather
   than disguising them.

For tractability, this first overview may use provisional deterministic
feature and error thresholds and may omit runtime skirts, P3DM encoding, mixed
LOD, and physical-hardware evidence. Such omissions must be recorded in the
artifact receipt. The output tests visual and structural plausibility; it does
not promote a runtime format.

## Acceptance gates before runtime promotion

Promotion requires more than the first Blender review:

- deterministic rebuild hashes;
- complete feature-graph provenance and topology checks;
- measured geometric, boundary, material, and horizon error;
- partition coverage and adjacency proof;
- same- and mixed-LOD seam proof after P3DM quantization;
- component size and work-distribution bounds;
- terrain-manager containment and hysteresis tests;
- collision broad- and narrow-phase integration;
- VDP PSRAM, object traversal, triangle, clipping, and frame-time evidence;
- emulator and physical-hardware qualification; and
- explicit human visual acceptance.

Until those gates pass, the exact straight-sided N=5 corpus remains the
runtime control and rollback point.

## Relationship to existing contracts

`docs/hexagonal-terrain-cells.md` remains authoritative for the accepted N=5
runtime corpus. This experiment supersedes its straight physical perimeter
only within separately named experimental artifacts; it retains logical axial
identity and approximate locality.

`docs/distant-terrain-mathematical-lod.md` remains authoritative for source-
derived feature constraints, projected error, horizon analysis, mixed-LOD
transitions, and exact encoded seam validation.

`docs/terrain-manager-runtime.md` remains authoritative for lifecycle,
publication, residency, rebasing, failure, and teardown. Providers gain an
explicit partition/adjacency/containment contract; the manager does not become
a terrain triangulator.

Implementation and qualification remain tracked under R1 and J1 in
`docs/todo.md`.
