# Feature-aware mesh pipeline (experiment)

Stage-1 implementation of the terrain-appearance pipeline from
[`../02-reading-precis-2026-08-15.md`](../02-reading-precis-2026-08-15.md):
three-class raster -> shared boundary polylines -> global Visvalingam
simplification -> integer constrained Delaunay triangulation ->
elevation-driven greedy insertion -> per-region materials -> OBJ.

Environment: deliberately runs on **system `python3` + numpy** (and the
system `cs2cs`, matching the precedent in
`application/scripts/build_regional_terrain.py`). This is experiment
tooling, not an application build product; the application `.venv` is left
untouched. The application's dependency-free GeoTIFF metadata parser is
imported read-only.

- `rasters.py` — 30 m working elevation + three-class grids from the
  checksum-pinned mosaics named by `bay-area-2026-08-02.json`.
- `boundaries.py` — boundary-chain extraction, Visvalingam ranking,
  small-ring removal, proper-crossing repair.
- `cdt.py` — deterministic pure-Python integer CDT.
- `refine.py` — Garland-Heckbert greedy insertion (vertical L-infinity,
  land samples only; water presents flat at sea level).
- `build_full_detail_mesh.py` — driver; writes OBJ/MTL/receipt under
  `../build/full-detail/`.
- `blender_review.py` — Blender import/view script.

Full-corpus run:

```bash
python3 build_full_detail_mesh.py
blender --python blender_review.py -- \
  ../build/full-detail/bay-area-full-detail.obj
```
