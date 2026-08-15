# Pingo Terrain

Experimental terrain research, source-data acquisition, offline generation,
Pingo scene fixtures, and performance evidence for reusable Agon terrain.

This application subtree keeps exploratory work out of maintained firmware
and unrelated applications. It was promoted with its complete standalone Git
history into `pingoasm/apps/fsim` on 2026-08-14. As the work succeeds:

1. reusable client asset tooling and application code may be promoted into
   shared `pingoasm` facilities;
2. proven renderer or protocol changes may be proposed separately to
   `~/Agon/mystuff/agon-vdp`; and
3. research history and rejected experiments remain in this subtree's merged
   history.

Start with the [current regular-hierarchy results](docs/devlog-2026-08-14.md);
the [prior natural and distance-LOD work](docs/devlog-2026-08-13.md) and
[first-day research log](docs/devlog-2026-08-02.md) remain durable. Active work
must first be recorded in the sole authoritative queue at
[`docs/todo.md`](docs/todo.md).

The accepted coordinate, chunk, camera, and cockpit contract is the
[terrain scene design specification](docs/terrain-scene-design.md).
The proposed renderer-integrated ordered-dither design is in the
[flat-pattern dithering proposal](docs/flat-pattern-dithering-proposal.md).
The proposed six-neighbor streaming topology is in the
[hexagonal terrain-cell proposal](docs/hexagonal-terrain-cells.md).
The deterministic silhouette-error, adaptive simplification, and mixed-LOD
seam rules are in the
[mathematical distant-terrain contract](docs/distant-terrain-mathematical-lod.md).
The accepted experiment that generates natural terrain before cutting it into
roughly hex-addressed streaming components is in the
[post-triangulation partition design](docs/natural-terrain-post-partition-experiment.md).
The reusable eZ80 lifecycle and provider ABI are specified in the
[universal terrain-manager runtime contract](docs/terrain-manager-runtime.md).
The current direct no-dynamics camera survey is the
[universal hex-manager fixture](fixtures/terrain-manager-survey/README.md).
The whole-region regular-only distance experiment is the
[regular hierarchy manager fixture](fixtures/terrain-manager-regular-lod-survey/README.md).
The prior [rectangular full-region viewer](fixtures/regional-camera-survey/README.md)
and fixed [dithered Berkeley sibling](fixtures/berkeley-flight-triangular-dither/README.md)
remain historical visual and control oracles.
The regional AGNB/P3DM layout and generated FAA hard-surface proof are in the
[streaming format](docs/p3dm-streaming-format.md) and
[airport corpus](docs/airport-p3dm-corpus.md) documents.
The shared deterministic force, trim, runway-support, cockpit, and fallback
contract is in the [light-flight model](docs/light-flight-model.md).
The backend-neutral static panel scene, bitmap-font seam, and Pillow review
renderer are described in the
[cockpit panel drawing program](docs/cockpit-panel-generator.md).
The current live nested-family integration witness is the
[KOAK fixed-west family-LOD fixture](fixtures/koak-flight-family-lod/README.md),
with the broader packaging and promotion contract in
[regional LOD family bundles](docs/regional-lod-bundles.md).
All eZ80 work must follow the project’s
[ADL fixed-width memory safety rule](docs/adl-fixed-width-safety.md).
The isolated, host- and headless-target-qualified C/assembly seam is documented
in the [AgonDev interoperability experiment](docs/agondev-interop-experiment.md)
and its [regular-LOD policy sibling](fixtures/terrain-manager-regular-lod-c-policy-survey/README.md);
it does not replace the accepted assembly terrain manager.

## Layout

```text
data/manifests/       tracked source-data provenance and checksums
assets/               vendored editable/source artwork with provenance
docs/                 authoritative TODO, specifications, and dated evidence
fixtures/             source and built Pingo terrain qualification scenes
experiments/          isolated source-level toolchain and architecture probes
moslets/              resident MOS launchers and their target artifacts
profiles/             tracked compiler/fixture configuration
scripts/              project setup and command-line entry points
src/pingo_terrain/    offline terrain compiler library
tests/                host-side regression tests
emulator/             ignored project-local PingoWolf emulator profile
```

Downloaded geospatial products live under ignored `data/downloads/`. Generated
host and target artifacts live under ignored `build/`. A downloaded product is
not accepted input until a tracked manifest records its provider, product,
coverage, projection/datum, retrieval date, size, and checksum.

## Python environment

The project uses Python 3.14 and the canonical editable `agonutils` checkout:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install --no-build-isolation --no-deps \
  -e ~/Agon/mystuff/agon-utils
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
```

Verify the environment and scaffold with:

```bash
.venv/bin/python -m pip check
.venv/bin/python ~/Agon/mystuff/agon-utils/tests/test_agonutils.py
.venv/bin/python -m unittest discover -s tests
```

When assembly changes, audit the exact include closure before accepting the
build. This command is also enforced by the regression suite for the approved
dither fixture:

```bash
.venv/bin/python scripts/audit_adl_width.py --follow-includes \
  --show-review --fail-review \
  fixtures/berkeley-flight-triangular-dither/src/berkeley-flight-triangular-dither.asm
```

The checker treats unsuffixed wide-register memory transfers as 24-bit under
ADL and rejects named `dw`/two-byte targets unless a reviewed three-byte
contract is documented with `ADL24 OK: <reason>`.

## Lake Anza feature-aware comparison

The controlled seven-cell comparison decodes the accepted regular P3DM control
and builds a feature-constrained candidate from a 19-cell overbuild context:

```bash
blender --background --python scripts/build_lake_anza_blender.py -- \
  --render-preview
blender build/visualization/lake-anza-control-vs-feature-aware.blend
```

The generated `.blend`, preview, and evidence receipt remain under ignored
`build/visualization/`; the generator, contour/crossing logic, tests, and
durable measurements are tracked.

## Natural full-region post-partition experiment

The complete Bay Area experiment builds one adaptive water-constrained master
surface before assigning its finished faces to connected roughly hex-addressed
components:

```bash
blender --background --python scripts/build_natural_region_blender.py -- \
  --render-preview
blender build/visualization/bay-area-natural-post-partition.blend
```

The terrain object exposes source-count/elevation point attributes and
material/logical-owner face attributes. Hidden diagnostic objects expose all
50,183 logical seeds and the irregular physical partition edges. The accepted
straight-sided N=5 P3DM corpus remains the rollback control; the experimental
natural surface now also has the complete runtime build described below.

## Complete natural runtime manager experiment

The complete runtime build extracts all 50,183 finished face owners from the
accepted master and emits one independently loadable `NAT` P3DM component per
logical cell. It preserves the completed master faces, adds no skirts, and
proves one exact ideal-world integer coordinate across every same-LOD seam
after final Pingo quantization. The universal manager streams a bounded live
neighborhood while the loose corpus covers the entire Bay Area region.
Top-row keys 0 through 5 select 1 through 91 resident components; the viewer
starts at ring five over the Berkeley Marina.

The fifteen source material IDs collapse to three exact opaque Agon base
colors: palette 20 lighter azure for water, palette 7 light gray for developed
land, and palette 21 spring green for every other land class. Each base is a
solid repeated 4x4 pattern. Scene illumination remains active, so any visible
dithering comes from the illumination value band rather than the base color.

```bash
blender --background --python scripts/export_natural_runtime_corpus_blender.py
.venv/bin/python scripts/build_natural_terrain_corpus.py
blender --background --python scripts/build_natural_runtime_review_blender.py
.venv/bin/python scripts/build_fsim_launcher.py
.venv/bin/python scripts/capture_natural_terrain_manager_survey.py \
  --output /tmp/pingo-natural-manager-full
```

The compact, checksum-bound 25.2 MB Blender bridge is written under
`build/source/bay-area-natural-post-partition-v2/`; the 50,183 loose records and
receipts are written to `build/p3dm/bay-area-natural-full-l0/`. The mandatory
derived review file is
`build/visualization/bay-area-natural-three-class-runtime-review.blend`.
The full container payload is 25,251,544 bytes, although 50,183 tiny host files
consume more filesystem allocation. This is still a uniform-L0 visual
experiment: explicit physical-adjacency containment, mixed LOD, hardware SD
bundling, collision, airports, and physical-hardware qualification remain open.

## Emulator

Build the current combined native VDP, then provision this repository's
ignored, fail-closed profile:

```bash
make -C ~/Agon/mystuff/agon-vdp/userspace \
  FAB_ROOT=~/Agon/mystuff/fab-agon-emulator smoke
.venv/bin/python scripts/build_berkeley_camera_survey.py
.venv/bin/python scripts/build_regional_hex_terrain.py --selection full
.venv/bin/python scripts/build_terrain_manager_survey.py
.venv/bin/python scripts/build_regular_lod_corpus.py
.venv/bin/python scripts/build_regular_lod_manager_survey.py
blender --background --python scripts/export_natural_runtime_corpus_blender.py
.venv/bin/python scripts/build_natural_terrain_corpus.py
blender --background --python scripts/build_natural_runtime_review_blender.py
.venv/bin/python scripts/build_fsim_launcher.py
.venv/bin/python scripts/setup_emulator.py
```

Launch from anywhere with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/apps/fsim/emulator
```

The profile maps both `fixtures/` and ignored `build/`, installs the launcher
as `/mos/fsim.bin`, and creates `/mos/fsim.cfg` with the absolute Agon path
`/mystuff/pingoasm/apps/fsim`. Invoke `fsim` from any MOS directory for the numbered
fixture menu; see the [launcher contract](moslets/fsim/README.md).

The regular universal hex-manager survey is entry `0`; the natural
post-partition survey is entry `N`; the rejected mixed-topology control is
entry `D`; and the whole-region regular-only hierarchy is entry `R`. In the
manager fixtures, keys 0 through 5 select the near-field disk. Entry `D` keeps
its 92 static regular distance chunks through ring 30, while entry `R`
replans the generated regular hierarchy around the live position. The old
rectangular survey and its capture tools remain available as historical
evidence:

```bash
.venv/bin/python scripts/capture_regional_camera_survey.py \
  --output /tmp/pingo-regional-camera-capture
.venv/bin/python scripts/trace_regional_camera_streaming.py \
  --output /tmp/pingo-regional-camera-streaming
```

The preserved Berkeley control oracle has its own clamp/reversal trace:

```bash
.venv/bin/python scripts/trace_berkeley_camera_survey.py \
  --output /tmp/pingo-camera-survey-evidence
```

Fresh profiles use a CRLF `autoexec.txt` containing only `SET KEYBOARD 1`.
Setup also retires the exact known older generated fixture presets, but
preserves any other user-edited autoexec byte-for-byte. Emulator behavior requires the
Author's explicit validation before related changes may be committed.
