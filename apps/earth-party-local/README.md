# Interactive eZ80-local Earth Party

`earth-party-local` combines the qualified asynchronous moveair Jet and
tracking camera with a six-object scene:

1. the user-controlled Jet at `(0,0,-640)`;
2. Earth at `(0,0,-4200)`;
3. Crash, Lara, HeavyTank, and Airliner on a 2,500-unit X-Z orbit around
   Earth, initially separated by 90 degrees.

The eZ80 owns every world pose. Current Pingo receives only absolute
create/scale/rotation/translation commands and never receives a retired
firmware-local transform.

## Persistent motion

The Jet retains the moveair controls and persistent local `-Z` throttle.
The fixed camera remains at world origin and continuously aims at the Jet.

Each orbiter is initialized once with:

```text
local linear velocity  = (0, 0, -123)
local angular velocity = (0, 256, 0)
```

No scripted orbit positions follow. `p3d_object_step16` rotates each object
about local `+Y`, then transforms its persistent local `-Z` displacement into
world space. The integer chord and angle close position, Euler pose,
orientation matrix, and angular residual exactly after 128 simulation ticks,
or 4.267 seconds at 30 Hz. Radius remains between 2500.0 and 2516.1 units.

Earth has a stable 23.69-degree coarse-Q15 approximation to the real
23.44-degree obliquity. Its north pole points toward screen-left and toward
the camera. Earth’s persistent local-Y rate advances an accumulated phase,
but each absolute pose is derived from the immutable tilted basis. This
avoids pole precession from repeatedly quantizing a compound orientation
through coarse Euler words.

## Simulation and rendering

Simulation advances in fixed four-tick quanta from MOS’s 120 Hz clock. It
continues at 30 Hz while one Pingo render is in flight. On completion, the
application displays that frame, coalesces every dirty object and camera pose,
and submits one new render. Renderer throughput therefore does not alter
world time.

The viewport remains 320×240 for the first hardware stress test. It is the
primary performance control and can be reduced independently of simulation
frequency.

Controls are unchanged from `moveair-local`:

| Keys | Effect |
|---|---|
| W / S | increase forward `-Z` throttle / decrease it toward zero |
| Up / Down | pitch `-X` / `+X` |
| Left / Right | roll `+Z` / `-Z` |
| A / D | yaw `+Y` / `-Y` |
| Escape | restore the normal display and return to MOS |

Space remains unbound because current Pingo command 41 is the render
completion registration command.

## Reproducible assets and build

`profile.json` names all authoritative OBJ/PNG inputs. The dedicated builder
regenerates the six app-local, symbol-prefixed model includes and RGBA2222
textures, assembles `src/earth-party.asm`, and verifies that the executable
plus the largest staged texture fits the 512 KiB eZ80 application window:

```bash
.venv/bin/python build/scripts/build_earth_party_local.py
```

The ordinary complete build invokes the same builder:

```bash
.venv/bin/python build/scripts/build_samples.py
```

Runtime output is:

```text
apps/earth-party-local/tgt/earth-party.bin
apps/earth-party-local/tgt/*.rgba2
```

Hardware deployment uses:

```bash
.venv/bin/python build/scripts/deploy.py hardware earth-party-local
```

The project-local `src/agon/3d.inc` and table remain a deliberate snapshot of
the canonical AgonMaths 3D API.

## Verification status

The four autonomous orbiters close their complete retained states after 128
fixed ticks in the deterministic oracle. The complete project build produces
16 binaries and all 96 Python regressions pass.

Human visual review passed on the isolated copied current-Pingo snapshot:

```text
emulators/tv-port-baseline
```

The directory name is historical; its manifest and VDP hash define the
qualified runtime. The mutable `emulator` profile is not interchangeable for
this callback-driven fixture.
