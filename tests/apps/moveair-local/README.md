# eZ80-local asynchronous moveair application

`moveair-local` reproduces the historical persistent-throttle aircraft
controls without using Pingo's retired local-delta commands. The eZ80 owns a
complete 64-byte object pose plus a 36-byte tracking-camera pose, advances
them on a fixed simulation clock, and submits only the newest absolute dirty
state whenever current Pingo is ready to begin another render.

## Runtime model

The Jet application uses the project-local integer 3D implementation:

```text
src/agon/3d.inc
src/agon/3d_sincos_table.inc
```

The remaining copied Agon includes are retained beside those files for
deliberate future API work, but are not assembled automatically because their
general MOS, timer, and VDU symbols overlap this application's curated
helpers.

The object state retains control, object, mesh, and texture bitmap IDs; world
position; absolute Pingo Euler angles; scale; a local-to-world orientation
matrix; local linear and angular velocity; and angular lookup residuals.
Initial synchronization emits current absolute commands `5`, `9`, `13`, and
`17`. Later ticks send only dirty rotation (`13`) and/or translation (`17`).
No retired high-bit local-transform command is emitted.

The camera state retains its scene ID, fixed world position, absolute Pingo
Euler angles, local-to-world orientation, and pole-traversal history. When a
simulation quantum changes the Jet's world position, the eZ80 calls
`p3d_camera_aim_at_object16`. The default `p3d_camera_roll_upright` policy
preserves a world-up horizon, holds the last reliable yaw inside a hysteretic
pole cone, and resumes ordinary tracking after the Jet leaves it. A single
`camera_tracking_roll_policy` equate can instead select continuous roll, which
passes smoothly over the pole and emerges with the horizon inverted.

Each update applies intrinsic local rotation first, then translates the local
velocity through the resulting orientation. Forward is local `-Z`, matching
the Jet's authored nose direction and the historical flight controls.

## Simulation, rendering, and input

Simulation time comes from MOS's 120 Hz interrupt-maintained clock. A fixed
step is four MOS ticks, or 1/30 second. Delayed foreground work advances from
the previous deadline and may run multiple fixed steps to catch up rather than
discarding elapsed time.

Angular rates are defined per 128 MOS ticks, making each fixed-step conversion
a right shift by five:

```text
angular: 4864 * 4 / 128 = 152 angle words per step
```

Forward velocity is persistent and expressed directly as local translation
words per fixed step. W makes local Z one word more negative on each quantum,
up to magnitude 255. S moves it one word back toward zero; as in the
historical moveair application, there is no reverse thrust. Once nonzero, this
velocity remains in the object state and advances the Jet on every simulation
quantum even when no key is held. Rotation is applied before that local
translation, so thrust follows the Jet's current orientation.

The foreground state machine permits exactly one Pingo render in flight.
While it is in flight, simulation continues and newer object and derived
camera poses become dirty. When the committed `P3DR` completion mailbox is
consumed, the client displays and flips that result, synchronizes the newest
absolute object and camera poses, and requests another render. Intermediate
visual states are therefore coalesced without slowing world time to renderer
throughput.

Pingo command `41` registers a caller token for render-completion records.
The UART interrupt callback only recognizes and copies the fixed ten-byte
record, publishes a ready flag, and neutralizes its `P3DR` prefix before
returning to MOS. All validation, display, synchronization, and rendering
remain in foreground code. Shutdown disables notifications before removing
the MOS keyboard vector.

There is one hardware-level input limitation: Pingo rendering currently
blocks the VDP command loop that delivers keyboard packets to MOS. The eZ80
continues simulating an already-held control during a render, but a new key
press or release can remain queued until that render completes. The callback
leaves ordinary four-byte keyboard packets untouched so MOS can update its
normal virtual-key map when they arrive.

The moveair control layer is:

| Keys | Effect |
|---|---|
| W / S | increase forward `-Z` throttle / decrease it toward zero |
| Up / Down | pitch `-X` / `+X` |
| Left / Right | roll `+Z` / `-Z` at twice the pitch rate |
| A / D | yaw `+Y` / `-Y` |
| Escape | restore the normal display and return to MOS |

Space-to-cycle-dithering is commented out. The old app sent a one-byte command
`41`, but current Pingo uses command `41` for render-completion registration
with a different packet, so sending the historical sequence would be unsafe.

The historical firmware-owned camera-track-object call used retired Pingo
command `42`. This application now reproduces that behavior on the eZ80: the
camera remains at world origin, aims at the retained Jet position on simulation
ticks, and emits only current absolute camera translation (`25`) and rotation
(`21`) commands while the renderer is idle. This focused transform test still
omits the old instrument panel, panorama, second model, and associated assets;
only the Jet and `jet.rgba2` are loaded.

The renderer is configured by `viewport_width` and `viewport_height`,
currently 320×240. These constants are the primary performance knob: reducing
them shortens render occupancy and callback/input-delivery latency without
changing the 30 Hz simulation rate. Hardware tuning should use that knob to
seek roughly 12 FPS minimum and preferably 15 FPS; there is no artificial
application frame limiter.

## Build

From the repository root:

```bash
.venv/bin/python build/scripts/build_samples.py
```

The normal builder treats this as a static, hand-developed app: it replaces
only `tgt/`, copies `jet.rgba2`, and assembles:

```text
src/jet.asm -> tgt/jet.bin
```

It never replaces `src/` or the local Agon API snapshot. For a targeted build:

```bash
cd tests/apps/moveair-local/src
ez80asm jet.asm ../tgt/jet.bin
```

The emulator profiles expose the repository's complete `apps/` tree directly.
Hardware deployment uses the ordinary application path:

```bash
.venv/bin/python build/scripts/deploy.py hardware moveair-local
```

As with every hardware SD write, flush and safely unmount the card before
moving it to the Agon.

## Verification status

The full project build assembles all 15 binaries. Source guards cover the
current command scope, exact command-41 registration packets, fixed-step
scheduler, disabled Space/dithering contract, camera-state initialization,
simulation-time aiming, render-idle camera synchronization, and persistent
local-Z coasting. The two local clients' asynchronous render layers must also
remain byte-identical.

The renderer, Jet model, persistent-throttle controls, eZ80 camera tracking,
pole safeguards, and former cardinal-crossing freeze path have passed
interactive emulator and physical-hardware review.
