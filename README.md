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

## Sample deployment

Each direct child of `src/asm/` is a self-contained sample package. Its
assembly source, executable, include files, textures, and supporting runtime
files are deployed together to the same path on emulator and hardware:

```text
/mystuff/pingoasm/src/asm/<sample>
```

Create the project-local emulator once:

```bash
cd ~/Agon/mystuff/agon-dev-env
python3 scripts/setup_emulator.py pingoasm
```

After rebuilding a sample, replace its emulator copy:

```bash
cd ~/Agon/mystuff/pingoasm
.venv/bin/python build/scripts/deploy.py emulator moveobj
```

With the Agon SD card mounted at `/media/smith/AGON`, deploy the identical
package to hardware:

```bash
.venv/bin/python build/scripts/deploy.py hardware moveobj
```

Both deployments are also available as one explicit operation:

```bash
.venv/bin/python build/scripts/deploy.py both moveobj
```

The hardware path is guarded in the same manner as AgonWolf3D deployment: the
mount must be a real mount point, the destination must be the expected
`mystuff/pingoasm/src/asm/<sample>` path, and symlinked deployment targets are
refused.

Launch the project-local Pingo emulator from anywhere with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/emulator
```
