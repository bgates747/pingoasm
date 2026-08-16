# Design decisions — feature-aware terrain mesh (stage 1)

Date: 2026-08-15. Status: provisional — accepted by the Author from Blender
review of the full-corpus mesh; hardware/emulator qualification has not
occurred and nothing here binds the active application yet. Context and
sources: [`01-initial-assessment-2026-08-15.md`](01-initial-assessment-2026-08-15.md)
and [`02-reading-precis-2026-08-15.md`](02-reading-precis-2026-08-15.md).
Implementation: [`pipeline/`](pipeline/README.md).

## D1. Priority order: class demarcations over vertical relief

The visual identity of the three-color flat-shaded world is carried by the
green/developed/water boundary shapes (coastlines, lake edges, urban
outlines) and by a handful of landmark silhouettes; relief detail beyond
that is expendable. Decision: boundaries are hard CDT constraints that no
refinement setting can degrade; relief fidelity is a single tunable error
tolerance. Accepted tolerance: **60 m vertical L-infinity** (Author,
2026-08-15, from a 12/30/60 m Blender comparison). Landmark check at 60 m
against the DEM: Tamalpais −3.2 m, Diablo −24.2 m, Grizzly Peak −17.6 m,
Hawk Hill −18.8 m, Pacific Heights −0.7 m — greedy max-error insertion
protects summits automatically, so explicit peak pre-insertion was
considered and **not adopted**.

## D2. Working raster: 30 m, three classes, majority-filtered

One aligned working grid at 30 m (every third 10 m DEM sample; NLCD is 30 m
native) over the full manifest footprint. Classes: NLCD 11 → water;
21–24 → developed; everything else → green; NLCD nodata resolves by DEM
sign (below sea level → water). Two 3×3 majority passes despeckle before
boundary extraction. Considered and rejected for stage 1: full 10 m
working grid (9× cost, no visible benefit at tol 60 through a 320×240
renderer).

## D3. Boundaries extracted and simplified globally, before any cutting

Class-boundary lattice edges are chained junction-to-junction across the
whole corpus and simplified once, so both future LOD levels and all future
hex cells inherit the same authoritative polylines (the seam rule from the
brief). Simplification is **Visvalingam–Whyatt** (effective-area threshold
3 cells², junctions anchored) with closed rings below 12 cells² dropped,
followed by a **Douglas–Peucker deviation floor of 1.5 cells (45 m)**.
The DP pass exists because VW's area threshold permits metre-scale
deviations over kilometre baselines, and those produced kilometre-long,
metres-thin CDT wedges along near-straight boundary runs — too thin to
contain any interior refinement sample and hostile to the fixed-point
rasterizer. Bounding deviation removes them at the source; boundary
movement stays within ~1.5 source pixels. Chain crossings introduced by
simplification are repaired by re-adding original points (staircase
originals cannot cross, so repair converges; 3 splits were needed on the
full corpus).

## D4. Pure-Python exact-integer constrained Delaunay triangulation

All triangulation coordinates are integers in **doubled working-grid
units**: corner-lattice points are even, cell centers odd. Orientation and
in-circle predicates evaluate exactly in Python unbounded integers — no
epsilon tuning, deterministic output, and (D6) exact on-segment bisection
of constrained edges. Triangle ids are append-only snapshots (any change
kills and reallocates), which lets the refinement heaps use ids as
immutable candidates. Considered and rejected: Shewchuk's Triangle
(non-free license, external dependency, queue-order nondeterminism) and
Ruppert quality refinement (min-angle guarantees serve FEM, not flat
shading, and fail precisely at small input angles where simplified
polygons meet cell borders; budgets become unpredictable).

## D5. Elevation refinement: greedy vertical L-infinity, land only

Garland–Heckbert Algorithm III: per-triangle worst land sample in a
max-heap; insert until tolerance or budget. Water samples are excluded so
bathymetry cannot attract triangles: water presents flat, with vertex
elevations clamped to max(DEM, 0). Accepted side effects: sub-sea-level
land (Delta islands, Alviso) flattens to 0; lakes keep their DEM surface
including mild relief. All refinement points are cell centers strictly
interior to their triangle, so refinement can never move a boundary.

## D6. Shape refinement: 1,200 m max-edge cap via exact edge bisection

Constrained polygons with empty interiors (bays) otherwise triangulate as
boundary-vertex fans — enormous, sliver-thin triangles that are the worst
case for a fixed-point scanline rasterizer (edge crawl, clipping
amplification, poor span efficiency) and that would cross many hex cells.
Decision: any triangle whose longest edge exceeds **1,200 m** (~2 hex
pitches of 480–550 m, within the 1,024 m half-extent P3DM model window)
has that edge split at the exactly-collinear integer lattice point nearest
its midpoint — legal even on constrained edges because the point lies
exactly on the segment, so the boundary geometry is unchanged. Interior
nearest-centroid samples are the fallback when an edge admits no interior
lattice point. Elevation repairs take priority over shape repairs.
Residue accepted for now: 39 of 150k triangles remain long-and-thin —
wedges pinched between two constrained boundaries converging at a
junction, unfixable without moving a boundary; any such boundary-moving
remedy is an Author decision deferred until hardware evidence demands it.

## D7. Materials: region flood fill, not per-triangle sampling

Triangles are labeled by flood fill across unconstrained edges; each
region takes the area-weighted majority class of its triangle-centroid
samples. This guarantees color changes exactly and only at constrained
boundary polylines — no speckle where simplification moved a boundary off
the raster's exact line.

## D8. Result accepted as the full-detail reference

`relief-60m-capped` (tol 60, cap 1,200 m, DP 1.5): **150,210 triangles /
75,432 vertices** for the full 102.6 × 128.5 km corpus. Per-hex-pitch-cell
distribution: median 2, mean 3.7, p95 11, p99 17, max 108 triangles —
uniform cost across terrain types, with residual variance following
boundary intricacy (North Bay sloughs), not relief. Calibration: the
active N=5 corpus spends a fixed 150 triangles per hex cell, so the
adaptive mesh's worst cell is already below the proven per-cell load.

## D9. Environment and determinism posture

The experiment runs on system python3 + numpy + cs2cs (the application's
own regional builder already shells out to cs2cs); the application `.venv`
is untouched and the application's GeoTIFF parser is imported read-only.
Determinism: exact integer predicates, sequence-numbered heaps, explicit
tie-breaking (first-index argmax/argmin, insertion order fixed by chain
order). Same-input/same-machine reproducibility is expected but has not
been qualified; a promoted implementation must decide whether to become
dependency-free (pure-Python rasters) or to pin numpy/PROJ identities in
the manifest chain.

## D10. Open questions for the next stage (distance meshes, hex cutting)

1. Derive the coarse LOD from this fine mesh by boundary-constrained edge
   collapse (PM/QEM, subset placement only), or re-run this pipeline at
   coarser knobs (higher tol, higher VW/DP, larger cap)? The re-run option
   is simpler and reuses one code path; the collapse option guarantees the
   coarse boundary is a subset of the fine one. The VW ranking already
   gives subset boundaries if both LODs cut the same ranked polylines at
   different thresholds — that may make re-running sufficient.
2. Hex cutting: cell borders become constraint chains in the same CDT
   machinery; shared-edge vertices must be derived identically for both
   neighbors. Skirts, the ±1,024 m model window, and P3DM vertex/triangle
   record limits need to bound the worst cell (currently 108 triangles —
   within limits).
3. Whether the eZ80 provider contract needs any change at all, or the new
   corpus is purely a generator-side replacement (goal: the latter).
4. LOD switch presentation: whether coarse/fine boundary agreement from
   the shared VW ranking is visually sufficient at ring 5→6, or whether
   transition cells need explicit stitching.
