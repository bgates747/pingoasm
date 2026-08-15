# Deterministic headless flight-input tracing

Fab has a suitable keyboard-injection boundary, but no headless command-line
or IPC front end for it. `src/main.rs` converts SDL key events to PS/2 set-2
codes and calls the native VDP ABI function `sendPS2KbEventToFabgl(code,
down)`. `src/vdp_interface.rs` requires that symbol, and
`src/vdp/rust_glue.cpp` passes it to FabGL's keyboard scancode injector. The
normal interactive and new diagnostic paths therefore enter at exactly the
same point below SDL.

The existing debugger can pause, inspect, step, and stop the eZ80, but cannot
inject a key or write memory. Fab's separate CLI emulator can synthesize MOS
key packets from stdin, but its fake VDP cannot run Pingo. Neither is a
replacement for the native-VDP input hook.

## Diagnostic mechanism

`tools/vdp_input_trace_proxy.c` is a complete forwarding implementation of
Fab's current native VDP ABI. Fab loads the proxy through its ordinary
`--vdp` option; the proxy loads the unchanged real module named by
`FAB_INPUT_REAL_VDP`. On each host vblank it drains newline-delimited commands
from the named pipe in `FAB_INPUT_FIFO` and calls the real module's
`sendPS2KbEventToFabgl` function.

The accepted command forms are:

```text
down 0x001d
up 0x001d
tap 0x002a 4
tapafter 0xe072 380 8
```

`tap` emits a make at the consuming vblank and a break after exactly the given
number of later host vblanks. Every event produces a record such as:

```text
FAB_INPUT frame=100 action=down scancode=0x002a source=fifo-tap
FAB_INPUT frame=104 action=up scancode=0x002a source=tap-release
```

`tapafter CODE DELAY HOLD` emits no immediate key event. If its command is
consumed at host vblank `N`, the make is emitted at `N + DELAY` and the break
at `N + DELAY + HOLD`. Both counts must be positive. Delayed make/break pairs
share a bounded 64-event queue; a full queue, malformed command, or requested
deadline overflow is reported as `FAB_INPUT_ERROR` rather than silently
changing the schedule. The takeoff driver writes its initial V, W, and delayed
pitch commands as one sub-512-byte FIFO payload, so all three have the same
consuming-vblank origin under POSIX's portable atomic-write guarantee.

The proxy fails closed when the real module, FIFO, or any required ABI symbol
is missing. It validates that the input path is actually a named pipe and does
not modify Fab, the real Pingo module, the KOAK program, or its coordinator.

The controls needed by the light-flight fixture use these complete set-2 make
codes, taken from Fab's own `src/sdl2ps2.rs` table:

| Control | Code |
| --- | ---: |
| W / S | `0x001d` / `0x001b` |
| A / D | `0x001c` / `0x0023` |
| V | `0x002a` |
| Up / Down | `0xe075` / `0xe072` |
| Left / Right | `0xe06b` / `0xe074` |
| Escape | `0x0076` |

Extended codes stay in one 16-bit value because that is the existing Fab ABI
contract.

## KOAK proof driver

`scripts/trace_koak_input.py` builds the proxy with warnings as errors, checks
all 15 required exports, starts a fresh emulator with dummy SDL video and
audio plus the software renderer, and selects the real diagnostic PingoWolf
module explicitly. It waits for an application-level Pingo render marker
rather than guessing how many host frames MOS and file loading will take.

After cockpit sequence 30 completes, the driver taps V for four vblanks. It
requires the command-51 record that activates exterior object 201 and retains
chase sequence 60. It then taps Escape, requires both make and break records,
and uses Fab's established debugger path for orderly shutdown. Run it with the
project virtual environment:

```sh
.venv/bin/python scripts/trace_koak_input.py \
  --output /tmp/pingo-koak-input-trace
```

Two consecutive 2026-08-02 qualification runs both exited with status zero
and produced byte-identical Pingo targets:

| View and sequence | RGBA2222 SHA-256 |
| --- | --- |
| Initial, 0 | `66e8797ef9cb9ca2197ea9ba612b7c7ff8f65470b7978085e0edbb764dc8186f` |
| Cockpit, 30 | `c5c1e706c4c30f5242ac1f2c560d8efb7f3a242c94ec1aa51708e5c539fdfbfc` |
| Chase, 60 | `347fbeebd41798c60b31b5f2d2909356c5fdeec5dbd5d3a695dc7cfb7ce7fe53` |

The first run injected V at host vblanks 100/104 and Escape at 160/164; the
repeat used 97/101 and 157/161 because boot and file loading crossed three
fewer host vblanks. This is intentional: synchronization is to the exact
application render sequence, while the make-to-break duration is exact in
host vblanks. Absolute boot-relative vblank numbers are evidence, not a
fragile timing assumption.

This proves the emulator input path and deterministic flight-fixture response.
It does not replace physical keyboard/control-feel testing, and the proxy,
driver, evidence, or documentation remain emulator-coupled changes subject to
the explicit human validation gate before commit.

## KOAK takeoff proof

`scripts/trace_koak_takeoff.py` extends the same path into a complete runway
departure. It first assembles an isolated copy of the exact fixture source with
symbol export enabled and refuses to continue unless that binary's SHA-256
matches the `P3DFSIM.BIN` being tested. After completed cockpit render 30 it
atomically schedules a four-vblank V tap, full W throttle, and an eight-vblank
Down pulse delayed by 380 host vblanks. An optional Up counter-pulse is
available but is disabled for the qualified profile.

At completed chase render 520 the driver releases W, pauses Fab, and installs a
breakpoint on the exported `submit_current_render` address. That next boundary
is after physics, floating-origin rebasing, and object/camera publication, so
the debugger cannot sample half of a multi-byte state transaction. The driver
then reads the packed 77-byte flight state, 64-byte object state, and adjacent
coarse-cell bytes, exits through the debugger, and validates:

- exact event count, source, common V/W origin, delay, and hold durations;
- no arithmetic failure, runway-support release, and positive climb velocity;
- airspeed at or above `3200`, full throttle with thrust `28`, positive AGL,
  and at least 250 m horizontal travel;
- distinct initial, cockpit, and airborne render targets.

Run it headlessly and silently into a new evidence directory:

```sh
.venv/bin/python scripts/trace_koak_takeoff.py \
  --output /tmp/pingo-koak-takeoff
```

Two 2026-08-02 runs qualified the same fixture binary
`9ac87b36695af3296cb11820f21aae231e87f1710e8e92e1125c711aa596f2e8`:

| Evidence | Run C | Run D |
| --- | ---: | ---: |
| report SHA-256 | `4e5021db6ca106471fa50cc4034bf5831d41214728f5280b50ad079e4a09fb5e` | `a36ca44736ac8325b88d45ee83d34ab9a26ceabedde91e567db684c779b8bd82` |
| log SHA-256 | `f151fe8ef041c1831a83efaef2af6e8e4efb415a2a9aa4aea3c6380a1b9be99a` | `cffbb28711194c1724950f964c939f76e5706e4ddab2030ecffe7e1d350ea375` |
| AGL | 9.959 m | 9.815 m |
| velocity Q8 | `[1827, 593, 4613]` | `[1827, 588, 4612]` |
| airspeed Q8 | 4993 | 4991 |
| horizontal travel | 398.863 m | 397.651 m |
| airborne RGBA2222 SHA-256 | `81a5d422e45c4eb01c9fee52ad8705823f3d091fdc259934334d3a1fe3725822` | `ff0a3774f94ba131d0932a73612810984f798ff47fa7189dd7a6045d83c20bfe` |

Both runs observed the exact `380`/`8`/`4` timing deltas and repeated the
initial and cockpit render hashes byte-for-byte. The final states differ by
roughly one or two fixed simulation quanta because host-vblank input timing is
exact while the host-time physics accumulator can meet render 520 at a nearby
scheduler phase. The qualification therefore asserts a narrow airborne state
envelope, not a misleading byte-identical final frame. Raw Pingo angle words
remain authoritative; displayed degrees use the documented 32768-unit binary
turn.

The later matrix-derived fallback-horizon correction changes only eZ80
backdrop preparation, so a fresh current-binary regression was also retained.
`P3DFSIM.BIN` SHA-256
`e29019c075e044f7721de5dcac9d0f323ceaa032e4402f06288c86c33a312bb0`
qualified at 9.815 m AGL after 397.651 m under the same exact input deltas.
Evidence is under `/tmp/pingo-koak-takeoff-20260802-matrix-horizon`; report
SHA-256 is
`006845576e08bb12c2fbd2769d5c3803a85717d81bb299a343be34471859d187`.

## Natural nested-family handoff proof

The later `scripts/trace_koak_family_transition.py` proof supersedes the earlier
assumption that the selected-record loader and flight coordinator were still
separate. It runs the sibling `koak-flight-family-lod` fixture, waits until all
37 planned terrain records can be resident, switches to chase view, holds W,
and applies the qualified delayed Down pulse. The aircraft's ordinary force
model and coarse-cell coordinator then carry it from family `(23,36)` into
`(22,36)`. The driver explicitly rejects the F12 test key, so no diagnostic
teleport or direct state patch can satisfy the crossing.

The trace reassembles an include-closed symbol copy and requires its SHA-256 to
match the exact `P3DLOD.BIN`. It then combines three independent evidence
streams:

- debugger memory at the next completed render-idle boundary proves coarse
  position, packed flight state, plan cursor, error hold, last loader error, and
  swap-complete state;
- command-50 and command-51 diagnostics prove 39 one-time mesh publications,
  the exact per-slot activation histories, and one contiguous 13-off/13-on
  transaction with neither a render nor a publication interleaved; and
- raw color/depth dumps retain the completed renders immediately before and
  after that transaction.

For this proof the diagnostic VDP also emits `PINGO_POSE` records for legacy
aircraft translation and camera translation/rotation. These records are inside
`#if PINGO_RENDER_DIAGNOSTICS`; the ordinary build defaults the macro to zero,
and the driver refuses a module that lacks the required strings. Thus the pose
witness is compile-gated diagnostic instrumentation, not a new protocol or
production logging burden.

The canonical 2026-08-02 run is
`/tmp/pingo-koak-family-transition-20260802-f-placement-validated`. Its v2
report used `P3DLOD.BIN` SHA-256
`fa41b2adca0da781441d6ded66e4460e68d713b9d38869d57376581956714cbb`
and diagnostic VDP SHA-256
`04ed9bbc80ef4981beae282c1db3d8a242ae12b0b305e7fda7a727ea4f20f0be`.
The report SHA-256 is
`877114ade487803fc9565537c0c744ed5e6b03f520af7d7e79ee82a1b5a429d3`
and the log SHA-256 is
`8c577e6ecc1449b3671c4be80a289b04f0b209ad7d1f7f7da068f096498fafda`.
It exited through the debugger with status zero at coarse cell `[91,148]`,
after horizontal displacements `[624.188720703125,1631.052978515625]` metres,
with cursor `37/37`, no error hold or last error, swap complete, 24 active
terrain slots, 39 mesh publications, and a maximum reported VDP publication
time of 57 microseconds. That last number times command-50 publication only;
it is not an end-to-end SD-card load latency.

The transaction is bracketed by consecutive renders 1192 and 1193. Aircraft
and camera translations both change by `[7,11,-8173]` raw counts, which is the
expected `[0,0,-8192]` floating-origin wrap plus natural motion `[7,11,19]`.
The chase offset remains `[-107,37,-277]`, and object 201 is active for both
renders. Before the activation group, exactly 37 command-52 records occur in
generated plan order. Each raw translation combined with its generated centre
reconstructs the same swap-time coarse cell `[91,147]`, centre
`[749568,1208320]`, and terrain Y `9728`. The debugger snapshot occurs later at
`[91,148]`; this fixed-west proof makes no subsequent north-family handoff
claim.

The pre/post frames contain respectively 19,459 and 21,136 matching nonzero
color/depth pixels. Their RGBA2222 hashes are
`97cc37ca562ec9b3424a050dbf1a94ce52c64283c728b34fe565f5eeb551bfdd`
and `c87cde45e65783f6cd9859ae0ad8d75c0559a9e76bbc6d018b0c00af671b3915`;
their depth hashes are
`c3135eca514d48efed0bfd838fcc61e58754104ebfa72a0184b0125daeb9b979`
and `025212f8681bf5804636de34b1d9a3423930c0912cd9485bd5159ecb5b50eb3f`.

The corrected interpretation is deliberately narrow. Independent inspection
found both bracketing captures coherent and nonblank, and the log proves that
no partially swapped scene was rendered. Different hashes, coverage, and LOD
silhouettes are expected; this is not evidence that the handoff has no visible
pop or seam. Human visual transition review and physical-hardware qualification
remain open, along with complete SD I/O timing and generalization beyond this
fixed westbound family pair.
