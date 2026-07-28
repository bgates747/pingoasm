# Earth fixture hardware comparison — 2026-07-28

## Test matrix

Each firmware was cold-reset five times. Every boot synchronously ran EarthIco
and then EarthUV. Each application rendered eight warmup frames followed by 36
measured frames at absolute 10-degree Y rotations.

The comparison changes the complete pixel pipeline together:

1. Corrected baseline: RGBA8888 source texture and RGBA8888 target.
2. Current one-byte renderer: RGBA2222 source texture and RGBA2222 target.

Both EarthUV variants use pixels generated from the same 320×160 source PNG.
The interval is `rendererRender()` only and excludes file loading, VDU upload,
bitmap display, and buffer flipping.

## Aggregate results

| Model | Pipeline | Mean frame | Rate | Population σ | Min | Max |
|---|---|---:|---:|---:|---:|---:|
| EarthIco | RGBA8888 corrected | 118.895 ms | 8.411 FPS | 0.349 ms | 118.198 ms | 119.546 ms |
| EarthIco | RGBA2222 one-byte | 97.225 ms | 10.285 FPS | 0.289 ms | 96.515 ms | 97.822 ms |
| EarthUV | RGBA8888 corrected | 174.488 ms | 5.731 FPS | 0.414 ms | 173.442 ms | 175.398 ms |
| EarthUV | RGBA2222 one-byte | 145.788 ms | 6.859 FPS | 0.500 ms | 144.739 ms | 146.760 ms |

## Improvement

| Model | Frame-time reduction | FPS increase |
|---|---:|---:|
| EarthIco | 18.226% | 22.288% |
| EarthUV | 16.448% | 19.686% |

The five per-run means differed by only 0.012 ms for EarthIco RGBA2222 and
0.007 ms for EarthUV RGBA2222. The result is therefore highly repeatable.

## Fixture distinction

EarthIco has 12 vertices and 20 triangles. It emphasizes fixed per-frame and
pixel-filling costs.

EarthUV has 482 vertices and 960 triangles. It adds substantially more
transform, clipping, triangle setup, and rasterization work. The improvement
remaining near 20% indicates that the one-byte pipeline helps under both
low-poly and geometry-heavy workloads rather than only the original Cube case.

## Invalid oversized-texture run

An earlier EarthUV RGBA8888 fixture used a 720×360 texture requiring 1,036,800
bytes. The client helper stages the complete texture in eZ80 RAM, but an
application loaded at `0x40000` has only approximately 512 KiB through MOS's
`0xBFFFF` RAM limit. Its partial globe, missing texture, and noisy equatorial
band were caused by client memory corruption and are excluded.

## Raw captures

1. `earth-suite-rgba8888-corrected-hardware-2026-07-28.log`
2. `earth-suite-rgba2222-one-byte-hardware-2026-07-28.log`
