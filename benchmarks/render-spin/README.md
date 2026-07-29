# Pingo render-spin benchmarks

This directory contains deterministic, profile-driven render fixtures. They are
separate from interactive sample applications because benchmark workloads must
remain fixed and machine-checkable.

## Build a fixture

From the `pingoasm` project root:

```bash
python3 build/scripts/build_render_benchmark.py \
  benchmarks/render-spin/profiles/cube-rgba8888.json
```

Build the workload-equivalent RGBA2222 texture variant with:

```bash
python3 build/scripts/build_render_benchmark.py \
  benchmarks/render-spin/profiles/cube-rgba2222.json
```

This creates:

```text
benchmarks/render-spin/fixtures/cube-rgba8888/
├── src/
│   ├── benchmark.asm
│   ├── model.inc
│   └── vdu_tv.inc
└── tgt/
    ├── benchmark.bin
    └── blenderaxes.rgba8
```

The generated source is self-contained and carries provenance banners. The
`tgt` directory is ignored because it is reproducible runtime output.

To define another workload, copy a JSON file under `profiles/` and change its
model, texture, texture format, target format, dimensions, scale, camera, or
rotation settings. `series_runs` controls how many complete warmup-plus-
revolution series execute in one invocation; the qualified profiles use five.
The generator deliberately keeps texture and target metadata outside the
geometry include.

The initial profiles demonstrate reuse:

1. `cube-rgba8888.json` is the original small visual-regression baseline.
2. `cube-rgba2222.json` uses the packed Cube texture and packed warmup/measured
   targets, providing the full one-byte pipeline comparison.
3. `heavytank-rgba8888.json` runs the same benchmark protocol against the
   higher-poly, chiral HeavyTank model.
4. `earthico-rgba2222.json` demonstrates the source-driven path: it converts
   the authoritative `earthico.obj` and `earthico160x76.png` into a portable
   model include and packed runtime texture before assembling the benchmark.
5. `earthuv-rgba2222.json` uses the same protocol with 482 vertices, 960
   triangles, and the established 320×160 Earth texture. Compared with
   EarthIco, it stresses geometry throughput with 40 times as many triangles
   and texture handling with approximately four times as many texels.
6. `earthuv-rgba8888.json` is the workload-equivalent four-byte fixture for
   testing the corrected RGBA8888 firmware baseline. The RGBA2222 and RGBA8888
   profiles deliberately change both source and target formats together; they
   are the two canonical EarthUV firmware comparisons.
7. `earthico-rgba8888.json` pairs with `earthico-rgba2222.json` in the same
   fashion. Together, the four Earth profiles form two sequential two-model
   firmware suites: corrected RGBA8888 and current one-byte RGBA2222.

The benchmark loader stages a complete texture in eZ80 RAM before uploading
it. Applications begin at `0x40000`, and MOS exposes RAM through `0xBFFFF`, so
the executable and staged texture must fit within approximately 512 KiB. A
720×360 RGBA8888 Earth texture requires 1,036,800 bytes and corrupts memory;
its partial globe, untextured faces, and noisy equatorial band are a client
overrun, not a renderer result. The paired 320×160 source keeps the RGBA8888
payload at 204,800 bytes and provides a valid like-for-like firmware test.

## Run and capture

Copy the fixture's `tgt` files to one directory on the hardware SD card and run
`benchmark.bin`. Hardware is the authoritative performance target. The program
performs the configured number of complete series; each series performs its
warmups and renders one revolution without input. It restores the normal
display mode and exits to MOS only after all series finish.

The generated assembly defines `benchmark_series_runs` with `EQU`. It loads
that value into `A`, saves it across the unrolled render sequence on the stack,
then restores, decrements, and loops while nonzero. This deliberately keeps the
individual poses unrolled and makes repetition cheap without imposing that
benchmark-specific idiom on production applications.

Ordinary firmware emits one stable timing record per Pingo command 38:

```text
PINGO_RENDER seq=0 bmid=1258 render_us=123456
```

The interval contains only `rendererRender()`. It excludes bitmap copying,
display, buffer flip, VDU parsing, and the diagnostic itself. Generated
fixtures reserve separate warmup and measured target bitmap IDs. The
summarizer recognizes the profile-declared number of consecutive
8-warmup/36-measured signatures, so unrelated interactive renders in the same
log are ignored.

Start the reconnecting debug listener before running a hardware fixture:

```bash
cd ~/Agon/mystuff/pingoasm
python3 build/scripts/listen_vdp_debug.py
```

It displays traffic immediately in that terminal and appends the identical raw
bytes to a timestamped `vdp-debug-*.log` in the current directory. It retries
`/dev/ttyUSB0` every second after unplugging, replugging, a VDP reset, or another
temporary connection failure.

While it is running:

1. Press `R` to pulse the VDP hardware-reset line. With a benchmark selected by
   `autoexec.txt`, this reboots the Agon and starts another unattended run.
2. Press Ctrl+C to stop the listener.

Listener status and reset notices appear only in the terminal. The log contains
the raw VDP byte stream and remains directly consumable by the summarizer.

Useful overrides:

```bash
python3 build/scripts/listen_vdp_debug.py \
  --port /dev/ttyUSB0 \
  --baud 115200 \
  --log benchmarks/render-spin/results/my-run.log
```

The listener uses only Python's standard library. Opening or reconnecting does
not reset the ESP32; it pulses reset only when you press `R`. It takes an
exclusive serial lock so an uploader or second listener cannot silently corrupt
the capture.

## Summarize a capture

```bash
python3 build/scripts/summarize_render_benchmark.py \
  benchmarks/render-spin/profiles/cube-rgba8888.json \
  hardware-console.log \
  --platform hardware \
  --firmware "Pingo 2.15 Alpha 1" \
  --json-output cube-hardware.json
```

The summarizer finds the latest complete tagged benchmark suite, removes each
series' profile-declared warmups, assigns series and angle identities to every
measured frame, validates the count and ordering, and reports aggregate and
per-series statistics. Those include total, minimum, mean, median, population
standard deviation, p95, maximum, and equivalent mean FPS.

The profiles previously described one series, so historical raw logs contain
only one 8+36 signature. Reparse one of those without editing its durable
profile by adding `--series-runs 1`.

## Renderer-attribution diagnostics

The separate `esp32dev-pingo-diag` firmware variant appends versioned phase
timings and workload counters to the same stable record prefix. Capture one
model per log initially: the current model profiles deliberately reuse the
same bitmap IDs and frame signature, so a chained multi-model log does not
identify which complete run belongs to which model.

Require and summarize the extended schema with:

```bash
python3 build/scripts/summarize_render_benchmark.py \
  benchmarks/render-spin/profiles/cube-rgba2222.json \
  hardware-console.log \
  --require-diagnostics \
  --platform hardware \
  --firmware "pingo-codex diagnostic" \
  --json-output cube-diagnostics.json
```

The parser validates the schema and both counter partitions before computing
renderer-phase shares, raster coverage, depth-rejection, and shade ratios.
Per-frame raw counters and timings are retained in the JSON. Run its regression
tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest \
  build/scripts/test_summarize_render_benchmark.py
```

Diagnostic builds add clocks and counters and therefore are for attribution,
not release-speed comparisons. Measure observer effect by running the same
fixture under ordinary firmware. The diagnostic command timer ends when the
selected target bitmap is ready; later display and buffer-flip commands are
outside its scope. The authoritative field definitions and firmware workflow
are in `agon-vdp/docs/pingo-render-diagnostics.md`.

## Qualified five-series diagnostics

The first qualified hardware suite used the RGBA2222 Cube profile and
diagnostic firmware. All 220 records arrived contiguously: five repetitions of
eight warmups plus 36 measured frames. The aggregate over 180 measured frames
was:

| Measurement | Result |
| --- | ---: |
| Mean renderer time | 209.210 ms |
| Equivalent rate | 4.780 FPS |
| Clear share | 12.751% |
| Transform share | 0.319% |
| Triangle-setup share | 0.088% |
| Raster share | 86.751% |
| Bounding-box coverage | 47.665% |
| Backface rejected | 72.222% |
| Rasterized triangles | 27.778% |

The five series means ranged only from 209.208 to 209.212 ms, a 3.94 µs or
0.0019% span. This is diagnostic attribution, not a release-speed comparison.
The durable summary is
`results/cube-rgba2222-diagnostics-hardware-2026-07-28.json`; its raw serial
capture is retained beside it locally.

The matching EarthIco suite also delivered all 220 records and passed every
strict invariant:

| Measurement | Cube | EarthIco | EarthUV |
| --- | ---: | ---: | ---: |
| Mean renderer time | 209.210 ms | 99.441 ms | 150.039 ms |
| Equivalent rate | 4.780 FPS | 10.056 FPS | 6.665 FPS |
| Clear mean | 26.676 ms | 26.673 ms | 26.669 ms |
| Transform mean | 0.668 ms | 0.695 ms | 11.966 ms |
| Triangle-setup mean | 0.185 ms | 0.206 ms | 2.184 ms |
| Raster mean | 181.492 ms | 71.667 ms | 108.436 ms |
| Bounding-box candidates | 14,595,160 | 6,347,485 | 9,744,415 |
| Covered fragments | 6,956,760 | 2,695,105 | 3,651,825 |
| Bounding-box coverage | 47.665% | 42.459% | 37.476% |
| Submitted triangles | 2,160 | 3,600 | 172,800 |
| Rasterized triangles | 600 | 1,560 | 62,420 |

The clear cost is effectively identical, as expected for equal 320×240
targets. EarthIco submits and rasterizes more triangles, yet Cube visits 2.30
times as many bounding-box candidates and shades 2.58 times as many
fragments. This directly shows that the present renderer is dominated by
screen-space raster workload rather than raw triangle count for these models.
EarthIco's five series means span 9.69 µs, or 0.0097%. Its durable summary is
`results/earthico-rgba2222-diagnostics-hardware-2026-07-28.json`.

EarthUV supplies the complementary geometry-heavy result. It submits 48 times
as many triangles as EarthIco, raising transform plus setup from 0.9% to 9.4%
of frame time, but visits only 1.54 times as many bounding-box pixels. Its
raster phase remains the largest cost at 72.3%. Compared with Cube, EarthUV
submits 80 times as many triangles while testing only two thirds as many
bounding-box pixels and completing 28.3% sooner. EarthUV's five series means
span 35.47 µs, or 0.0236%. Its durable summary is
`results/earthuv-rgba2222-diagnostics-hardware-2026-07-28.json`.

Do not compare emulator timings as ESP32 performance. The same fixture may be
run there for correctness and for emulator-specific regression measurements
after the hardware result has been validated.

## Qualified dual-input result

Pingo 2.15 Alpha 1 accepts both source texture formats through existing VDP
bitmap metadata. Visually qualified hardware runs measured:

```text
RGBA8888:                   232.631 ms mean, 4.299 FPS
RGBA2222, direct expansion: 239.969 ms mean, 4.167 FPS (two-run mean)
RGBA2222, shared lookup:    232.720 ms mean, 4.297 FPS
```

The shared 1 KiB read-only lookup removed the per-texel expansion penalty.
Lookup-table RGBA2222 was within 0.038% of RGBA8888 while retaining a 75%
smaller source texture and transfer. These results cover source textures only;
Pingo's working framebuffer and render target remain RGBA8888.

## Qualified one-byte working/output result

The qualified implementation in `agon-vdp` commit `a382ede` makes RGBA2222
Pingo's working pixel, samples packed textures directly, and binds the
command-selected RGBA2222 target as the framebuffer. RGBA8888 sources retain
four-byte stride and are packed when sampled; RGBA8888 targets are expanded
after the timed renderer interval for legacy compatibility.

The first hardware capture deliberately used the old RGBA8888-target binary to
test that compatibility path:

```text
Mean:                 203.729 ms
Equivalent rate:        4.908 FPS
Frame-time reduction:  12.46%
FPS increase:          14.23%
```

The regenerated 2,681-byte `cube-rgba2222` fixture creates both targets with
`CTB2`. Two direct-target hardware captures agreed to approximately 1 µs in
mean frame time. The clean canonical repeat is:

```text
Mean:                 203.626 ms
Equivalent rate:        4.911 FPS
Minimum:              191.603 ms
Median:               202.931 ms
P95:                  213.917 ms
Maximum:              213.955 ms
```

Against the best preceding RGBA2222 lookup implementation at 232.720 ms and
4.297 FPS, the one-byte pipeline reduces timed renderer work by 12.50% and
increases effective FPS by 14.29%. The saved result is
`results/cube-rgba2222-one-byte-hardware-2026-07-28.json`.

The interval excludes output conversion/copying. Consequently this comparison
credits the one-byte renderer but does not count the additional end-to-end
benefit of rendering directly into the packed target.
