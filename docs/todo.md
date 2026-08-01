# Pingo project TODO

This is the sole authoritative queue for unfinished Pingo project work. Use
stable manual IDs so discussions and commits can cite an item without relying
on its position in the file.

When an item is accepted, rejected, or superseded:

1. record its ID, outcome, evidence, and rationale in the current dated
   devlog;
2. remove it from this file rather than leaving a checked item here; and
3. update any affected specification or technical précis so it describes the
   settled state without becoming another action queue.

Historical checklists and roadmap dispositions are evidence only. Do not begin
work merely because an old document contains an unchecked box. New work must
first be promoted here.

## Priority work

P1 [ ] Prepare the first current-fixture PingoASM release. Reconcile the dirty
tree, preserve unrelated Lara animation work, rebuild and qualify the intended
fixture set, define a deterministic SD-ready package, commit it, and create a
new versioned ordinary GitHub Release. The two 2024 alpha releases are retained
as prereleases; do not move or reuse their historical tags.

P2 [ ] Select the next isolated renderer experiment. Choose one distinct
mechanism from the renderer backlog below, state its hypothesis and acceptance
gate in the devlog, and preserve firmware commit `6c24691` as the current
rollback point. Do not stack candidates before debriefing the previous one.

P3 [ ] Add a historically realistic half-screen benchmark: a true 320x120
render target in the upper half with a representative static 2D HUD or flight
instrument panel below. Retain the 320x240 fixtures as worst-case controls and
report renderer time separately from UI, application logic, audio, and final
presentation.

## Renderer backlog

R1 [ ] Give chained benchmark applications an explicit fixture/run identity
or add an occurrence selector so shared bitmap IDs no longer require manual
record-boundary splitting.

R2 [ ] Measure remaining object/triangle invariants before hoisting them,
including projection half-dimensions and any material state still recomputed
inside the triangle loop.

R3 [ ] Evaluate one-time integer area/edge-sign normalization for the exact
span path. Preserve both windings, viewport-Y reflection, inclusive-zero edge
behavior, and defined overflow handling.

R4 [ ] Attribute depth clear, RGBA2222 color clear, and RGBA8888 compatibility
output separately before optimizing any of them.

R5 [ ] After R4, evaluate safe wider or platform-appropriate clears without
changing the one-byte working-pixel contract.

R6 [ ] Evaluate dirty-region or generation-based depth clearing only as an
independent invasive experiment, including frames whose new coverage is
smaller than the previous frame.

R7 [ ] Revisit tiling or top-left shared-edge ownership only as separate
experiments. Do not combine a fill-rule change with interpolation changes.

R8 [ ] Measure an indexed transformed-vertex cache so visible complex meshes
do not transform the same source vertex for every triangle corner.

R9 [ ] As part of R8, account explicitly for PSRAM/internal-RAM cost and cache
invalidation after object, camera, scene, mesh, scale, or pose changes.

R10 [ ] Evaluate precomputed or transformed normals separately from the
position cache so their performance and memory effects remain attributable.

R11 [ ] Decide final Pingo branch consolidation now that the combined PingoWolf
firmware base and ownership contract are accepted. Preserve meaningful tags
and evidence; delete only genuinely disposable branches.

## Model and asset pipeline backlog

A1 [ ] Make every generated model include local or directly traceable to its
authoritative `.blend`, exported OBJ/MTL, and source image assets.

A2 [ ] Replace the temporary central `src/asm/models` library only after all
active consumers have explicit sources.

A3 [ ] Introduce an explicitly named shared-assets area for textures used by
multiple models or applications.

A4 [ ] Keep editable `.blend` and PNG/XCF assets authoritative; treat
`.rgba2`, `.rgba8`, generated `.asm`, and generated `.inc` as reproducible
outputs.

A5 [ ] Define machine-readable application dependencies on models and
textures while retaining portable generated includes under each app's `src/`
and runtime payload under `tgt/`.

A6 [ ] Audit every active model include for generator and source provenance,
including Blender version, object name, coordinate conversion, winding, UV
conversion, and texture source.

A7 [ ] Ensure every generated assembly file carries the standard generator and
authoritative-input warning, and verify deterministic regeneration against
accepted includes and binaries.

A8 [ ] Inventory users of shared textures such as `blenderaxes` and Earth
textures; assign stable names, dimensions, pixel formats, and overwrite guards.

A9 [ ] Before structural migration, preserve and hash the accepted 18-binary
build. Regenerate into a disposable directory and compare every application
and runtime asset before removing the old model library.

A10 [ ] Design a tracked release/export area producing portable application
ZIPs with matching `src/`, `tgt/`, generator versions, provenance, and
checksums.
