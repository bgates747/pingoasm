# Rendering and asset pipeline

`pingoasm` is the source of truth for scripts that transform Blender scenes,
meshes, textures, and images into data consumed by Pingo clients.

The repository boundary is:

```text
src/blender/
    editable Blender scenes, meshes, textures, and source assets

build/scripts/
    Blender automation, extraction, conversion, image processing, and probes

apps/_common/
    shared assembly and the generic model-viewer template

apps/<name>/src/
    flat authoritative or generated application assembly

apps/<name>/tgt/
    flat ignored binaries and RGBA2 runtime textures

src/asm/models/
    temporary model definitions and texture library
```

The emulator repository may invoke this pipeline, but it must not own copies
of these scripts. `agon-vdp` owns renderer and protocol implementation rather
than client asset generation.

## Blender

Pop!_OS uses the native APT package rather than Flatpak:

```sh
sudo apt-get install blender
blender --version
```

The validated installation is Blender 4.0.2. Direct headless execution is:

```sh
blender --background scene.blend --python pipeline_script.py -- [arguments]
```

`build/scripts/blender_headless.py` supplies the reusable Python wrapper. It
finds lowercase `blender` on Linux, retains the standard macOS application
fallback, accepts an explicit executable, and raises an error when Blender or
the invoked pipeline script fails.

The Linux path was validated end to end with the tracked `src/blender/tri.blend`
scene and mesh `cube`: the wrapper launched Blender 4.0.2, ran
`blend_export.py`, and emitted three transformed vertices, one triangle, three
UV coordinates, and their indices to a disposable output file.

Check executable discovery from the project-local Python environment:

```sh
.venv/bin/python build/scripts/blender_headless.py
```

Blender scripts importing `bpy`, `bmesh`, or `mathutils` execute inside
Blender's bundled Python. Do not install those modules into `.venv`.

## Script groups

The current collection contains both reusable utilities and historical,
model-specific experiments.

### Blender scene and mesh operations

- `blender_headless.py`: shared headless launcher and version check.
- `blend_export.py`: triangulate a named mesh and export transformed vertices,
  face indices, unique UVs, and UV indices as Python data.
- `blend_clean_uvs.py`, `blend_select_uvs_by_mat.py`: UV editing helpers.
- `blend_scene_cleanup.py`: remove unused Blender data.
- `blend_to_obj_invert.py`, `blend_pingo_obj*.py`: OBJ export experiments.
- `blend_get_mesh.py`, `blender_bone_mesh.py`: mesh/armature probes.

### Pingo and Agon conversion

- `blender_obj_to_asm.py`: convert OBJ geometry and texture metadata to Agon
  assembly include data.
- `blender_obj_to_basic*.py`, `blender_py_to_basic.py`,
  `lara_obj_to_basic.py`: BBC BASIC conversion experiments.
- `c_to_obj.py`: convert C array data to OBJ.
- `agonImages.py`, `bgra_to_rgba.py`: Agon bitmap and channel conversion.

### Texture and diagnostic tools

- `dither_bayer.py`, `make_img_hsv64.py`, `checkerboard.py`,
  `color_grid.py`, `shading_chooser.py`: palette and texture experiments.
- `plot.py`, `plot_uv.py`, `plot_framerate.py`,
  `pingo_check_bearing.py`: geometry, UV, timing, and camera diagnostics.
- `wolf_tiles.py`: Wolfenstein texture-atlas preparation.

## Python environment

External utilities use a project-local environment:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-pipeline.txt
```

The dependency list covers the imported external packages used across the
current scripts. Individual utilities may need only a subset.

## Current cleanup boundary

The scripts predate the present repository structure. Some specialized
entry points still contain former `ez80/` paths, macOS Blender paths, or
machine-specific absolute paths. Treat those as historical scripts requiring
parameterization before reuse; do not copy their paths into new automation.

Utilities formerly mixed into `src/asm/template` now live under
`build/scripts/legacy/template`. They were moved intact to clarify that
`apps/_common` contains assembly shared by applications; moving them did not
promote the historical utilities to supported pipeline entry points.

The former `src/asm/apps5` generated package collection is historical and now
lives under `archive/asm/apps5`.

The first modernization target is one end-to-end, argument-driven path:

```text
.blend source
  -> headless mesh/UV extraction
  -> validated coordinate and winding conversion
  -> packed texture conversion
  -> generated assembly include/runtime asset
  -> fixture build and emulator regression
```

Generated output should be written explicitly, never overwrite a source
`.blend`, and record its generator and input provenance. Generated `.asm` and
`.inc` files must carry the standard warning banner described in
`docs/assembly-build-pipeline.md`.
