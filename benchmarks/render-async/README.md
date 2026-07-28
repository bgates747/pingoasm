# Asynchronous Pingo render fixture

This fixture proves the stock-MOS render-completion callback path with the
labeled cube. Unlike the deterministic timing benchmark, it never waits idly
for VDP or sends blind render requests.

The UART callback only copies keyboard/completion data into application
mailboxes and sets commit flags. The foreground loop:

1. advances the world at a fixed rate from MOS's interrupt-maintained clock;
2. accepts Escape through the same interrupt callback;
3. consumes and displays a completed render;
4. submits the newest absolute cube pose only when no render is in flight.

The world performs 36 ten-degree steps independently of render throughput. If
the VDP is still drawing when one or more steps occur, the fixture coalesces
them and submits only the newest pose after completion. This is deliberately a
functional asynchronous test, not a timing benchmark.

Fixture initialization is itself asynchronous. Before timing the first render,
the application sends a stock general-poll marker and waits for MOS to receive
its echo. This queue barrier prevents video-mode allocation, texture upload,
and scene construction from being misclassified as first-render latency on
hardware.

The fixture deliberately does not select or restore a video mode. It runs in
the mode already established at boot and leaves the last completed framebuffer
visible after printing its result and returning to MOS. This avoids a second
mode allocation and prevents a fast cleanup transition from hiding the render
before a physical monitor can resynchronize.

The first returned Pingo sequence is accepted as-is because a Pingo control
buffer can survive a MOS reset; every later 16-bit completion sequence must
increment modulo 65536. Correlation also checks the `P3DR` magic and caller
token. With exactly one render in flight, the application already owns the
target bitmap and does not need the VDP to repeat it.

Control ID 1350 is reserved for this fixture family so it cannot inherit the
objects used by the render-spin benchmarks. Pingo still lacks a complete,
leak-free control teardown; each profile should use its own reserved control
ID until that separate lifecycle defect is repaired.

Generate and assemble:

```bash
./.venv/bin/python build/scripts/build_render_async.py

# Or generate another profile-driven model:
./.venv/bin/python build/scripts/build_render_async.py \
  benchmarks/render-async/profiles/<model>.json
```

The executable and texture are written to:

```text
benchmarks/render-async/fixtures/cube/tgt/
```

Press Escape to request a clean exit. If a render is already in flight, the
fixture waits for its completion before disabling notifications and removing
the MOS keyboard vector. A timeout is reported only after that outstanding
completion is drained; if the VDP never completes at all, the fixture remains
resident so MOS cannot later jump through a stale callback address.

The callback follows the stock MOS ABI: `DEU` is copied to `IX`, the index
registers are preserved, no MOS/VDU/file calls occur inside the interrupt
path, and recognized `P3DR` bytes are scrubbed before MOS resumes its normal
keyboard processing. The completion payload is ten bytes (twelve bytes
including VDP framing), matching the established stock mouse-packet size and
remaining below the eZ80's sixteen-byte receive FIFO.

## Qualified hardware result

The 2026-07-28 hardware run completed with `PASS` and visibly carried the Cube
through its complete 360-degree revolution. The 36 fixed simulation steps
produced 17 submitted renders (`seq=0` through `seq=16`), proving that the
foreground continued advancing world state and coalesced intermediate poses
while VDP was busy.

Both the original 18-byte wire record and the compact 12-byte record initially
reported the same false timeout; compacting the record did not solve it. Queue
synchronization did. The compact record remains the qualified protocol because
its omitted fields are redundant for one render in flight and its size matches
a proven stock event—not because the larger experimental record was shown to
fail.

The renderer-only diagnostic records ranged from 192.849 ms to 214.143 ms,
with a mean of 203.659 ms. Those values describe `rendererRender()` and are not
an end-to-end callback latency benchmark.
