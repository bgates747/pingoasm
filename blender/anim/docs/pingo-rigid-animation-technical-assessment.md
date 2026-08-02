# Technical assessment: rigid Lara animation on Pingo

Status: implemented application architecture; temporal policy revised after visual review
Date: 2026-08-01; implementation update 2026-08-02

## Decision

Implement the running animation entirely as an eZ80-owned, sampled rigid-body
animation. Do not add armatures, skinning, animation storage, interpolation, a
camera tracker, or any new command to PingoWolf.

The current Blender result is already in the form Pingo needs: static textured
meshes plus one absolute rigid transform per driven part and source frame. The
current assembly applications already own world time, retain absolute object
state, coalesce obsolete poses while one render is in flight, and send the
newest pose through existing Pingo commands. The implemented client is the
isolated `apps/anim` application, derived from the modern
`apps/earth-party-*` runtime pattern.

The recommended first runtime asset has:

1. 15 static Pingo meshes and objects;
2. one shared RGBA2222 Lara texture;
3. 23 frame-major pose samples at 30 Hz, plus one non-stored periodic successor
   used for validation;
4. 15 records per frame, each containing absolute XYZ translation and XYZ
   Euler rotation; and
5. no runtime forward kinematics and no VDP-side animation state.

This is a firm recommendation, not merely a possible fallback. The existing
wire format, object limit, memory budget, and measured transport rate all fit.

## Scope of the conclusion

The design directly covers the validated 68-frame run, including its captured
root translation, a root-locked inspection mode, and application-owned camera
following. A standalone Pingo control can also use the existing scene transform
as a character-wide placement transform because every object in that control
belongs to Lara.

Placing the animated actor at an arbitrary changing heading inside a larger
mixed Pingo scene is a later eZ80 composition problem. Pingo has no per-group
transform: its scene transform affects every object in the control. That does
not justify firmware work for the first implementation. It means a later
multi-actor client must compose an actor root with each part on the eZ80, or use
a constrained/precomputed heading policy.

## Evidence base

This assessment treats the following as authoritative:

1. [`apps/earth-party-tex`](../../../apps/earth-party-tex/README.md) and
   [`apps/earth-party-flat`](../../../apps/earth-party-flat/README.md) for the
   current assembly architecture. Older applications and benchmarks are
   supporting evidence only.
2. [`apps/earth-party-tex/src/agon/3d.inc`](../../../apps/earth-party-tex/src/agon/3d.inc)
   for eZ80 object state, numeric domains, transform order, dirty-state
   synchronization, and packet sizes.
3. [`apps/earth-party-tex/src/render-async.inc`](../../../apps/earth-party-tex/src/render-async.inc)
   for the qualified one-render-in-flight and `P3DR` mailbox pattern.
4. [`lara_running_normal_001.blend`](../bandai_namco/run_normal_001/output/lara_running_normal_001.blend)
   and its reproducible
   [builder](../bandai_namco/run_normal_001/scripts/build_lara_running_scene.py)
   for the animation and rigid-part mapping.
5. The owned `~/Agon/mystuff/agon-vdp` `pingowolf` branch. Its current head is
   `16b8aa6302fcf01495a80cee97f669875e209335`; the accepted PingoWolf Alpha 1
   renderer/protocol source is tag `pingowolf-v0.1.0-alpha.1`, commit
   `3c07e754b00cc863b9cf04e0baf140d778553eed`. The later commit changes only
   combined-emulator fixture paths.
6. The complete canonical `agon-dev-env/cross-agent/wolf_pingo_vdp` topic,
   including all coordination messages. It confirms Pingo's `0x49` ownership,
   `P3DR` completion contract, one global buffer-ID namespace, and the accepted
   PingoWolf resource/lifecycle boundary.

The experimental TurboVega OTF/BDPP paths are deliberately excluded. They add
coordinated MOS/VDP machinery that this animation neither needs nor benefits
from.

## Why the current VDP is sufficient

Pingo already exposes every operation required by rigid sampled animation:

| Operation | Existing Pingo subcommand |
|---|---:|
| Define mesh positions | 1 |
| Define position indices | 2 |
| Define UVs | 3 |
| Define UV indices | 4 |
| Create textured object | 5 |
| Set absolute XYZ scale | 9 |
| Set absolute XYZ Euler rotation | 13 |
| Set absolute XYZ translation | 17 |
| Set camera XYZ rotation/translation | 21 / 25 |
| Set scene XYZ scale/rotation/translation | 29 / 33 / 37 |
| Render to bitmap | 38 |
| Delete the control | 39 |
| Configure `P3DR` notification | 41 |

Subcommand 42 is explicitly reserved after removal of the historical
firmware-side `camera_track_object`. Camera following must stay on the eZ80,
which is also the desired ownership boundary.

For column vectors, current Pingo constructs an object transform as:

```text
Mobject = T · Rz · Ry · Rx · S
```

The scene transform is composed outside it:

```text
Mfinal = Mscene · Mobject
```

Blender's XYZ Euler decomposition represents the same `Rz · Ry · Rx` rotation
order. An evaluated Blender rigid matrix can therefore be converted and
quantized without changing the VDP representation. Pingo does not need to know
which bone produced that matrix.

## Source parts and runtime objects

The Blender file retains 17 semantic meshes because that is the clearest
editable and diagnostic representation. Direct inspection of all 68 evaluated
frames found that `pelvis`, `holster.l`, and `holster.r` have identical object
matrices on every frame. They should remain distinct in Blender but be joined
into one generated Pingo mesh. This gives 15 runtime objects and exactly 15
unique tracks.

| Runtime object | Blender source mesh or meshes | Animation driver |
|---|---|---|
| `pelvis_bundle` | `pelvis`, `holster.l`, `holster.r` | `pelvis` |
| `torso` | `torso` | `torso` |
| `head` | `head` | `head` |
| `arm.l` | `arm.l` | `arm.l` |
| `forearm.l` | `forearm.l` | `forearm.l` |
| `hand.l` | `hand.l` | `hand.l` |
| `arm.r` | `arm.r` | `arm.r` |
| `forearm.r` | `forearm.r` | `forearm.r` |
| `hand.r` | `hand.r` | `hand.r` |
| `thigh.l` | `thigh.l` | `thigh.l` |
| `leg.l` | `leg.l` | `leg.l` |
| `foot.l` | `foot.l` | `foot.l` |
| `thigh.r` | `thigh.r` | `thigh.r` |
| `leg.r` | `leg.r` | `leg.r` |
| `foot.r` | `foot.r` | `foot.r` |

The export-only join is lossless because the three inputs share a transform,
material, texture, coordinate frame, and animation track. It also reduces
object traversal and transform traffic without obscuring the source asset's
hand/holster correction.

Pingo admits at most 32 renderables to one scene. Fifteen fits comfortably. A
17-object diagnostic export would also fit, but it would add no information to
the renderer.

## Proposed asset path

```text
lara_running_normal_001.blend
        |
        | evaluated by Blender 4.0.2, stored frames 1..23 + successor 24
        v
dedicated Pingo exporter
        |
        +-- 15 compact indexed meshes + shared UV texture contract
        +-- 23 x 15 command-domain pose records
        +-- generated constants, provenance, and validation metadata
        v
apps/anim/src/*.inc
        |
        | fixed 30 Hz eZ80 phase; newest-pose coalescing
        v
existing Pingo 0x49 object commands -> render 38 -> existing P3DR callback
```

Generated assembly belongs in the consuming application's `src/` so that the
application remains portable. The editable Blender and image assets remain the
authoritative inputs; generated files must name their generator and exact
input. At only 4,140 pose bytes, compiling the first clip into the application
is simpler and safer than adding SD streaming.

## Geometry export contract

### Preserve the current shared origin

The running scene's mesh data is the corrected Lara rest geometry. Every part
retains the model's shared origin; its keyed `matrix_world` is the complete
rigid delta that rotates about the proper rest pivot. The exporter should
preserve those local coordinates and matrices. Recentring each mesh on a bone
is unnecessary and would create another bind-offset calculation to validate.

The pelvis/holster join must concatenate their unchanged local vertices and
remap indices. It must not apply an animation frame to the mesh data.

### Use one normalization factor

All 15 runtime meshes must share one geometry normalization factor computed
across the complete character. Calling the current generic OBJ writer once per
part would be wrong because it normalizes each input independently, making
small parts grow to the size of large ones.

A direct audit of the generated Blender file found the aggregate maximum
absolute local coordinate to be:

```text
0.7247999906539917
```

For each converted local vertex `v`, the mesh word is therefore based on
`v / 0.7247999906539917`, not on a per-part bound. The exporter should derive
and record the value rather than hard-code the decimal.

The current asset totals 300 positions and 526 triangles. Pingo uses separate
position and UV index arrays, so the exporter must compact and remap both for
each runtime mesh while retaining one shared 256×184 texture. No vertex-normal
command exists in the current bridge; lighting derives face normals from
transformed triangle edges. A dedicated exporter need not emit the unused
normal arrays found in older generated includes.

Because Pingo performs backface culling and does not alpha-blend covered
fragments, winding and opacity are export gates. The basis conversion below is
a proper rotation, not a reflection, so it preserves handedness and winding.

### Convert Blender Z-up to Pingo Y-up once

Pingo's accepted world is right-handed: `+X` right, `+Y` up, `+Z` toward the
viewer, with unrotated forward along `-Z`. Use this proper basis conversion:

```text
(xp, yp, zp) = (xb, zb, -yb)
```

For a Blender object matrix `Mb` and corresponding basis matrix `C`:

```text
Mp = C · Mb · C^-1
```

Apply the same basis to static vertices and every animated matrix. Do not swap
axes independently in the mesh and pose exporters.

## Pose extraction and quantization

For each runtime track and each frame from 1 through 68:

1. set the Blender scene frame and read the evaluated `matrix_world`;
2. compute `Mp = C · Mb · C^-1`;
3. take translation directly from `Mp`;
4. take the normalized rotation, discarding only verified near-unit scale
   residue;
5. extract Blender `XYZ` Euler angles using the preceding frame as the
   compatibility reference;
6. normalize the mesh and translation by the same whole-character geometry
   factor;
7. multiply translation by the selected Pingo object scale;
8. quantize translation and Euler values to Pingo's signed 16-bit wire domains;
   and
9. reconstruct `T · Rz · Ry · Rx · S` and compare it with the source transform
   before emitting output.

Pingo's relevant numeric domains are:

```text
mesh coordinate = signed_word / 32767
Euler radians    = signed_word * 2*pi / 32767
translation      = signed_word * 256 / 32767
scale            = unsigned_word / 256
```

Use the already qualified static Lara scale of `1280`, or 5.0, for the first
client. Object scale does not scale object translation in Pingo because
translation is applied after scale. The exporter must consequently multiply
the normalized translations by 5.0 before encoding them. Changing character
scale later requires regenerating or multiplying translations as well as
changing command 9.

Do not wrap each Euler component to ±180 degrees. Blender's compatible Euler
selection keeps adjacent samples continuous, and this clip's continuous values
fit inside Pingo's full ±360-degree signed domain. Wrapping produced artificial
354–359-degree component jumps in the audit even though the matrices remained
equivalent.

### Measurements from the full-capture audit

The pre-extraction read-only Blender 4.0.2 audit sampled every part on all 68
frames after the Pingo basis conversion. These measurements remain the sizing
and numeric-domain evidence for the source capture:

| Property | Measured result |
|---|---:|
| Frames / source rate | 68 / 30 Hz |
| Semantic parts / runtime tracks | 17 / 15 |
| Maximum keyed scale deviation from 1.0 | `2.08e-5` |
| Maximum rigid decomposition coefficient error | `1.71e-5` |
| Closest XYZ Euler sample to gimbal lock | 40.45 degrees away |
| Continuous Euler X range | −182.07 to +131.14 degrees |
| Continuous Euler Y range | −196.06 to +195.08 degrees |
| Continuous Euler Z range | −188.39 to +49.90 degrees |
| Largest adjacent continuous Euler step, X/Y/Z | 34.06 / 15.90 / 18.51 degrees |
| Scale-5 translation word range, X | −322 to +381 |
| Scale-5 translation word range, Y | −956 to +391 |
| Scale-5 translation word range, Z | −512 to +7635 |
| Maximum quantized transformed-vertex error at scale 5 | 0.00657 Pingo world units |

The translation and angle ranges are far inside signed 16-bit limits. The
maximum reconstructed vertex error is about 0.08 percent of the approximately
8.7-unit-tall scale-5 character. There is no matrix-representation reason to
add a VDP quaternion or matrix command.

The implemented 23-sample loop plus virtual successor has a 4,140-byte table,
2,131-count forward stride, zero endpoint rotation error, at most one word of
endpoint translation quantization error, and finite-step world-hierarchy
velocity residuals of 1.81 degrees and 20 translation counts. Frames 1..15
retain the exact pre-closure pose records.

## Generated pose record

The preferred record deliberately matches the contiguous 12-byte position and
rotation slice in the current 64-byte `p3d_object` state:

| Byte offset | Field | Encoding |
|---:|---|---|
| 0 | `tx` | signed little-endian 16-bit Pingo translation |
| 2 | `ty` | signed little-endian 16-bit Pingo translation |
| 4 | `tz` | signed little-endian 16-bit Pingo translation |
| 6 | `rx` | signed little-endian 16-bit Pingo turn |
| 8 | `ry` | signed little-endian 16-bit Pingo turn |
| 10 | `rz` | signed little-endian 16-bit Pingo turn |

Store records frame-major in the stable 15-object order shown above. One frame
is 180 bytes; the full table is:

```text
23 frames * 15 tracks * 12 bytes = 4,140 bytes
```

Generated constants should include frame count, source rate, record size,
track count, normalization provenance, object scale word, source frame range,
and the stable track IDs. Translation values are scale-5 command-domain values,
so that coupling must be explicit in the banner and machine-readable metadata.

The current sampled-Earth mechanism also stores an 18-byte Q15 orientation
matrix because Earth uses its orientation for continuing local-space motion.
Lara's part states are render-only: no limb invokes `p3d_object_step16`.
Duplicating 18 matrix bytes per part and frame would therefore add 18,360 bytes
without affecting the rendered result. It can be introduced later only if an
eZ80 actor-composition design actually consumes it.

Delta compression, keyframe interpolation, quaternion decoding, and cached VDP
command buffers are similarly unnecessary for a 4,140-byte first clip. Direct
absolute records are easier to inspect, test, and recover after skipped render
frames.

## eZ80 runtime design

### Initialization

The application should follow the modern Earth Party sequence:

1. load the 47,104-byte RGBA2222 Lara texture through the shared staging area;
2. create an RGBA2222 target and one Pingo control with exactly matching
   dimensions;
3. upload the 15 compact meshes and their UV data;
4. create 15 textured objects with stable control-local IDs;
5. initialize 15 `p3d_object` states and set static XYZ scale to 1280;
6. install the initial frame's position and Euler words, mark both pose bits
   dirty, and synchronize all objects;
7. use the established general-poll barrier to fence texture and scene setup;
8. install the MOS keyboard callback, enable command-41 notifications, and
   submit the first render.

Pingo control SIDs, Wolf control SIDs, and ordinary buffer/bitmap IDs share one
global 16-bit buffer namespace. The application manifest must reserve its
control, texture, target, and other buffer-backed IDs in that namespace. Mesh
and object IDs instead index maps local to the selected Pingo control; record
their stable local values in the manifest for reproducibility, but do not
misclassify them as global buffer IDs. Ordinary buffered output must never be
redirected to the live Pingo control SID.

### Playback and rendering

Animation phase must follow elapsed time, not completed-render count. The BVH
declares 30 Hz, matching the established four-tick fixed step used by the
modern assembly apps. While a render is in flight, the foreground continues to
advance the cyclic clip phase. When `P3DR` makes the renderer idle, the
foreground selects the newest due frame, copies its 15 records into the 15
states, marks rotation and translation dirty, synchronizes every object, then
queues command 38 last.

This gives two useful application policies without changing the data:

1. **Real-time playback:** phase remains tied to the 30 Hz clock and intermediate
   source frames may be skipped when rendering is slower.
2. **Frame-faithful inspection:** phase advances only after a completion, so
   every source frame is displayed even when the result is slower than real
   time.

Visual review selected the motion at the beginning of the capture. Subsequent
gait analysis identified frames 1 -> 24 as the earliest complete same-left-foot
stride. The implemented table stores unique samples 1..23 and uses frame 24 as
a non-stored periodic witness. A local-bone cubic closure preserves frames
1..15, conditions 16..24, makes frame 24 equal frame 1 modulo captured forward
travel, and matches the 23 -> 24 local increment to 1 -> 2. The eZ80 therefore
wraps a qualified 23-tick cycle instead of wrapping the unconditioned 68-frame
capture.

The interrupt callback remains exactly as qualified: copy the ten-byte `P3DR`
payload, commit a byte flag last, neutralize the signature before MOS resumes
normal keyboard handling, and do no VDU, file, display, or rendering work in
the callback. On exit, drain any render in flight, disable notifications, then
remove the keyboard vector.

### Root motion and camera truth modes

After basis conversion and scale-5 encoding, the full source pelvis travels
approximately `(+0.07, -0.08, +56.17)` Pingo world units from frame 1 to frame
68. The selected conditioned stride advances 2,131 pose counts, approximately
16.65 Pingo world units, over 23 ticks. The historically qualified static
camera at raw `(0,0,3200)` is only about +25 world units away, so a
preserved-root run would pass that fixed camera.

The first client should expose two explicit scene policies:

1. **Root-locked inspection:** send scene translation equal to the negative
   current pelvis translation. Lara stays near the origin and a static camera
   makes limb mapping easy to judge.
2. **Captured-root playback:** leave the clip translation intact and update the
   camera pose from the pelvis plus a retained offset. Existing eZ80 camera
   look-at code can aim at the pelvis position; commands 21 and 25 send only
   absolute camera state.

Both use existing Pingo commands. Neither uses reserved command 42. The
root-locked scene translation is also a useful first point of truth because it
separates articulation defects from camera and locomotion behavior.

## Transport, memory, and rendering budgets

### UART

Each current absolute XYZ rotation or translation packet is 15 bytes. With 15
runtime objects, one submitted animated pose costs:

| Traffic | Bytes per submitted render |
|---|---:|
| 15 absolute rotations | 225 |
| 15 absolute translations | 225 |
| Render command | 9 |
| Optional scene translation for root lock | 13 |
| Optional camera rotation and translation | 26 |
| Base animated submission | 459 |
| Root-locked submission | 472 |
| Camera-following submission | 485 |
| Conservative scene-plus-camera maximum | 498 |

The established UART is 1,152,000 baud, 8N1, or a theoretical 115,200 payload
bytes per second. Even the conservative 498-byte scene, pose, camera, and render
submission occupies about 4.32 ms of line time. If 30 complete snapshots were
submitted each second, that is 14,940 bytes per second, about 13.0 percent of
raw payload capacity. The two proposed truth modes normally use either the
scene or camera addition, not both, and normal coalescing submits fewer
snapshots when rendering is slower.

Transport is therefore not the likely bottleneck. Pingo rendering currently
blocks the VDP command loop until a frame completes, which is why the existing
one-render-in-flight protocol and foreground coalescing remain mandatory.

### eZ80 RAM and executable window

The principal incremental costs are small:

| Item | Bytes |
|---|---:|
| Complete pose table | 4,140 |
| 15 current `p3d_object` states | 960 |
| Shared update-packet scratch | 15 |
| Lara RGBA2222 texture staging | 47,104 |
| Compact mesh/UV payload | approximately 9–14 KiB |

The static mesh replaces rather than duplicates the existing Lara geometry in
a standalone client. A dedicated exporter can also omit roughly 5 KiB of
unused normal data present in the old general-purpose include. This is safely
inside the project's enforced 512 KiB executable-plus-largest-staging window.

### VDP memory and object count

At 320×240, the current control needs approximately 384,000 bytes for Pingo's
private one-byte frame and 32-bit depth buffer. A native RGBA2222 target adds
76,800 bytes, the Lara texture adds 47,104 bytes, and the compact mesh arrays
add roughly 9–14 KiB before allocator and container overhead. Fifteen objects
remain below the 32-renderable scene limit.

This is modest for PSRAM, but repeated embedded heap/PSRAM exhaustion remains
an explicit PingoWolf Alpha limitation. Physical create/render/teardown testing
is still required; a successful native or emulator run is not a capacity claim.

### Expected display rate

The accepted 320×240 static Lara hardware baseline measured 50.100 ms of
renderer time, or 19.96 equivalent FPS, across 180 measured frames. A later
exact-span renderer checkpoint recorded 23.89 equivalent FPS. Those runs used
the same 300-position, 526-triangle Lara geometry, but neither included the
15-object traversal, pose traffic, presentation, or this animation.

The first implementation must not promise one displayed frame per 30 Hz source
sample. It should preserve 30 Hz world time and skip stale samples. If a later
goal requires 30 displayed frames per second, target dimensions such as
256×192 can be qualified independently; viewport size is already the accepted
performance knob and does not require a protocol change.

## Integration with current applications

An isolated app is the clean first proof. Replacing Earth Party's current
single-object Lara is possible later: the present scene has 12 objects, so
replacing one with 15 yields 26, still under Pingo's limit. The difficulty is
not the renderer. Earth Party's Lara also follows an application-owned orbit
and yaw. Since Pingo has no character-group transform inside that mixed scene,
the eZ80 would need to compose the orbit root with all 15 animated part poses.
That composition should be assessed separately after the standalone absolute
clip is qualified.

The implementation also reconciles the asset-manifest drift found during this
assessment. Both Earth Party profiles, all active orbit-scene profiles, and the
static Lara render profile now name the canonical source:

```text
blender/anim/bandai_namco/run_normal_001/source/LaraCroft.obj
```

The corresponding texture profiles point at the adjacent canonical `Lara.png`.
The copied texture was already byte-identical, so this was path drift caused by
the asset move rather than a rendering or animation defect. Historical fixture
snapshots retain their original effective profiles as run evidence and are not
authoritative build inputs.

## Implementation acceptance evidence

This section defines evidence, not a second project task queue. Any accepted
implementation work belongs in the sole authoritative
[`docs/todo.md`](../../../docs/todo.md).

The initial `apps/anim` implementation now supplies automated evidence for
LA-01 through LA-03 and LA-05. LA-04, the display-order portion of LA-06, and
LA-07 remain deliberate emulator/hardware and Author-visual checks; a clean
assembly build is not being substituted for those observations.

1. **LA-01 — deterministic export:** two clean Blender exports produce
   byte-identical mesh, UV, pose, metadata, and application include outputs.
2. **LA-02 — source inventory:** the export proves 17 semantic source parts,
   15 runtime objects, 300 total positions, 526 triangles, one shared texture,
   and the exact pelvis/holster merge.
3. **LA-03 — transform round trip:** every emitted sample reconstructs
   `C · matrix_world · C^-1` within declared matrix and transformed-vertex
   tolerances; all values are finite and in their wire domains.
4. **LA-04 — visual truth frames:** rest/reference view plus selected running
   frames explicitly recheck the corrected left hand/forearm, independent
   hands and thighs, pelvis-bound holsters, corrected torso/head basis, and the
   formerly malformed first frame.
5. **LA-05 — asynchronous discipline:** setup barrier, single render in flight,
   sequence/token validation, frame coalescing, ordinary keyboard handling, and
   clean callback teardown match the current Earth Party contract.
6. **LA-06 — temporal policy:** real-time playback loops 23 unique samples
   without making animation time depend on render count; source frame 24 is a
   non-stored seam witness, and `R` publishes paused frame 1 before any later
   sample can coalesce over it.
7. **LA-07 — physical qualification:** hardware records renderer time, submitted
   and skipped animation frames, UART/callback failures, and PSRAM lifecycle;
   the Author visually accepts both root-locked and camera-following modes.

Emulator behavior remains useful for deterministic and visual development, but
emulator timing is not hardware timing. Any emulator-profile change also
retains the project's explicit human-validation requirement before commit or
push.

## Alternatives not recommended for the first implementation

1. **VDP armature or skinning support:** the asset is already rigidly segmented,
   and adding bones would duplicate work completed offline while expanding the
   protocol, lifetime, and PSRAM surface.
2. **Runtime eZ80 forward kinematics:** it recreates Blender's hierarchy and
   coordinate corrections in assembly, then still must convert the result to
   Pingo Euler commands. Absolute baked samples are smaller in engineering risk
   and only 4,140 bytes for the selected stride.
3. **One mesh per animation frame:** it multiplies geometry upload/storage for
   no benefit; only transforms change.
4. **Per-part normalization:** it destroys Lara's proportions.
5. **Frame-to-frame delta compression:** recovery after a skipped frame becomes
   stateful, while the uncompressed clip is already small.
6. **One cached VDP command buffer per frame:** existing buffered calls could do
   this without custom firmware, but they would consume extra VDP memory and
   global buffer IDs merely to save about four milliseconds of UART time. Keep
   this as a measured fallback, not the baseline.
7. **Render-count-driven animation:** it would slow the motion whenever the
   renderer falls below 30 FPS, contrary to the qualified application-owned
   simulation model.

## Rights and release boundary

The motion source and adaptations are CC BY-NC 4.0 and must remain
non-commercial with attribution. The Lara model's creator, original source,
license, redistribution rights, and commercial status remain unresolved, as
recorded in the experiment's [NOTICE](../bandai_namco/run_normal_001/NOTICE.md)
and machine-readable
[provenance](../bandai_namco/run_normal_001/source/LaraCroft.provenance.json).

The animation client should therefore be treated as an experimental,
non-commercial qualification app and excluded from a generally distributable
Pingo release manifest until the model's rights are established. That is a
release boundary, not a technical reason to alter the architecture.

## Final recommendation

The implemented first Pingo version is a 15-object, fixed-scale assembly client
with a 4,140-byte absolute pose table containing one loop-conditioned stride.
It preserves 30 Hz clip time, coalesces stale poses behind the existing `P3DR`
gate, and keeps view and locomotion controls on the eZ80. All armature
evaluation, coordinate conversion, loop conditioning, Euler continuity,
quantization, and validation remain in the Blender/export pipeline. PingoWolf
remains unchanged.
