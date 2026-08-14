# Regional Bay Area camera survey

FSIM entry 0 is this no-dynamics fixture. It retains the accepted Campanile
start and direct camera controls while replacing Berkeley's embedded 32 meshes
with reads from the full 50,652-component regional loose-L0 corpus.

It keeps 32 stable terrain-only Pingo slots. The live window spans tile-X
offsets `-2..+5` and tile-Y offsets `-2..+1`, matching the useful 8×4 footprint
of the accepted Berkeley fixture. Slot identity is the collision-free rolling
map `(tile_y & 3) * 8 + (tile_x & 7)`. The current component is a startup gate;
one missing component is read, validated, CRC-checked, uploaded, and published
between each later pair of completed renders.

“Full region” describes the available on-disk corpus, not simultaneous VDP
residency: only those 32 cells are live. Crossing a 512 m boundary repositions
the retained cells and recycles the four outgoing edge slots for the incoming
edge, so the window can follow the camera anywhere in the 201×252 grid.

The absolute start is the profile's Campanile coordinate in coarse cell
`(85,179)`, canonical fine counts `(-1857,3496,3638)`, 120 m AGL, facing east.
Legacy object translations cannot represent the asymmetric window directly,
so camera and terrain share a `+12288` Z frame bias. The emitted camera starts
at `(-1857,3496,15926)` and rebases local Z within `[8192,16384)`; subtracting
the bias always reconstructs the canonical regional coordinate. X uses the
ordinary `[-4096,+4096)` fine interval and Y remains absolute.

Controls are unchanged from the visually accepted Berkeley survey: arrows
change pitch/yaw with no roll, WASD translates only in the yaw-rotated XZ
plane, Page Up/Down changes world Y, and Minus/Equals changes the bounded
translation rate. The 320×240 attitude backdrop remains visible where terrain
is absent or still streaming.

Build the full corpus and fixture from the repository root:

```text
.venv/bin/python scripts/build_regional_terrain.py \
  --selection full --lods 0 --output build/p3dm/bay-area-full-l0
.venv/bin/python scripts/build_regional_camera_survey.py
```

The runtime root is `build/p3dm/bay-area-full-l0`; its executable is
`P3DSURV.BIN`. Generated fixture listing/symbols are retained in this fixture's
`tgt` directory. The builder verifies the recorded size and SHA-256 of every
one of the 50,652 containers before assembling.

Qualify the initial 32-cell publication and a real eastward cell crossing with:

```text
.venv/bin/python scripts/capture_regional_camera_survey.py \
  --output /tmp/pingo-regional-camera-capture
.venv/bin/python scripts/trace_regional_camera_streaming.py \
  --output /tmp/pingo-regional-camera-streaming
```

Emulator-coupled work remains uncommitted until human visual qualification.
