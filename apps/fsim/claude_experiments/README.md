# claude_experiments

Claude's working area for the terrain-appearance improvement effort begun
2026-08-15. Nothing here is part of the active application build under
[`../application/`](../application/README.md); documents graduate into the
application tree (or `deprecated/`) only through explicit review.

## Index

1. [`01-initial-assessment-2026-08-15.md`](01-initial-assessment-2026-08-15.md)
   — current state of the active application and of terrain generation, the
   appearance problem, and the proposed feature-aware triangulation pipeline.
2. [`02-reading-precis-2026-08-15.md`](02-reading-precis-2026-08-15.md)
   — précis of the assigned literature (Douglas–Peucker,
   Visvalingam–Whyatt, Delaunay refinement, Garland–Heckbert, Hoppe, ROAM)
   with project-specific relevance notes.
3. [`03-design-decisions-2026-08-15.md`](03-design-decisions-2026-08-15.md)
   — provisional design decisions D1–D10 accepted from the stage-1
   Blender reviews, and the open questions for the distance-mesh stage.
4. [`pipeline/`](pipeline/README.md) — stage-1 implementation: the
   feature-aware full-detail mesh builder and Blender review script.
   Outputs land under ignored `build/full-detail/`.
