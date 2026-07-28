# Model and asset reorganization TODO

This structural work is deferred until after renderer correctness and safety.
Keep item numbers stable when updating it.

## Phase 1 — authoritative layout

1. [ ] Make each generated model include local or directly traceable to its
   `.blend` file and source assets.
2. [ ] Replace the temporary central `src/asm/models` directory.
3. [ ] Introduce a clearly named shared-assets directory for common textures.
4. [ ] Keep `.blend` and original PNG/XCF images authoritative.
5. [ ] Treat `.rgba2`/`.rgba8` as generated runtime output.
6. [ ] Define machine-readable application dependencies on models and textures.
7. [ ] Continue copying generated model includes to app `src/` and runtime
   textures to app `tgt/`.

## Phase 2 — provenance and determinism

1. [ ] Audit every existing model include for generator and source assets.
2. [ ] Put the standard generator/input warning on every generated `.asm` and
   `.inc`.
3. [ ] Record source `.blend`, object name, Blender version, coordinate
   conversion, winding, UV conversion, and texture source.
4. [ ] Regenerate deterministically enough to compare with accepted includes
   and binaries.
5. [x] Establish fresh outward-wound `heavytank.blend/.obj/.mtl` as the
   canonical HeavyTank source.
6. [x] Remove numbered, inverted, axis-modified, and video HeavyTank rabbit
   holes.

## Phase 3 — shared textures

1. [ ] Inventory users of `blenderaxes`, `earthuv`, and other shared textures.
2. [ ] Decide whether shared assets use separate authoritative and generated
   directories.
3. [ ] Prevent model builds from silently overwriting a shared texture with
   different dimensions or bytes.
4. [ ] Give shared assets stable names and record dimensions and pixel format.

## Phase 4 — migration safety

1. [ ] Preserve the accepted 13-binary build before moving assets.
2. [ ] Hash current model includes and textures.
3. [ ] Regenerate into a disposable directory first.
4. [ ] Compare applications and runtime assets with accepted versions.
5. [ ] Update build, deployment, Blender, and documentation paths together.
6. [ ] Remove the old model library only after every active application builds.

## Phase 5 — release packaging

1. [ ] Design a tracked deployment/release directory.
2. [ ] Produce portable ZIPs containing app `src/` and matching `tgt/`.
3. [ ] Include generator versions, source provenance, and checksums.
