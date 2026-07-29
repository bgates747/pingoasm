# Pingo renderer optimization roadmap

Status: active, begun 2026-07-28 under Codex Ultra reasoning.

This is the controlled evolutionary path from the last known-working renderer
to measured optimizations. It is deliberately separate from the general
project TODO so experimental branches, rejected ideas, and performance evidence
remain easy to follow.

## Phase 0: immutable point of departure

0.1 [x] Tag `agon-vdp` commit `207f87b` as
`working-pre-optimization`.

0.2 [x] Tag `pingoasm` commit `15ef335` as
`working-pre-optimization`.

0.3 [x] Preserve the ordinary and diagnostic firmware artifacts outside Git
under `~/Agon/mystuff/pingo-firmware-archive`.

0.4 [x] Establish five-series hardware attribution baselines for Cube,
EarthIco, and EarthUV.

0.5 [x] Preserve the visually qualified coordinate, winding, UV, texture, and
one-byte framebuffer behavior as non-negotiable correctness controls.

0.6 [x] Capture exact-tag ordinary five-series Cube, EarthIco, and EarthUV
results. The existing diagnostic results identify work distribution, but the
earlier ordinary results predate commit `207f87b`; absolute optimization claims
need an ordinary baseline built from the exact tag.

0.7 [x] Archive fresh ordinary and diagnostic binaries built from the exact
tag under
`~/Agon/mystuff/pingo-firmware-archive/04-working-pre-optimization`.

## Phase 1: experimental discipline and moving-frustum fixture

1.1 [x] Continue integrated work on `pingo-codex`, protected by the immutable
baseline tag.

1.2 [x] Use one short-lived `experiment/<subject>` firmware branch for each
independent idea. The first branch is `experiment/frustum-culling`.

1.3 [x] Add a reusable, profile-driven motion definition to the render-spin
generator. A pose must set absolute translation and absolute rotation so no
firmware-side accumulation can affect repeatability.

1.4 [x] Add RGBA2222 Cube and EarthUV frustum-sweep fixtures with the identical
motion path. During one revolution each must move toward and away from the
camera and laterally through every viewport edge, producing fully visible,
partially clipped, and wholly offscreen intervals. Cube is the labeled visual
control; EarthUV amplifies per-triangle cost and potential savings.

1.5 [x] Retain the stationary Cube, EarthIco, and EarthUV fixtures unchanged.
They remain the controls for detecting overhead on ordinary in-frame scenes.

1.6 [x] Capture and preserve the moving fixture on
`working-pre-optimization` before enabling any culling experiment.

1.7 [x] Exercise the far clip plane in native tests. The current bridge
projection approaches its nominal far boundary asymptotically, and the signed
16-bit VDU translation range cannot put an ordinary fixture near the declared
2500-unit value. Do not mix a projection repair into this experiment.

1.8 [ ] Give chained benchmark applications an explicit model/run identity or
add an occurrence selector to the summarizer. The stationary profiles reuse
bitmap IDs, so a combined log must presently be split at its known 220-record
application boundaries before model-specific parsing.

## Phase 2: upstream-style clip-space frustum rejection

2.1 [x] Verify every clip inequality against our actual projection matrix.
Do not copy upstream's nominal near-plane expression blindly: this renderer's
visible depth interval is clip-space `-w <= z <= 0`, not the conventional
`-w <= z <= w`.

2.2 [x] Reject a triangle only when all three vertices lie outside the same
clip plane. A triangle crossing a plane must remain eligible for the existing
pipeline; rejection is not clipping.

2.3 [x] Give frustum rejection its own diagnostic outcome. Do not silently
relabel it as projected-Z, back-face, or viewport rejection. If the serialized
diagnostic schema changes, increment its version and retain parser support for
version 1.

2.4 [x] Add deterministic native cases for all six planes, exact-boundary
vertices, plane-crossing triangles, negative or zero `w`, and the existing
triangle-partition invariant.

2.5 [x] Run strict scope checks, ordinary and diagnostic native suites, and
both embedded builds before touching hardware.

2.6 [ ] Hardware-qualify visual behavior with Cube and HeavyTank. Moving and
stationary Cube, EarthIco, and EarthUV have passed; HeavyTank remains.

2.7 [x] Compare the baseline and experimental ordinary firmware on the moving
fixture. Use diagnostic firmware separately to explain rejection counts; never
compare diagnostic absolute time with an ordinary baseline.

2.8 [x] Repeat the stationary Cube, EarthIco, and EarthUV controls. Frustum
tests add per-triangle work when nothing is rejected, so a negative result is
plausible and must be retained.

2.9 [ ] Promote the experiment only if its repeatable moving-scene benefit is
worth any stationary-scene cost. Otherwise document the result and delete the
branch; the immutable tag remains the point of departure.

2.10 [ ] Before deciding item 2.9, test a small code-generation refinement.
The inlined by-value clip helper grows `renderObject`'s stack frame and causes
extra loads and spills even when no triangle is rejected. Compare an
out-of-line helper taking three `const Vec4f *` arguments so the enable branch
precedes those loads. Retain it only if it reduces the measured stationary
cost without surrendering the moving EarthUV gain.

## Phase 3: low-risk invariant work

3.1 [ ] Replace unintended double-precision literal expressions in the hot
path with deliberate float expressions. ESP32 disassembly shows
`1.0 / area` and `(1.0 + dot) * 0.5` currently call double-precision runtime
helpers once per affected triangle.

3.2 [ ] Hoist the constant normalized light vector out of the triangle loop.

3.3 [ ] Hoist framebuffer half-width, half-height, material state, and other
object-invariant values out of the triangle loop.

3.4 [x] Evaluate and retain the guarded upstream `vec3Normalize` improvement:
one square root, one reciprocal, and three multiplies instead of three
software divisions. Zero and exact-unit inputs have explicit fast paths.
Native tests and emulator target equivalence pass; hardware qualification
remains part of item 8.2.

3.5 [ ] Cache framebuffer and z-buffer pointers and avoid repeated backend
callback lookup in the fragment loop. Compute and increment a linear pixel
index rather than recalculating `x + y * width`, and quantize depth only once.

3.6 [ ] Normalize integer triangle area and edge signs once so the common
raster loop can use one bitwise-OR coverage test. Account explicitly for the
viewport Y reflection and integer overflow; copying upstream's positive-area
test directly would be wrong.

3.7 [x] Evaluate and retain a locally derived view/projection composition
outside the triangle loop. It is computed once per object, preserves
model-space lighting, and is covered by a nontrivial sequential-versus-composed
math test and final-target equivalence. Hardware qualification remains part of
item 8.2.

3.8 [ ] Treat each item above as its own A/B experiment. EarthUV is the primary
geometry-pressure fixture; Cube remains the primary raster-pressure and visual
orientation control.

3.9 [ ] Design runtime illumination controls without making the experimental
unlit build flag part of the public API. The design should provide:

3.9.1 [ ] A runtime-configurable illumination-vector direction.

3.9.2 [ ] A runtime-configurable illumination intensity, with its numeric
range, clamping behavior, and interaction with the renderer's present
half-Lambert calculation stated explicitly.

3.9.3 [ ] An explicit unlit mode that performs no illumination computation and
writes sampled texture colors at their defined values.

3.9.4 [ ] Decide whether illumination state belongs to the renderer/scene,
individual objects, or materials. Begin with the least invasive scene-wide
state unless a concrete application requires finer control.

3.9.5 [ ] Stable VDU command semantics so applications can select these
behaviors without rebuilding firmware.

3.9.6 [ ] A backward-compatible default matching the visually qualified
current renderer unless a later versioned API deliberately says otherwise.

3.9.7 [ ] Separate correctness and performance fixtures for directional,
intensity-adjusted, and unlit rendering. The 2026-07-28 hardware experiment
establishes the initial unlit performance bound.

## Phase 4: clear and output costs

4.1 [ ] Measure depth clear, RGBA2222 color clear, and any RGBA8888 expansion
as separate costs before changing them.

4.2 [ ] Investigate safe wider or platform-appropriate clears without changing
the renderer's one-byte pixel contract.

4.3 [ ] Evaluate dirty-region or generation-based depth clearing only as a
separate invasive experiment. Account for frames in which the next object
covers less screen area than the previous one.

4.4 [ ] Preserve direct RGBA2222 targets and legacy RGBA8888 compatibility.

## Phase 5: upstream math changes

5.1 [x] Diff each upstream vector and matrix change against the TurboVega-era
math retained by this port.

5.2 [x] Separate correctness repairs, API refactors, desktop/SIMD assumptions,
and genuine scalar ESP32 optimizations.

5.3 [x] Add equivalence and edge-case tests before replacing one routine at a
time.

5.4 [ ] Benchmark math routines in isolation and then measure whole-frame
hardware impact. Upstream desktop percentage claims are hypotheses, not Agon
results. Same-host emulator screening and attribution are complete for the
accepted candidates; embedded visual and timing qualification remain.

5.5 [x] Reject upstream's incompatible `Entity`/callback object-model rewrite,
camera inversion in the renderer, scale-only inverse without a zero guard,
and matrix composition performed inside the triangle loop.

5.6 [x] Preserve provenance for accepted adaptations and durable evidence for
rejected candidates. The accepted sources are `fb67d951` for normalization
and translation-only inverse, plus a locally derived view/projection
composition inspired by upstream `a0ed0cb`.

## Phase 6: raster-loop evolution

6.1 [ ] Replace four per-sample `fminf`/`fmaxf` calls with a proven equivalent
sampler clamp, then evaluate inlining the RGBA2222 read. Define NaN and endpoint
behavior before changing it.

6.2 [ ] Compute one reciprocal of interpolated `1/W` and multiply both UV
numerators by it. The present code performs two software floating-point divides
per shaded textured fragment.

6.3 [ ] Evaluate a bit-identical packed RGBA2222 lighting lookup and a direct
cached-framebuffer write for the default backend. Keep custom backend behavior
available.

6.4 [ ] Increment depth, reciprocal W, U/W, and V/W across rows and pixels
instead of recomputing three-term barycentric expressions per fragment.

6.5 [ ] Verify perspective-correct UVs, depth ordering, shared-edge coverage,
both triangle area signs, and subpixel behavior before performance testing.

6.6 [ ] Evaluate fixed-point edge and interpolant arithmetic only after the
incremental floating-point reference is qualified.

6.7 [ ] Revisit scanline bounds, Hecker-derived perspective spans, tiling, and
other structural rasterizers as separate experiments with objective image
comparisons.

## Phase 7: geometry reuse and scene-level rejection

7.1 [ ] Measure a transformed-vertex cache for indexed meshes so EarthUV does
not transform the same source vertex once per triangle corner.

7.2 [ ] Account explicitly for PSRAM/internal-RAM cost, cache invalidation, and
object/camera/scene pose changes.

7.3 [ ] Evaluate precomputed or transformed normals separately from position
caching.

7.4 [ ] Add conservative object-level bounds before considering per-triangle
frustum work for large multi-object scenes.

7.5 [ ] Add a true multi-object benchmark before drawing conclusions about
scene-level culling.

## Phase 8: experiment acceptance and integration

8.1 [ ] Keep one intentional code variable per performance comparison whenever
practical.

8.2 [ ] Require native correctness tests, both embedded builds, hardware visual
qualification, and repeated ordinary-firmware timing before promotion.

8.3 [ ] Use diagnostic builds to explain *why* a result changed. Use ordinary
builds to state absolute frame-time or FPS improvement.

8.4 [ ] Preserve raw logs, structured summaries, firmware identity, source
commit, fixture profile, and observed visual result for every accepted or
important rejected experiment.

8.5 [ ] Test hardware first. Refresh an emulator snapshot only after hardware
passes, then wait for explicit human emulator validation before committing any
emulator-related change.

8.6 [ ] Merge successful experiment branches into `pingo-codex`. Tag meaningful
milestones; delete disposable experiment branches after their evidence and
conclusion are durable.

## Phase 9: ideas already present or presently unsupported

9.1 [x] Backface culling already occurs before rasterization.

9.2 [x] Viewport bounding-box clamping, incremental barycentric edge stepping,
and the bitwise positive-area edge rejection already exist.

9.3 [x] Depth rejection already precedes texture lookup, lighting application,
and pixel output. Upstream's advertised early-Z toggle currently executes the
same depth test in both branches and supplies no new mechanism to port.

9.4 [ ] Reopen any completed item in this phase only when a distinct mechanism
and a workload capable of exercising it have been identified.
