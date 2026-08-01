# Pingo lighting and flat-palette visual fixture

This standalone application qualifies the scene-wide lighting controls and
mesh-local shading mode without changing the legacy compatibility fixtures.
It renders two identically posed Cubes into four 160×120 targets and displays
them together on one 320×240 screen.

In every panel, the left Cube uses the labeled `blenderaxes` texture and the
right Cube uses one constant Agon palette color per source triangle. The four
panels are:

1. top-left: untouched firmware lighting defaults;
2. top-right: unit-intensity light from `+X`;
3. bottom-left: the default light direction at intensity 255 with ambient 64;
4. bottom-right: illumination disabled, showing native texture colors.

Flat shading remains responsive to lighting. It bypasses illumination only in
the fourth panel because illumination state and shading mode are independent.

The Cubes are positioned at `(−480,0,0)` and `(+480,0,0)`. The unrotated
camera is at `(0,0,+3200)` and looks along canonical `−Z` toward the scene;
placing the camera on positive Z is intentional under the project coordinate
contract.

The generated flat Cube chooses the predominant mapped color of each original
triangle in `blenderaxes.png`, rewrites all three corners to the same cell of
the canonical row-major 8×8 `colors64.png` palette, then validates the final
assembly words against Pingo's actual texture sampler. A multi-color triangle
makes the ordinary build fail.

## Build

Regenerate portable source explicitly after changing the authoritative OBJ,
textures, common API helper, or conversion code:

```bash
.venv/bin/python build/scripts/build_lighting_shading.py --regenerate
```

The normal build treats the tracked generated source as an editable fixture:

```bash
.venv/bin/python build/scripts/build_lighting_shading.py
```

It validates the existing final `flat-cube.inc` before assembly and never
silently replaces it. Both paths assemble `tgt/lighting-shading.bin` and stage
the two RGBA2222 textures. Press any key after inspection to return to MOS.

## Hardware deployment

```bash
.venv/bin/python build/scripts/deploy.py hardware lighting-shading
```

Hardware is the qualification ground truth. Do not refresh or commit an
emulator snapshot until the hardware result passes; any emulator-related
change also requires explicit human validation before commit or push.
