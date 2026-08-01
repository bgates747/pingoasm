# Pingo renderer optimization roadmap and dispositions

Status: historical technical roadmap, reconciled through Pingo firmware commit
`6c24691` and `pingoasm` commit `a6b0b3b` on 2026-07-31. The filename is
retained to avoid breaking historical references. `docs/todo.md` is the sole
authoritative unfinished-work queue; a deferred disposition below does not
authorize work.

This is the controlled evolutionary path from the last known-working renderer
to measured optimizations. It is deliberately separate from the general
project TODO so experimental branches, rejected ideas, and performance evidence
remain easy to follow.

## Phase 0: immutable point of departure

0.1 Completed — Tag `agon-vdp` commit `207f87b` as
`working-pre-optimization`.

0.2 Completed — Tag `pingoasm` commit `15ef335` as
`working-pre-optimization`.

0.3 Completed — Preserve the ordinary and diagnostic firmware artifacts outside Git
under `~/Agon/mystuff/pingo-firmware-archive`.

0.4 Completed — Establish five-series hardware attribution baselines for Cube,
EarthIco, and EarthUV.

0.5 Completed — Preserve the visually qualified coordinate, winding, UV, texture, and
one-byte framebuffer behavior as non-negotiable correctness controls.

0.6 Completed — Capture exact-tag ordinary five-series Cube, EarthIco, and EarthUV
results. The existing diagnostic results identify work distribution, but the
earlier ordinary results predate commit `207f87b`; absolute optimization claims
need an ordinary baseline built from the exact tag.

0.7 Completed — Archive fresh ordinary and diagnostic binaries built from the exact
tag under
`~/Agon/mystuff/pingo-firmware-archive/04-working-pre-optimization`.

## Phase 1: experimental discipline and moving-frustum fixture

1.1 Completed — Continue integrated work from the historical `pingo-codex` lineage,
protected by the immutable baseline tag. Accepted renderer work currently
lives on `experiment/hecker-rasterizer`; this item does not prescribe the
eventual combined-Wolf/Pingo branch structure.

1.2 Completed — Use one short-lived `experiment/<subject>` firmware branch for each
independent idea. The first branch is `experiment/frustum-culling`.

1.3 Completed — Add a reusable, profile-driven motion definition to the render-spin
generator. A pose must set absolute translation and absolute rotation so no
firmware-side accumulation can affect repeatability.

1.4 Completed — Add RGBA2222 Cube and EarthUV frustum-sweep fixtures with the identical
motion path. During one revolution each must move toward and away from the
camera and laterally through every viewport edge, producing fully visible,
partially clipped, and wholly offscreen intervals. Cube is the labeled visual
control; EarthUV amplifies per-triangle cost and potential savings.

1.5 Completed — Retain the stationary Cube, EarthIco, and EarthUV fixtures unchanged.
They remain the controls for detecting overhead on ordinary in-frame scenes.

1.6 Completed — Capture and preserve the moving fixture on
`working-pre-optimization` before enabling any culling experiment.

1.7 Completed — Exercise the far clip plane in native tests. The current bridge
projection approaches its nominal far boundary asymptotically, and the signed
16-bit VDU translation range cannot put an ordinary fixture near the declared
2500-unit value. Do not mix a projection repair into this experiment.

1.8 Deferred — Give chained benchmark applications an explicit model/run identity or
add an occurrence selector to the summarizer. The stationary profiles reuse
bitmap IDs, so a combined log must presently be split at its known 220-record
application boundaries before model-specific parsing.

## Phase 2: upstream-style clip-space frustum rejection

2.1 Completed — Verify every clip inequality against our actual projection matrix.
Do not copy upstream's nominal near-plane expression blindly: this renderer's
visible depth interval is clip-space `-w <= z <= 0`, not the conventional
`-w <= z <= w`.

2.2 Completed — Reject a triangle only when all three vertices lie outside the same
clip plane. A triangle crossing a plane must remain eligible for the existing
pipeline; rejection is not clipping.

2.3 Completed — Give frustum rejection its own diagnostic outcome. Do not silently
relabel it as projected-Z, back-face, or viewport rejection. If the serialized
diagnostic schema changes, increment its version and retain parser support for
version 1.

2.4 Completed — Add deterministic native cases for all six planes, exact-boundary
vertices, plane-crossing triangles, negative or zero `w`, and the existing
triangle-partition invariant.

2.5 Completed — Run strict scope checks, ordinary and diagnostic native suites, and
both embedded builds before touching hardware.

2.6 Completed — Hardware-qualify visual behavior with Cube and HeavyTank. The later
expanded 15-fixture hardware chain included HeavyTank and passed; HeavyTank
was subsequently removed only from abbreviated near-plane performance runs
because its smaller projected scale made it an unhelpful raster-pressure case.

2.7 Completed — Compare the baseline and experimental ordinary firmware on the moving
fixture. Use diagnostic firmware separately to explain rejection counts; never
compare diagnostic absolute time with an ordinary baseline.

2.8 Completed — Repeat the stationary Cube, EarthIco, and EarthUV controls. Frustum
tests add per-triangle work when nothing is rejected, so a negative result is
plausible and must be retained.

2.9 Completed — Promote the experiment only if its repeatable moving-scene benefit is
worth any stationary-scene cost. The conservative triangle-level rejection
was retained as a correctness fallback and later complemented by accepted
object-AABB rejection; its stationary overhead remains part of the evidence.

2.10 Completed — Close the proposed out-of-line pointer-helper refinement without
implementation. Later exact-span, clipping, incremental-depth, and object-AABB
work changed the relevant hot path and produced much larger measured gains;
the 2026-07-28 stack-frame observation remains historical evidence, not a
current prerequisite to the already accepted frustum path.

## Phase 3: low-risk invariant work

3.1 Completed — Audit unintended double-precision literal expressions independently.
The illumination expression now uses explicit float literals. Changing the
area reciprocal to `1.0f / (float)area` removed its software-double path but
changed one exact color target, so it was rejected and preserved as
`agon-vdp/docs/experiments/float-area-reciprocal.patch`. Do not silently fold
that numerical change into another optimization.

3.2 Completed — Hoist the constant normalized light vector out of the triangle loop.

3.3 Deferred — Hoist framebuffer half-width, half-height, material state, and other
object-invariant values out of the triangle loop.

3.4 Completed — Evaluate and retain the guarded upstream `vec3Normalize` improvement:
one square root, one reciprocal, and three multiplies instead of three
software divisions. Zero and exact-unit inputs have explicit fast paths.
Native tests and emulator target equivalence pass; hardware qualification
remains part of item 8.2.

3.5 Completed — Cache framebuffer and z-buffer pointers and avoid repeated backend
callback lookup in the fragment loop. Compute and increment a linear pixel
index rather than recalculating `x + y * width`, and quantize depth only once.
The retained implementation caches the z-buffer per object, reuses each
fragment's linear index, fuses depth comparison/write, and writes the default
pixel backend directly.

3.6 Deferred — Normalize integer triangle area and edge signs once so the common
raster loop can use one bitwise-OR coverage test. Account explicitly for the
viewport Y reflection and integer overflow; copying upstream's positive-area
test directly would be wrong.

3.7 Completed — Evaluate and retain a locally derived view/projection composition
outside the triangle loop. It is computed once per object, preserves
model-space lighting, and is covered by a nontrivial sequential-versus-composed
math test and final-target equivalence. Hardware qualification remains part of
item 8.2.

3.8 Completed — Treat each item above as its own A/B experiment. EarthUV is the primary
geometry-pressure fixture; Cube remains the primary raster-pressure and visual
orientation control.

3.9 Completed — Design and implement runtime illumination controls without making the
experimental
unlit build flag part of the public API. The design should provide:

3.9.1 Completed — A runtime-configurable illumination-vector direction (subcommand
43, normalized signed-Q15 components).

3.9.2 Completed — A runtime-configurable illumination intensity, with its numeric
range, clamping behavior, and interaction with the renderer's present
half-Lambert calculation stated explicitly (subcommand 44; byte 127 is unity,
values through 255 deliberately overdrive with saturated output).

3.9.3 Completed — An explicit unlit mode that performs no illumination computation and
writes sampled texture colors at their defined values (subcommand 46).

3.9.4 Completed — Put direction, intensity, ambient, and enable state on the scene;
put the independently required self-illumination override on the mesh, matching
the existing mesh-owned shading policy.

3.9.5 Completed — Stable VDU subcommands 43–48 let applications select these behaviors
without rebuilding firmware. Historical camera-track subcommand 42 remains
reserved and render completion remains subcommand 41.

3.9.6 Completed — Backward-compatible defaults preserve scene lighting, zero ambient,
unity intensity, textured meshes, and inherited illumination.

3.9.7 Completed — The four-panel `lighting-shading` fixture and the mixed-policy
`earth-party-flat` scene cover directional, intensity-adjusted, ambient,
unlit, textured, flat-palette, inherited, and self-illuminated behavior. Both
firmware features passed emulator and physical-hardware review.

3.9.8 Completed — Add a scene-wide ambient floor (subcommand 45). Byte 127 is unity;
the floor combines with the retained half-Lambert response before intensity
and saturated RGBA2222 shading.

3.10 Completed — Add mesh-owned flat-palette shading without a second geometry or OBJ
format. Generated assets select one Agon palette cell per source triangle;
firmware retains the established clip, depth, and raster paths while skipping
perspective texture work for that triangle.

3.11 Completed — Add mesh-owned self-illumination independently of shading mode.
Subcommand 48 defaults to inherited scene light and lets either textured or
flat-palette meshes emit native colors.

## Phase 4: clear and output costs

4.1 Deferred — Measure depth clear, RGBA2222 color clear, and any RGBA8888 expansion
as separate costs before changing them.

4.2 Deferred — Investigate safe wider or platform-appropriate clears without changing
the renderer's one-byte pixel contract.

4.3 Deferred — Evaluate dirty-region or generation-based depth clearing only as a
separate invasive experiment. Account for frames in which the next object
covers less screen area than the previous one.

4.4 Completed — Preserve direct RGBA2222 targets and legacy RGBA8888 compatibility.
Both paths remain covered by native tests and qualified fixtures; future clear
experiments must retain them.

## Phase 5: upstream math changes

5.1 Completed — Diff each upstream vector and matrix change against the original
port-era math retained by this codebase.

5.2 Completed — Separate correctness repairs, API refactors, desktop/SIMD assumptions,
and genuine scalar ESP32 optimizations.

5.3 Completed — Add equivalence and edge-case tests before replacing one routine at a
time.

5.4 Completed — Benchmark math routines in isolation and then measure whole-frame
hardware impact. Upstream desktop percentage claims are hypotheses, not Agon
results. Same-host emulator screening, embedded visual review, and hardware
timing are complete for the accepted tranche.

5.5 Completed — Reject upstream's incompatible `Entity`/callback object-model rewrite,
camera inversion in the renderer, scale-only inverse without a zero guard,
and matrix composition performed inside the triangle loop.

5.6 Completed — Preserve provenance for accepted adaptations and durable evidence for
rejected candidates. The accepted sources are `fb67d951` for normalization
and translation-only inverse, plus a locally derived view/projection
composition inspired by upstream `a0ed0cb`.

## Phase 6: raster-loop evolution

6.1 Completed — Replace four per-sample `fminf`/`fmaxf` calls with a proven equivalent
sampler clamp, then evaluate inlining the RGBA2222 read. Define NaN and endpoint
behavior before changing it. The retained NaN-safe inline clamp and texture
sampler match all 1,447 color/depth states.

6.2 Completed — Supersede the original shared-perspective-reciprocal patch with the
accepted subdivided-affine mapper. The old patch targeted the pre-Hecker
per-fragment path and changed nine color targets. Current boundary recovery
already computes one reciprocal of `1/W` and multiplies both U/W and V/W by it,
but does so only at shared eight-pixel block boundaries and the final tail.
Keep the patch as historical evidence; do not apply it to the current loop.

6.3 Completed — Evaluate a bit-identical packed RGBA2222 lighting lookup and a direct
cached-framebuffer write for the default backend. Keep custom backend behavior
available.

6.4 Completed — Compute triangle-wide X gradients for reciprocal W, U/W, and V/W and
advance them across accepted row spans. The accepted subdivided-affine mapper
recovers perspective-correct block boundaries, shares each boundary, and uses
affine U/V increments within each eight-pixel block. Incremental depth was
stacked separately at firmware commit `2c9acdb`.

6.5 Completed — Verify the accepted span/interpolant path for perspective-correct UVs,
depth ordering, shared-edge coverage, both triangle area signs, final tails,
one-pixel spans, and near-plane workloads before hardware promotion. Any new
fill or interpolation experiment must repeat the applicable gates.

6.6 Completed — Evaluate fixed-point edge and interpolant arithmetic only after the
floating-point reference is qualified. The signed 16.16 texture-span tranche
passed correctness and visual gates but reduced weighted hardware FPS by
10.01%; commit `953ec2b` restored the accepted floating implementation while
preserving the rejected experiment in history.

6.7 Completed — Introduce exact integer scanline bounds as a separate structural
experiment with objective image comparisons. The clean-room span preserves
the existing fill rule across all 1,447 color/depth states and raised weighted
hardware equivalent FPS from 6.49 to 9.12 (+40.59%).

6.8 Completed — Evaluate replacing row-span quotients with fixed-point/rational edge
walking. The clean-room candidate was exact but slower on ESP32 and was
rejected. Full design and evidence remain in
`~/Agon/mystuff/agon-vdp/docs/pingo-rasterizer-experiment-2026-07-29.md`.

6.9 Deferred — Revisit tiling and top-left ownership only as separate experiments.
Hecker-style attribute gradients are complete under item 6.4. Do not mix a
fill-rule change with another interpolation optimization.

## Phase 7: geometry reuse and scene-level rejection

7.1 Deferred — Measure a transformed-vertex cache for indexed meshes so EarthUV does
not transform the same source vertex once per triangle corner.

7.2 Deferred — Account explicitly for PSRAM/internal-RAM cost, cache invalidation, and
object/camera/scene pose changes.

7.3 Deferred — Evaluate precomputed or transformed normals separately from position
caching.

7.4 Completed — Add conservative object-level bounds before considering more
per-triangle work for large multi-object scenes. Cached finite mesh AABBs,
eight-corner transformed common-plane rejection, fail-open invalidation, schema
3 diagnostics, exact emulator hashes, and matched hardware runs were accepted
at firmware commit `cc7aa96`.

7.5 Completed — Add true multi-object benchmarks before drawing conclusions about
scene-level culling. Earth Party, camera dolly, and camera ellipse provided the
accepted three-scene object-AABB comparison; the ellipse gained 14.78% FPS and
the weighted chain gained 10.08% over incremental depth.

## Phase 8: experiment acceptance and integration

8.1 Completed — Keep one intentional code variable per performance comparison whenever
practical.

8.2 Completed — Require native correctness tests, both embedded builds, hardware visual
qualification, and repeated ordinary-firmware timing before promotion.

8.3 Completed — Use diagnostic builds to explain *why* a result changed. Use ordinary
builds to state absolute frame-time or FPS improvement.

8.4 Completed — Preserve raw logs, structured summaries, firmware identity, source
commit, fixture profile, and observed visual result for every accepted or
important rejected experiment.

8.5 Completed — Keep hardware as final ground truth. Refresh a persistent emulator
snapshot only under the agreed gate, and always wait for explicit human
validation before committing any emulator-related change. The human emulator
gate is now also a canonical environment rule.

8.6 Deferred — Decide the final branch consolidation policy now that the Wolf/Pingo
VDP integration contract and combined base are accepted. The accepted Pingo
lineage remains preserved in `experiment/hecker-rasterizer`, and the combined
release line is `pingowolf`; retain meaningful tags and durable evidence, and
delete only genuinely disposable branches.

## Phase 9: ideas already present or presently unsupported

9.1 Completed — Backface culling already occurs before rasterization.

9.2 Completed — Viewport bounding-box clamping, incremental barycentric edge stepping,
and the bitwise positive-area edge rejection already exist.

9.3 Completed — Depth rejection already precedes texture lookup, lighting application,
and pixel output. Upstream's advertised early-Z toggle currently executes the
same depth test in both branches and supplies no new mechanism to port.

9.4 Completed — Reopen any completed item in this phase only when a distinct mechanism
and a workload capable of exercising it have been identified.
