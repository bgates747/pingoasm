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

## Layout

```text
data/manifests/       tracked source-data provenance and checksums
docs/                 authoritative TODO, specifications, and dated evidence
fixtures/             source and built Pingo terrain qualification scenes
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

## Emulator

Build the current combined native VDP, then provision this repository's
ignored, fail-closed profile:

```bash
make -C ~/Agon/mystuff/agon-vdp/userspace \
  FAB_ROOT=~/Agon/mystuff/fab-agon-emulator smoke
.venv/bin/python scripts/setup_emulator.py
```

Launch from anywhere with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingo_terrain/emulator
```

The profile maps `fixtures` live at `/mystuff/pingo_terrain/fixtures` and
preserves a user-edited CRLF `autoexec.txt`. Emulator behavior requires the
Author's explicit validation before related changes may be committed.
