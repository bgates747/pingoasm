# eZ80-local asynchronous move-object application

`moveobj-local` reproduces the historical interactive move-object controls
without using Pingo's retired local-delta commands. The eZ80 owns a complete
64-byte object pose, advances it on a fixed simulation clock, and submits only
the newest absolute dirty state whenever current Pingo is ready to begin
another render.

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

Each update applies intrinsic local rotation first, then translates the local
velocity through the resulting orientation. Forward is local `-Z`, matching
the Jet's authored nose direction and the historical flight controls.

## Simulation, rendering, and input

Simulation time comes from MOS's 120 Hz interrupt-maintained clock. A fixed
step is four MOS ticks, or 1/30 second. Delayed foreground work advances from
the previous deadline and may run multiple fixed steps to catch up rather than
discarding elapsed time.

Velocities are defined per 128 MOS ticks, making each fixed-step conversion a
right shift by five:

```text
linear:   352 * 4 / 128 = 11 translation words per step
angular: 4864 * 4 / 128 = 152 angle words per step
```

The foreground state machine permits exactly one Pingo render in flight.
While it is in flight, simulation continues and newer world poses make the
object dirty. When the committed `P3DR` completion mailbox is consumed, the
client displays and flips that result, synchronizes the newest absolute dirty
pose, and requests another render. Intermediate visual states are therefore
coalesced without slowing world time to renderer throughput.

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

Controls and signs are unchanged:

| Keys | Object-local velocity |
|---|---|
| W / S | forward `-Z` / backward `+Z` |
| A / D | left `-X` / right `+X` |
| Page Up / Page Down | up `+Y` / down `-Y` |
| Q / E | roll `+Z` / `-Z` |
| Up / Down | pitch `-X` / `+X` |
| Left / Right | yaw `+Y` / `-Y` |
| Escape | restore the normal display and return to MOS |

Space-to-cycle-dithering is commented out. The old app sent a one-byte command
`41`, but current Pingo uses command `41` for render-completion registration
with a different packet, so sending the historical sequence would be unsafe.

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
cd tests/apps/moveobj-local/src
ez80asm jet.asm ../tgt/jet.bin
```

The emulator profiles expose the repository's complete `apps/` tree directly.
Hardware deployment uses the ordinary application path:

```bash
.venv/bin/python build/scripts/deploy.py hardware moveobj-local
```

As with every hardware SD write, flush and safely unmount the card before
moving it to the Agon.

## Verification status

The full project build assembles all 14 binaries, and all 88 Python regression
tests pass. The static-app build test proves that regenerating `tgt/` does not
alter `src/agon`. Source guards reject retired local-transform helpers, require
the exact current command-41 registration packets, enforce the fixed-step Jet
contract, and keep the obsolete Space/dithering binding disabled.

A fresh headless run on the isolated copied current-Pingo profile rendered the Jet.
The paused eZ80 callback state proved that the completion was consumed:
`render_in_flight` and `completion_ready` were clear, the mailbox and snapshot
held the matching version-1 `P3DR` record, the expected sequence had advanced
to one, and callback error remained clear. The asynchronous Jet controls and
appearance subsequently passed interactive emulator and physical-hardware
review.
