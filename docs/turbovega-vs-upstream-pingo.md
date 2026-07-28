# TurboVega Pingo versus latest upstream Pingo

Status date: 2026-07-27

This document summarizes the material differences found between:

1. TurboVega's final Agon Pingo implementation:
   `TurboVega/agon-vdp-otf`, commit
   `f4814813e8155780c5ad2602cd45f82ca5a72eec`.
2. The latest inspected upstream Pingo:
   `fededevi/pingo`, commit
   `f171c81aa597436e8db8fafd842ab7af6ef13b83`.

Upstream Pingo publishes no tagged releases. “Latest upstream” therefore means
the inspected tip of its `master` branch, not a formal release.

## Material differences

1. **Scene architecture**

   TurboVega uses a `Scene` containing tagged `Renderable` objects. Latest
   upstream replaces this with callback-based root `Renderable` objects and
   transformed `Entity` wrappers.

2. **Object-transform ownership**

   TurboVega stores the transform directly in `Object`. Latest upstream stores
   it in `Entity`. Adapting one representation to the other changes where and
   how parent, scene, and object transforms are composed.

3. **Camera semantics**

   TurboVega consumes `Renderer.camera_view` directly as the view matrix.
   Latest upstream treats the same field as a camera pose and inverts it during
   object rendering.

   Passing TurboVega's already-final view transform directly to latest upstream
   inverted it a second time. With the strict fixtures' camera command of
   Z = -25, all geometry was rejected behind the camera.

4. **Model/view composition**

   TurboVega transforms vertices by the composed object/scene matrix and then
   by the supplied view matrix. Latest upstream combines its entity/model
   matrix with its newly inverted camera matrix before transforming vertices.

   The attempted compatibility adapter made geometry visible but produced
   distant-looking models and rotation resembling an orbit around the scene
   origin. This demonstrated that camera inversion was not the only semantic
   difference.

5. **Renderer organization**

   TurboVega's scene traversal and triangle renderer largely live in
   `renderer.c`. Latest upstream moves object rendering into `object.c` and
   reorganizes the renderer around callbacks.

6. **Culling and optimization controls**

   Latest upstream adds switches for:

   - backface culling;
   - frustum culling; and
   - early-Z testing.

   TurboVega's backface test is unconditional and it has no equivalent
   configurable optimization interface.

7. **Frustum rejection**

   Latest upstream adds rejection against all six clip-space frustum planes.
   TurboVega has a simpler “completely behind camera” test followed by
   screen-bound clipping.

8. **Texture-coordinate ownership**

   TurboVega allows an object-local texture-coordinate pointer to override the
   mesh coordinates. This supports its command `40`. Latest upstream expects
   texture coordinates through the mesh, requiring an adapter or shallow mesh
   copy to reproduce TurboVega's protocol.

9. **Backend API**

   `BackEnd` becomes `Backend`. Latest upstream removes the backend's
   `drawPixel` and `clientCustomData` members, renames fields and functions, and
   changes how an embedding application reaches its owning control structure.

10. **Pixel and texture APIs**

    Pixel-format selection, texture fields, initialization functions, and
    several color operations are reorganized. This is not merely a cosmetic
    renaming because the Agon bridge borrows existing VDP bitmap memory.

11. **Supporting data structures**

    Latest upstream adds `Array`, `State`, `Entity`, and additional math
    helpers. It removes TurboVega's `Scene` implementation and tagged
    render-dispatch table.

12. **Lighting direction**

    TurboVega uses the light vector `{-8, -5, 5}`. Latest upstream uses
    `{-8, +5, 5}`, reversing its Y component.

13. **Texture perspective correction**

    Latest upstream contains an explicit attempt to correct perspective
    interpolation. Commit `f11ea309fb81d95b8e9b0bdb9bde4fd7dc22006c`
    is titled “Ugly but correct texture projection,” and later commit
    `9ee1ace27f627fd62e2aa325543c12011282efa3` is titled “Improve attributes
    interpolation and use better projection matrix.”

    The current upstream object renderer pre-divides each vertex UV by its
    projected depth, interpolates those adjusted values barycentrically, and
    multiplies the result by the interpolated depth term. This is intended to
    provide perspective-correct texture mapping.

    TurboVega's older renderer retains the visibly affine interpolation defect.
    We have not yet run the strict cube fixture against an otherwise-correct
    port of latest upstream, so the current upstream formula still requires
    visual and mathematical validation in our Agon environment.

## Recommended engineering sequence

The work should proceed on a new branch from the qualified `tv-port` baseline.
Keep `tv-port` unchanged as the historical control. Introduce one behavioral
change per commit so every regression can be attributed or reverted cleanly.

### Priority 1: establish objective tests

1. **Freeze golden baseline evidence.**

   Capture emulator images and hardware observations for triangle, cube, and
   HeavyTank at zero transform and at a small, fixed set of translations and
   90-degree rotations. Record frame time at 320×240.

   This is low effort and essential. Current visual faults must become named
   test expectations before they can be changed deliberately.

2. **Add transform-only fixtures.**

   Render the cube with fixed face colors as well as the labeled texture. This
   separates geometry, backface-culling, and coordinate-system failures from
   UV and texture-row-order failures.

3. **Create mathematical unit tests.**

   Test known points through model, view, projection, perspective division, and
   viewport conversion without invoking the rasterizer. Preserve a regression
   case for the historical fixture's Z = -25 value being consumed directly as
   a view transform. Add the decided semantics: an unrotated camera pose at
   world Z = +25 produces a view translation of Z = -25 and looks toward the
   origin along its forward axis, -Z.

   These tests should run on the host and use the same Pingo C functions as the
   firmware.

### Priority 2: low-risk corrections and guardrails

4. **Coordinate convention: decided and stated; enforcement in progress.**

   The authoritative public VDU and world convention is:

   1. The world is right-handed. `+X` points right, `+Y` points up, and `+Z`
      points out of the screen toward the viewer. Positive rotations follow
      the right-hand rule.
   2. The unrotated forward axis is `-Z`. Moving a camera, player, vehicle, or
      other conventionally oriented object forward therefore decreases its
      world Z coordinate.
   3. VDU camera translation and rotation values describe the camera's pose,
      exactly as object translation and rotation values describe an object's
      pose. The bridge constructs the camera pose normally and inverts it
      exactly once to obtain the renderer's view matrix. Applications never
      supply an already-inverted view transform.
   4. An unrotated camera viewing the origin from 25 units away has world pose
      `(0, 0, +25)`, looks along `-Z`, and initially sees the cube's `+Z`
      face. Moving the camera `+X` moves the camera right and consequently
      makes the rendered world appear to move left; this visual reversal is
      the natural result of view-matrix inversion, not reversed command
      semantics.
   5. Retain Pingo's existing matrix representation: row-major storage with
      column vectors. Transform construction applies scale, rotation X,
      rotation Y, rotation Z, and translation in that order, producing
      `T × Rz × Ry × Rx × S`. Do not replace `video/pingo/math` while
      correcting the pipeline.
   6. Treat the counterintuitive behavior of `mat4MultiplyM(m1, m2)`—which
      currently returns `m2 × m1`—as an implementation fact requiring
      documentation and numerical tests. Do not casually reverse arguments or
      rewrite it while other convention errors remain compounded.
   7. World and normalized-device `+Y` point up. Render-target memory has its
      origin at the top left and its `+Y` points down. Viewport conversion
      flips Y exactly once. The corresponding winding, backface-culling, and
      rasterizer edge signs must be corrected as one coordinated change.
   8. UV coordinates follow Blender/OBJ convention: `v = 0` is the bottom of
      the texture and `v = 1` is the top. PNG and raw RGBA texture memory remain
      top-row first. The sampler performs the sole conversion with the
      equivalent of `image_y = (1 - v) × (height - 1)`.
   9. Preserve TurboVega's published VDU command meanings at the bridge. If an
      internal renderer ever adopts different conventions, all conversion
      belongs at that boundary and must not leak into application data,
      controls, models, or texture assets.

   The `pingo-codex` branch now satisfies the camera-pose rule by inverting the
   pose once at the VDU bridge. The remaining renderer still omits the viewport
   Y flip, negates texture V during interpolation, and wraps texture Y by the
   texture width rather than its height. Those are implementation defects to
   correct against mathematical and visual regression tests, not alternative
   conventions.

   > **Margin note — The Author:** “Whoever invented such a stupid convention
   > needs to be dragged out back and shot.”

5. **Add geometry and allocation validation.**

   Port or independently implement upstream's useful bounds, null, allocation,
   and division-by-zero checks without changing successful rendering behavior.
   Reject malformed mesh indexes and mismatched UV indexes before rendering.

   Acceptance requires identical valid-fixture images plus clean failure of
   deliberately malformed fixtures.

6. **Keep object-local UV compatibility in the Agon bridge.**

   Do not remove TurboVega command `40`. If a future renderer requires UVs on
   the mesh, retain the shallow per-object mesh view used by the discarded
   adapter or provide an equivalent compatibility layer.

7. **Defer cosmetic API modernization.**

   Renaming `BackEnd` to `Backend`, converting functions to snake case, and
   importing the newer pixel/texture API offer little immediate rendering
   benefit. Perform them only when required by a selected functional change.

### Priority 3: correct the transform pipeline

8. **Resolve the cube axis permutation and vertical inversion first.**

   Trace one vertex and its face normal through the complete pipeline. Explain
   why the visible top, bottom, right, and left faces currently correspond to
   the wrong labeled axes and why Page Up moves the model downward.

   Acceptance requires the cube to show `+Y` on top, `-Y` on the bottom, `+X`
   on the right, and `-X` on the left under the chosen convention, without
   relying on compensating UV or image flips.

9. **Separate camera pose from view-matrix semantics. — Complete**

   TurboVega's wire protocol supplies the transform consumed directly as the
   view matrix. Latest upstream stores a camera pose and inverts it internally.
   The public and bridge representation is now the camera pose. The
   `pingo-codex` VDU bridge inverts it exactly once when assigning the
   renderer's world-to-view matrix.

   Hardware qualification with the strict cube fixture confirmed that a camera
   pose at `(0, 0, +25)` again renders the cube. X and Z translations behave
   correctly. The remaining Y-translation and X/Z-rotation reversals form the
   exact pattern expected from the separately tracked viewport Y reflection;
   they are not evidence for another camera inversion.

10. **Verify transform composition order.**

    Establish explicit model, scene, view, and projection matrices and test
    their multiplication order. Do not import upstream `Entity` until the
    simpler object/scene composition is proven correct.

### Priority 4: repair texture projection

11. **Implement standard perspective-correct UV interpolation.**

    Use the conventional formulation based on reciprocal clip-space W:

    1. retain `1/w` for each projected vertex;
    2. interpolate `u/w`, `v/w`, and `1/w` with screen-space barycentric
       coordinates; and
    3. divide the interpolated `u/w` and `v/w` by interpolated `1/w`.

    Treat upstream commits `f11ea30` and `9ee1ace` as references, not automatic
    cherry-picks. The current upstream code expresses the correction through
    its depth term, so its equivalence to the standard formula must be proved
    under Pingo's projection matrix.

    Acceptance requires the cube texture to remain geometrically stable as a
    face recedes in depth, with no affine swimming or skew.

12. **Separate UV orientation from geometry orientation.**

    After perspective correction, test U direction, V direction, bitmap row
    order, and triangle winding independently. Never repair an upside-down
    model by silently flipping texture V, or repair a mirrored texture by
    reversing geometry.

### Priority 5: worthwhile renderer improvements

13. **Add proper near-plane clipping.**

    Neither TurboVega's simple behind-camera rejection nor upstream's
    whole-triangle frustum rejection clips a triangle that intersects the near
    plane. Implement polygon clipping in clip space before perspective
    division.

    This is difficult but worthwhile: it prevents exploding or disappearing
    geometry when the camera approaches or passes through a polygon.

14. **Introduce frustum culling only after clipping is correct.**

    Port upstream's six-plane rejection as a separately switchable change.
    Verify boundary cases to prevent visible triangles from popping at the
    edges of the screen.

15. **Make backface culling explicit and testable.**

    Add a switch during diagnosis, then settle the winding convention and
    restore culling by default. HeavyTank is the primary acceptance fixture
    because its chirality exposes inverted or inside-out geometry.

16. **Benchmark optimizations individually.**

    Measure each candidate against the 320×240 globe target. Record frame time,
    triangles submitted, triangles rejected, and pixels shaded. Keep only
    changes with demonstrated benefit and identical reference images.

    Upstream's current “early-Z enabled” and “early-Z disabled” branches perform
    the same depth check, so that switch should not be imported as though it
    were already a working optimization.

### Priority 6: architectural changes only when justified

17. **Defer `Entity` and callback-scene adoption.**

    Upstream's newer architecture may eventually make hierarchy and reusable
    renderables cleaner, but it provides no immediate correction to the
    historical faults and substantially increases adaptation risk.

    Reconsider it only after the transform and rasterization tests pass, and
    only if a concrete application needs hierarchical scene behavior.

18. **Modernize the backend behind a stable Agon adapter.**

    If later upstream work requires the new `Backend` interface, keep ownership
    and borrowed VDP bitmap lifetime in an Agon-specific wrapper. Do not expose
    those internal changes through new VDU commands until the existing
    TurboVega contract is stable.

19. **Reassess the performance goal after correctness.**

    Once cube and HeavyTank are visually correct, benchmark the spinning globe
    at 320×240. The project target remains at least 15 FPS, compared with the
    historical result of roughly 3 FPS.

    If correct scalar rendering cannot approach that target, then evaluate
    larger interventions such as fixed-point inner loops, tiled rasterization,
    work distribution across both ESP32 cores, or deliberately reduced
    resolution. Each should remain subordinate to the golden-image tests.

## Consequence for this project

Latest upstream Pingo is not a drop-in cleanup of TurboVega's renderer. It
changes the scene graph, transform ownership, camera meaning, transform
composition, clipping, and embedding API.

The `tv-port` baseline must therefore remain canonical Agon VDP 2.15 plus
TurboVega's final Pingo implementation. Later upstream changes should be
introduced and tested incrementally on a separate branch rather than imported
wholesale.
