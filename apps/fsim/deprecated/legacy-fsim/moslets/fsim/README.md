# FSIM fixture launcher

`fsim` is a resident MOSlet that provides one menu for the runnable Pingo
terrain appliances. It may be invoked from any MOS working directory:

```text
fsim
```

The numbered controls and the additional natural-terrain shortcut are:

| Key | Appliance | Purpose |
|---|---|---|
| 1 | Rectangular Berkeley | Original embedded-grid free-flight control |
| 2 | Triangular Berkeley | Continuous, self-lit triangular-lattice terrain |
| 3 | Dithered Berkeley | Scene-lit terrain using flat-pattern shading |
| 4 | Berkeley Light Flight | Cockpit presentation and deterministic dynamics |
| 5 | KOAK Streamed | Runway 28L with loose position-streamed terrain records |
| 6 | KOAK Family LOD | Runway 28L with the nested-family mixed-LOD handoff |
| 7 | P3DM Loader Probe | Atomic publication of one loose terrain record |
| 8 | Nested AGNB Probe | Selection of one component from a ten-record family |
| 9 | Campanile Probe | Streamed solid-flat Sather Tower landmark |
| 0 | Hex Manager Survey | Direct camera over the full axial-hex corpus using the universal manager |
| N | Natural Survey | Direct camera over the full post-partition natural corpus using the same manager |

Entry 0 starts at the accepted Campanile position without aircraft, dynamics,
or collision. Top-row keys 0 through 5 change its complete terrain disk at run
time, selecting 1, 7, 19, 37, 61, or 91 resident cells. Motion selects further
cells from the complete 50,183-record hex corpus through the same manager API
available to arbitrary future clients. The prior rectangular regional survey
remains preserved as a historical direct-streaming oracle.

Entry N starts over the Berkeley Marina with the reviewed south-facing pose and
loads from the complete 50,183-component natural corpus. It starts at the
maximum accepted ring five and retains the 0-through-5 live controls. The
provider clips only at the true regional boundary. Entry 0 remains the regular
straight-sided N=5 control instead of being silently replaced.

Press the corresponding digit, or N/n, to run a fixture. Escape inside an
interactive fixture returns to this menu; press Escape again at the menu to
leave `fsim` and return to the ordinary MOS prompt. The launcher waits for
keys to be physically released at both boundaries, so the Escape consumed by
a fixture cannot also exit the launcher.

## Path and entry contract

`/mos/fsim.cfg` contains one absolute MOS path naming the project root. The
project-local emulator installation writes:

```text
/mystuff/pingoasm/apps/fsim
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
.venv/bin/python scripts/build_regional_hex_terrain.py --selection full
.venv/bin/python scripts/build_terrain_manager_survey.py
blender --background --python scripts/export_natural_runtime_corpus_blender.py
.venv/bin/python scripts/build_natural_terrain_corpus.py
blender --background --python scripts/build_natural_runtime_review_blender.py
.venv/bin/python scripts/build_fsim_launcher.py
.venv/bin/python scripts/setup_emulator.py
```

The first command rebuilds the fixed Berkeley oracle. The next two build and
verify all 50,183 indexed axial-hex containers and assemble entry 0 as
`P3DHXMG.BIN`. The following three commands extract the compact complete
natural source, build entry N as `P3DNAT.BIN`, and save its required
full-region Blender review artifact.
The launcher command then assembles `moslets/fsim/src/fsim.asm` into
`moslets/fsim/tgt/fsim.bin` and emits its listing and symbols. Other fixture
binaries and runtime assets must already exist in their normal `tgt/` or
ignored `build/` locations. Setup maps the project `fixtures/` and `build/`
trees into the dedicated SD image, installs the MOSlet as `/mos/fsim.bin`, and
writes `/mos/fsim.cfg`.

Launch the dedicated emulator from any host directory with:

```bash
~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh \
  ~/Agon/mystuff/pingoasm/apps/fsim/emulator
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
