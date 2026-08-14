# Flight-simulator cockpit artwork

`fsimpanel.png` is the authoritative 320×92, 8-bit RGBA source artwork for the
initial 2D cockpit overlay.

Provenance:

- vendored from:
  `/home/smith/Agon/mystuff/pingoasm/src/blender/fsimpanel.png`
- source repository: `~/Agon/mystuff/pingoasm`
- historical consumers: `tests/apps/movefsim` and `tests/apps/moveair`
- source SHA-256:
  `4beb8066ea7baa53914d0c02e67e53b41519f7bdd1da89f30903349527bd7b36`
- vendored on: 2026-08-02

The PNG is source art. Do not hand-edit a generated `.rgba2` derivative and
treat it as authoritative. Runtime conversions must be deterministic and
record their generator and input checksum.

The experimental procedural reconstruction is defined by
`src/pingo_terrain/cockpit_panel.py`; it reads no pixels from this PNG.  Its
Pillow review backend and eventual assembly backend share the same integer
drawing program.  See `docs/cockpit-panel-generator.md`.  Until that
reconstruction is visually accepted, this file remains its visual reference.
