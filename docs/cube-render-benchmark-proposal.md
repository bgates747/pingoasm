# Deterministic cube render benchmark proposal

Status: implemented and qualified on hardware; emulator timing is non-authoritative
Date: 2026-07-28

## Objective

Create a short, deterministic Pingo fixture that measures rendering performance
across a complete rotation of the labeled cube.

The benchmark establishes a stable comparison point before work on:

1. Dual RGBA2222/RGBA8888 texture sampling.
2. Backface and frustum culling.
3. Hecker-inspired rasterizer optimizations.
4. Depth and interpolation changes.
5. Other renderer or memory-access optimizations.

The fixture must require no input, terminate automatically, and produce timing
records that can be captured from the VDP debug serial link.

## Implemented reusable layout

The benchmark is not cube-specific assembly maintained by hand. Its durable
inputs and tools are:

```text
benchmarks/render-spin/
├── profiles/
│   ├── cube-rgba8888.json
│   ├── cube-rgba2222.json
│   └── heavytank-rgba8888.json
└── fixtures/<profile>/src/

build/scripts/
├── build_render_benchmark.py
└── summarize_render_benchmark.py
```

A JSON profile declares geometry, texture and target formats, texture
dimensions, object scale, camera pose, resolution, warmups, measured frames,
axis, and angular step. The builder generates provenance-marked,
self-contained assembly and includes, copies the runtime texture, and invokes
`ez80asm`. Target directories remain reproducible and ignored.

Cube remains the visual baseline. HeavyTank proves that changing the model is a
profile operation rather than another hand-written fixture.

## Fixed workload

```text
Model:              labeled regression cube
Resolution:         320 x 240
Render target:      RGBA8888
Baseline texture:   blenderaxes.rgba8 (RGBA8888)
Camera pose:        (0, 0, +25)
Measured axis:      object Y
Measured increment: 10 degrees
Measured frames:    36
Warm-up frames:     8
```

The measured poses are:

```text
0, 10, 20, ... 350 degrees
```

This samples one complete revolution without rendering both 0 and 360 degrees,
which represent the same pose.

Clockwise or counterclockwise progression is acceptable, but it must remain
fixed once the baseline is established.

## Application behavior

The generated assembly application:

1. Initialize the same geometry, UVs, texture, camera, object position, scale,
   render target, and display mode for every run.
2. Perform eight unmeasured warm-up renders.
3. Set an absolute object rotation for each measured pose using command `13`.
4. Render exactly once per measured pose using command `38`.
5. Perform no keyboard polling, artificial delay, or frame-rate limiting.
6. Avoid changing camera, translation, scale, texture, lighting, or any other
   state during the measured sequence.
7. Restore the normal display mode after frame 36.
8. Print an application-level summary if available.
9. Exit cleanly to MOS.

The fixture calculates absolute angles. It does not use or reintroduce
VDP-side rotation accumulation.

## Warm-up behavior

Eight warm-up frames run before measurement to absorb one-time effects such as:

1. First object/scene traversal.
2. Cold instruction and data caches.
3. Lazy setup not completed during object creation.
4. Initial bitmap/render-target access.

Warmups use the first eight 10-degree poses; measurement then restarts at zero
degrees. They render to reserved bitmap `1258`, while measured frames render to
`1257`.

## Primary measurement: VDP renderer time

The authoritative renderer measurement belongs around `rendererRender()` inside
Pingo command `38`.

Conceptually:

```cpp
uint32_t start = micros();
rendererRender(&renderer);
uint32_t elapsed_us = micros() - start;
```

Microseconds are preferred over milliseconds so the benchmark remains useful
after substantial optimization. Unsigned subtraction must be used so timer
wraparound remains well-defined.

Timing must exclude:

1. Receiving the VDU command.
2. Parsing the bitmap ID.
3. Drawing the completed bitmap to the display.
4. Buffer flipping.
5. Serial diagnostic output itself.

## Serial record

After stopping the timer, the VDP emits one machine-parseable, policy-neutral
record:

```text
PINGO_RENDER seq=0 bmid=1258 render_us=123456
```

Requirements:

1. Use a stable `PINGO_RENDER` prefix.
2. Number every command-38 render monotonically from control initialization.
3. Report integer microseconds.
4. Emit the record only after the measured interval.
5. Do not mix prose into timing records.

Generated fixtures use distinct reserved bitmap IDs for warmup and measured
targets. A complete run therefore has a machine-identifiable signature of
eight warmup-target records followed by 36 measured-target records. This
remains unambiguous when a log also contains resets, interrupted runs, repeated
benchmarks, or arbitrary renders from interactive Pingo applications.

Command 38 cannot know the application's model, angle, or distinction between
warmup and measured frames. Those are application policy and do not belong in
the renderer. The profile-aware host summarizer assigns the first eight records
as warmups and maps the following 36 records to their declared angles.

Per-frame output exposes angular variation, warm-up behavior, and outliers. A
later opt-in timing mode may be added if unconditional diagnostics prove too
noisy for ordinary Pingo applications.

## Host aggregation

A host-side parser should consume `PINGO_RENDER` records and report:

1. Signature count: eight warmups and exactly 36 measured frames are required.
2. Total renderer time.
3. Minimum and maximum.
4. Arithmetic mean.
5. Median.
6. Standard deviation.
7. 95th percentile.
8. Equivalent mean frames per second.

It should reject or prominently flag:

1. Missing or duplicate frame numbers.
2. Unexpected angles.
3. More or fewer than 36 measured records.
4. Mixed firmware/build identities.
5. Malformed timing values.

Raw serial logs should remain available beside summaries so results can be
recomputed later.

## Run metadata

Every saved result should identify:

```text
Firmware version
agon-vdp commit and dirty state
pingoasm fixture commit and dirty state
Hardware or emulator
Resolution
Texture format
Render-target format
Warm-up count
Measured frame count
Angle sequence
Timing scope
Enabled optimization flags
```

The hardware result is authoritative. Emulator timing is recorded separately
and must never be compared as though it represented ESP32 performance.

## Texture-format extension

After the RGBA8888 baseline is qualified, build a paired RGBA2222 fixture:

```text
RGBA8888: cube geometry + blenderaxes.rgba8
RGBA2222: cube geometry + blenderaxes.rgba2
```

Both variants use identical geometry, UVs, camera, transforms, measured
angles, and warm-ups. During the source-only experiment both used RGBA8888
targets. The full one-byte pipeline profile now explicitly pairs the RGBA2222
texture with RGBA2222 warmup and measured targets.

The comparison should determine:

1. Whether RGBA2222 sampling preserves accepted geometry and UV behavior.
2. Whether source-memory reduction offsets per-sample expansion cost.
3. How mean, distribution, and worst-frame time change.
4. Whether RGBA8888 performance or correctness regresses.

## Acceptance criteria

The initial RGBA8888 fixture was accepted when:

1. It renders eight warm-up frames and exactly 36 measured frames.
2. The measured angles cover 0 through 350 degrees in 10-degree increments.
3. The cube remains visually correct throughout the revolution.
4. Exactly 44 ordered `PINGO_RENDER` records are captured: eight warmups and
   36 measured frames.
5. The application restores the display and exits to MOS without input.
6. Repeated hardware runs produce reasonably stable distributions.
7. Ordinary VDP operation remains healthy after the benchmark.
8. The same fixture completes correctly in the project-local PingoWolf
   emulator after
   hardware qualification.

## Scope exclusions

The first fixture does not:

1. Change renderer behavior.
2. Add optimization counters.
3. Benchmark model upload or texture transfer.
4. Benchmark bitmap drawing or buffer flipping as renderer work.
5. Change texture format.
6. Exercise near-plane clipping.
7. Replace the later need for a higher-poly benchmark such as the globe.

The cube establishes trustworthy measurement mechanics and angular coverage.
Once that harness is stable, heavier geometry can reuse the same timing and
aggregation conventions.

## Qualified baseline

The canonical July 28 hardware capture contains one clean tagged run:

```text
Mean renderer time: 231.28 ms
Median:             230.37 ms
Minimum:            219.25 ms
P95:                241.67 ms
Maximum:            241.68 ms
Equivalent rate:    4.32 FPS
```

The raw capture and generated JSON live under
`benchmarks/render-spin/results/cube-rgba8888-hardware-2026-07-28.*`.

## Qualified one-byte result

The regenerated `cube-rgba2222` fixture now emits `CTB2` for both reserved
targets and is 2,681 bytes. The legacy RGBA8888-target binary was retained on
the hardware SD for the first compatibility run of the packed renderer:

```text
Mean renderer time: 203.729 ms
Equivalent rate:      4.908 FPS
Frame-time reduction: 12.46% versus the 232.720 ms lookup baseline
FPS increase:         14.23%
```

That capture proved the one-byte renderer completed the deterministic workload
through the RGBA8888 compatibility output path. The regenerated all-RGBA2222
fixture was then deployed without changing its SD directory or executable
name. Its binary contains two `CTB2` target-create commands and no RGBA8888
target-create command.

Two direct-target runs produced effectively identical means. The clean
canonical capture contains exactly eight warmups followed by 36 measured
frames:

```text
Mean renderer time: 203.626 ms
Equivalent rate:      4.911 FPS
Minimum:            191.603 ms
Median:             202.931 ms
P95:                213.917 ms
Maximum:            213.955 ms
```

Relative to the 232.720 ms lookup baseline, frame time fell 12.50% and
equivalent FPS rose 14.29%. The timer still excludes final output work, so it
does not credit the direct RGBA2222 target for eliminating the old post-render
copy/conversion.
