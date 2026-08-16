# Initial assessment — terrain appearance improvement

Date: 2026-08-15. Author: Claude. Status: awaiting Author review; no
application code changed.

This document freezes two things so we can track the state of the art as the
effort proceeds: (A) the current state of the active FSIM application and its
terrain generation, and (B) the proposed feature-aware triangulation pipeline
supplied as the working brief.

## A. Current state of the active application

1. The sole active FSIM application is `application/`: an AgonDev C policy
   module combined with the proven eZ80 assembly runtime. Assembly owns
   fixed-point math, terrain loading, transforms, MOS/VDP communication,
   staging, and atomic publication. C owns only bounded coverage-group
   selection (`fsim_regular_policy_select`, ≤38 three-byte descriptors,
   revalidated by assembly). `C_GUARDED` is canonical and permanently falls
   back to the accepted assembly selector on any fault.
2. The universal transactional terrain residency manager
   (`application/runtime/ez80/terrain-manager.inc`) is topology-neutral,
   driven by provider hooks, and supports coverage-group staging with atomic
   group commit. The regular-LOD survey fixture reserves all 255 manager
   slots: detailed cells own slots 0..90; the hierarchy plan dynamically owns
   91..254 (max 159 coarse leaves, five protected replacement slots, proven
   250-object maximum).
3. Terrain is generated offline and deterministically by Python
   (`application/src/pingo_terrain/`, `application/scripts/`) from
   checksum-pinned USGS inputs (3DEP 10 m elevation, Annual NLCD land cover)
   named by `data/manifests/bay-area-2026-08-02.json`. `make client` rebuilds
   the client; `make soup-to-nuts` also regenerates the corpus; `make test`
   runs the focused regressions.
4. The exact `C_GUARDED` image was interactively exercised and accepted in
   the emulator on 2026-08-15. Open TODO items: C1 (complete application
   behavior across remaining regional boundaries and longer routes), H1
   (physical-hardware qualification), D1 (single documented deployment
   entry). Optimization is deliberately deferred until behavior is complete.

## B. Current terrain generation, as it bears on appearance

1. Horizontal topology is a lattice of exact-count flat-top hexagonal cells
   in the integer Pingo domain (one sixteenth of a metre), so independently
   generated neighboring cells reuse byte-identical shared edge and corner
   keys (`hex_terrain.py`).
2. The detailed corpus is a uniform N=5 triangular lattice inside every hex
   cell. The first (and only) distance level is a strict N=1 decimation: the
   N=5 centre plus six N=5 corners, centre joined to each boundary side, each
   coarse material derived from the 25 fine triangles in that sector
   (`regular_lod.py`). Coarse reuse is grouped by the aligned
   `8x4 -> 4x2 -> 2x1 -> 1x1` hierarchy; rings 0..5 stay N=5, rings 6..30
   have exactly one N=1 owner.
3. Presentation is flat-shaded solid Agon base colors over a small
   categorical material set (three classes in the survey presentation:
   green/gray/blue), illumination disabled, far plane 65,535.
4. Consequence: triangle density is uniform per LOD and fixed by the hex-cell
   dimensions. It is completely insensitive to where the visual information
   actually is. Featureless interiors (flat water, uniform vegetation) spend
   the same triangle budget as coastline, shoreline, urban boundaries, and
   relief — so boundaries alias coarsely while flat interiors waste budget.

## C. The problem statement

Improve how the terrain looks. For a three-color, flat-shaded renderer the
visible information is almost entirely (1) the categorical class boundaries
(coast, lake, city/green edges) and (2) the silhouette/relief of the height
field. The mesh should therefore budget triangles by two independent error
measures rather than by cell geometry:

1. Classification/boundary error — how far the drawn green/gray/blue
   boundary departs from the source boundary.
2. Elevation error — how far a triangle departs vertically from the source
   height field.

## D. Proposed pipeline (working brief, 2026-08-15)

The brief proposes feature-aware adaptive triangulation of a classified
height field:

1. Treat color boundaries as geometry. Extract green/gray/blue class
   boundaries as polylines; simplify to a bounded geometric tolerance
   (Douglas–Peucker bounds positional deviation; Visvalingam–Whyatt removes
   points by effective area and tends to look more natural on coastlines).
2. Constrained Delaunay triangulation. Feed simplified coastlines, lake
   outlines, urban boundaries, and hex borders into a CDT as a planar
   straight-line graph; constrained edges cannot be crossed or removed, so
   class boundaries are exact in the mesh while interiors stay very sparse
   (a lake shoreline can cost twenty vertices while the surrounding uniform
   region costs almost none).
3. Elevation-error-driven interior refinement. After boundaries are locked,
   insert interior vertices only where the flat-triangle approximation of
   the height field exceeds a vertical error threshold; repeat to
   convergence (Garland–Heckbert greedy insertion / quadric-error family).
4. Simplification cost model, specialized for three categorical colors:
   collapsing an ordinary interior vertex costs its elevation error;
   collapsing a vertex that destroys a class boundary costs infinity — with
   the boundary polyline itself offered at several predefined simplification
   levels.
5. Only after a feature-sensitive high-resolution mesh exists does
   distance-dependent selection (Progressive Meshes, view-dependent
   refinement, ROAM, QEM hierarchies) become relevant. ROAM is explicitly
   not to be implemented yet.
6. Full pipeline: classified source map → shared boundary polylines →
   Visvalingam/Douglas–Peucker simplification → constrained Delaunay
   triangulation → elevation-error-driven interior refinement → cut into
   hex chunks.
7. Critical seam rule: simplify shared coast/city/lake boundaries globally,
   before chopping into hexes; otherwise adjoining hexes independently
   simplify the same boundary differently and produce seam discontinuities.
8. All expensive work happens in the PC-side terrain-building tool, not on
   the eZ80.

## E. Constraints any implementation must respect (Claude's additions)

1. Determinism and provenance: corpus builds must stay offline,
   deterministic, and checksum-qualified; integer Pingo-domain coordinates
   are what currently guarantee byte-identical shared vertices between
   independently generated cells. Adaptive triangulation must preserve an
   equivalent seam guarantee — the global-boundary-first rule (D.7) plus
   hex borders as constrained edges is the intended mechanism, and shared
   hex-edge vertices must still be derived identically on both sides.
3. Runtime budget: the manager plan is bounded (255 slots, proven 250-object
   maximum, ≤159 coarse leaves); per-cell triangle/vertex counts feed P3DM
   records and VDP load/render cost, so adaptive cells need explicit
   per-cell and per-plan budget caps rather than only a global error
   tolerance.
4. Contract stability: the eZ80 manager/provider contract, the C policy ABI,
   and the P3DM/AGNB container format should not need to change for a
   mesh-content improvement; the LOD grouping (which cells own which rings)
   may, and that would touch `regular_lod.py`/`regular_lod_runtime.py` and
   the generated include tables together.
5. Variable per-cell geometry likely breaks the current strict N=1
   decimation identity between LOD levels; the coarse level would need its
   own boundary-preserving simplification target instead.
6. Emulator-visible results remain behind the explicit human validation
   gate; nothing lands without Author acceptance.

## F. Immediate next step

Read the assigned references and produce
[`02-reading-precis-2026-08-15.md`](02-reading-precis-2026-08-15.md), then
halt for Author review of both documents before any design or code work.
