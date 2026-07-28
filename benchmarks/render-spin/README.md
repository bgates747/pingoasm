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
rotation settings. The generator deliberately keeps texture and target metadata
outside the geometry include.

The initial profiles demonstrate reuse:

1. `cube-rgba8888.json` is the original small visual-regression baseline.
2. `cube-rgba2222.json` uses the packed Cube texture and packed warmup/measured
   targets, providing the full one-byte pipeline comparison.
3. `heavytank-rgba8888.json` runs the same benchmark protocol against the
   higher-poly, chiral HeavyTank model.

## Run and capture

Copy the fixture's `tgt` files to one directory on the hardware SD card and run
`benchmark.bin`. Hardware is the authoritative performance target. The program
performs its warmups, renders the configured revolution without input, restores
the normal display mode, and exits to MOS.

Pingo command 38 emits one firmware diagnostic per render:

```text
PINGO_RENDER seq=0 bmid=1258 render_us=123456
```

The interval contains only `rendererRender()`. It excludes bitmap copying,
display, buffer flip, VDU parsing, and the diagnostic itself. Generated
fixtures reserve separate warmup and measured target bitmap IDs. The
summarizer recognizes the resulting 8-warmup/36-measured signature, so
unrelated interactive renders in the same log are ignored.

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

The summarizer finds the latest complete tagged benchmark sequence, removes the
profile-declared warmups, assigns angles to measured frames, validates the count
and ordering, and reports total, minimum, mean, median, population standard
deviation, p95, maximum, and equivalent mean FPS.

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
