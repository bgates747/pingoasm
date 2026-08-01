# Pingo assembly clients and asset pipeline

This repository is the project hub for Pingo assembly applications, fixtures,
Blender/model assets, deployment, and cross-repository notes. Firmware belongs
in `agon-vdp`; emulator implementation belongs in the owned
`fab-agon-emulator:pingo` branch.

## Layout

```text
apps/earth-party-tex/   showcased fully textured application
apps/earth-party-flat/  showcased mixed flat/textured application
tests/apps/             preserved application-level regression fixtures
benchmarks/             profile-driven performance and torture fixtures
src/asm/models/         temporary central model/texture library
src/blender/            editable Blender scenes and source assets
build/scripts/          build, conversion, deployment, and diagnostic tools
docs/                   authoritative TODO, specifications, and devlogs
archive/                historical material
```

Generated `.asm` and `.inc` files live in the consuming application's `src/`
for portability. They carry a banner naming their generator and authoritative
input. Rerunning the generator replaces them.

Current work belongs only in the [authoritative TODO](docs/todo.md). The
central model library is temporary; its detailed historical scope is retained
in the [model and asset reorganization planning
record](docs/model-asset-reorganization-todo.md), while promoted actions use
the `A` IDs in the authoritative TODO.

## Build

```bash
~/Agon/mystuff/pingoasm/.venv/bin/python \
  ~/Agon/mystuff/pingoasm/build/scripts/build_samples.py
```

The build regenerates `movecam` and `moveobj` for five models—jet, cube,
earthuv, triangle, and HeavyTank—then builds `moveair`, `movefsim`, `wolf`, and
the source-preserved asynchronous `moveobj-local` and `moveair-local` Jet
clients. It also regenerates the six prefixed models, real-star sky, and seven
textures for the interactive `earth-party-tex` application, then validates
and builds its `earth-party-flat` rendering-policy sibling and the
`lighting-shading` qualification fixture. The complete build produces 18
binaries and exits on the first assembly failure.

See [Assembly build pipeline](docs/assembly-build-pipeline.md).

## Showcase: Earth Party

Earth Party is the principal Pingo demonstration. Both editions provide a
flyable Jet, eZ80-owned asynchronous simulation, a tracking camera, rotating
Earth, four independently orbiting models, and a firmament of 128 catalogued
stars. They differ only in rendering policy:

1. [`earth-party-tex`](apps/earth-party-tex/README.md) texture-maps every model.
2. [`earth-party-flat`](apps/earth-party-flat/README.md) uses predominant-color
   flat shading for Jet and Airliner, self-illuminated flat stars, and textured
   scene-lit rendering for the other models.

Build either application directly:

```bash
.venv/bin/python build/scripts/build_earth_party_tex.py
.venv/bin/python build/scripts/build_earth_party_flat.py
```

## Preserved application fixtures

`tests/apps/moveobj-local` and `tests/apps/moveair-local` keep authoritative object pose
and local velocities on the eZ80. Both advance fixed four-MOS-tick simulation
steps at 30 Hz while current Pingo renders independently, allow one render in
flight, and coalesce intermediate poses until the `P3DR` completion callback
makes the renderer available. `moveobj-local` derives transient translation
from held controls; `moveair-local` retains forward velocity between ticks and
uses W/S as throttle. It also keeps a camera pose on the eZ80, aims that fixed
world-space camera at the newest Jet position on simulation ticks, and sends
only dirty absolute camera commands before rendering. Their 320×240
render-target constants are the primary render-throughput knob; changing them
does not change simulation time.

### Earth Party implementation

`apps/earth-party-tex` retains the moveair Jet and tracking camera while
adding Earth, Crash, Lara, HeavyTank, and Airliner. Earth spins about a tilted
axis. The four companions begin 90 degrees apart and obtain closed circular
motion solely from persistent local forward and yaw velocities; their world
positions are not scripted. Its profile-driven hybrid builder regenerates
portable prefixed model includes and sequentially staged RGBA2222 textures
from the authoritative OBJ/PNG sources. A tracked Bright Star Catalogue
selection adds 128 real stars with magnitude-scaled five-point glyphs and
exaggerated B−V colors. Six spatial batches share one palette texture so
Pingo's object-level frustum culling can reject most of the sky cheaply.

`apps/earth-party-flat` preserves the same scene, controls, asynchronous
simulation architecture, and sampled Earth rotation while turning Jet and
Airliner into predominant-palette-color flat meshes, selecting flat native-
color rendering for all six self-illuminated star sectors, and setting the
scene-lit ambient floor to 32/127. Its orbiters use the later, slower closed
three-revolution cycle documented by the app. Earth, Crash, Lara, and
HeavyTank remain textured and scene-lit.

### Lighting and shading qualification

`tests/apps/lighting-shading` displays four simultaneous views of a textured Cube
and a flat-palette Cube. The panels exercise default lighting, a side light,
overdrive plus ambient light, and illumination bypass. Both mesh modes remain
on the established Pingo geometry, clipping, depth, and RGBA2222 paths.

Its normal build validates the tracked final flat-palette UV words and fails
if one source triangle selects more than one palette cell; it does not silently
regenerate edited source. Use the explicit `--regenerate` option only when the
canonical OBJ, texture, palette, common VDU helper, or conversion code changes:

```bash
.venv/bin/python build/scripts/build_lighting_shading.py
.venv/bin/python build/scripts/build_lighting_shading.py --regenerate
```

The two Cubes are at `(−480,0,0)` and `(+480,0,0)`. The unrotated camera is at
`(0,0,+3200)` and looks along canonical `−Z` toward the scene; the positive-Z
camera position is intentional under the project's right-handed convention.

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

## Deployment

The project owns exactly one generated local profile at `emulator`. It uses
the combined PingoWolf native VDP built from the `pingowolf` branch of
`~/Agon/mystuff/agon-vdp` and exposes the showcased apps, preserved tests, and
benchmarks through live mappings:

```text
sdcard/mystuff/pingoasm/apps -> ~/Agon/mystuff/pingoasm/apps
sdcard/mystuff/pingoasm/tests/apps -> ~/Agon/mystuff/pingoasm/tests/apps
sdcard/mystuff/pingoasm/benchmarks -> ~/Agon/mystuff/pingoasm/benchmarks
```

Rebuilding an application therefore updates emulator-visible files
immediately. Setup and deployment preserve a user-edited `autoexec.txt`; a
new profile defaults to Earth Party Textured. MOS text uses CRLF endings.

Build the native VDP and create or repair the profile on rails:

```bash
make -C ~/Agon/mystuff/agon-vdp/userspace \
  FAB_ROOT=~/Agon/mystuff/fab-agon-emulator smoke
cd ~/Agon/mystuff/agon-dev-env
python3 scripts/setup_emulator.py pingoasm

cd ~/Agon/mystuff/pingoasm
.venv/bin/python build/scripts/deploy.py emulator
```

Hardware is the only copy deployment:

```bash
.venv/bin/python build/scripts/deploy.py hardware earth-party-tex
.venv/bin/python build/scripts/deploy.py hardware earth-party-flat
```

Deploy the complete combined application payload as flat sibling directories
at `/PingoWolf/Pingo` and `/PingoWolf/Wolf` (clearing both destinations first)
and leave MOS at `/PingoWolf` on boot:

```bash
.venv/bin/python build/scripts/deploy_pingowolf_sd.py
```

It replaces the selected `apps/<app>/tgt` or `tests/apps/<fixture>/tgt` at the
matching mounted SD path, normally beneath `/media/smith/AGON`. Deployment
never edits `autoexec.txt`.
After every card write, flush and safely unmount the hardware SD, verify that
its partition is no longer mounted, and only then ask the author to move it
from the PC to an Agon. Routine dismounting is part of the deployment
workflow, not a manual cleanup left to the author.

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

Launch from anywhere:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/emulator
```

Emulator changes require explicit human validation before commit or push.

## Current milestone

The current combined firmware banner is:

```text
Agon Platform VDP Version 2.16.0 Bistromathics
Pingo 0.1.0 Alpha 1
Wolf3DOrig 0.1.0 Alpha 1
```

The qualified pipeline has correct camera pose semantics, transforms,
viewport orientation, texture orientation, perspective-correct UVs,
scene-wide lighting controls, flat-palette shading, self-illuminated meshes,
and combined Pingo/Wolf dispatch. See the dated development logs for the
chronological evidence.

The qualified four-byte-working Cube baseline is approximately 232.7 ms mean
renderer time (4.30 equivalent FPS) at 320×240. The qualified one-byte pipeline
retains both source formats and renders directly to a profile-selected RGBA2222
target. Its clean repeat hardware run measured 203.626 ms (4.911 FPS): 12.50%
less renderer time and 14.29% more effective FPS than the best preceding
RGBA2222 implementation. See the
[2026-07-28 devlog](docs/devlog-2026-07-28.md).

Historical package and benchmark material remains under `archive/` and
`docs/benchmarks`. The last pre-layout-migration commit is `9da1c25`.
