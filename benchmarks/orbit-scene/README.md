# Pingo multi-object orbit benchmark

This independent benchmark complements, and does not replace, the single-model
`render-spin` stationary and viewport-motion fixtures. It exercises scene-wide
rendering, mutual occlusion, multiple meshes and textures, per-object absolute
poses, and whole-object visibility changes.

## Earth party fixture

`profiles/earth-party-rgba2222.json` defines:

1. EarthUV centered at world `(0, 0, -1000)` with the camera at
   `(0, 0, 3200)`.
2. Crash, Lara, Jet, and Airliner spaced 90 degrees apart on a 2,500-unit
   X-Z orbit.
3. Two complete revolutions sampled every 2.5 degrees, followed by the exact
   closing pose: 289 measured renders.
4. One series with no warmup renders. This fixture favors broad visual and
   visibility-state coverage over strict repeated-run benchmarking.
5. Three Earth Y rotations per orbit.
6. Distinct half-integer XYZ spin rates for every orbiter. Each object is
   deliberately not front-facing after one orbit and returns exactly to its
   starting orientation after two.
7. RGBA2222 source textures and render targets throughout.

At any orbital angle one object is near the camera, one is behind Earth, and
two approach the viewport sides. This provides useful whole-object culling,
clipping, depth-buffer, and overdraw pressure while remaining deterministic.

## Generate

From the project root:

```bash
.venv/bin/python build/scripts/build_orbit_scene.py \
  benchmarks/orbit-scene/profiles/earth-party-rgba2222.json
```

The generator:

1. validates unique mesh, object, and bitmap IDs;
2. rejects spin rates that do not close after the declared orbital period;
3. rejects an orbiter that already returns fully front-facing after one orbit;
4. converts every authoritative OBJ/PNG pair into a prefixed model include and
   RGBA2222 texture;
5. emits provenance-marked, self-contained assembly;
6. assembles `tgt/benchmark.bin`; and
7. rejects an executable plus largest staged texture that would overflow the
   512 KiB eZ80 application window.

The application loads each texture sequentially into the same eZ80 staging
area. It does not attempt to hold all five source textures in eZ80 RAM at once.
The VDP retains the resulting five texture bitmaps.

## Emulator

The isolated current-Pingo emulator exposes the canonical `benchmarks/` tree
by symlink. Its private `autoexec.txt` may select:

```text
cd /mystuff/pingoasm/benchmarks/orbit-scene/fixtures/earth-party-rgba2222/tgt
load benchmark.bin
run
```

The first emulator qualification on 2026-07-29 uploaded all five textures,
rendered the complete animation, restored the normal video mode, and exited
cleanly. A subsequent 2.5-degree hardware review completed all 289 poses with
stable model identities and correct motion. Emulator timings are never
reported as ESP32 performance.

## Hardware SD card

Deploy one generated orbit fixture with:

```bash
.venv/bin/python build/scripts/deploy_orbit_scene.py \
  earth-party-camera-ellipse-rgba2222
```

The source `tgt` contents are copied directly into:

```text
/pingo/<fixture>/benchmark.bin
/pingo/<fixture>/<texture files>
```

There is no project-source hierarchy or redundant `tgt` directory on the
hardware card. The deployer replaces only the selected fixture directory,
preserves render-spin fixtures sharing `/pingo`, and selects only this
application in `autoexec.txt`. Orbit-scene and render-spin fixture names must
remain globally unique; deployment rejects a collision.

## Capture

The generated effective profile is directly consumable by the common
summarizer:

```bash
.venv/bin/python build/scripts/summarize_render_benchmark.py \
  benchmarks/orbit-scene/fixtures/earth-party-rgba2222/effective-profile.json \
  hardware.log \
  --platform hardware \
  --firmware "firmware identity" \
  --json-output earth-party-hardware.json
```

Frame records use `orbit_angle_deg` and `orbit_revolution`; they are not
mislabelled as a single-axis object rotation.

## Camera-dolly fixture

`earth-party-camera-dolly-rgba2222` runs the original two-revolution object
choreography while the camera moves linearly on its Z axis from `10000` to
`2500`, then returns to `10000`, in 2.5-degree sampling steps. The exact near
and far endpoints are included, and every object also returns exactly to its
initial pose.

This deliberately introduces no camera rotation. It exercises absolute camera
translation, view-matrix inversion, changing depth, near-camera clipping, and
whole-object visibility transitions while retaining the now-qualified object
motion.

## Polar elliptical-camera fixture

`earth-party-camera-ellipse-rgba2222` is an independent fixture. The objects
complete their original two orbits while the camera completes one polar
ellipse in the Y-Z plane. Earth is one focus. The camera starts 11,000 units
from Earth, passes over both poles, reaches periapsis 2,500 units beyond
Earth's far side, and returns exactly to its starting pose.

The radius follows the focus-based polar equation
`r = p / (1 - e cos(theta))`, with constant angular sweep rather than
Keplerian timing. The camera points toward Earth using a continuous X rotation
from 0 through -360 degrees; Y rotation and local roll remain zero. At the
polar crossings, camera-forward is parallel to world-up. A conventional
look-at function using a fixed world-up vector would therefore be singular,
while this explicit continuous Euler path chooses the orientation by
continuity and deliberately exercises the +/-90-degree pitch conditions.
