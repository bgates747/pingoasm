# Cockpit panel drawing program

The historical 320×92 `assets/cockpit/fsimpanel.png` is the visual and
provenance reference for a procedural light-flight panel.  The procedural
scene is intentionally provisional until the Author accepts its presentation.
It corrects the source artwork's approximately 0.86 vertical gauge squash
without changing the 320:92 panel footprint.

## Coordinate and presentation contract

The scene is authored on one 320×92 integer grid with an exact 80:23 aspect
ratio.  Every scaled output uses one isotropic factor.  The eight gauge wells
are true circles with 22-pixel outer radii; no backend may stretch a completed
bitmap independently on X and Y.  A Pillow-only legacy comparison can apply
the measured squash around each gauge center, but it does not mutate the
canonical geometry.

The initial scene contains panel structure and fixed gauge art only:

- fixed bezels, faces, tick scales, legends, blank value windows, knobs, and
  control-position recesses are present;
- needles, attitude and compass cards, CDI/glideslope bars, slip ball, live
  digits, flags, and annunciators are absent; and
- the former radio stack is one framed, entirely blank GPS/map opening.

The blank instruments are deliberate.  Named `dynamic.*` bounds reserve the
small regions that a working panel will repaint from flight state.

## Shared drawing representation

`src/pingo_terrain/cockpit_panel.py` produces one ordered `PanelProgram`.
Pillow objects, image paths, host font handles, and already-rasterized pixels
do not appear in it.  Its primitive vocabulary is restricted to filled
rectangles, one-pixel lines, filled triangles, and filled or outlined circles,
plus semantic bitmap-glyph runs.  Every operation carries a stable name,
layer, semantic color, and optional instrument group.

This representation is the seam for the eventual assembly generator.  A VDP
backend can walk the same commands, insert color changes only when necessary,
and emit deterministic `db`/`dw` packets for VDU plot operations.  The native
panel uses coordinates x=0..319 and y=0..91; the cockpit client will add the
screen-space y origin of 148.  Future moving values should patch multibyte
coordinates bytewise or emit fresh bounded packets, following the project's
ADL fixed-width rule.

All authored colors are opaque members of the Agon RGB222 cube.  The native
hard-edged 320×92 render is the palette authority.  Optional Pillow
supersampling exists only for enlarged design review and is not evidence of
pixel identity with the VDP circle rasterizer.

## Font seam

Text remains semantic in the scene.  A `BitmapFontProvider` selects a
`BitmapTypeface` by role and requested height; glyphs may have arbitrary
widths, heights, and spacing.  The checked-in 3×5 face is a deterministic,
plain placeholder rather than an aesthetic commitment.  Replacing it with
the Author's later bitmap fonts changes neither instrument geometry nor the
future assembly-generator contract.

## Review renderer

Pillow 12.3 is the sole additional project dependency.  Generate the default
1280×368 review image with:

```bash
.venv/bin/python scripts/draw_cockpit_panel.py --force
```

The exact native render and the historical comparison are:

```bash
.venv/bin/python scripts/draw_cockpit_panel.py \
  --size 320x92 --output build/visualization/cockpit-panel-round-320x92.png \
  --force
.venv/bin/python scripts/draw_cockpit_panel.py \
  --legacy-squash --force
```

Generated PNGs belong under ignored `build/visualization/`; the vendored
historical PNG remains unmodified.
