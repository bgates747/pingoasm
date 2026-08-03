# Mathematical distant-terrain LOD and seam contract

Status: **accepted design direction; not yet implemented for the hex corpus**.
This document defines how distant terrain is simplified, how potential
silhouettes are measured, and how same- and mixed-LOD seams are proved.  It is
a provider/compiler policy behind the universal terrain manager, not a new
fixture-local loader or residency coordinator.

The governing requirement is that terrain generation depend only on pinned
source data, declared numerical parameters, and deterministic algorithms.
Geographic names and human knowledge may identify useful review views, but
must never decide which source samples survive, where a mesh gains detail, or
which distant components are selected.

## Purpose

The attitude-derived sky and neutral-ground triangles remain a useful final
clear beneath the 3D scene, but they cannot provide a convincing terrain
horizon.  At altitude, a player expects distant relief to continue far beyond
the complete high-detail neighborhood.  Extending the high-detail hex disk is
the wrong primary response because its triangle and object-processing costs
grow quadratically with radius even when memory remains available.

The distant-terrain system therefore has four related goals:

1. preserve the apparent skyline and other high-value relief at progressively
   greater ranges;
2. bound geometric and switching error in projected pixels rather than relying
   on subjective feature labels;
3. guarantee crack-free same-LOD and mixed-LOD boundaries after P3DM
   quantization; and
4. remain deterministic, offline-reproducible, and independent of specialized
   geographic knowledge.

The existing N=5 hex terrain is the near L0 source.  Middle and far tiers use
larger physical components and fewer samples per square kilometre.  Each tier
is compiled directly from the pinned DEM and categorical rasters rather than
by repeatedly decimating the preceding tier; this prevents accumulated error
and keeps every acceptance measurement relative to one authority.

## Non-goals

This contract does not ask a language model, map gazetteer, or manually
maintained landmark list to annotate important mountains, ridges, islands, or
shorelines.  It does not use aerial imagery, learned semantic segmentation,
or undocumented visual heuristics.  It does not require view-dependent mesh
mutation during every frame.

Named locations may appear in Blender, emulator, or physical-hardware review
instructions because a human reviewer needs recognizable witnesses.  Such a
name is evidence about the output, never an input to the compiler.

## Authoritative inputs

A complete build profile pins the following inputs and parameters:

1. the elevation raster, horizontal CRS, vertical datum, affine transform,
   nodata policy, and checksum;
2. any categorical rasters used for water, land cover, or other material
   boundaries, including their checksums and resampling rules;
3. the global terrain lattice and component topology at every LOD;
4. the deterministic observer domain used to measure potential silhouettes;
5. the viewport dimensions, projection, and pixel-error thresholds used for
   simplification;
6. the P3DM normalization, coordinate quantization, material-selector
   vocabulary, and object scale; and
7. deterministic tie rules, iteration limits, and vertex/triangle safety
   ceilings.

The profile records exact rational or integer values wherever practical.
Floating-point host calculations must have a canonical evaluation order and
must quantize their accepted result into the existing integer source and P3DM
domains before checksums are calculated.

## Terrain field and notation

Let the pinned elevation source define a sampled scalar field

```text
h : D -> R
```

over projected horizontal domain `D`.  A source sample has projected position

```text
p = (x_p, y_p, h(p)).
```

An observer is

```text
o = (x_o, y_o, z_o).
```

Its horizontal distance, azimuth, and elevation angle to `p` are

```text
d(o,p)     = hypot(x_p-x_o, y_p-y_o)
phi(o,p)   = atan2(y_p-y_o, x_p-x_o)
theta(o,p) = atan2(h(p)-z_o, d(o,p)).
```

Samples with zero horizontal distance do not enter the distant-horizon
calculation.  All azimuth wrapping, exact-bin ties, equal-distance ordering,
nodata handling, and source-boundary clipping are fixed by the build profile.

## Deterministic observer domain

Silhouette importance is view-dependent, but the compiler need not know the
future flight path.  It evaluates a declared finite observer set `O` generated
mechanically from the corpus.

Horizontal observer positions come from a regular projected lattice or from
canonical terrain-component centres.  The origin, basis, bounded coverage,
and stride are profile fields.  There are no hand-added observer positions.
For each horizontal point `q`, observer altitude is generated from a declared
set of above-ground offsets:

```text
o(q,a) = (q.x, q.y, h(q) + a),  a in A.
```

The altitude set `A` represents the intended operating envelope and is stored
in metres as a sorted tuple.  Every valid observer position receives the same
set.  A profile may additionally include absolute MSL planes when required by
the application, but those planes are also regular and declared rather than
geographically selected.

Azimuth is divided into `N_phi` deterministic bins.  Within a bin, samples are
processed by increasing horizontal distance, then by one canonical global
sample key.  Increasing `N_phi`, reducing the observer stride, or expanding
the altitude set produces a strictly stronger analysis profile with a new
identity; it is not an unrecorded quality knob.

The observer domain is an offline analysis instrument.  Its size affects build
time, not eZ80 or VDP runtime cost.

## Horizon-envelope detection

For one observer and azimuth bin, let the distance-ordered samples be

```text
p_0, p_1, ..., p_n.
```

The prefix horizon before sample `i` is

```text
Theta_i = max(theta(o,p_j)) for 0 <= j < i.
```

Sample `p_i` contributes to the visible terrain envelope when

```text
theta(o,p_i) > Theta_i + epsilon_theta.
```

`epsilon_theta` is a declared numerical tolerance used only to make equality
and floating-point noise deterministic.  A positive contribution has angular
excess

```text
delta_theta(o,p_i) = theta(o,p_i) - Theta_i.
```

This running-maximum test identifies terrain that actually establishes a new
horizon from that observer.  It naturally discovers summits, ridges, islands,
and nearer occluders without knowing what any feature is called.

For each source sample `p`, the compiler accumulates at least:

```text
exposure_count(p) = number of observer/bin profiles where p raises the envelope
maximum_excess(p) = max(delta_theta(o,p)) over those exposures
distance_span(p)  = min/max distance over those exposures.
```

The maximum rather than only the mean is retained because a feature that is
critical from one direction must not disappear merely because it is hidden
from many others.  Counts remain useful as a secondary deterministic priority
when two candidates have equal worst-case error.

## Projected error

Terrain LOD is judged at the final viewport, not in metres alone.  For a
vertical field of view `beta` and viewport height `H`, the focal scale in
pixels is

```text
f_y = H / (2*tan(beta/2)).
```

For an original elevation angle `theta` and a simplified angle `theta_hat`,
the vertical screen error is

```text
e_px = f_y * abs(tan(theta) - tan(theta_hat)).
```

This equation is used directly rather than relying on the small-angle
approximation.  It converts a height residual into the quantity that matters
at the target 320-pixel-wide flight viewport.  Every LOD profile declares its
nearest intended display distance and its maximum permitted pixel error.

An ordinary interior sample may tolerate substantial height error at long
range.  A horizon-contributing sample is evaluated against both its own
projected displacement and the change it causes in the running angular
envelope.  The latter prevents a coarse interpolant from deleting a narrow
summit while remaining close to surrounding elevations in a least-squares
sense.

For candidate mesh `M`, observer `o`, and azimuth bin `b`, let
`Theta_source(o,b)` and `Theta_M(o,b)` be the source and rendered maximum
elevation angles.  The normative silhouette discrepancy is

```text
E_horizon(M) = max over o,b of
    f_y * abs(tan(Theta_source(o,b)) - tan(Theta_M(o,b))).
```

The corresponding mean and percentile errors may be reported diagnostically,
but acceptance is controlled by a declared worst-case bound over the analysis
domain.  Any bounded edge region excluded because the source corpus lacks
terrain beyond it must be reported separately rather than silently lowering
the maximum.

## Intrinsic geometric importance

A finite observer set could miss terrain that becomes important between
observer samples.  The compiler therefore combines horizon exposure with a
purely local geometric residual.

For each source point, fit or interpolate the declared local support surface
from neighboring samples and compute

```text
e_local(p) = abs(h(p) - h_support(p)).
```

The support stencil, boundary rule, and tie ordering belong to the profile.
This residual responds to extrema, sharp ridges, and abrupt changes without
classifying them semantically.  A discrete gradient or Hessian norm may be
reported, but it must be defined from the same fixed stencil and must not
replace the direct height residual.

The combined deterministic candidate priority is lexicographic:

```text
1. maximum projected horizon error if p is omitted;
2. maximum projected ordinary height error if p is omitted;
3. categorical-boundary constraint membership;
4. horizon exposure count;
5. local geometric residual;
6. canonical global sample key.
```

The first five fields are descending; the final key breaks exact ties in one
declared direction.  A weighted scalar score is permitted only if every weight
and fixed-point quantization is recorded and the result is proven equivalent
under rebuild.  Lexicographic ordering is preferred because its priorities are
auditable and do not depend on arbitrary unit conversion between unlike
metrics.

## Categorical boundaries

Water and land-cover information enters only through pinned categorical
rasters.  A categorical boundary exists where two source samples or cells
with different canonical classes share an edge under the declared raster
adjacency.

Important boundaries are converted into projected polylines by a deterministic
contour rule.  Their source edge keys become constraints during triangulation.
This preserves coastlines and islands mathematically as discontinuities in a
categorical field, not as named geographic features.  Tiny components may be
removed only by a declared area or projected-pixel threshold with deterministic
ties.

Distant face materials are selected by deterministic area voting over the
source categorical field.  A profile may merge source classes into a smaller
distant vocabulary, but the mapping is a pinned table.  Geometry selection and
material voting remain separate: a dominant material must not erase a
protected geometric or categorical boundary.

## Feature-aware near geometry and boundary LOD

The regular triangular lattice remains useful as a source-sampling framework
and as a high-quality default fill in unconstrained interiors. It is not the
final topology wherever a categorical boundary carries visible shape. A lake,
coastline, or airport property must not inherit a triangular outline merely
because its source classes were previously voted onto regular faces.

For each retained categorical region, the compiler therefore:

1. extracts a deterministic contour from the pinned classification raster;
2. removes source-pixel staircase noise within a declared source-resolution
   tolerance while preserving topology;
3. simplifies the contour to the LOD tier's projected horizontal-error and
   minimum-feature-size bounds;
4. installs the resulting vertices and segments as triangulation constraints;
5. triangulates the feature and surrounding terrain without overlapping or
   coincident faces; and
6. refines poor local triangles to satisfy a declared minimum-angle or
   equivalent quality bound.

External hex seams remain canonical and immutable. Interior constrained faces
need not be equilateral. A constrained Delaunay-style triangulation is a
candidate because it favors well-shaped triangles while honoring mandatory
segments, but the accepted contract is expressed in topology, error, and
quality bounds rather than the name of one library or algorithm.

Boundary simplification is the horizontal counterpart to height and skyline
simplification. For focal scale `f` pixels, observer distance `d`, and maximum
world-space perpendicular contour deviation `delta`, its small-angle screen
error is approximately

```text
e_boundary_px = f * delta / d.
```

Acceptance may instead project and measure the source and candidate contours
directly; direct measurement is preferred near the camera. Near LOD retains a
detailed but numerically smoothed outline, middle LOD uses fewer constrained
segments, far LOD may retain only a compact polygon, and a feature disappears
only when its projected area and boundary displacement meet declared omission
bounds. Every tier derives its contour from the authoritative categorical
source, not recursively from the preceding tier's polygon.

Topology is a hard constraint. Smoothing or simplification must not create a
self-intersection, invert a ring, merge separate water bodies, close a channel,
or delete an island unless an explicit tier-level feature-size rule permits
that complete topological change. Shared feature crossings at component edges
use the same canonical keys on both sides. Water and surrounding land then
stitch at one boundary rather than relying on coplanar overlays or material
votes that expose triangular bites.

Flat shading makes this requirement more important than geometric residuals
alone suggest. Each face is also a visible color and illumination patch.
Aligning faces with shorelines and other constraints improves material shape,
lighting coherence, and dithering even where the height field itself is nearly
flat.

## Adaptive constrained triangulation

Each component begins with a mandatory constraint set:

1. canonical component corners and seam samples;
2. any cross-LOD transition samples required by neighboring tiers;
3. retained categorical-boundary vertices and segments; and
4. source samples whose declared hard threshold forbids omission.

The initial constrained triangulation covers the component exactly.  For each
triangle, the compiler evaluates every authoritative DEM sample inside or on
that triangle against the interpolated triangle plane and the observer-domain
horizon envelope.  The highest-priority failing sample is inserted and the
affected region is retriangulated.  Iteration continues until all declared
error thresholds pass or the profile's safety ceiling is reached.

If a safety ceiling is reached while an error bound still fails, the build
fails.  It must not silently emit a lower-quality mesh.  Degenerate candidate
triangles, zero-area categorical segments, and samples that collide after P3DM
quantization use declared tie and merge rules; an unresolved collision is a
build error.

Relief-aware diagonal selection remains required.  When two legal diagonals
use the same vertex set, the compiler chooses the one minimizing the same
ordered error tuple used for sample insertion, followed by a canonical edge-key
tie.  This avoids reintroducing the visually artificial repeated diagonal seen
in the earliest rectangular experiment.

Every LOD is triangulated from authoritative source samples and constraints.
A far mesh is not made by loading a middle mesh and simplifying it again.

## Host implementation policy

The first implementation remains Python orchestrating NumPy arrays. DEM
resampling, finite differences, raster masks, contour preparation, observer
batches, cumulative horizon maxima, projected-error evaluation, material
voting, coordinate transformation, and P3DM quantization are all suitable for
vectorized or chunked array processing. Independent components or observer
batches may be processed in parallel only with deterministic reduction and
file ordering.

The compiler must keep small scalar reference implementations for important
equations and compare vectorized results against them in tests. Full-corpus
profiling, with separate wall-time and peak-memory measurements by phase,
precedes any native optimization. The preferred response to a slow build is
first to improve batching, spatial restriction, cumulative algorithms, data
layout, and reuse of source-space intermediates.

Custom C or C++ extensions are not part of the initial design. They become a
candidate only when profiling identifies a stable, isolated kernel whose time
is dominated by Python object or topology-mutation overhead and for which an
established compiled geometry library is unsuitable. Likely candidates are
incremental constrained retriangulation, large seam-ledger topology passes, or
batched horizon evaluation. Provenance, build profiles, diagnostics, Blender
generation, and orchestration remain in Python even if such a kernel is later
introduced.

## Controlled Lake Anza experiment

Before changing the accepted regional L0 corpus, the compiler will run a
controlled experiment centered on Lake Anza in Tilden Regional Park. The lake
is a deliberately human-chosen review witness—the Author's favorite childhood
watering hole—but its outline and retained vertices must come only from pinned
elevation and categorical data plus declared numerical rules.

The experiment preserves the current regular hex mesh as its control and emits
separate candidate artifacts. It must include enough surrounding relief and
cell context to exercise shoreline triangulation and any component-edge
crossing; it must not overwrite the full-corpus Blender file or P3DM records.
At minimum it compares:

1. existing regular-lattice material voting;
2. source contour before smoothing;
3. numerically smoothed, topology-preserving near contour;
4. constrained near triangulation with elevation and triangle-quality
   refinement; and
5. at least two progressively simplified boundary/terrain LOD candidates.

Each candidate records source and profile checksums, boundary vertex count,
terrain vertex and triangle counts, maximum source-space and projected contour
error, elevation and horizon errors, minimum triangle angle, topology results,
seam results, packed P3DM bytes, build time, and peak host memory. A dedicated
Blender comparison file is mandatory and must expose control, contours,
constraints, tiers, and error witnesses as independently selectable
collections. Human review asks whether Lake Anza reads as a small natural lake
nearby and degrades gracefully with distance; numerical failures cannot be
waived by that visual result.

## Tier geometry and selection

Memory permits a generous hierarchy: the Agon VDP has 4 MiB of PSRAM available
to the application, with a project caution threshold near 3 MiB.  The current
radius-five N=5 hex disk contains 91 components and exactly 301,210 bytes
(294.15 KiB) of packed P3DM DATA.  This means distant design is governed first
by transformed triangles, object traversal, clipping, rasterization, and
visible transitions—not by a need to squeeze every vertex from storage.

Middle and far tiers therefore use larger physical component footprints so
range grows without a quadratic increase in object count.  Exact tier side
lengths, lattice subdivisions, and active annuli are profile fields.  A useful
candidate family may scale footprint linearly while reducing internal sample
density, but this document does not freeze one untested ratio.

At runtime, the provider computes desired components from exact regional
position, tier bounds, view direction, and declared hysteresis.  It does not
look up named features.  Optional importance-based priority comes from the
precomputed numerical component metadata:

```text
maximum horizon contribution
maximum elevation
projected error bound
distance interval
categorical-boundary presence
```

These values affect load order or admission within a configured object budget;
they do not change the source geometry after compilation.

Adjacent visible terrain ordinarily differs by at most one LOD.  A farther
tier may overlap beneath a nearer tier over a declared transition band.  The
overlap is useful presentation insurance, but it does not waive the geometric
seam contract.

## Canonical seam representation

Every component edge is parameterized by a rational coordinate

```text
t in [0,1]
```

from one canonical directed corner key to the other.  A seam sample is
identified by

```text
(global edge identity, reduced rational t).
```

Its projected position and elevation are evaluated once from authoritative
source data, then quantized once through the tier's documented P3DM transform.
Meshes duplicate boundary vertices for independent loading, but never
independently resample or normalize them.

The corpus build retains a seam ledger containing, for every component and
edge:

```text
neighbor identity
edge direction and canonical orientation
ordered rational sample keys
source projected coordinates and elevation
encoded P3DM coordinates
material on each incident boundary face
owning triangle and winding
```

This ledger is build evidence and an input to cross-component validation.  It
is not required in VDP memory.

## Same-LOD seam proof

Two same-LOD neighbors must expose the same ordered seam keys in opposite
directions.  After reversing one edge, every corresponding source coordinate,
elevation, and encoded world position must be byte-identical.  Consecutive
samples must describe the same physical segments, and each segment must have
exactly one incident surface triangle from each component.

The compiler rejects:

1. missing, duplicated, or differently ordered seam keys;
2. unequal source or encoded coordinates;
3. non-collinear plan-view samples on an edge declared straight;
4. T-junctions or unclaimed boundary subsegments;
5. inconsistent triangle winding; and
6. material disagreement not explained by an explicit categorical boundary
   coincident with the seam.

These checks occur after final coordinate quantization.  A seam that matches
in floating-point source space but separates by one encoded count is a failed
seam.

## Mixed-LOD seam proof

For adjacent fine and coarse edges, the preferred invariant is

```text
coarse seam keys are an ordered subset of fine seam keys.
```

Every coarse segment is then exactly the union of one or more consecutive fine
segments in plan view.  Where the fine edge contains intermediate elevations
that are not collinear with the coarse 3D segment, an explicit transition mesh
owns the strip between the two boundary profiles.  It is generated from both
ordered key sequences and contains no freehand samples.

The transition triangulation must prove:

1. every fine and coarse boundary segment is consumed exactly once;
2. every transition edge has one or two incident triangles as appropriate;
3. no T-junction, zero-area face, inversion, or duplicate coplanar face exists;
4. its outer boundaries are byte-identical to the terrain edges they meet; and
5. its maximum height and projected error satisfy the stricter of the two
   adjacent tier profiles.

If the topology cannot make coarse keys a subset of fine keys, the profile
must define a common refinement containing the union of both rational key
sets.  Both incident meshes are retriangulated against that refinement.  A
downward skirt may remain as a fail-soft coverage guard, but it is not accepted
as the mathematical solution to an arbitrary crack.

## Seam detector

The offline seam detector enumerates every adjacency admitted by the corpus,
including all six hex directions, all supported LOD deltas, transition meshes,
regional coverage edges, and three-component corners.  It operates from
manifests and decoded P3DM geometry rather than trusting in-memory compiler
objects.

For each adjacency it reconstructs world-space boundary polylines and computes:

```text
exact key equality or subset relation
maximum encoded position delta
maximum source elevation delta
unmatched-segment count
T-junction count
nonmanifold-edge count
winding failures
material-boundary discrepancies
```

Correct seams require zero encoded position delta and zero unmatched topology.
Reported source-space deltas are diagnostic only; they cannot excuse an encoded
failure.  Three-component corners are checked independently so pairwise edge
success cannot conceal three different encodings of one shared point.

This is literal seam detection: it is a complete corpus proof, not a screenshot
comparison.

## LOD switching and visible pop

Crack-free geometry does not by itself prevent a visible LOD change.  For each
admitted switch, the compiler compares the outgoing and incoming surfaces over
the transition domain and evaluates their projected displacement across the
same observer set used for simplification.

Let `h_a(x,y)` and `h_b(x,y)` be the two piecewise-linear surfaces.  At an
observer and projected sample, switching error is

```text
E_switch = f_y * abs(
    tan(atan2(h_a-z_o,d)) -
    tan(atan2(h_b-z_o,d))
).
```

The provider's distance threshold must place the switch no nearer than the
distance at which the profile's maximum permitted pixel displacement holds.
Separate enter and leave thresholds provide hysteresis.  Exact boundary ties
use the same deterministic ownership rule as ordinary terrain selection.

Activation remains atomic at a render-idle barrier.  If both representations
are briefly resident for preload, exactly one owns each visible surface in a
submitted frame unless the profile explicitly uses a noncoplanar underlap.
Memory is available for double residency; z-fighting is not an acceptable
cross-fade mechanism.

## Optional mathematical horizon shell

If even the far terrain tier cannot economically reach the desired apparent
horizon, the same analysis may produce a final camera-relative shell.  For one
observer profile, retain the source horizon angle `Theta(phi)` in each azimuth
bin and choose a render radius `R` inside the qualified Pingo far plane.  The
shell point is

```text
x = x_o + R*cos(phi)
y = y_o + R*sin(phi)
z = z_o + R*tan(Theta(phi)).
```

This radial compression preserves the horizon's azimuth and elevation angle
for that observer exactly while discarding true distant parallax.  Neighboring
observer profiles, altitude correction, selection hysteresis, and shell
replacement error must be bounded numerically before use.  A shell is a final
silhouette device, not collision terrain and not a substitute for middle-range
3D relief.

The shell uses the same source DEM, observer lattice, angular envelope, and
error metrics as ordinary far LOD.  It receives no manually drawn skyline.

## Memory and runtime accounting

Every build records both compact and runtime-relevant counts:

```text
P3DM DATA bytes
container bytes
vertices
position indices
material selectors
selector indices
triangles
components per tier
worst simultaneous resident and active sets
```

The current caution threshold is 3 MiB of total VDP PSRAM consumption for the
application scene, below the nominal 4 MiB available.  Packed bytes alone are
not a literal PSRAM measurement because Pingo currently converts positions and
UV coordinates to float arrays.  Emulator diagnostics and physical hardware
must therefore record free PSRAM before control creation, after shared-resource
binding, and after the maximum resident set converges.  The compiler's compact
budget and the measured VDP allocation are reported separately.

Memory headroom permits conservative geometry.  Passing a memory threshold
does not excuse excessive transformed triangles, object traversal, clipping,
or rasterization.  Frame-time qualification remains tiered by camera altitude,
attitude, and worst visible relief.

## Determinism and failure policy

A build from identical inputs and profile must reproduce byte-identical P3DM
components, seam ledger, analysis report, and Blender review artifact source.
Parallel execution may change scheduling but not reduction order, candidate
ties, triangulation, file order, or checksums.

Nodata never becomes an implicit zero elevation.  The profile chooses one of:
rejecting the component, clipping coverage, or using one documented fill
method whose support lies entirely in valid pinned samples.  Observer rays
crossing absent source coverage are marked incomplete and excluded only under
an explicit reported boundary policy.

Failure to satisfy an error threshold, seam invariant, topology invariant,
quantization bound, or safety ceiling aborts the affected corpus build.  The
compiler does not quietly spend fewer vertices, drop a difficult categorical
boundary, or substitute a human-authored approximation.

## Acceptance evidence

The host build report for each profile must include:

1. complete input and profile hashes;
2. observer, altitude, and azimuth-domain cardinalities;
3. maximum and percentile ordinary projected error by tier;
4. maximum and percentile horizon-envelope error by tier;
5. the source location and canonical key of every worst case;
6. complete same-LOD, mixed-LOD, and three-cell-corner seam results;
7. LOD-switch projected-error and hysteresis bounds;
8. exact mesh, component, packed-byte, and simultaneous-residency budgets; and
9. deterministic rebuild hashes.

Every regional terrain set also requires a Blender file containing the full
LOD corpus or a faithful deterministic overview that preserves every component
identity, footprint, tier, seam class, and material class.  Review collections
must allow individual tiers, transition meshes, protected horizon samples, and
reported worst cases to be inspected independently.

Emulator and physical-hardware evidence must then measure convergence,
position-driven switching, object/triangle traversal, frame time, depth
behavior, and actual PSRAM.  Human review may use recognizable Bay Area
features to judge whether the mathematical bounds correspond to a convincing
scene.  Such witnesses do not alter the generated result and cannot waive a
failed numerical or seam invariant.

## Academic lineage and project-specific synthesis

This contract is deliberately mathematical, but it is not being invented in a
vacuum.  The following primary literature supplies useful precedents:

1. Lindstrom et al., *Real-Time, Continuous Level of Detail Rendering of
   Height Fields*, SIGGRAPH 1996, DOI 10.1145/237170.237217, bounds height-field
   simplification using projected image error and a screen-space threshold.
   The `e_px` criterion above adopts that central principle, although Pingo
   compiles discrete offline tiers rather than continuously adapting one mesh
   every frame.  [Georgia Tech record and manuscript][lindstrom-1996]
2. Duchaineau et al., *ROAMing Terrain: Real-time Optimally Adapting Meshes*,
   IEEE Visualization 1997, DOI 10.1109/VISUAL.1997.663860, establishes a
   bounded-error adaptive terrain hierarchy with frame-to-frame coherence.
   It is precedent for error-driven refinement and constrained neighboring
   levels, not a requirement that Pingo implement ROAM at runtime.
   [Authoritative OSTI manuscript][roam-1997]
3. Stewart, *Fast Horizon Computation at All Points of a Terrain with
   Visibility and Shading Applications*, IEEE TVCG 4(1), 1998, pp. 82-93,
   computes terrain skylines from elevation data and explicitly identifies
   flight-simulation visibility as an application.  It grounds the use of a
   distance-ordered angular envelope; this contract specializes that idea to a
   finite, pinned observer-and-azimuth analysis domain.
   [Author publication page][stewart-1998]
4. Pajarola, *Large Scale Terrain Visualization Using the Restricted Quadtree
   Triangulation*, IEEE Visualization 1998, pp. 19-26, provides exact error
   approximation and a restricted hierarchical triangulation for large
   terrain databases.  Its quadtree topology is not suitable as Pingo's
   hex-cell identity, but its restriction of adjacent refinement states is an
   important crack-control precedent.  [University of Zurich record][pajarola-1998]
5. Lindstrom and Pascucci, *Terrain Simplification Simplified: A General
   Framework for View-Dependent Out-of-Core Visualization*, IEEE TVCG 8(3),
   2002, pp. 239-254, combines view-dependent refinement, error metrics, and
   out-of-core terrain access.  Pingo separates those concerns differently:
   the host compiler produces fixed tiers, while the universal manager streams
   whole components.  [LLNL manuscript][lindstrom-pascucci-2002]
6. Garland and Heckbert, *Surface Simplification Using Quadric Error Metrics*,
   SIGGRAPH 1997, pp. 209-216, is the relevant general-mesh simplification
   baseline.  Ordinary geometric error alone does not protect a terrain
   skyline, categorical boundary, or independently encoded seam, so this
   design does not adopt unconstrained quadric decimation as its governing
   algorithm.  [Carnegie Mellon project page][garland-heckbert-1997]

No one cited method directly specifies this complete Pingo contract.  The
deterministic observer lattice, maximum angular-envelope discrepancy,
categorical constraints, canonical rational seam ledger, post-P3DM exact seam
proof, and offline fixed-tier/runtime-component split are a project-specific
synthesis.  The citations support the underlying error, horizon, hierarchy,
and simplification concepts; the combined algorithm and its acceptance
obligations must still be implemented and qualified here.

[lindstrom-1996]: https://repository.gatech.edu/entities/publication/39f1dca8-ec3c-46d4-a26c-d6ceeab70a3a
[roam-1997]: https://www.osti.gov/servlets/purl/632827
[stewart-1998]: https://research.cs.queensu.ca/home/jstewart/papers/tvcg97.html
[pajarola-1998]: https://www.ifi.uzh.ch/en/vmml/publications/vis-98.html
[lindstrom-pascucci-2002]: https://computing.llnl.gov/sites/default/files/Terrain%20Simplification%20Simplified.pdf
[garland-heckbert-1997]: https://www.cs.cmu.edu/~garland/quadrics/

## Relationship to existing contracts

`docs/hexagonal-terrain-cells.md` remains authoritative for L0 hex identity,
exact basis vectors, straight six-edge boundaries, same-LOD canonical samples,
stable slots, and manager/provider ownership.  This document supplies the
previously missing mathematical policy for simplifying larger-distance
components and proving mixed-LOD transitions.

`docs/regional-lod-bundles.md` remains implementation evidence for selectable
multi-record packaging, wide object placement, projection range, bounded
loading, and one live rectangular fixed-west transition.  Its named regional
features are review witnesses only.  A hex-native hierarchy must use the
observer and error analysis specified here rather than a hand-authored
importance list.

`docs/terrain-manager-runtime.md` remains authoritative for lifecycle,
residency, render-idle publication, retry state, rebasing, and teardown.  The
manager receives desired components and numerical priorities from a provider;
it does not calculate horizon envelopes or know why a component is important.

The unfinished implementation and qualification work remains tracked only by
R1 and J1 in `docs/todo.md`.
