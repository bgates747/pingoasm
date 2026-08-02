# Model and asset reorganization planning record

Status: historical planning detail. The filename is retained to avoid breaking
references. Current actionable asset work has moved to `docs/todo.md`; entries
below are dispositions and scope evidence, not authorization. The ordinary
sample build now contains 19 binaries, including the rigid Lara animation app.

## Phase 1 — authoritative layout

1. Deferred — Make each generated model include local or directly traceable to its
   `.blend` file and source assets.
2. Deferred — Replace the temporary central `src/asm/models` directory.
3. Deferred — Introduce a clearly named shared-assets directory for common textures.
4. Deferred — Keep `.blend` and original PNG/XCF images authoritative.
5. Deferred — Treat `.rgba2`/`.rgba8` as generated runtime output.
6. Deferred — Define machine-readable application dependencies on models and textures.
7. Deferred — Continue copying generated model includes to app `src/` and runtime
   textures to app `tgt/`.

## Phase 2 — provenance and determinism

1. Deferred — Audit every existing model include for generator and source assets.
2. Deferred — Put the standard generator/input warning on every generated `.asm` and
   `.inc`.
3. Deferred — Record source `.blend`, object name, Blender version, coordinate
   conversion, winding, UV conversion, and texture source.
4. Deferred — Regenerate deterministically enough to compare with accepted includes
   and binaries.
5. Completed — Establish fresh outward-wound `heavytank.blend/.obj/.mtl` as the
   canonical HeavyTank source.
6. Completed — Remove numbered, inverted, axis-modified, and video HeavyTank rabbit
   holes.

## Phase 3 — shared textures

1. Deferred — Inventory users of `blenderaxes`, `earthuv`, and other shared textures.
2. Deferred — Decide whether shared assets use separate authoritative and generated
   directories.
3. Deferred — Prevent model builds from silently overwriting a shared texture with
   different dimensions or bytes.
4. Deferred — Give shared assets stable names and record dimensions and pixel format.

## Phase 4 — migration safety

1. Deferred — Preserve the pre-animation 18-binary baseline before moving assets.
2. Deferred — Hash current model includes and textures.
3. Deferred — Regenerate into a disposable directory first.
4. Deferred — Compare applications and runtime assets with accepted versions.
5. Deferred — Update build, deployment, Blender, and documentation paths together.
6. Deferred — Remove the old model library only after every active application builds.

## Phase 5 — release packaging

1. Deferred — Design a tracked deployment/release directory.
2. Deferred — Produce portable ZIPs containing app `src/` and matching `tgt/`.
3. Deferred — Include generator versions, source provenance, and checksums.
