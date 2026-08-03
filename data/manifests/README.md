# Source-data manifests

Record every accepted geospatial input here before an ordinary build depends
on it. Each manifest must identify the provider and product, source URL or API
query, coverage, horizontal and vertical reference systems, retrieval date,
local filename, byte size, and SHA-256 checksum.

Downloaded products themselves belong under ignored `data/downloads/` unless
a later, explicit distribution decision says otherwise.

The regional Bay Area corpus is planned, acquired, resumed, and validated with
the project-local environment:

```
.venv/bin/python scripts/acquire_bay_area.py --plan-only
.venv/bin/python scripts/acquire_bay_area.py
.venv/bin/python scripts/acquire_bay_area.py --validate-only
```

The script uses balanced, independently retryable requests no larger than
2,048 pixels per axis. It writes the accepted per-tile request, projected
bounds, TIFF metadata, content summary, byte size, and SHA-256 checksum to the
dated manifest only after the complete corpus passes validation.

`bay-area-full-l0-2026-08-02.json` is the compact tracked receipt for the
generated loose-file runtime corpus. Its ignored `WORLD.json` binds all 50,652
P3DM components individually; the tracked receipt records that manifest's
length and SHA-256, the exact build command, source-manifest identity, grid and
normalization contract, and aggregate geometry/byte counts.

`bay-area-hex-full-l0-2026-08-02.json` is the corresponding receipt for the
superseding 50,183-cell N=5 hexagonal corpus. In addition to the runtime
`WORLD.json`, it binds the mandatory complete-region Blender review artifact
and records the six straight-side boundary contract.
