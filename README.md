# Pingo Terrain

Experimental terrain research, source-data acquisition, offline generation,
Pingo scene fixtures, and performance evidence for reusable Agon terrain.

This repository keeps exploratory work out of the maintained firmware and
application repositories. If the work succeeds:

1. reusable client asset tooling and application code may be promoted into
   `~/Agon/mystuff/pingoasm`;
2. proven renderer or protocol changes may be proposed separately to
   `~/Agon/mystuff/agon-vdp`; and
3. research history and rejected experiments remain here.

Start with [today's terrain research](docs/devlog-2026-08-02.md). Active work
must first be recorded in the sole authoritative queue at
[`docs/todo.md`](docs/todo.md).

The accepted coordinate, chunk, camera, and cockpit contract is the
[terrain scene design specification](docs/terrain-scene-design.md).
The proposed renderer-integrated ordered-dither design is in the
[flat-pattern dithering proposal](docs/flat-pattern-dithering-proposal.md).
The proposed six-neighbor streaming topology is in the
[hexagonal terrain-cell proposal](docs/hexagonal-terrain-cells.md).
The current direct no-dynamics camera survey is the
[full-region rolling fixture](fixtures/regional-camera-survey/README.md).
Its fixed [dithered Berkeley sibling](fixtures/berkeley-flight-triangular-dither/README.md)
remains the exact visual and control oracle.
The regional AGNB/P3DM layout and generated FAA hard-surface proof are in the
[streaming format](docs/p3dm-streaming-format.md) and
[airport corpus](docs/airport-p3dm-corpus.md) documents.
The shared deterministic force, trim, runway-support, cockpit, and fallback
contract is in the [light-flight model](docs/light-flight-model.md).
The current live nested-family integration witness is the
[KOAK fixed-west family-LOD fixture](fixtures/koak-flight-family-lod/README.md),
with the broader packaging and promotion contract in
[regional LOD family bundles](docs/regional-lod-bundles.md).
All eZ80 work must follow the project’s
[ADL fixed-width memory safety rule](docs/adl-fixed-width-safety.md).

## Layout

```text
data/manifests/       tracked source-data provenance and checksums
assets/               vendored editable/source artwork with provenance
docs/                 authoritative TODO, specifications, and dated evidence
fixtures/             source and built Pingo terrain qualification scenes
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

## Emulator

Build the current combined native VDP, then provision this repository's
ignored, fail-closed profile:

```bash
make -C ~/Agon/mystuff/agon-vdp/userspace \
  FAB_ROOT=~/Agon/mystuff/fab-agon-emulator smoke
.venv/bin/python scripts/build_berkeley_camera_survey.py
.venv/bin/python scripts/build_regional_camera_survey.py
.venv/bin/python scripts/build_fsim_launcher.py
.venv/bin/python scripts/setup_emulator.py
```

Launch from anywhere with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingo_terrain/emulator
```

The profile maps both `fixtures/` and ignored `build/`, installs the launcher
as `/mos/fsim.bin`, and creates `/mos/fsim.cfg` with the absolute Agon path
`/mystuff/pingo_terrain`. Invoke `fsim` from any MOS directory for the numbered
fixture menu; see the [launcher contract](moslets/fsim/README.md).

The full-region survey fixture is entry `0`. Its complete initial window and a
live eastward cell crossing can be qualified silently with:

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
