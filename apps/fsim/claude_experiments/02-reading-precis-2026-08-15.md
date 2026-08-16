# Reading précis — feature-aware terrain triangulation literature

Date: 2026-08-15. Author: Claude. Status: awaiting Author review.

Companion to
[`01-initial-assessment-2026-08-15.md`](01-initial-assessment-2026-08-15.md).
Each section states which source was actually read. All papers except
Douglas–Peucker were read in full (PDF or full-text scan); Douglas–Peucker
was available only as the publisher's abstract, with algorithm details from
general knowledge and labeled as such. The project context assumed
throughout: an offline, deterministic Python terrain builder sampling a 10 m
USGS DEM plus NLCD land cover; three flat-shaded categorical material
classes with one material per face; integer Pingo-domain coordinates; hex
cells with byte-identical shared edges; two fixed LOD levels; hard per-cell
triangle budgets; no runtime remeshing on the eZ80.

## 1. Douglas & Peucker 1973 — line reduction

Citation: Douglas, D. H. and Peucker, T. K., "Algorithms for the reduction
of the number of points required to represent a digitized line or its
caricature," *Cartographica* 10(2), 1973. Source read: publisher's abstract
only (live DOI page 403s; archived capture); algorithm details are general
knowledge.

1. Recursive anchor–floater method: connect the endpoints, find the interior
   point of maximum perpendicular distance, retain it and recurse if it
   exceeds tolerance ε, else drop all interior points.
2. ε bounds the maximum deviation of the simplified line from the source;
   output vertices are always a subset of input vertices.
3. Worst case O(n²), typically O(n log n) (O(n log n) worst case with the
   Hershberger–Snoeyink refinement).
4. Weaknesses: at coarse tolerances it latches onto extreme points and
   produces spiky, angular caricatures; no guarantee against
   self-intersection of the result.

Relevance: ε is a useful *hard cap* on boundary deviation, but the
spike-retaining behavior at the aggressive tolerances tiny per-cell meshes
need, and the absence of a global point ranking, make it a poorer primary
simplifier here than Visvalingam–Whyatt. Candidate role: a final ε-check on
VW output rather than the driver.

## 2. Visvalingam & Whyatt 1993 — effective-area elimination

Citation: Visvalingam, M. and Whyatt, J. D., "Line generalisation by
repeated elimination of points," *Cartographic Journal* 30(1), 1993. Source
read: full 16-page text of the discussion-paper version (CISRG Discussion
Paper 10, University of Hull, 1992) via an archived repository capture.

1. Each interior point gets an *effective area*: the area of the triangle it
   forms with its two current neighbors — the areal displacement caused by
   deleting that point alone.
2. Repeatedly eliminate the least-area point from the current
   part-simplified line, recomputing only the two adjoining points' areas;
   record each point with its (monotonically clamped) elimination area.
3. One pass therefore *ranks every point*, yielding a continuous scale of
   generalisations filterable afterward at any level.
4. Because elimination is measured against the current line, whole small
   features (creeks, headlands, estuaries) are removed cleanly from smallest
   to largest, where Douglas–Peucker latches onto spikes and digitising
   noise. The authors match a manual 1:625,000 coastline generalisation with
   77 of 1583 points, a regime where Douglas–Peucker fails badly.

Relevance: the natural fit for globally simplifying class-boundary polylines
before hexagonal cutting. The single global ranking is exactly what the
two-LOD requirement wants: compute effective areas once, then cut the same
ranked polyline at a fine threshold for the detailed corpus and a coarse
threshold for the N=1-replacement level, guaranteeing the coarse boundary is
a subset of the fine one — which directly helps seam and LOD-transition
coherence. Deterministic ties need an explicit rule (e.g. lexicographic on
integer coordinates).

## 3. Shewchuk — Triangle, CDT, and Delaunay refinement

Citation: Shewchuk, J. R., "Triangle: Engineering a 2D Quality Mesh
Generator and Delaunay Triangulator," 1996 (read in full), with details
cross-checked against the Triangle web pages; his 2002 "Delaunay Refinement
Algorithms for Triangular Mesh Generation" is the definitive deeper
treatment.

1. Input is a planar straight-line graph (PSLG): vertices plus non-crossing
   segments. A *constrained Delaunay triangulation* (CDT) forces every
   segment to appear as an edge, inserts no new vertices, and exempts
   constrained edges from the empty-circle test — they may never be flipped.
   (A *conforming* Delaunay triangulation instead splits segments with
   Steiner midpoints until true Delaunay everywhere.)
2. Holes and internal regions are handled by a "triangle-eating virus" flood
   fill halted by segments — a unified hole/region mechanism.
3. Ruppert's refinement inserts circumcenters of poor-quality or oversized
   triangles, giving segments priority: a segment whose diametral circle
   contains a point is *encroached* and is split at its midpoint instead.
   Termination is proven for minimum-angle bounds up to 20.7° (practice:
   ~33.8°), but small angles *in the input* (where segments meet) can defeat
   any bound; concentric-shell segment splitting mitigates down to roughly
   5° input angles.
4. Density is user-controllable by per-region maximum-area constraints;
   refinement output depends on queue ordering (the paper shows 290 vs 450
   triangles from ordering alone). Robustness rests on exact orientation and
   incircle predicates.

Relevance: the pipeline's stage-2 model is exactly Triangle's model —
simplified class boundaries plus hex borders as PSLG segments; constrained
edges guarantee flips never destroy cell walls or coastlines. Three
practical conclusions: (a) skip Ruppert quality refinement — minimum-angle
quality matters for FEM conditioning, not flat-shaded terrain, and it has
failure modes precisely where simplified polygons meet hex edges at small
angles, plus unpredictable counts; enforce budgets by ranked
elevation-error insertion instead; (b) queue-ordering sensitivity is a
determinism warning: fix insertion order explicitly; (c) Triangle's license
is non-free and this repo prefers self-contained Python — but with integer
input coordinates, exact predicates are trivial with Python unbounded ints,
so a deterministic pure-Python incremental CDT (Delaunay insertion, segment
insertion by cavity retriangulation, virus-style region fill) is entirely
implementable and byte-reproducible.

## 4. Garland & Heckbert 1995 — greedy insertion for height fields

Citation: Garland, M. and Heckbert, P. S., "Fast Polygonal Approximation of
Terrains and Height Fields," CMU-CS-95-181, 1995. Source read: full report
PDF.

1. Greedy insertion: start from two triangles over the corners; repeatedly
   insert the input sample worst-approximated by the current piecewise-linear
   surface; retriangulate incrementally. Recommended variant (Algorithm III):
   each triangle caches one *candidate* (its worst interior sample),
   candidates live in a heap keyed on error, each pass pops the max, inserts
   it with incremental Delaunay (spoke edges + circle-test flips), and
   rescans only triangles incident on the new vertex. Expected
   O((m+n) log m).
2. Error metric: after comparing curvature, lookahead, and product measures,
   they recommend the simple local vertical error
   |H(p) − interpolated(p)| — simplest and most accurate in their tests. For
   accumulation, a hybrid (max within a triangle, sum across triangles)
   scored best; RMS is preferred for *reporting*.
3. Data-dependent triangulation (Algorithm IV, fit-driven edge swaps) gives
   only ~12% lower RMS on natural terrain at 3–4× the runtime and produces
   slivers; they recommend Delaunay when speed or shape matters.
4. Practical guidance: terminate on vertex budget or error tolerance;
   sequential insertion beats batch insertion (batch causes snowballing
   over-subdivision); greedy is short-sighted at step discontinuities (the
   "cliff problem") and outlier-sensitive on noisy data. Their explicit
   suggestion for critical features: preinsert them, or replace the
   triangulator with a *constrained* Delaunay triangulator so ridge lines,
   roads, and boundaries are preinserted and left untouched by refinement.

Relevance: this is stage 3 of the pipeline, and the paper itself endorses
the composition we plan — CDT with locked boundaries, then greedy insertion
where flips simply never cross constrained edges; the candidate/heap
machinery is unchanged. Vertical L∞ per sample is right for a smooth 10 m
DEM (outlier sensitivity is moot). Hard per-cell caps are exactly their
vertex-budget termination (each insertion adds ~2 triangles). Avoid
Algorithm IV: aggressive flipping conflicts with immutable constraints and
its slivers read badly flat-shaded. Determinism care point: break
equal-error ties explicitly (lexicographic on lattice coordinates) and use
exact integer predicates so sample-to-triangle assignment is reproducible.

## 5. Garland & Heckbert 1998 — quadrics with color and boundaries

Citation: Garland, M. and Heckbert, P. S., "Simplifying Surfaces with Color
and Texture using Quadric Error Metrics," IEEE Visualization 1998. Source
read: full paper PDF.

1. Extends QEM edge-collapse simplification (heap of edges keyed by quadric
   cost; contract cheapest; quadrics add componentwise; new vertex at an
   endpoint, "subset placement," or at the quadric optimum −A⁻¹b).
2. The generalization treats each vertex as a point in Rⁿ (position plus
   linearly interpolated attributes: color, texture, normals); each triangle
   defines a 2-plane in Rⁿ and the quadric measures squared distance to it,
   with off-diagonal terms correlating position and attributes. Quadric size
   grows quadratically in n (10 coefficients for geometry, 28 for
   geometry+color).
3. Boundaries and attribute borders are handled by *constraint planes*:
   each boundary edge generates a perpendicular plane converted to a
   heavily weighted quadric added to its endpoints — explicitly including
   their discrete-palette map-coloring example, i.e. edges separating faces
   of different discrete colors. Works when boundaries are sparse; degrades
   if constraints are dense.
4. Results: 1M faces → 20k in ~176 s (1998 hardware); mesh edges align with
   color contours and triangulation densifies near color boundaries.

Relevance: the discrete-attribute case is exactly this project's situation,
and with three classes the sparse-boundary assumption holds. What does
*not* transfer is the entire n-dimensional attribute quadric — categorical
per-face materials are not interpolable, so vertices stay in R³. Simplest
faithful adaptation: plain 3-D QEM; mark inter-class edges and hex-perimeter
edges constrained; replace soft penalty quadrics with hard rules (disallow
collapses that move, remove, or topologically change a class boundary;
boundary vertices collapse only along their own polyline via subset
placement). Prefer subset placement everywhere: soft penalties and −A⁻¹b
optimal placement cannot guarantee bit-exact seams; subset placement plus a
deterministic shared-edge rule can, and it avoids matrix-degeneracy
handling entirely.

## 6. Hoppe 1996 — Progressive Meshes

Citation: Hoppe, H., "Progressive Meshes," SIGGRAPH 1996. Source read: full
paper PDF.

1. Any mesh is stored as a coarse base mesh plus a stream of invertible
   *vertex-split* records — the inverses of the edge collapses used to
   simplify it. Applying a prefix of the stream reconstructs any
   intermediate resolution losslessly; discrete LODs are snapshots of this
   continuous family.
2. The collapse sequence is chosen by a priority queue on an energy
   E = E_dist (sampled squared surface distance) + E_spring (regularizer) +
   E_scalar (attribute deviation) + E_disc (discontinuity-curve error), with
   the unified vertex position optimized among vₛ, vₜ, midpoint, and
   dihedral-flip collapses rejected.
3. Discontinuity machinery: scalar attributes live on *corners* so fields
   can be discontinuous across edges; an edge is *sharp* if it is a
   boundary, its two faces differ in discrete attributes (materials!), or
   corner attributes differ. Sharp edges form discontinuity curves; local
   tests disallow (or ad-hoc-penalize) collapses that would change their
   topology, and E_disc keeps their geometry accurate.
4. Also defines geomorphs (smooth LOD transitions), progressive
   transmission, and selective refinement — all runtime features.
5. Limitations: slow construction, no guaranteed error bounds, strict
   discontinuity preservation curtails simplification.

Relevance: runtime PM machinery is out of scope on the eZ80. What transfers
is the offline recipe for deriving the coarse LOD *from* the fine mesh
instead of remeshing independently: priority-queue edge collapse, stop at
the coarse face budget, with inter-class edges marked sharp and
boundary-topology-changing collapses forbidden — keeping material borders
stable across the LOD switch, the artifact players actually notice. With
flat-shaded categorical faces, E_scalar drops out and the energy reduces to
distance + spring + discontinuity — a small, implementable core. Note the
tension with the current strict N=1 decimation identity: PM-style collapse
gives a better coarse mesh but abandons the fixed vertex-subset pattern, so
coarse/fine seam rules must come from the shared global boundary ranking
(§2) rather than lattice identity.

## 7. Duchaineau et al. 1997 — ROAM

Citation: Duchaineau, M. et al., "ROAMing Terrain: Real-time Optimally
Adapting Meshes," IEEE Visualization 1997. Source read: full 6-page LLNL
preprint via an archived capture.

1. A preprocessed right-isosceles triangle bintree (split at the base-edge
   midpoint) structurally avoids cracks, T-vertices, and slivers; runtime
   split/merge operations on "diamonds" add or remove one vertex at a time,
   with forced split chains keeping neighbors within one level.
2. Dual split/merge priority queues start each frame from the previous
   frame's mesh and apply minimal work (frame-to-frame coherence); work is
   proportional to triangle *changes*.
3. Priorities come from nested monotonic error bounds ("wedgies": per-
   triangle world-space thickness volumes built bottom-up) projected to
   guaranteed screen-space distortion each frame; monotonicity makes the
   greedy optimizer provably minimize maximum error and lets ROAM target an
   exact triangle count directly.
4. Motivating application is flight simulation, including consistent
   line-of-sight queries; optimization is progressive and interruptible for
   strict frame rates.

Relevance: per the brief, not to be implemented — the runtime split/merge
engine is exactly what the eZ80 cannot do, and our CDT meshes are irregular
rather than bintree-structured anyway. Two ideas survive offline: (a) the
forced-split discipline is the clean mental model for crack-free
transitions at cell boundaries (never let adjacent cells disagree about a
shared-edge vertex); (b) nested monotonic error bounds computed bottom-up
would let the builder *certify* a maximum world-space deviation per cell
and per LOD, and target exact triangle counts — matching our hard budget
model better than tolerance-hunting.

## 8. Synthesis — what the literature says about our pipeline

1. The proposed pipeline is well-founded and each stage has a canonical
   algorithm: VW effective-area ranking for global boundary simplification
   (with an optional DP ε-check), pure-Python integer CDT for locking
   boundaries and hex borders, and Garland–Heckbert Algorithm III greedy
   insertion (constraint-respecting) for elevation refinement under vertical
   L∞ error with per-cell vertex budgets.
2. The coarse LOD should be derived from the fine mesh by PM/QEM-style edge
   collapse with hard boundary constraints and subset placement — not by
   independent remeshing and not by the current N=1 lattice decimation,
   which cannot survive feature-adaptive fine meshes.
3. Determinism and byte-identical seams are achievable but only by design:
   integer coordinates with exact predicates, explicit tie-breaking in every
   priority queue, subset placement only, boundaries simplified once
   globally (VW ranking) before cutting, and hex-edge geometry derived by a
   rule both neighbors compute identically.
4. Quality (minimum-angle) refinement, data-dependent triangulation, soft
   penalty quadrics, optimal vertex placement, and all runtime adaptivity
   (PM vsplits, geomorphs, ROAM split/merge) are explicitly *not* wanted:
   each either breaks determinism, breaks constraints, breaks budgets, or
   exceeds the eZ80.
5. Open questions for design review: how the two LOD boundary thresholds
   relate to ring geometry; whether coarse cells remain per-hex or per
   hierarchy group; how per-cell budgets are allocated globally (uniform vs
   error-proportional); and how P3DM per-cell size limits bound the worst
   coastal cell.
