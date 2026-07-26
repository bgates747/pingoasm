# Model and asset reorganization TODO

This is the next structural task after the application `src/`/`tgt/`
migration. No model files are moved as part of the current task.

## Intended direction

- [ ] Make each generated model include local to the `.blend` file and source
  assets that produce it.
- [ ] Replace the temporary central `src/asm/models` directory.
- [ ] Introduce a clearly named common-assets directory for textures shared by
  multiple models.
- [ ] Keep editable source assets authoritative:
  - `.blend`;
  - source texture images such as PNG/XCF where applicable;
  - explicit conversion configuration or metadata.
- [ ] Treat `.rgba2` as generated runtime output, not the only authoritative
  texture source.
- [ ] Define how an application declares which model and shared texture assets
  it consumes.
- [ ] Make the build copy generated model `.inc` files into app `src/` and
  runtime `.rgba2` files into app `tgt/`.

## Provenance requirements

- [ ] Audit existing model `.inc` files to determine which generator and
  source assets produced each one.
- [ ] Ensure every generated `.asm` and `.inc` begins with the standard
  auto-generated warning and repository-relative generator path.
- [ ] Record the source `.blend`, mesh/object name, coordinate conversion,
  winding convention, UV conversion, texture source, and Blender version.
- [ ] Make regeneration deterministic enough to compare output with the
  currently accepted includes and binaries.

## Shared texture questions

- [ ] Inventory models that share `blenderaxes.rgba2`, `earthuv.rgba2`, and
  other textures.
- [ ] Decide whether the common-assets directory stores authoritative source
  textures, generated RGBA2 textures, or separate `src` and `tgt` forms.
- [ ] Prevent a model-local build from silently overwriting a shared texture
  with different dimensions or pixel data.
- [ ] Give shared assets stable names and document their dimensions and pixel
  format.

## Migration safety

- [ ] Preserve the currently successful eleven-application build before
  moving model assets.
- [ ] Hash current model includes and textures before relocation.
- [ ] Regenerate into a disposable directory first.
- [ ] Compare rebuilt application binaries and runtime assets with the accepted
  pre-migration versions.
- [ ] Update build, deployment, Blender, and documentation paths together.
- [ ] Do not remove the old model library until every active application can
  build from the new locations.

## Deferred release packaging

- [ ] Design a tracked deployment/release directory.
- [ ] Produce ZIP packages containing a portable app `src/` plus its matching
  runtime `tgt/`.
- [ ] Include generator/version metadata and checksums in each release package.
