# TurboVega-compatible regression fixtures

This application contains self-contained Agon MOS assembly fixtures for the
final TurboVega Pingo VDU surface. Sources are tracked in `src/`; binaries and
RGBA8888 textures are generated in ignored `tgt/`.

## Fixtures

1. `triangle` checks the smallest textured geometry path.
2. `cube` uses labeled axis faces to expose face selection, mirroring, UV
   orientation, transforms, and perspective errors.
3. `heavytank` uses asymmetric chiral geometry to expose winding and compounded
   perspective errors hidden by simpler models.

Cube and HeavyTank use `blenderaxes.rgba8`; triangle uses
`triangle.rgba8`. Both are 34×34 RGBA8888 images (4,624 bytes).

The canonical HeavyTank comes from the freshly exported
`src/blender/heavytank.obj`. Its winding is outward. The historical OBJ was
consistently inward-wound and caused the apparent inside-out rendering.

## Compatibility boundary

The fixtures use only TurboVega commands:

1. `0` create control.
2. `1`/`2` define vertices and indexes.
3. `3`/`4` define UVs and UV indexes.
4. `5` create object.
5. `9`, `13`, and `17` set object scale, rotation, and translation.
6. `25` set camera translation.
7. `38` render to bitmap.

They do not use later normals, dithering, diagnostics, local transforms, or
extended commands. `vdu_tv.inc` is intentionally curated.

The camera pose is `(0, 0, +25)`, looking along `-Z`. A conforming bridge
inverts the pose once to produce view translation `(0, 0, -25)`.

## Build

From `apps/turbovega/src`:

```bash
ez80asm triangle.asm ../tgt/triangle.bin
ez80asm cube.asm ../tgt/cube.bin
ez80asm heavytank.asm ../tgt/heavytank.bin
```

Place each binary beside its named texture in `tgt/`.

## Controls

1. `W`/`S`, `A`/`D`, and Page Up/Page Down translate.
2. `Q`/`E`, Up/Down, and Left/Right rotate.
3. Escape restores normal screen mode and returns to MOS.

Transforms accumulate and use only absolute commands `13` and `17`. Rendering
occurs after an actual input change, is limited to ten updates per second for
held keys, clears the back buffer, and then flips buffers.

Z translation is clamped to ±10 because TurboVega/Alpha 1 does not yet clip
triangles that cross the near plane.

## Qualification

Pingo 2.15.0 Alpha 1 passed cube and HeavyTank on real hardware and the
isolated Fab emulator. The accepted result has:

1. correct translation and rotation directions;
2. correct face and texture orientation;
3. perspective-correct UV interpolation; and
4. coherent outward-facing HeavyTank geometry.

Hardware remains the behavioral ground truth.
