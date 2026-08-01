# TurboVega Pingo versus modern upstream

Status: historical comparison, reconciled with the accepted selective-port
lineage through 2026-07-31. Its optimization dispositions remain in
`pingo-renderer-optimization-todo.md`; current work is authorized only through
`docs/todo.md`.

This comparison uses:

1. TurboVega's final Agon port:
   `TurboVega/agon-vdp-otf@f4814813e8155780c5ad2602cd45f82ca5a72eec`.
2. Inspected `fededevi/pingo` master:
   `f171c81aa597436e8db8fafd842ab7af6ef13b83`.

Upstream Pingo has no tagged releases. “Modern upstream” below means that
inspected master commit, not a formal release.

## Why modern upstream was not merged

Modern upstream is not a drop-in bug-fix release for TurboVega's port:

1. `Scene` plus tagged renderables became callback-driven root `Renderable`
   objects and transformed `Entity` wrappers.
2. Object transforms moved from `Object` to `Entity`, changing ownership and
   composition.
3. TurboVega consumes `camera_view` directly; upstream treats it as a camera
   pose and inverts it while rendering.
4. Model/view composition and traversal were reorganized between
   `renderer.c`, `object.c`, and callbacks.
5. Upstream adds six-plane frustum rejection and switches for backface,
   frustum, and early-Z work.
6. TurboVega supports object-local UVs for VDU command `40`; upstream expects
   UVs on the mesh.
7. `BackEnd` became `Backend`; bitmap ownership, draw callbacks, and embedding
   access changed.
8. Pixel, texture, allocation, and supporting container APIs changed.
9. Upstream changes the light Y component from `-5` to `+5`.

An attempted combined port made geometry visible only after compensating for
camera inversion, then produced distant models and origin-orbiting rotation.
That proved broader semantic drift. It was discarded in favor of incremental
repairs on the exact TurboVega baseline.

## Upstream ideas assessed

1. Upstream commits `f11ea30` (“Ugly but correct texture projection”) and
   `9ee1ace` (“Improve attributes interpolation and use better projection
   matrix”) attempt perspective correction through UV/depth terms.
2. Pingo Alpha 1 instead uses the conventional reciprocal clip-W method:
   interpolate `u/w`, `v/w`, and `1/w`, then divide.
3. Upstream's frustum rejection is useful, but whole-triangle rejection is not
   a substitute for clipping triangles crossing the near plane.
4. Bounds, null, allocation, and division guards are worth porting
   independently.
5. Entity/callback architecture and cosmetic API renames offer no immediate
   correctness or performance benefit to the Agon bridge.

## Selective upstream sweep result — 2026-07-29

Modern upstream was re-audited routine by routine against the
`working-pre-optimization` lineage. The object-model concern was valid:
wholesale adoption would mix camera, transform, traversal, UV-ownership, and
backend semantics into an optimization experiment. No `Entity` or callback
scene code was imported.

The emulator-qualified candidate retains only:

1. upstream `fb67d951`'s guarded `vec3Normalize` structure, replacing three
   divisions with one reciprocal and three multiplies;
2. that commit's exact translation-only matrix inverse, adapted so the same
   predicate covers identity and excluding the unsafe scale-only path; and
3. a locally derived `projection × view` composition performed once per
   object. It is inspired by upstream lineage (`a0ed0cb`, with historical
   antecedent `6d8dd2f`) but preserves model-space lighting and the Agon
   camera-pose contract.

Rejected measured candidates include arbitrary-input-W matrix-vector work,
broad and narrow raster cleanups, general matrix-multiply identity/translation
predicates, and additional renderer state to hoist the composed matrix from
once per object to once per render. They were neutral or slower on the
same-host ellipse workload. Upstream's object-model rewrite, renderer-side
camera inversion, scale-only inverse without a zero guard, hard-coded far
distance, and composition inside the triangle loop were rejected on semantic
or safety grounds.

The exact final candidate passed ordinary and diagnostic native suites. A
temporary Cube probe found its final 76,800-byte RGBA2222 Pingo target
byte-identical to the pre-sweep target:

```text
aa3033b451bd8fe6168a998073dd445738ec9ce1bd91b4a6dd515244b13fb859
```

On the five-object polar ellipse, exact final source averaged 713.496
microseconds versus a pooled 785.110-microsecond pre-sweep control, a 9.12%
same-host reduction. This is emulator screening evidence, not an ESP32
performance claim. Human review passed in the emulator, and the later complete
1,447-frame physical run passed visually and improved all fifteen fixtures,
from 0.42% on HeavyTank to 8.41% on the multi-object camera-dolly scene.

## Decided coordinate contract

1. World space is right-handed: `+X` right, `+Y` up, `+Z` toward the viewer.
2. Unrotated forward is `-Z`.
3. Camera VDU values describe a pose, like object values. The bridge performs
   the sole pose-to-view inversion.
4. A camera pose `(0, 0, +25)` sees the origin along `-Z`.
5. Retain Pingo's row-major storage with column vectors and construction order
   `T × Rz × Ry × Rx × S`.
6. `mat4MultiplyM(m1, m2)` currently returns `m2 × m1`; preserve and test this
   behavior before considering cleanup.
7. World/NDC `+Y` is up; top-origin target memory `+Y` is down. The viewport
   reflects Y once.
8. Blender/OBJ UV V is bottom-origin; raw RGBA rows are top-first. The sampler
   performs the sole texture-row conversion.
9. TurboVega's public VDU meanings remain stable. Internal conversions belong
   at the bridge or renderer boundary, never in application assets.

> The Author's margin note: “Whoever invented such a stupid convention needs
> to be dragged out back and shot.”

## Completed on the Pingo development lineage

1. **Camera semantics:** the bridge inverts camera pose exactly once.
2. **Viewport orientation:** Y is reflected once; rasterizer edge signs remain
   consistent after reflection.
3. **Texture orientation:** U/V endpoints are clamped, V is converted once,
   and rectangular textures use their true height.
4. **Perspective interpolation:** standard reciprocal-W UV interpolation is
   implemented.
5. **Geometry/texture separation:** labeled cube tests confirm every face,
   label, and designed top/bottom rotation is correct.
6. **Chiral acceptance:** a fresh outward-wound HeavyTank passes hardware and
   emulator; the old inward-wound OBJ explained the historical inside-out
   result.
7. **VDU compatibility:** the implementation retains TurboVega commands
   `0`–`40`, including object-local UV command `40`.

This qualified state is branded:

```text
Agon Pingo VDP Version 2.15.0 Alpha 1 SEP Field
```

## Action-plan disposition

This section originally described the work required after Alpha 1. It is kept
as a compact disposition rather than a second live TODO list; remaining work
is maintained only in `docs/todo.md`.

### Phase 1 — objective regression evidence

1. Completed — Capture exact render-target hashes and preserve Cube/HeavyTank visual
controls. The broader emulator oracle now compares complete color and depth
targets across 1,447 frames.
2. Completed — Add host tests for known points through model, view, projection,
   perspective division, and viewport conversion.
3. Completed — Add numerical unequal-W and perspective-span tests for UV
reconstruction.
4. Completed — Record 320×240 frame time and submitted/rejected/shaded counts through
versioned renderer diagnostics and deterministic hardware fixtures.

### Phase 2 — safety and geometry correctness

1. Completed — Validate mesh and UV index counts and ranges before rendering.
2. Completed — Handle allocation failures, null textures, invalid dimensions, and zero
   divisors without corrupting VDP state.
3. Completed — Make backface culling switchable during diagnosis, then retain the accepted
   outward-winding convention by default.
4. Completed — Implement homogeneous clip-space polygon clipping for triangles crossing
   all production view planes, including the near
   plane.
5. Completed — Retain triangle common-plane rejection and add conservative cached
object-AABB rejection with fail-open invalidation and hardware evidence.

### Phase 3 — measured performance

1. Completed — Establish corrected Cube, EarthIco, EarthUV, complex-model, near-plane,
and multi-object baselines at 320×240.
2. Deferred — Reach the aspirational 15 FPS threshold on representative demanding
workloads. Several simpler models exceed it, but the full-screen Earth and
multi-object stress scenes remain below it on hardware.
3. Completed — Benchmark backface, frustum, early-Z, math, fixed-point, span,
interpolation, and object-culling changes separately.
4. Completed — Keep only changes with measured benefit and accepted image behavior;
preserve important rejected patches and numerical differences explicitly.

### Phase 4 — architecture only if justified

1. Completed — Defer upstream `Entity` and callback-scene adoption until a concrete
   hierarchical application requires it.
2. Deferred — If a newer `Backend` becomes necessary, hide it behind a stable Agon
   adapter that preserves borrowed bitmap lifetime and command `40`.
3. Completed — Do not extend the VDU surface merely to mirror upstream internal APIs.

## Branch policy

`tv-port` remains the immutable VDP 2.15 plus TurboVega-final historical
control. `pingo-codex` is the historical Alpha 1 integration line; accepted
renderer, safety, lighting, and bridge work currently continues on
`experiment/hecker-rasterizer`. Modern upstream changes remain references to
evaluate one at a time, not a branch to merge wholesale. The future combined
Wolf/Pingo branch is governed separately through
`agon-dev-env/cross-agent/wolf_pingo_vdp` and does not alter these rollback
boundaries.
