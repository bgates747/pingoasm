# Hecker rasterizer overnight test plan

Status: emulator-qualified exact-output candidate at `agon-vdp:b87c95e`;
hardware remains on `working-pre-hecker` pending privileged upload approval
and human qualification.

The objective is to investigate and, if justified by evidence, adapt the
Hecker-derived scanline work without sacrificing the renderer behavior already
qualified on Agon hardware. The overnight work may flash the VDP repeatedly,
but it must not mistake an unattended test pass for final human visual
approval.

## 1. Boundaries and point of departure

1.1 [x] Finish hardware qualification of the current upstream-derived math
tranche before beginning Hecker work.

1.2 [x] Commit and tag that exact source as the new known-working point of
departure. Archive its ordinary and diagnostic firmware binaries outside Git,
with source commit and SHA-256 identities.

1.3 [x] Create one `experiment/hecker-rasterizer` branch. Use one small commit
per independently reversible experiment instead of creating a branch for
every variation.

1.4 [x] Do not import either historical `hecker` branch wholesale. Treat
`~/Agon/mystuff/pingo-hecker-reference/{hecker,hecker2}` and their patches as
provenance and hypotheses only. Those branches also changed mesh ownership,
removed or bypassed established lighting/depth behavior, wrapped UVs, and
contained incomplete viewport and edge handling.

1.5 [x] Preserve the current VDU protocol, object model, coordinate
conventions, RGBA2222 render target, back-face convention, perspective-correct
UV behavior, depth buffer, illumination, and callback contract.

1.6 [x] Use only the fifteen fixtures already present on the SD card for
overnight application-level testing. Native unit fixtures may exercise
individual raster functions but may not be used to claim application
compatibility.

1.7 [x] Do not alter the project emulator snapshot or commit emulator changes
overnight. Temporary emulator modules and headless result directories are
allowed. The user must visually approve any durable emulator change before it
is committed.

## 2. Preserve the test inputs

2.1 [ ] Record a manifest containing the SHA-256 and size of every
`/pingo/<fixture>/benchmark.bin`, texture, and the card's `autoexec.txt`.

2.2 [x] Configure `autoexec.txt` as one synchronous, fixed-order chain:

1. `cube-rgba2222`
2. `heavytank-rgba2222`
3. `earthuv-rgba2222`
4. `earth-party-camera-ellipse-rgba2222`
5. `cube-near-plane-rgba2222`
6. `earthuv-near-plane-rgba2222`
7. `jet-near-plane-rgba2222`
8. `airliner-near-plane-rgba2222`
9. `earthico-rgba2222`
10. `lara-rgba2222`
11. `crash-rgba2222`
12. `jet-rgba2222`
13. `airliner-rgba2222`
14. `earth-party-rgba2222`
15. `earth-party-camera-dolly-rgba2222`

This order is deliberately fail-fast: Cube exposes edge, orientation, UV, and
large-fragment errors; HeavyTank exposes chirality, winding, depth, and
perspective errors; EarthUV stresses triangle and texture work; the ellipse
fixture stresses multiple objects, camera pose, occlusion, and offscreen
motion.

2.3 [x] Teach the capture parser the two persistent control streams. The
single-model applications reuse bitmap 1257 and continue one sequence; the
three orbit applications reuse bitmap 1410 and continue another. The streams
interleave in the fixed application order, so fixture-level summaries still
need ordered occurrence boundaries.

2.4 [x] Expect 36 records from each of eight stationary fixtures, 73 from each
of four near-plane fixtures, and 289 from each of three orbit fixtures: 1,447
records for one complete boot suite. Require bitmap 1257 sequence `0..579`
and bitmap 1410 sequence `0..866`.

## 3. Establish exact overnight baselines

3.1 [x] Run the known-working ordinary firmware through the complete hardware
chain once before experimentation. Preserve raw logs and structured
per-fixture summaries. Repeat the complete chain for promotion candidates;
three baseline passes are unnecessary during exploratory screening.

3.2 [ ] Run the exact known-working firmware through every fixture in the
headless emulator. Capture the final RGBA2222 target and selected intermediate
frames for each fixture, not merely the final Cube frame.

3.3 [ ] Store baseline image hashes plus the raw target bytes. Hash equality is
the automatic correctness gate; raw bytes permit pixel-difference diagnosis
when a deliberate coverage-rule change prevents exact equality.

3.4 [ ] Preserve, outside the repositories, a run directory containing source
commit, dirty-diff hash if any, firmware and emulator-module hashes, build
logs, fixture manifest, `autoexec.txt`, raw serial log, parsed summary, image
artifacts, and terminal status.

## 4. Automatic gates for every candidate

4.1 [x] Reject a candidate immediately if the scope diff contains unrelated
VDU, object-model, coordinate, texture-format, callback, or deployment
changes.

4.2 [x] Require ordinary and diagnostic native tests to pass.

4.3 [x] Require ordinary and diagnostic PlatformIO firmware builds to pass.

4.4 [x] Run the headless emulator before flashing hardware. For a
semantics-preserving optimization, require exact selected-frame and
final-target equality across all fifteen fixtures.

4.5 [x] If a candidate intentionally changes pixel coverage rules, preserve
its images and pixel-difference report, then stop that line of work for human
review. Do not classify a visually plausible difference as correct
unattended.

4.6 [ ] Flash only a candidate that passes the emulator gate. Stop any serial
listener before upload, verify the uploaded firmware identity, restart
capture, reset the eZ80, and wait for the expected ordered records.

4.7 [ ] Fail the hardware run on a missing or malformed record, unexpected
sequence reset, wrong per-program count, VDP reboot/version banner, timeout,
upload failure, or MOS failure. Use a timeout derived from the baseline run
plus a generous margin, rather than one fixed short timeout.

4.8 [ ] Save a failed candidate and its evidence, restore the known-working
firmware, and continue only with an independent experiment. Never stack a new
hypothesis on an unexplained failure.

## 5. Evolutionary implementation sequence

5.1 [x] First extract testable raster primitives and characterize current
coverage at horizontal edges, vertical edges, shared diagonals, both accepted
area signs, degenerate triangles, subpixel coordinates, viewport boundaries,
and negative or zero reciprocal depth. This step changes no rendering.

5.2 [ ] Add incremental interpolation inside the existing bounding-box
rasterizer: advance edge functions, depth, `1/W`, `U/W`, and `V/W` across
pixels and rows while retaining current coverage and z-buffer decisions.
Change one interpolant family at a time and require exact image equality.

5.3 [x] Evaluate replacing the two per-fragment perspective divisions with one
reciprocal of interpolated `1/W`, followed by two multiplies. The candidate
changed color in 9 of 1,447 frames while preserving every z-buffer, so it was
rejected and reverted.

5.4 [x] Introduce scanline span bounds as a coverage accelerator while keeping
the current fragment shader and depth path intact. Prove the span endpoints
against current edge coverage before deleting any old coverage check.

5.5 [ ] Add top-left/shared-edge ownership rules only as a separate candidate.
Because this may change boundary pixels, it cannot pass solely by “looks
reasonable” and must await human review if hashes differ.

5.6 [ ] Only after the floating-point span reference is correct, evaluate the
Hecker-style gradient and edge stepping. Adapt it to clip-space reciprocal
`W`, not its historical use of screen-space `Z`; clamp spans to the viewport;
retain z-buffer testing, illumination, RGBA2222 output, and the established
non-wrapping texture sampler.

5.7 [ ] Keep geometric frustum clipping separate. The card's moving scenes
exercise offscreen objects, but they are not a controlled near-plane clipping
torture suite. Do not mix clipping into a Hecker performance result.

5.8 [x] Run diagnostic firmware only to attribute a change. State absolute
frame-time and FPS improvements only from ordinary firmware.

## 6. Hardware test cadence

6.1 [ ] During rapid iteration, use the first four programs in the fixed chain
as the quick gate. Their expected boundary is 397 total records. A controller may
interrupt the remaining chain with the next flash/reset after those four pass.

6.2 [ ] Run all 1,447 records once for every candidate that survives the quick
gate.

6.3 [ ] Run the full chain three times for a candidate proposed for retention.
Compare per-fixture distributions, not only a pooled average.

6.4 [ ] Retain an exploratory candidate when it produces a repeatable,
fixture-specific signal worth investigating and does not regress another
fixture by more than normal baseline variance.

6.5 [ ] Propose promotion only when correctness gates pass and the candidate
has a repeatable practical improvement on EarthUV or the multi-object scene
without a material Cube or HeavyTank regression. Final promotion still
requires human hardware visual review.

## 7. Unattended safety and recovery

7.1 [x] Before sleep, verify that the hardware is powered, the card is in the
Agon, `/dev/ttyUSB0` is stable, the serial listener is not competing with the
uploader, and a known-good upload/reset/capture cycle completes.

7.2 [x] Bound the number of candidate flashes and retries. A failed upload may
be retried once after reconnecting; repeated failure ends hardware work and
leaves the known-good firmware restored if possible. Privileged approval
timed out twice before the uploader started, so no flash was attempted.

7.3 [x] Never rewrite the SD card, change MOS, or change application binaries
during the unattended run.

7.4 [x] Leave a machine-readable ledger showing every candidate attempted,
commit/diff identity, emulator result, hardware result, performance summary,
reason retained or rejected, and final firmware left on the device. See the
dated rasterizer experiment document in `agon-vdp/docs`.

7.5 [x] End with the known-good firmware unless one candidate passed every
automatic gate. Even then, mark the candidate “awaiting human visual
qualification,” not accepted.

## 8. What the overnight suite cannot prove

8.1 [ ] The card contains only RGBA2222 fixtures. No Hecker candidate may be
declared legacy-compatible until an RGBA8888 regression fixture is tested
later.

8.2 [x] Cube, EarthUV, Jet, and Airliner now provide controlled camera motion
from `Z=3200` through the mesh center at `Z=0` and back while rotating twice.
The narrow aircraft profiles create strongly phase-dependent plane crossings.
The suite still
lacks a single-triangle viewport-edge fixture, shared-edge crack fixture, and
deliberate depth-tie application. Native cases can detect arithmetic
regressions, but hardware visual qualification of those remaining conditions
remains future work.

8.3 [ ] Serial timing confirms completion and performance; it does not prove
the displayed image is correct. Exact emulator targets are the unattended
image gate, and physical display review remains the final ground truth.

8.4 [ ] Existing application records do not carry an explicit fixture ID.
Ordered record counts are adequate for this frozen suite, but durable chained
benchmarking still needs the identity improvement tracked as optimization
roadmap item 1.8.

## 9. Deliverables for the morning

9.1 [x] A concise ledger of accepted and rejected experiments.

9.2 [ ] Raw and parsed emulator and hardware evidence for every retained or
important rejected candidate.

9.3 [x] Separate commits for each reversible code experiment, with no emulator
snapshot commit.

9.4 [x] A recommendation to retain, revise, or abandon the Hecker direction,
including which raster subphase changed and which fixtures benefited.

9.5 [x] The exact firmware identity left on the hardware and the command to
restore the known-working image.
