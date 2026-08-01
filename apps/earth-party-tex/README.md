# Interactive eZ80-local Earth Party

`earth-party-tex` combines the qualified asynchronous moveair Jet and
tracking camera with six moving/solid bodies plus a six-sector real-star sky:

1. the user-controlled Jet at `(0,0,-640)`;
2. Earth at `(0,0,-4200)`;
3. Crash, Lara, HeavyTank, and Airliner on a 2,500-unit X-Z orbit around
   Earth, initially separated by 90 degrees.
4. 128 catalogued stars batched into six static spatial objects.

The eZ80 owns every world pose. Current Pingo receives only absolute
create/scale/rotation/translation commands and never receives a retired
firmware-local transform.

## Persistent motion

The Jet retains the moveair controls and persistent local `-Z` throttle.
The fixed camera remains at world origin and continuously aims at the Jet.

Each orbiter is initialized once with:

```text
local linear velocity  = (0, 0, -46)
local angular velocity = (0, 96, 0)
```

No scripted orbit positions follow. `p3d_object_step16` rotates each object
about local `+Y`, then transforms its persistent local `-Z` displacement into
world space. The later clean integer resonance closes position, Euler pose,
orientation matrix, and angular residual exactly after three revolutions or
1,024 simulation ticks (34.133 seconds at 30 Hz). Radius remains approximately
2470.8–2535.4 units.

Earth has a stable 23.69-degree coarse-Q15 approximation to the real
23.44-degree obliquity. Its north pole points toward screen-left and toward
the camera. Earth’s persistent local-Y rate advances a 32768-unit internal
phase, wrapped explicitly after one turn. The nearest of 256 generated
absolute pose samples supplies both the fine Pingo wire Euler angles and the
matching signed-Q15 orientation matrix. One complete revolution therefore
closes byte-exactly after 256 fixed ticks (8.533 seconds at 30 Hz), without
either accumulated precession or the coarse inverse-trig snapping of the
earlier fixed-basis implementation.

The sampled-cycle mechanism is not Earth-specific. The reusable generator
accepts any base Euler pose, local X/Y/Z spin axis, and up to 256 samples; the
common assembly loader applies its 24-byte records to any `p3d` object. It is
deliberately separate from the ordinary free-motion integrator used by the
Jet and orbiters.

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

Like the flat edition, every star triangle selects one constant palette cell,
uses flat-palette shading, and is self-illuminated. The solid models remain
texture mapped and scene lit. Both editions set ambient light to 32/127 and
use the same directional vector `(-16384,0,28377)` in the world X-Z plane.

Celestial north is rotated onto Earth's immutable tilted north-pole axis.
The initial right-ascension phase places the Orion/Sirius region near the
forward view. The camera remains at the world origin, so all six inward-facing
sectors are created once and never enter the simulation dirty-state path.

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

`profile.json` names all authoritative OBJ/PNG and star-catalog inputs. The
dedicated builder regenerates the six app-local, symbol-prefixed model
includes, the six-sector `starfield.inc`, the app-local `pose-cycle.inc`
snapshot, `earth-spin-cycle.inc`, and seven RGBA2222 textures. It then
assembles `src/earth-party.asm` and verifies that the executable plus the
largest staged texture fits the 512 KiB eZ80 application window:

```bash
.venv/bin/python build/scripts/build_earth_party_tex.py
```

The ordinary complete build invokes the same builder:

```bash
.venv/bin/python build/scripts/build_samples.py
```

Runtime output is:

```text
apps/earth-party-tex/tgt/earth-party.bin
apps/earth-party-tex/tgt/*.rgba2
```

The ordinary build is offline. To deliberately refresh the tracked derived
catalogue from the verified CDS V/50 source:

```bash
.venv/bin/python build/scripts/update_earth_party_star_catalog.py
```

Hardware deployment uses:

```bash
.venv/bin/python build/scripts/deploy.py hardware earth-party-tex
```

The project-local `src/agon/3d.inc` and table remain a deliberate snapshot of
the canonical AgonMaths 3D API.

## Verification status

The four autonomous orbiters close their complete retained states after 1,024
fixed ticks in the deterministic oracle. Starfield regressions verify the
catalog anchors, deterministic sector assignment, magnitude/size ordering,
palette extremes, Q15 bounds, inward winding, and Earth-pole alignment.
Pose-cycle regressions additionally require 256 unique Earth poses, exact
index closure, stable generated hashes, and adjacent physical steps within
approximately 0.01 degree of the ideal 1.40625-degree increment.

Human visual review passes in the project-local PingoWolf emulator:

```text
~/Agon/mystuff/pingoasm/emulator
```

That profile runs the combined PingoWolf VDP from the canonical `pingowolf`
branch. Regenerate it with the canonical environment setup script whenever the
combined userspace module changes.
