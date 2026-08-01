# Flat-vehicle, emissive-star Earth Party

`earth-party-flat` is a rendering-policy sibling of
`earth-party-tex`. It combines the same asynchronous moveair Jet and
tracking camera with six moving/solid bodies plus a six-sector real-star sky:

1. the user-controlled Jet at `(0,0,-640)`;
2. Earth at `(0,0,-4200)`;
3. Crash, Lara, HeavyTank, and Airliner on a 2,500-unit X-Z orbit around
   Earth, initially separated by 90 degrees.
4. 128 catalogued stars batched into six static spatial objects.

The eZ80 owns every world pose. Current Pingo receives only absolute
create/scale/rotation/translation commands and never receives a retired
firmware-local transform.

## Rendering-policy delta

The scene, controls, camera tracking, object placement, scale, viewport, and
asynchronous render architecture derive from `earth-party-tex`. This later
edition deliberately slows the four orbiters to the closed cycle documented
below; that motion change is independent of its rendering-policy comparison.

Its rendering-policy differences are:

1. Jet and Airliner use one predominant Agon palette color per source
   triangle and remain scene-lit.
2. All six star-sector meshes use their already constant per-triangle atlas
   colors and bypass illumination, preserving their native colors.
3. Every scene-lit mesh has a 32/127 ambient-light floor, the nearest encoded
   value to one quarter.
4. The directional-light vector is explicitly
   `(-16384,0,28377)`, normalized by Pingo to approximately
   `(-0.5,0,+0.8660)`: plotting `+X` right and `+Z` up, 30 degrees
   counterclockwise from `+Z` (Cartesian `+120` degrees from `+X`). Keeping
   the light in the X-Z plane lets Earth's axial tilt supply the apparent
   elevation instead of compounding it with an elevated light.

Earth, Crash, Lara, and HeavyTank retain their ordinary textured rendering.
Mesh shading and mesh illumination policy remain independent.

## Persistent motion

The Jet retains the moveair controls and persistent local `-Z` throttle. The
camera begins 5,450 world units from Earth's center—half an orbital radius
farther away than the original world-origin viewpoint—retains its position
relative to Earth, and continuously aims at the Jet. Camera translation never
changes that aim target. See the concise
[control card](../earth-party-controls.md).

Each orbiter is initialized once with:

```text
local linear velocity  = (0, 0, -46)
local angular velocity = (0, 96, 0)
```

No scripted orbit positions follow. `p3d_object_step16` rotates each object
about local `+Y`, then transforms its persistent local `-Z` displacement into
world space. This is half the preceding accepted orbital rate, or 37.5 percent
of the original: one revolution takes approximately 11.378 seconds at 30 Hz.
The nearest clean integer resonance uses `+96` yaw with `-46` forward motion;
position, Euler pose, orientation matrix, and angular residual close exactly
after three revolutions (1,024 simulation ticks, or 34.133 seconds). Radius
remains approximately 2470.8–2535.4 units.

Earth has a stable 23.69-degree coarse-Q15 approximation to the real
23.44-degree obliquity. Its north pole points toward screen-left and toward
the camera. Its local-Y velocity advances a wrapped 32768-unit internal phase.
The nearest of 256 generated absolute samples supplies both the fine Pingo
wire Euler angles and the matching signed-Q15 orientation matrix, closing one
complete revolution byte-exactly after 256 fixed ticks (8.533 seconds at
30 Hz). This replaces both the rejected accumulating diagnostic and the
coarse inverse-trig export that caused visible correction judder.

The mechanism is reusable rather than Earth-specific. The generator accepts
an arbitrary base Euler pose, local X/Y/Z spin axis, and up to 256 samples;
the common loader applies each 24-byte pose record to any `p3d` object. The
ordinary free-motion integrator remains unchanged for the Jet and orbiters.

## Real-star sky

The sky contains every normal Bright Star Catalogue entry at Johnson
`V <= 2.00`, plus the principal Bayer vertices of 19 familiar constellation
figures. The resulting 128 visible stars retain catalogued J2000 right
ascension, declination, V magnitude, B−V color, and spectral type. Close
catalogue components such as Alpha Centauri and Acrux are merged by adding
their V-band flux.

Each star is a canonical five-point glyph: five triangles form its central
pentagon and five more form its points. Apparent magnitude controls a
deliberately compressed 2.0–5.5 pixel radius. B−V selects an exaggerated
RGBA2222 palette, making Sirius saturated hot blue and Betelgeuse and Antares
red.

The sky is conceptually one generated asset but is partitioned by dominant
cube-map direction into six meshes and six objects sharing one 24×2 texture.
Pingo can normally reject five sector bounds before visiting their triangles;
a single whole-sphere mesh would defeat object-level frustum culling and
submit all 1,280 triangles every frame.

Celestial north is rotated onto Earth's immutable tilted north-pole axis.
The initial right-ascension phase places the Orion/Sirius region near the
forward view. The bounded movable camera remains inside the firmament, so all
six inward-facing sectors are created once and never enter the simulation
dirty-state path.

## Simulation and rendering

Simulation advances in fixed four-tick quanta from MOS’s 120 Hz clock. It
continues at 30 Hz while one Pingo render is in flight. On completion, the
application displays that frame, coalesces every dirty object and camera pose,
and submits one new render. Renderer throughput therefore does not alter
world time.

The viewport remains 320×240 for the first hardware stress test. It is the
primary performance control and can be reduced independently of simulation
frequency.

Jet controls remain those of `moveair-local`; six additional keys move the
camera relative to Earth while its look-at target remains the Jet:

| Keys | Effect |
|---|---|
| W / S | increase forward `-Z` throttle / decrease it toward zero |
| Up / Down | pitch `-X` / `+X` |
| Left / Right | roll `+Z` / `-Z` |
| A / D | yaw `+Y` / `-Y` |
| Page Up / Page Down | move camera along world `+Y` / `-Y` |
| Home / End | move camera toward / away from Earth's center |
| Insert / Delete | increase / decrease Earth-relative camera sweep |
| Escape | restore the normal display and return to MOS |

Sweep is a rotation about world `+Y`; it preserves the camera's radius and
angle above the world X-Z plane. Home/End scale the complete Earth-relative
radial direction, including its world-Y component. The display background is
Agon palette index 16, Navy (`0,0,85`), the darkest non-black blue.

Space remains unbound because current Pingo command 41 is the render
completion registration command.

## Reproducible assets and build

`profile.json` names all authoritative OBJ/PNG inputs and carries its own copy
of the tracked star-catalogue snapshot. The
dedicated builder regenerates the six app-local, symbol-prefixed model
includes, converting Jet and Airliner through the shared predominant-color
tool. It also regenerates the six-sector `starfield.inc`, stages seven
RGBA2222 textures, snapshots the reusable `pose-cycle.inc`, generates
`earth-spin-cycle.inc`, assembles `src/earth-party.asm`, and verifies that the
executable plus the largest staged texture fits the 512 KiB eZ80 application
window:

```bash
.venv/bin/python build/scripts/build_earth_party_flat.py
```

The ordinary complete build invokes the same builder:

```bash
.venv/bin/python build/scripts/build_samples.py
```

Runtime output is:

```text
apps/earth-party-flat/tgt/earth-party-flat.bin
apps/earth-party-flat/tgt/*.rgba2
```

The ordinary build is offline. To deliberately refresh the tracked derived
catalogue from the verified CDS V/50 source:

```bash
.venv/bin/python build/scripts/update_earth_party_star_catalog.py
```

Hardware deployment uses:

```bash
.venv/bin/python build/scripts/deploy.py hardware earth-party-flat
```

The project-local `src/agon/3d.inc` and table remain a deliberate snapshot of
the canonical AgonMaths 3D API.

## Verification status

The sibling regression oracle pins the revised 1,024-tick/three-revolution orbit
closure,
tilted Earth basis, static-sector, resource-ID, and camera/simulation tests.
Additional checks require exactly Jet and Airliner to use predominant-color
conversion, all six star meshes to be flat and self-illuminated, and ambient
light to be exactly 32. They also pin the explicit upper-left/front light
direction so a firmware default change cannot silently alter the fixture.
The pose-cycle oracle separately pins all 256 unique fine poses, exact closure,
wire/internal-domain hashes, and sub-0.02-degree step and orientation bounds.
