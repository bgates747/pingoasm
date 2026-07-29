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
benchmarks/          profile-driven timing and asynchronous render fixtures
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

## Render benchmark

`benchmarks/render-spin` generates deterministic Cube and HeavyTank workloads
from JSON profiles. The Cube baseline performs eight warmups followed by 36
absolute 10-degree Y rotations. Firmware reports only `rendererRender()` time;
reserved warmup and measured bitmap IDs identify complete runs inside logs
containing resets or unrelated interactive renders.

Generate the Cube fixture:

```bash
python3 build/scripts/build_render_benchmark.py \
  benchmarks/render-spin/profiles/cube-rgba8888.json
```

Capture hardware traffic from anywhere:

```bash
~/Agon/mystuff/pingoasm/build/scripts/listen_vdp_debug.py \
  --log ~/Agon/mystuff/pingoasm/benchmarks/render-spin/results/my-run.log
```

While listening, press `R` to reset the VDP/Agon and trigger a benchmark
selected by the hardware SD's `autoexec.txt`; use Ctrl+C to stop. See the
[render-spin README](benchmarks/render-spin/README.md).

## Asynchronous render fixture

`benchmarks/render-async` is a functional client for the opt-in Pingo
render-completion callback. Its foreground advances 36 fixed simulation steps
while VDP renders independently, permits one render in flight, and coalesces
obsolete intermediate poses. A one-time general-poll barrier separates queued
scene setup from the first render deadline.

Generate its Cube profile:

```bash
./.venv/bin/python build/scripts/build_render_async.py
```

The 2026-07-28 hardware run visibly completed the full revolution and reported
`PASS`. See the
[render-async README](benchmarks/render-async/README.md).

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

The isolated current-Pingo profile also exposes the canonical `benchmarks/`
tree, so regenerated emulator fixtures need no copy.

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

Generated benchmark fixtures use a deliberately short, runtime-only hardware
layout:

```text
/pingo/<fixture>/benchmark.bin
/pingo/<fixture>/<texture files>
```

There is no source-tree hierarchy or redundant `tgt` directory on the card.
The render-spin and orbit-scene deployers replace only the named fixture
directories within the shared `/pingo` root, so the two suites coexist.
Fixture names form one global hardware namespace; both deployers reject a name
that exists in the other suite:

```bash
.venv/bin/python build/scripts/deploy_render_benchmark_suite.py
.venv/bin/python build/scripts/deploy_orbit_scene.py \
  earth-party-camera-ellipse-rgba2222
```

These benchmark deployers intentionally select their fixture or suite in
`autoexec.txt`. The local `~/copy_to_sd.sh` helper uses the same `/pingo`
convention for every built render-spin fixture and selects the requested
fixture, defaulting to `cube-rgba2222`.

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

The qualified four-byte-working Cube baseline is approximately 232.7 ms mean
renderer time (4.30 equivalent FPS) at 320×240. The qualified one-byte pipeline
retains both source formats and renders directly to a profile-selected RGBA2222
target. Its clean repeat hardware run measured 203.626 ms (4.911 FPS): 12.50%
less renderer time and 14.29% more effective FPS than the best preceding
RGBA2222 implementation. See the
[2026-07-28 devlog](docs/devlog-2026-07-28.md).

Historical package and benchmark material remains under `archive/` and
`docs/benchmarks`. The last pre-layout-migration commit is `9da1c25`.
