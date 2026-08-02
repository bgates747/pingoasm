# Lara rigid animation

`apps/anim` is the first PingoASM application of external motion capture to an
existing Blender model. It loops the first complete stride from the 68-frame
Bandai Namco `run_normal_001` capture as 23 unique samples on 15 rigid Lara
objects without adding animation, armature, or interpolation support to
PingoWolf.

The meshes and texture are uploaded once. The eZ80 retains a 12-byte absolute
translation-and-Euler record for every object and source frame, advances source
time at 30 Hz, coalesces poses while one render is in flight, and submits only
the newest pose through existing Pingo commands 13 and 17.

On exit, the client drains the active render, disables completion notices,
deletes its Pingo control, clears its target and texture buffers behind a VDP
barrier, and then restores MOS.

## Controls

| Key | Action |
|---|---|
| W | Run forward at the capture's frame-relative speed |
| A / D | Strafe left / right |
| Left / Right | Yaw left / right |
| S | Unbound; this fixture does not synthesize reverse running |
| Page Up / Page Down | Raise / lower the following camera |
| P | Pause or resume animation playback |
| R | Reset to source frame 1 and pause |
| Escape | Drain the current render and return to MOS |

The default controlled mode removes the capture's progressive pelvis `+Z`
translation when composing the scene, while retaining its lateral sway and
vertical motion. Animation continues at 30 Hz whether or not movement is
commanded. While W is held during playback, the eZ80 advances Lara along her
current yaw using the outgoing source frame's captured forward delta; paused
movement uses the rounded 93-count cycle mean. The wrap uses its own generated
77-count step, matching the conditioned frame 23 -> virtual-frame-24 motion and
the original frame 1 -> 2 step. Rotation and strafing are also entirely
eZ80-owned. This keeps the nonuniform mocap speed instead of replacing it with
a synthetic constant rate.

The default camera is an Earth Party-style look-at observer: it remains at a
fixed world position and continually aims at Lara's pelvis. W/A/D movement is
therefore visible, and turning or strafing exposes different viewing angles.
Page Up and Page Down change only camera height. The novel world-offset chase
positioner remains in `lara-animation.inc` behind a dormant camera mode for a
future fixture; it is not selected here because exact chase motion is visually
indistinguishable from no translation in an empty scene. All of this uses the
existing Pingo scene, object, and camera commands.

Playback stores source frames 1 through 23. Source frame 24 is the earliest
same-left-foot gait recurrence and is retained in Blender only as a non-stored
seam witness, so the table has no duplicate endpoint or one-frame hold. The
scene builder preserves frames 1 through 15 byte-for-byte and conditions local
bone quaternion/location channels over frames 16 through 24. Frame 24 then
matches frame 1 after removing the captured 2,131-count stride translation,
while the frame 23 -> 24 local increment matches frame 1 -> 2. This provides an
exact pose closure and discrete-time local C1 closure at 30 Hz; the measured
finite-step world-hierarchy residual remains bounded at 1.8 degrees and 20
translation counts rather than independently moving rigid parts and breaking
the articulated hierarchy.

The directional light sits on the camera's `+Z` side and is swung 15 degrees
clockwise toward `+X` in plan view. Pingo normalizes the signed ratio
`(8481, 0, 31650)`; intensity and ambient retain their defaults of unity and
zero respectively.

## Source and build

The authoritative animation input is:

```text
blender/anim/bandai_namco/run_normal_001/output/lara_running_normal_001.blend
```

Build from the repository root:

```bash
.venv/bin/python build/scripts/build_anim.py
```

The builder invokes the qualified Blender 4.0.2 in background mode, validates
and exports 15 meshes plus the 23-frame pose table, converts `Lara.png` to
RGBA2222, snapshots the current Earth Party transport/runtime includes,
assembles the app, and writes:

```text
apps/anim/tgt/anim.bin
apps/anim/tgt/Lara.rgba2
```

With the project emulator profile already linked, run it from MOS with:

```text
cd /mystuff/pingoasm/apps/anim/tgt
load anim.bin
run
```

For hardware, use the ordinary application deployer:

```bash
.venv/bin/python build/scripts/deploy.py hardware anim
```

Generated assembly remains in `apps/anim/src` with source banners. Novel
hand-written animation logic is isolated in `src/lara-animation.inc`.
Machine-readable export evidence is written to
`assets/lara-running.export.json`.

## Validation and rights

The exporter checks source inventory, shared pelvis/holster transforms,
triangle and UV index validity, whole-character normalization, scale residue,
continuous Euler range, signed-word bounds, and quantized transformed-vertex
error before it emits assembly. It also gates the non-stored successor, exact
loop endpoint, finite-step velocity residual, and captured cycle distance.
`profile.json` additionally pins Blender 4.0.2,
all transitive source hashes, the exact 17 corrected rest/running mesh
identities and bone drivers, shared `tile0`/`Lara.png` wiring, and the qualified
mesh, pose, and texture hashes. The builder independently verifies that
contract and records final executable/texture hashes in the export metadata.

The motion is © 2022 Bandai Namco Research Inc. and the motion and its
adaptations are [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
This application is non-commercial, changes the original as documented, and
does not imply Bandai Namco Research endorsement. See the repository-wide
[`THIRD_PARTY_ASSETS.md`](../../THIRD_PARTY_ASSETS.md), the experiment
[`NOTICE.md`](../../blender/anim/bandai_namco/run_normal_001/NOTICE.md), and its
machine-readable provenance. The Lara model's original
creator, source, and redistribution license remain unresolved. This is an
experimental, non-commercial qualification app.
