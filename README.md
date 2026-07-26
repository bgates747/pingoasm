# Pingo assembly clients and asset pipeline

This repository owns:

- Agon assembly clients and their deployable runtime assets under `src/asm/`;
- Blender source scenes and model assets under `src/blender/`;
- Blender, mesh, texture, image-conversion, and diagnostic pipeline scripts
  under `build/scripts/`.

Pingo firmware and native renderer code belong in `agon-vdp`. Emulator
build/run/regression orchestration belongs in the owned
`fab-agon-emulator:pingo` branch.

See [Rendering and asset pipeline](docs/rendering-pipeline.md) before changing
or invoking the existing pipeline scripts.
