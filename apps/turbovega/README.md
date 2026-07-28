# Textured triangle regression

This application family provides self-contained Agon MOS assembly fixtures for
testing the Pingo 3D port through TurboVega's final VDU command surface.

Sources live in `src/`; assembled binaries and their RGBA8888 runtime textures
live in the ignored `tgt/` directory, matching the other `pingoasm`
applications.

The same application also contains cube and HeavyTank variants. Both use
the identical TV-compatible harness, move-object controls, and
`blenderaxes.rgba8` texture:

- `cube.asm`, `cube.inc`, and `cube.bin` exercise the six faces of the
  canonical orientation and UV regression cube.
- `heavytank.asm`, `heavytank.inc`, and `heavytank.bin` exercise a larger,
  chiral model whose asymmetric geometry makes orientation and compounded
  transform errors unambiguous.

It is adapted from these `pingoasm` inputs:

- `apps/moveobj/src/tri.asm`
- `apps/moveobj/src/inputobj.inc`
- `src/asm/models/tri.inc`
- `src/asm/models/blenderaxes.png`

The texture is `34 x 34` RGBA8888 (`34 * 34 * 4 = 4624` bytes). It was
expanded from the corresponding RGBA2222 asset without changing the image.
Both the texture bitmap and the render-target bitmap are RGBA8888.

The running fixture uses only TurboVega Pingo subcommands:

- `0` create control structure
- `1` define mesh vertices
- `2` define mesh vertex indices
- `3` define mesh texture coordinates
- `4` define mesh texture-coordinate indices
- `5` create object
- `9` set object scale
- `13` set absolute object rotation
- `17` set absolute object translation
- `25` set absolute camera translation
- `38` render to bitmap

It deliberately does not use later normals, dithering, diagnostic, or extended
transform commands. `vdu_tv.inc` is a deliberately curated helper subset rather
than a copy of the later Pingo command surface.

TurboVega decodes scale as unsigned 8.8 fixed point (`value / 256`) and
translation as signed world units (`value * 256 / 32767`). The fixture uses
scale word `5 * 256` (`5.0x`) and camera Z word `+25 * 128` (approximately
`+25.0`). The positive camera value deliberately follows the project's decided
pose semantics rather than TurboVega's historical view-transform
compensation.

Build from `apps/turbovega/src`:

```bash
ez80asm triangle.asm ../tgt/triangle.bin
ez80asm cube.asm ../tgt/cube.bin
ez80asm heavytank.asm ../tgt/heavytank.bin
```

Copy the selected executable and its texture into the same SD-card directory:

- `triangle.bin` uses `triangle.rgba8`;
- `cube.bin` and `heavytank.bin` use `blenderaxes.rgba8`.

Load and run `triangle.bin` at the MOS prompt. It draws one initial frame, then
redraws only when a key changes the object through this move-object key map:

- `W`/`S`, `A`/`D`, and Page Up/Page Down translate the object;
- `Q`/`E`, Up/Down, and Left/Right rotate it;
- Escape restores the normal screen mode and returns to MOS.

The controls accumulate an absolute transform and send only TurboVega commands
13 and 17. They deliberately avoid the later local-transform commands. A frame
is rendered only after an actual input change, rather than flooding the VDP
continuously while idle. Held-key input is limited to ten updates per second.
Each redraw clears the back buffer before displaying the newly rendered target,
then flips buffers, so earlier object positions do not remain on screen.

The fixture uses a dedicated control ID (`sid=300`) and the emulator-proven
extended bitmap IDs `256` and `257`. It does not issue command 39. TurboVega's
final `deinitialize()` is empty, so command 39 would discard the control slot
while leaking its large internal allocations. Leaving the control resident
lets an immediate rerun replace mesh arrays, rebind the object, and reset its
absolute transform.

Z translation is clamped to plus or minus 10 world units. TurboVega has no
near-plane triangle clipping; preventing the test triangle from reaching or
crossing the camera avoids turning an intentional control test into undefined
projection behavior.

The initial camera pose is `(0, 0, +25)`, looking along `-Z`. A conforming
bridge must invert that pose once, producing a view translation of
`(0, 0, -25)`. The unchanged TurboVega baseline consumed the positive value
directly as a view transform and displayed only the clear color. The
`pingo-codex` camera-pose correction makes the fixture visible.

Reset the VDP before the first hardware run after an older malformed fixture;
that program may have left corrupted renderer state behind.
