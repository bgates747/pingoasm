# Campanile P3DM visual probe

This isolated L1 fixture loads the freshly regenerated procedural Sather Tower
component without changing the live KOAK fixture. Runtime assets are deliberately
8.3-safe:

```text
CAMPTEST.BIN
CAMPANIL.AGN
SOLID64.RG2
```

The build first runs the canonical landmark-corpus builder, then byte-copies
its current Campanile component and raw native 8x8 palette. It derives only a
local translation that puts the decoded lowest landmark vertex on zero ground;
the P3DM mesh, face selectors and exact uniform scale remain unchanged. The
camera uses the qualified eZ80 integer look-at solver for a two-facade oblique
view.

Build and run the focused qualification:

```text
.venv/bin/python scripts/build_campanile_p3dm_probe.py

PYTHONPYCACHEPREFIX=/tmp/pingo-terrain-pycache \
  .venv/bin/python -m unittest -v tests.test_campanile_p3dm_probe

.venv/bin/python scripts/capture_campanile_p3dm_probe.py \
  --output /tmp/pingo-campanile-p3dm-capture
```

The builder runs the full assembly include-closure ADL audit before invoking
`ez80asm`, and records input, component, palette, generated include and binary
hashes in `tgt/probe.json`. The silent capture executes private byte-verified
copies under the actual `CAMPTEST.BIN` runtime name. It requires the exact
command-50 mesh counts, object activation, matching color/depth coverage, an
unclipped centered recognition silhouette with material diversity, and a
controlled process shutdown.

## Automated evidence, 2026-08-02

The stable post-ground-contact corpus produced a 268-vertex, 130-triangle
Campanile component. Its SHA-256 is
`7c434d711cfe16d62636c307da9c71142fd3538d28fe2c0e2f4ac27e4ce96864`;
the native 8x8 palette SHA-256 is
`47f7e1441be49b5e4701d19e2af2c31a5ee056914c03bd8d6249bdb085bb374d`.
The local Y translation leaves a 0.019470809 m decoded base residual without
changing the mesh or its Q8.8 scale.

The audited `CAMPTEST.BIN` SHA-256 is
`84683e13f8341d1e0a9bfb2f3a423bf93656017646ddf868ebfe9533659856dd`.
A silent diagnostic capture under
`/tmp/pingo-campanile-p3dm-capture-20260802-b` published that exact component
and produced 5,682 matching color/depth pixels. Its unclipped silhouette spans
X 141..176 and Y 11..207, with seven non-black RGBA2222 values. Color SHA-256
is `6c999bb64fcf17364cbd40667c7d422b66a3e6643162a43b131e2079100444dc`;
depth SHA-256 is
`744fb1e05172d1a181b0621fbe43a5d8eeb678babe66afdceaad38386cd61267`.
The emulator accepted SIGINT and returned zero; no process remained.

Automated evidence does not waive the project's human emulator gate.
