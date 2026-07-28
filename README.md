# Pingo assembly clients and asset pipeline

This repository is the project hub for Pingo assembly applications, fixtures,
Blender/model assets, deployment, and cross-repository notes. Firmware belongs
in `agon-vdp`; emulator implementation belongs in the owned
`fab-agon-emulator:pingo` branch.

## Layout

```text
apps/_common/       shared assembly and model-viewer template
apps/<app>/src/     flat tracked assembly source
apps/<app>/tgt/     flat ignored binaries and runtime textures
src/asm/models/     temporary central model/texture library
src/blender/        editable Blender scenes and source assets
build/scripts/      build, conversion, deployment, and diagnostic tools
docs/               specifications, comparisons, TODOs, and devlogs
archive/            historical material
```

Generated `.asm` and `.inc` files live in the consuming application's `src/`
for portability. They carry a banner naming their generator and authoritative
input. Rerunning the generator replaces them.

The central model library is temporary; see
[Model and asset reorganization TODO](docs/model-asset-reorganization-todo.md).

## Build

```bash
~/Agon/mystuff/pingoasm/.venv/bin/python \
  ~/Agon/mystuff/pingoasm/build/scripts/build_samples.py
```

The build regenerates `movecam` and `moveobj` for five models—jet, cube,
earthuv, triangle, and HeavyTank—then builds `moveair`, `movefsim`, and `wolf`.
It produces 13 binaries and exits on the first assembly failure.

See [Assembly build pipeline](docs/assembly-build-pipeline.md).

## Qualified Pingo fixtures

`apps/turbovega` contains strict triangle, cube, and HeavyTank clients using
only TurboVega commands `0`–`40` and RGBA8888 textures. Cube is the primary
orientation/UV regression. HeavyTank is the chiral winding and compounded
perspective regression.

Pingo 2.15.0 Alpha 1 passed cube and the fresh outward-wound HeavyTank on
hardware and the isolated emulator.

## Deployment

The two project-local emulator profiles are independent:

1. `emulator` retains the older heavily extended Pingo VDP.
2. `emulators/tv-port-baseline` contains the current copied comparison
   snapshot, presently Pingo 2.15.0 Alpha 1. Its historical directory name is
   retained to avoid breaking tooling.

Both expose the canonical `apps/` tree through:

```text
sdcard/mystuff/pingoasm/apps -> ~/Agon/mystuff/pingoasm/apps
```

Rebuilding an application therefore updates emulator-visible files
immediately. Setup and deployment preserve `autoexec.txt`.

Create or repair profiles/mappings:

```bash
cd ~/Agon/mystuff/agon-dev-env
python3 scripts/setup_emulator.py pingoasm
python3 scripts/setup_emulator.py pingo-tv-baseline

cd ~/Agon/mystuff/pingoasm
.venv/bin/python build/scripts/deploy.py emulator
.venv/bin/python build/scripts/deploy.py baseline-emulator
```

Hardware is the only copy deployment:

```bash
.venv/bin/python build/scripts/deploy.py hardware moveobj
.venv/bin/python build/scripts/deploy.py hardware turbovega
```

It replaces `apps/<app>/tgt` at the matching mounted SD path, normally beneath
`/media/smith/AGON`. Deployment never edits `autoexec.txt`.

Refresh the isolated VDP snapshot only after hardware passes:

```bash
make -C ~/Agon/mystuff/agon-vdp/userspace \
  FAB_ROOT=~/Agon/mystuff/fab-agon-emulator smoke
cd ~/Agon/mystuff/agon-dev-env
python3 scripts/setup_emulator.py pingo-tv-baseline \
  --refresh-baseline-vdp
```

Launch from anywhere:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/emulator

~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/emulators/tv-port-baseline
```

Emulator changes require explicit human validation before commit or push.

## Current milestone

The validated firmware banner is:

```text
Agon Pingo VDP Version 2.15.0 Alpha 1 SEP Field
```

The qualified pipeline now has correct camera pose semantics, transforms,
viewport orientation, texture orientation, perspective-correct UVs, and
outward-wound HeavyTank geometry. See
[2026-07-27 devlog](docs/devlog-2026-07-27.md) and
[TurboVega versus upstream](docs/turbovega-vs-upstream-pingo.md).

Historical package and benchmark material remains under `archive/` and
`docs/benchmarks`. The last pre-layout-migration commit is `9da1c25`.
