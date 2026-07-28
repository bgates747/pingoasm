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

The project owns two completely independent emulator profiles:

1. `emulator` runs the existing heavily modified and extended Pingo VDP.
2. `emulators/tv-port-baseline` runs the VDP 2.15 plus TurboVega-final
   historical baseline.

Both profiles expose the canonical project `apps/` tree through a host
filesystem symlink:

```text
emulator/sdcard/mystuff/pingoasm/apps
    -> ~/Agon/mystuff/pingoasm/apps
```

The baseline profile has the same mapping beneath its own `sdcard`. Rebuilding
an application therefore updates both emulators immediately; application files
are never copied between project space and emulator profiles. Setup and
deployment preserve each profile's user-controlled `autoexec.txt`.

Create or refresh either project-local emulator:

```bash
cd ~/Agon/mystuff/agon-dev-env
python3 scripts/setup_emulator.py pingoasm
python3 scripts/setup_emulator.py pingo-tv-baseline
```

Create or repair the live emulator mapping, or copy an app to hardware:

```bash
cd ~/Agon/mystuff/pingoasm
.venv/bin/python build/scripts/deploy.py emulator
.venv/bin/python build/scripts/deploy.py baseline-emulator
.venv/bin/python build/scripts/deploy.py hardware moveobj
.venv/bin/python build/scripts/deploy.py both moveobj
```

The baseline setup copies a frozen `vdp_pingo.so` snapshot into its profile
and records runtime and fixture hashes in `baseline-manifest.txt`. Ordinary
application deployment cannot replace that module. To deliberately establish
a new baseline module:

```bash
make -C ~/Agon/mystuff/agon-vdp/userspace \
  FAB_ROOT=~/Agon/mystuff/fab-agon-emulator smoke
cd ~/Agon/mystuff/agon-dev-env
python3 scripts/setup_emulator.py pingo-tv-baseline \
  --refresh-baseline-vdp
```

Only hardware deployment copies application files out of project space. It
remains app-specific: it copies
`apps/<app>/tgt` to `/mystuff/pingoasm/apps/<app>/tgt`. It requires the SD card
to be mounted at `/media/smith/AGON` unless `--sd-mount` is supplied.
Mount-point, expected-path, and symlink guards are enforced.

Deployment does not rewrite any emulator or hardware `autoexec.txt` file.
To load the jet demo:

```text
cd /mystuff/pingoasm/apps/moveair/tgt
load jet.bin
```

Launch either project-local Pingo emulator from anywhere with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/emulator

~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/emulators/tv-port-baseline
```

The baseline profile initially runs
`/mystuff/pingoasm/apps/turbovega/tgt/cube.bin`. Its separate autoexec can be
changed without affecting the extended emulator.

The cube fixture has been visually qualified as matching the hardware
baseline. Its substantially higher emulator speed is expected for
video-buffer applications and is not evidence of a firmware mismatch.

## Historical material

The old Alpha 5 package matrix is retained under `archive/asm/apps5`.
Frame-rate observations formerly stored beside assembly source are under
`docs/benchmarks`. The last repository state before the application-layout
migrations is commit `9da1c25`.
