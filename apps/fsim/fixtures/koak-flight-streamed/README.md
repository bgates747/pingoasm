# KOAK streamed light-flight fixture

This is the first combined regional fixture. It starts on KOAK runway 28L,
loads paired self-lit runway surfaces plus a bounded terrain neighborhood from
P3DM files, runs the deterministic 30 Hz force model, and retains the 320x148
attitude-aware cockpit viewport.

The initial aircraft reference is `(3088,44,2181)` translation counts in
coarse cell `(94,146)`. Its local cockpit-eye offset and runway yaw `-14411`
produce the canonical camera `(3106,64,2226)` exactly. The aircraft starts
stationary on runway support with zero throttle. `W/S` changes throttle,
arrows control pitch/roll, `A/D` applies rudder, `V` toggles cockpit/chase, and
Escape exits after the current asynchronous render completes.

The shared integer model retains Berkeley's exact 18-count cruise thrust at
throttle 160 and provides 28 counts at full throttle. In the host contract, a
held-W ramp followed by a modest eight-degree rotation at takeoff speed leaves
runway support on tick 393 after approximately 268.17 m. This is deterministic
runway support and force integration, not general terrain collision.

It is deliberately separate from every Berkeley fixture. The generated binary
is copied to the ignored regional proof root as `P3DFSIM.BIN`, because runtime
paths such as `TRN/L0/73/00.AGN` and `APT/KOAK/P00.AGN` are relative to that
directory.

Build from the repository root:

```text
.venv/bin/python scripts/build_koak_flight_streamed.py
```

The builder first verifies the ignored regional proof and canonical start,
regenerates the pinned Jet and cockpit resources, installs 8.3-safe runtime
names, assembles `P3DFSIM.BIN`, and writes a hash manifest as `FLIGHT.json`.
Provision the dedicated emulator profile with:

```text
.venv/bin/python scripts/setup_emulator.py \
  --vdp-module /home/smith/Agon/mystuff/agon-vdp/video/build/userspace-p3dm-loader-diagnostics/vdp_combined.so
```

The project autoexec now contains only the keyboard directive. Invoke this
fixture as entry 5 in the `fsim` MOSlet menu, or LOAD/RUN `P3DFSIM.BIN`
directly from the proof root. Unattended qualification must set both
`SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy` and terminate the emulator
cleanly after collecting the requested diagnostic frames.

## Runtime publication policy

- Twenty-five stable terrain mesh/object IDs are a direct-mapped 5x5 ring.
  Slot `((tile_y mod 5)*5 + tile_x mod 5)` is collision-free for the complete
  radius-two neighborhood.
- The current terrain component loads first. KOAK pavement P00 and marking M00
  then load into inactive stable objects and activate only after both succeed.
- After the first render, one absent terrain component may be read, fully
  validated, CRC-checked, uploaded and published between completed renders.
- Horizontal position uses a 512 m coarse cell and signed 16.8 fine state.
  Crossing `[-256,+256)` m reissues resident transforms without changing
  absolute position; vertical position remains absolute.
- Terrain is patterned/scene-lit. Airport hard surfaces are solid-flat and
  self-lit. The aircraft is solid-flat/scene-lit and inactive in cockpit mode.
- Every displayed frame paints the camera-attitude sky/ground fallback before
  compositing Pingo's transparent 320x148 target, then preserves the static
  320x92 panel below it.

The experimental VDP subcommands 50 and 51 and all emulator-coupled changes
remain uncommitted until human qualification.

The silent qualification command is:

```text
.venv/bin/python scripts/capture_koak_flight.py \
  --output /tmp/pingo-terrain-koak-flight-capture-20260802-c
```

It captures raw color/depth at sequences 0 and 30, verifies matching coverage,
requires all 27 expected command-50 publications, reconstructs the final
active-object set, rejects protocol/scene errors, and stops the emulator with
SIGINT. The 2026-08-02 run passed with exactly objects 1–25, 101, and 102
active; aircraft 201 was correctly inactive in the starting cockpit view.
