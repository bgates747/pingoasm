# FSIM fixture launcher

`fsim` is a resident MOSlet that provides one menu for the runnable Pingo
terrain appliances. It may be invoked from any MOS working directory:

```text
fsim
```

The numbered entries are:

| Key | Appliance | Purpose |
|---:|---|---|
| 1 | Rectangular Berkeley | Original embedded-grid free-flight control |
| 2 | Triangular Berkeley | Continuous, self-lit triangular-lattice terrain |
| 3 | Dithered Berkeley | Scene-lit terrain using flat-pattern shading |
| 4 | Berkeley Light Flight | Cockpit presentation and deterministic dynamics |
| 5 | KOAK Streamed | Runway 28L with loose position-streamed terrain records |
| 6 | KOAK Family LOD | Runway 28L with the nested-family mixed-LOD handoff |
| 7 | P3DM Loader Probe | Atomic publication of one loose terrain record |
| 8 | Nested AGNB Probe | Selection of one component from a ten-record family |
| 9 | Campanile Probe | Streamed solid-flat Sather Tower landmark |
| 0 | Bay Area Survey | Direct upright camera over the full regional loose-L0 corpus |

Entry 0 starts at the accepted Campanile position without aircraft, dynamics,
or collision. Only its rolling 8×4 terrain window is resident at once; motion
selects further cells from the complete 50,652-record corpus.

Press the corresponding single digit to run a fixture. Escape inside an
interactive fixture returns to this menu; press Escape again at the menu to
leave `fsim` and return to the ordinary MOS prompt. The launcher waits for
keys to be physically released at both boundaries, so the Escape consumed by
a fixture cannot also exit the launcher.

## Path and entry contract

`/mos/fsim.cfg` contains one absolute MOS path naming the project root. The
project-local emulator installation writes:

```text
/mystuff/pingo_terrain
```

The launcher saves the caller's working directory, combines that root with
the selected appliance's relative runtime directory, and silently changes to
it before loading. This makes each fixture's relative terrain, palette,
pattern, cockpit, aircraft, and container paths resolve normally. The original
working directory is restored after every fixture and again before the MOSlet
returns. A missing or malformed configuration, failed directory change,
failed load, or incompatible executable is reported without calling an
unknown address.

All listed fixtures load at `0x040000` and expose the same callable public
entry there: their first instruction jumps over the aligned MOS executable
header to the normal saved-register wrapper. `fsim` validates both that jump
and the header before it calls `0x040000`. The fixture's final `RET` therefore
returns to the resident launcher. The same binary may still be loaded and run
directly from MOS; in that case the identical `RET` returns directly to MOS.
New menu fixtures must preserve this entry structure and must keep all runtime
paths relative to their selected working directory.

## Build and emulator installation

Use the project virtual environment from the repository root:

```bash
.venv/bin/python scripts/build_berkeley_camera_survey.py
.venv/bin/python scripts/build_regional_camera_survey.py
.venv/bin/python scripts/build_fsim_launcher.py
.venv/bin/python scripts/setup_emulator.py
```

The first command rebuilds the fixed Berkeley oracle. The second verifies all
50,652 indexed regional containers and assembles entry 0 as `P3DSURV.BIN`.
The launcher command then assembles `moslets/fsim/src/fsim.asm` into
`moslets/fsim/tgt/fsim.bin` and emits its listing and symbols. Other fixture
binaries and runtime assets must already exist in their normal `tgt/` or
ignored `build/` locations. Setup maps the project `fixtures/` and `build/`
trees into the dedicated SD image, installs the MOSlet as `/mos/fsim.bin`, and
writes `/mos/fsim.cfg`.

Launch the dedicated emulator from any host directory with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingo_terrain/emulator
```

The launcher is explicit rather than an auto-run payload. The project-owned
`autoexec.txt` policy is the single CRLF-terminated keyboard directive:

```text
SET KEYBOARD 1
```

There is no `cd`, `load`, `run`, or `fsim` command in that file. Emulator
installation and launcher behavior remain subject to the project's explicit
human-validation gate before commit or promotion.

The private lifecycle qualification does not alter that profile or autoexec:

```bash
.venv/bin/python scripts/qualify_fsim_launcher.py \
  --output /tmp/pingo-fsim-launcher-qualification
```

It drives menu entry 8, returns with one Escape, exits FSIM with a distinct
second Escape, and proves the caller's real FatFS directory by loading a
harness-only relative witness before reaching a mode-0 MOS prompt.
