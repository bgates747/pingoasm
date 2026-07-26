# Pingo assembly clients and asset pipeline

This repository owns the Pingo assembly applications and their Blender/model
asset pipeline. Pingo firmware and native renderer code belong in `agon-vdp`;
emulator integration belongs in the owned `fab-agon-emulator:pingo` branch.

## Repository layout

```text
apps/
    _common/       authoritative shared assembly and model-viewer template
    moveair/
        src/       flat assembly source
        tgt/       ignored runtime files
    movecam/
        src/
        tgt/
    movefsim/
        src/
        tgt/
    moveobj/
        src/
        tgt/
    wolf/
        src/
        tgt/

src/asm/models/    temporary model include and texture library
src/blender/       editable Blender scenes and source assets
build/scripts/     build, deployment, conversion, and diagnostic tools
archive/           retained historical material
docs/              pipeline notes, decisions, and measurements
```

Every application has a flat `src/` and `tgt/`:

- `src/` contains only `.asm` and `.inc` files;
- `tgt/` contains only assembled `.bin` files and runtime `.rgba2` textures;
- `tgt/` is generated locally and ignored by Git.

`apps/_common` is not an application. It holds shared authoritative inputs.
Any common file needed to assemble a generated application is copied into that
application's `src/`, making the resulting source directory portable.

Generated `.asm` and `.inc` files are tracked and begin with a conspicuous
banner naming the script and authoritative input that produced them. They may
be copied elsewhere for experimentation, but rerunning the generator replaces
the versions inside the generated application directories.

The current `src/asm/models` layout is deliberately temporary. Its planned
replacement is recorded in
[Model and asset reorganization TODO](docs/model-asset-reorganization-todo.md).

## Build

Build all applications from anywhere inside or outside the repository with:

```bash
~/Agon/mystuff/pingoasm/.venv/bin/python \
  ~/Agon/mystuff/pingoasm/build/scripts/build_samples.py
```

The build:

- regenerates `apps/movecam/src` and `apps/moveobj/src`;
- assembles four generic models for both control modes;
- assembles the specialized `moveair`, `movefsim`, and `wolf` applications;
- writes all eleven binaries into their respective ignored `tgt/` directories;
- exits nonzero on the first failed assembly;
- prints every successfully produced binary.

See [Assembly build and sample-packaging pipeline](docs/assembly-build-pipeline.md)
for history, generated-file rules, and remaining limitations.

## Deployment

Emulator deployment completely clears the project-local emulated SD card and
copies the entire `apps/` tree beneath `/mystuff/pingoasm`:

```text
apps/
    -> /mystuff/pingoasm/apps/
```

The resulting emulator SD contains only this application tree and the existing
user-controlled `autoexec.txt`. Deployment preserves `autoexec.txt` unchanged.

Create or refresh the project-local emulator:

```bash
cd ~/Agon/mystuff/agon-dev-env
python3 scripts/setup_emulator.py pingoasm
```

Deploy a rebuilt app:

```bash
cd ~/Agon/mystuff/pingoasm
.venv/bin/python build/scripts/deploy.py emulator
.venv/bin/python build/scripts/deploy.py hardware moveobj
.venv/bin/python build/scripts/deploy.py both moveobj
```

Hardware deployment remains app-specific: it copies
`apps/<app>/tgt` to `/mystuff/pingoasm/apps/<app>/tgt`. It requires the SD card
to be mounted at `/media/smith/AGON` unless `--sd-mount` is supplied.
Mount-point, expected-path, and symlink guards are enforced.

Deployment does not rewrite either emulator or hardware `autoexec.txt` files.
To load the jet demo:

```text
cd /mystuff/pingoasm/apps/moveair/tgt
load jet.bin
```

Launch the project-local Pingo emulator from anywhere with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/emulator
```

## Historical material

The old Alpha 5 package matrix is retained under `archive/asm/apps5`.
Frame-rate observations formerly stored beside assembly source are under
`docs/benchmarks`. The last repository state before the application-layout
migrations is commit `9da1c25`.
