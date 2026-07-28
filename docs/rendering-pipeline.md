# Rendering and asset pipeline

`pingoasm` owns conversion from editable Blender/image sources to Pingo client
assembly and runtime textures. `agon-vdp` owns renderer/protocol code; the
emulator may invoke this pipeline but must not duplicate it.

## Current boundary

```text
src/blender/        editable scenes, OBJ/MTL exports, source images
build/scripts/      Blender, mesh, texture, and diagnostic tools
src/asm/models/     temporary generated model/texture library
apps/_common/       shared assembly and generic viewer
apps/<app>/src/     flat portable assembly
apps/<app>/tgt/     flat ignored binaries and runtime textures
```

The intended end-to-end path is:

```text
.blend + source image
  -> deterministic mesh/UV export
  -> coordinate and winding validation
  -> texture conversion
  -> generated model include
  -> portable application source
  -> assembled binary/runtime payload
  -> hardware regression
  -> emulator regression
```

Generated `.asm`/`.inc` must identify their generator and authoritative input.
Generated output must never overwrite an editable `.blend`.

## Blender

The validated Pop!_OS installation is native Blender 4.0.2:

```bash
blender --version
blender --background scene.blend --python pipeline_script.py -- [arguments]
```

`build/scripts/blender_headless.py` provides the project wrapper and propagates
Blender/script failures. Check discovery through the project environment:

```bash
.venv/bin/python build/scripts/blender_headless.py
```

Scripts importing `bpy`, `bmesh`, or `mathutils` run inside Blender's bundled
Python; do not install those modules into `.venv`.

The wrapper was validated with `src/blender/tri.blend` and `blend_export.py`.

## Canonical HeavyTank chain

The accepted HeavyTank sources are:

```text
src/blender/heavytank.blend
src/blender/heavytank.obj
src/blender/heavytank.mtl
```

The fresh OBJ has 30 vertices, 48 triangles, 84 UVs, outward winding, and
positive signed volume. The old OBJ had the same geometry but inward winding,
which explained its inside-out rendering.

Generated consumers are:

1. `src/asm/models/heavytank.inc` for ordinary RGBA2222 apps.
2. `apps/turbovega/src/heavytank.inc` for the strict RGBA8888 fixture.
3. Generated `movecam`/`moveobj` `heavytank.asm/.inc` portable sources.

All numbered, axis-modified, inverse, and video HeavyTank experiments were
deleted. Plainly named `heavytank.*` files are canonical.

`blender_obj_to_asm.py` and its legacy template lazy-load image dependencies,
so geometry conversion can run without Pillow/NumPy when texture conversion is
not requested.

## Tool groups

1. Blender execution/export: `blender_headless.py`, `blend_export.py`.
2. UV/scene helpers: `blend_clean_uvs.py`, `blend_select_uvs_by_mat.py`,
   `blend_scene_cleanup.py`.
3. Pingo conversion: `blender_obj_to_asm.py` and historical BASIC converters.
4. Image conversion: `agonImages.py`, `bgra_to_rgba.py`.
5. Diagnostics: `plot*.py`, `pingo_check_bearing.py`, texture/palette probes.

Many model-specific scripts predate the current layout and contain obsolete
paths or assumptions. Treat them as historical until parameterized and tested.
Legacy template utilities live under `build/scripts/legacy/template`;
`apps/_common` is reserved for shared assembly.

## Python environment

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-pipeline.txt
```

Use only the dependencies required by the selected external utility.

## Deferred structural work

The temporary central model library remains until the numbered
`model-asset-reorganization-todo.md` is completed. That migration will make
model/texture provenance explicit, introduce shared source assets, compare
regenerated hashes, and preserve the accepted 13-binary build throughout.
