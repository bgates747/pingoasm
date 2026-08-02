# Pioneer flight-simulator techniques for the Agon fixture

Status: **research note and implementation guidance**, 2026-08-02. This is
not a claim that Pingo should reproduce any one historical simulator. It
separates documented implementation facts from design inferences for the
Agon/eZ80/Pingo project.

## Evidence labels

- **FACT — primary:** contemporary source written by the developer, a product
  manual, patent, or technical paper.
- **FACT — reconstructed:** behavior verified in a buildable reconstruction
  made from the released binary. Names and interpretation may be modern even
  when the machine code is exact.
- **RECOLLECTION:** later interview or institutional history. Useful, but not
  equivalent to source code or a contemporary specification.
- **INFERENCE:** a project recommendation derived from one or more sources.

The distinction matters here. Bruce Artwick's 1976 report is a display-system
report, not a publication of the later Apple II flight equations. Conversely,
the first FS1 manual documents the forces and numeric organization of the
flight model, but does not print its exact equations.

## Conclusions for this project

1. **Keep the existing fixed 30 Hz eZ80 simulation clock.** Rendering, disk
   service, panel refresh, and physics must have distinct cadences. Render the
   newest complete state; never make world time depend on Pingo's frame rate.
2. **Implement a compact force-and-moment model, not direct turn-rate
   controls.** Calculate air-relative velocity in body axes, lift/drag/side
   force and pitch/roll/yaw moments, rotate linear force into world axes, then
   integrate acceleration, velocity, position, angular acceleration, angular
   velocity, and attitude.
3. **Use a coefficient model with only small nonlinear tables.** Linear
   coefficients cover normal flight; short angle-of-attack tables cover stall
   onset and post-stall lift/drag. A blade-element or CFD model is an optional
   later experiment, not the first light-flight fixture.
4. **Keep metric simulation units and explicit fixed-point domains.** Reuse
   the qualified Q15 matrices, trigonometric tables, 16x16-to-32 arithmetic,
   and fixed simulation scheduler in PingoASM. Use wide intermediates and
   convert to Pingo's render scale only at the boundary.
5. **Use a resident geographic index and bounded near-to-far streaming.** Load
   a complete chunk into a free slot before publishing it; degrade far range
   before allowing a near hole. Terrain, airport surfaces, and landmarks are
   separate layers over a permanent background.
6. **Start every offscreen frame with an attitude-derived solid sky/ground
   partition.** Clip the viewport rectangle against the projected horizon and
   draw the two resulting convex polygons as filled-triangle fans before 3D
   terrain. This is both a coherent degradation layer and a technique with a
   direct Artwick precedent.
7. **Treat cockpit and exterior cameras as different policies.** The cockpit
   follows aircraft attitude. The default exterior chase camera follows
   heading and position with a world-up horizon and filtered lag; an explicit
   aerobatic camera may follow roll. Do not let a wingtip-relative chase point
   jump sides during a roll.
8. **Spend visual and CPU budget on strong flight cues.** Horizon, runway
   outline/centerline, airspeed, attitude, altitude, vertical speed, heading,
   and control feedback outrank decorative detail. Update high-value panel
   cues more frequently than fuel or secondary indicators.
9. **Build a deterministic flight recorder before tuning by feel.** Record
   control input and state every physics tick. Compare trim, step response,
   stall, coordinated turn, climb, glide, and landing traces before adjusting
   coefficients.

## Bruce Artwick: what the sources actually say

### The 1976 dynamic-display report

**FACT — primary.** Artwick's University of Illinois report,
[*A Versatile Computer-Generated Dynamic Flight Display*](https://archive.org/details/AVersatileComputerGeneratedDynamicFlightDisplay),
describes a real-time FORTRAN display driver for a 16-bit minicomputer. It is
the clearest original account of his early rendering architecture.

The report's useful details are remarkably close to the problems in Pingo:

- It integerizes the display pipeline because, on the measured system,
  floating point consumed twice the memory and roughly three times the
  execution time. Fractions use a sign bit plus fifteen fractional bits.
  Multiplication retains a 32-bit product before narrowing.
- Sine and cosine are generated once into lookup tables. A single 4x4 matrix
  concatenates translation, rotation, and field-of-view scaling before the
  database transform.
- A modified Cohen-Sutherland path clips large lines. Small objects expected
  to leave the screen as a unit use a cheaper all-or-nothing projection path.
- Index and display data live in separate, consistently structured buffers.
  The buffers can be concatenated and handed to interchangeable transformation
  modules, including assembly replacements or a hardware matrix multiplier.
- Successive true screen projections can be interpolated using only additions.
  Artwick calls this frame synthesis. The report also applies screen-coordinate
  hysteresis to suppress small bidirectional quantization jitter.
- World range is extended with map overlays, local offsets, and simultaneous
  scale changes. It explicitly suggests simplified or eliminated far objects
  and different maps for coarse cruise flight versus precise final approach.
- A sample runway, centerline, and approach bar are the report's worked
  database example.

**Important negative finding.** This report's simulator supplies position and
attitude to the display driver; it does not disclose the later Apple II
aerodynamic model. Claims that it is the complete FS1 flight model are not
supported by the report.

**INFERENCE.** The durable lessons are domain-specific fixed point, wide
intermediates, tables for expensive functions, coarse/fine geographic frames,
separate index and payload data, and cheap rejection before expensive
per-primitive work. Pingo already embodies much of the rendering side. The
regional chunk origin is the modern equivalent of Artwick's map offset.

The frame-synthesis trick should **not** be copied into the interactive fixture.
Artwick's later book explains that interpolated frames lag a true frame and
suggests control extrapolation to compensate. Pingo's current asynchronous
absolute-state model—fixed simulation ticks with visual-state coalescing—is
more responsive and does not guess future input.

### FS1 on the Apple II

**FACT — primary.** The preserved
[*A2-FS1 Flight Simulator* manual](https://archive.org/details/a2fs1)
documents a much more specific implementation than later summaries usually
credit:

- The program runs in 16 KiB, is optimized assembly, presents roughly 2–5
  frames per second, and splits the display into a 3D upper viewport and a
  lower instrument panel.
- The aircraft is controlled by 23 characteristics. The simulation uses
  double- and triple-precision arithmetic internally and MKS units.
- Its named kinematics effects include attitude; lift from airflow and angle of
  attack; propeller thrust; gravity; induced and parasitic drag; lift loss in a
  turn; linear and "polar" (rotational) momentum; altitude derating; bank side
  force; stall;
  fixed-pitch propeller efficiency and propeller stall; excessive-g failure;
  and wheel steering.
- Navigation state retains north/east/up position, velocity, and heading at
  precision much finer than the visible display can show.
- The manual says the straight simulation produced aerobatic behavior without
  maneuver-specific routines, while also admitting deliberate simplifications:
  rudder and aileron are coordinated, slips/skids are unavailable, and calm air
  is assumed.
- The main loop samples one key and advances about 3–5 times per second.
  Controls are persistent notches rather than commands for a target bank or
  pitch. The manual carefully teaches that aileron produces roll rate and that
  opposite input is needed to stop rolling.
- The full 36-square-mile world is simplified and shown at about 2.5 fps. A
  separate detailed airport database supplies runway lines and taxi features
  for takeoff and landing. The landing-gear keys manually select high- or
  low-altitude scenery because the 16 KiB machine cannot hold both views at
  full detail.

**INFERENCE.** A small force model does not have to be a toy. FS1 demonstrates
that recognizable flight can emerge from a compact set of physical effects,
provided momentum and rate behavior are retained. Its scenery switch is an
early manual LOD system. Our loader should automate the selection by aircraft
position, altitude, projected error, and measured budget instead of overloading
the gear control.

### Flight Simulator II

**FACT — primary.** The 1984
[*Flight Simulator II Pilot's Operating Handbook*](https://archive.org/details/flight-simulator-ii-pilots-operating-handbook-and-airplane-flight-manual-sublogic)
documents a Piper PA-28-181 model based on 47 aircraft characteristics. Its
Atari implementation specification lists 48 KiB core memory, two 8 KiB screen
pages, 2–6 fps projection, 6502 assembly, 8-, 16-, and 32-bit integer math, and
an eight-way time-sliced executive with a software-emulated real-time
interrupt. Keyboard state is sampled at 15 Hz.

The handbook describes an "over-control limiter" that compensated for lag by
repeating/backing up a display frame after the controls were centered during a
high-rate turn. That is historically interesting but unsuitable for this
project: rewinding a visible frame conflates rendering and simulation. Fixed
physics plus asynchronous rendering is the cleaner answer.

The manual also records a persistent low-resolution problem: while taxiing,
nearly everything is viewed edge-on and crowds the horizon. A map/radar and
clear runway cues compensate. This directly supports the decision to make
runway pavement and markings crisp, self-lit, non-dithered exceptions.

### Artwick's 1984 graphics book

**FACT — primary.** Artwick's
[*Applied Concepts in Microcomputer Graphics*](https://archive.org/details/artwick-1984-applied-concepts-in-microcomputer-graphics)
collects the practical techniques behind his contemporary work:

- Profile before optimizing. His worked Apple II A2-3D2 measurement attributes
  about 45% of large-database time to transforms, 30% to projection, and 25%
  to line drawing once matrix setup is amortized.
- Use native integer widths and keep multiplication/division products wide.
  For perspective, it specifically recommends multiplying screen width by the
  world coordinate into a wide intermediate before dividing by depth.
- Interleave control sampling, physics, and graphics. Fast physical events may
  need several simulation substeps per display; slow displays and indicators
  can be time-sliced.
- Double buffering may cover only the dynamic upper viewport while the static
  panel remains in a single memory area. That is exactly the right conceptual
  split for the reduced Pingo viewport and 2D cockpit.
- Surface illumination is decomposed into ambient reflection, directional
  reflection based on surface-normal/light angle, and self-emission. That is a
  direct historical analogue of Pingo's ambient/directional lighting plus
  self-illuminated runway layer.
- Shared vertices should be transformed once and then referenced by multiple
  edges. A more specialized "space framing" trick transforms the corners of a
  regular planar grid and synthesizes interior points by adds and shifts.
  Relief terrain is not planar, so the latter does not replace its vertices,
  but it can inform very coarse flat background or airport geometry.

Most strikingly, the book's incremental-fill example is a flight display with
solid blue sky and green ground. It observes that pitch moves a narrow band at
the horizon, while bank creates one or two wedge-shaped changed regions between
successive horizon lines. The book proposes polygon filling only those changed
regions.

**INFERENCE.** Pingo should redraw the full two-color background in the
offscreen target because its filled-triangle operation and page flip make that
simpler and deterministic. But the visual premise, the attitude-driven horizon,
and the polygon construction are directly Artwick's—not a coincidental modern
embellishment.

### Artwick's scenery-file patents

**FACT — primary, with patent caveat.** Two Artwick/BAO patents filed from a
1993 priority date describe the transition from abrupt scenery blocks to
indexed, layered scenery:

- [US 5,604,849, overlay management](https://patents.google.com/patent/US5604849A/en)
- [US 5,651,676, scenery organization and storage](https://patents.google.com/patent/US5651676A/en)

Their documented techniques include small resident file headers; geographic
bounds and offsets for object-type sections; coarse range rejection before
object reads; latitude bands and sorted coordinates that permit early exit;
per-feature near/far radii; recurring geometry stored once and instanced; and
a gradual reduction of viewing distance when a fixed object buffer fills.

They also describe "seeded scenery": small records specify a surface class and
location from which progressively resolved background is generated. Uniform
areas use coarser cells, boundaries between surface types use finer cells, and
more specific scenery overwrites the seed background. The patents document
eight resolution levels in the described embodiment.

Patents state claims and example embodiments, not a line-by-line declaration
of what every shipped release executed. Even with that limitation, these are
strong primary design evidence.

**INFERENCE.** The project's P3DM/container plan is on sound historical
ground. Keep a tiny manifest resident, store offsets and bounds for separately
streamable layers, traverse near to far, and reduce far range under pressure.
The solid horizon fill is an even cheaper permanent background beneath coarse
terrain; terrain is beneath airports and landmarks. Never let a detailed far
object consume the slot or render budget needed for the runway beneath the
aircraft.

### Artwick's account of the original flight model

**RECOLLECTION.** A 2023 National Air and Space Museum article based on an
Artwick interview says he derived the original model from *Aerodynamics for
Naval Aviators*. It describes control-surface input producing differential
lift, rotational acceleration, integration of roll over time, and transformation
between aircraft and world reference frames. Artwick recalls writing and
paper-benchmarking 6502 multiply/divide subroutines and laying out memory byte
by byte. He says the original model accepted characteristics such as weight,
span, length, drag coefficient, engine thrust, and did not depend on
pre-recorded performance tables. See
[*Pilot Program*](https://airandspace.si.edu/air-and-space-quarterly/spring-2023/pilot-program).

This recollection agrees with the contemporary FS1 manual's force list, but it
still does not establish the exact equations or fixed-point formats in the
released code.

## Independent pioneers and alternative solutions

### Geoff Crammond's *Aviator* (BBC Micro, 1983)

**FACT — reconstructed.** Mark Moxon's
[*Aviator* software archaeology](https://aviator.bbcelite.com/) is a fully
buildable reconstruction from the shipped binary; it produces byte-identical
game files. The explanatory names are Moxon's, not Crammond's original symbols,
but the operations are exact. The corresponding
[1983 instruction manual](https://aviator.bbcelite.com/pdfs/Acornsoft_Aviator_Manual.pdf)
is the contemporary product source.

The reconstructed
[flight model](https://aviator.bbcelite.com/deep_dives/the_flight_model.html)
is valuable because it exposes how another author fit convincing dynamics into
an 8-bit machine:

- It rotates world velocity into aircraft axes, computes linear lift/drag/side
  forces and angular stability/control moments, scales each component with
  small integer coefficients and powers of two, then rotates linear force back
  into world axes.
- Gravity is applied in world space. Forces change velocity; moments change
  turn rate; turn rate changes orientation; updated velocity changes position.
- Air-density effect falls with altitude. Engine force falls with forward
  velocity and altitude. Gear, flaps, and engine state alter drag. Flaps add
  lift and shift pitch moment.
- Stall is a deliberate regime change: the lift coefficient is reduced to one
  quarter and asymmetric wing behavior initiates the departure rather than
  merely clamping speed.
- Each force has a byte-sized multiplier and a signed power-of-two scale. This
  gives useful tuning range without general floating-point constants.

Its
[visibility system](https://aviator.bbcelite.com/deep_dives/visibility_checks.html)
checks an object's anchor distance before transforming its component points.
Hidden lines are reconsidered in small batches. Its
[scheduler](https://aviator.bbcelite.com/deep_dives/scheduling_tasks_in_the_main_loop.html)
timeboxes hidden-line discovery and refreshes high-value instruments more
often than low-value ones.

**INFERENCE.** This independently validates the chosen force/moment pipeline
and provides an attractive eZ80 tuning representation: a compact signed
coefficient plus binary exponent per contribution. We should preserve physical
units in the retained state, though, and use coefficient/exponent pairs as
calculation parameters rather than letting every state variable become an
undocumented byte scale.

The visibility lesson applies one level higher in Pingo: reject a terrain chunk
or landmark by bounds before any object submission; then let Pingo do its
whole-object frustum rejection. The scheduler lesson applies to disk discovery,
instrument refresh, and debug logging, but physics must remain fixed-step.

### Ned Lerner and *Chuck Yeager's Advanced Flight Trainer* (1987)

**FACT — primary.** The
[*Advanced Flight Trainer* manual](https://www.gamesdatabase.org/Media/SYSTEM/Amstrad_CPC/Manual/formated/Chuck_Yeager-s_Advanced_Flight_Trainer_-_1989_-_Electronic_Arts.pdf)
credits Ned Lerner with software design, Gabe Hoffman with the aerodynamic
model, and Chuck Yeager as technical consultant. It offers many different
aircraft, structured lessons and aerobatic tasks, and a flight recorder that
can replay or score performance. The manual does not disclose enough math to
justify claims about its integrator or force equations.

**INFERENCE.** The important portable idea is not an unverified algorithm; it
is the validation apparatus. A flight recorder turns tuning from memory and
impression into repeatable evidence. Our trace format should make the same
control sequence exactly replayable and compare key state at named gates.

### Loren Carpenter and the Lucasfilm fractal landscape

**FACT — primary/institutional.** Loren Carpenter's SIGGRAPH paper,
[*Computer Rendering of Fractal Curves and Surfaces*](https://doi.org/10.1145/800250.807478),
describes statistical subdivision for economical fractal surfaces. Lucasfilm's
history of
[*Rescue on Fractalus!*](https://www.lucasfilm.com/news/defining-moments-an-alien-surprise/)
describes David Fox's collaboration with Carpenter to create mountain terrain
on Atari hardware.

**INFERENCE.** Procedural terrain is a powerful way to supply plausible distant
relief, but the Bay Area project's value comes from recognizable real geography.
Use real DEM as the structural truth. If statistical detail is ever added, make
it deterministic, offline, bounded by source elevation, and absent from shared
chunk edges. Do not spend eZ80 time growing fractals during flight.

### Seamus Blackley and *Flight Unlimited* (1995)

**RECOLLECTION/secondary.** Blackley has repeatedly described pursuing a
force-based atmosphere model so aerobatics emerged from physics rather than
scripted maneuvers. A contemporary discussion appears in
[*Computer Gaming World* 133](https://www.cgwmuseum.org/galleries/issues/cgw_133.pdf),
and a later developer interview is available from
[TresCom](https://www.trescom.org/interviews/seamus-blackley-interview/).
Descriptions often call the implementation real-time CFD, but public sources
do not provide enough code or numerical detail to evaluate that label as a
fluid-dynamics method.

**INFERENCE.** The useful lesson is to tune for coherent forces and recognizable
aircraft behavior, then validate with pilots and recorded maneuvers. It is not a
reason to attempt Navier–Stokes calculations on the eZ80.

### Austin Meyer, X-Plane, and blade elements (1995 onward)

**FACT — developer documentation, current description.** X-Plane's official
[technical overview](https://www.x-plane.com/desktop/how-x-plane-works/)
describes splitting lifting surfaces into elements, calculating force on each,
summing forces and moments, and integrating the resulting acceleration. This is
a current explanation of a system that has evolved since 1995, not proof that
every detail or element count appeared in the first version.

**INFERENCE.** A strip model can later improve asymmetric stalls, damaged wings,
or odd aircraft. It multiplies transforms and coefficient work per physics tick
and complicates authoring. The first Agon fixture should instead use one
whole-aircraft coefficient buildup with an explicit asymmetric-stall perturbation
if needed. Retain force/moment interfaces so a two- or four-strip wing can be
tested later without changing the integrator.

### The later Microsoft model and JSBSim

**FACT — developer technical paper.** Michael K. Zyskowski's Microsoft paper,
[*Aircraft Simulation Techniques Used in Low-Cost, Commercial Software*](https://doi.org/10.2514/6.2003-5818),
describes the later SimEngine as six-degree-of-freedom dynamics: forces and
moments are calculated in body axes, linear force is transformed into earth
axes, acceleration is integrated with a first-order modified Euler method, and
quaternions avoid Euler singularities. Aerodynamic coefficients are mostly
linear in the ordinary envelope, augmented by interpolated tables or scalars
for nonlinear high-angle behavior. Ground contact uses defined contact points,
spring/damping, and friction.

This is a 2003 account of the evolved Microsoft lineage, not evidence that FS1
or FSII used modified Euler or quaternions.

**FACT — later open reference.** [JSBSim](https://github.com/JSBSim-Team/jsbsim)
began in the late 1990s and remains an inspectable coefficient-buildup flight
dynamics system. Its
[forces-and-moments documentation](https://jsbsim-team.github.io/jsbsim-reference-manual/user/concepts/forces-and-moments/)
shows independent contributions multiplied by dynamic pressure and reference
geometry. Current JSBSim is not a snapshot of its 1996 implementation.

**INFERENCE.** The hybrid model is the best target for Agon: linear coefficient
buildup in ordinary light flight, short lookup tables only where the curve
truly bends, and a simple first-order fixed-step integrator. Keep ground contact
outside the initial airborne qualification, as already specified by C1.

### Human-factors evidence for sparse cues

**FACT — research paper.** Gavan Lintern's 1980 study,
[*Transfer of Landing Skill After Training with Supplementary Visual Cues*](https://doi.org/10.1177/001872088002200109),
used a low-cost simulator display with a sparse airport scene including horizon,
runway, centerline, and an aiming cue. Simulator-trained groups showed transfer
on relevant landing measures, with adaptive supplementary feedback performing
best in the study. This does not prove that any minimal display is sufficient
for all flight training, but it does establish that carefully chosen sparse
cues can carry useful landing information.

**INFERENCE.** The horizon and KOAK 28L markings are functional flight
instruments. They should survive terrain-loading failure, dithering choices,
and aggressive detail reduction.

## Recommended eZ80 flight model

### Retained state

Use one authoritative eZ80 state, with renderer packets derived from it:

| State | Suggested domain | Notes |
|---|---:|---|
| regional chunk coordinate | signed integer pair | unbounded regional address |
| local world position | signed 24-bit fixed point | metres relative to current origin |
| world velocity | signed 24-bit fixed point | metres/second |
| body angular velocity | signed 16- or 24-bit fixed point | radians/second or turns/second |
| attitude | existing signed-Q15 3x3 orientation | reuse qualified PingoASM path |
| control deflections | signed normalized words | aileron, elevator, rudder, flap |
| engine state | unsigned normalized word | throttle plus RPM/thrust state |
| derived air data | scratch/telemetry | airspeed, alpha, beta, load, vertical speed |

The current `moveair-local` code already supplies a good substrate: a 30 Hz
fixed step from the 120 Hz MOS clock, Q15 local-to-world orientation, absolute
dirty-state submission, and simulation/render decoupling. Its direct local
velocity and angular-rate controls should be replaced, not its scheduler and
transport discipline.

Use metres, seconds, kilograms, and radians or binary turns consistently inside
the flight model. Terrain/render scale conversion belongs at the camera/object
packet boundary. This repeats FS1's sensible MKS separation and reduces magic
cross-domain constants.

### One fixed physics tick

For each 1/30-second step:

1. Sample/retain control demand; apply trim, limits, and keyboard centering
   policy.
2. Obtain world wind (zero initially) and calculate air-relative world velocity.
3. Rotate air-relative velocity into aircraft body axes with the inverse of the
   existing Q15 orientation.
4. Derive speed, angle of attack, sideslip, and dynamic-pressure scale. Avoid a
   general square root if squared speed is sufficient for force scale; use the
   existing inverse-trig/table work only when alpha/beta are needed.
5. Calculate body-axis thrust, lift, drag, side force, and control/stability
   moments. Use wide intermediates and saturate only at an explicitly documented
   boundary.
6. Rotate net aerodynamic/engine force into world axes and add world gravity.
7. Integrate linear acceleration into velocity, then updated velocity into
   position (semi-implicit/modified Euler).
8. Divide moments by principal inertias, integrate angular acceleration into
   body rates, and advance attitude with the proven matrix rotation path.
9. Derive instruments and regional/chunk position. Rebase the local origin only
   at a safe boundary and leave the physical state continuous.
10. Publish at most the newest absolute pose when Pingo is ready; append one
    deterministic trace record regardless of whether a frame was rendered.

### Minimum coefficient set

The first aircraft needs a small, legible parameter block:

```text
mass, Ixx, Iyy, Izz
wing_area, wing_span, mean_chord
CL0, CL_alpha, CL_elevator, CL_flap
CD0, induced_drag_k, CD_flap, CD_gear
CY_beta, CY_rudder
Cl_beta, Cl_p, Cl_aileron, Cl_rudder
Cm0, Cm_alpha, Cm_q, Cm_elevator, Cm_flap
Cn_beta, Cn_r, Cn_rudder, Cn_aileron
thrust_static, thrust_speed_falloff
alpha_breakpoints[], CL_stall[], CD_stall[]
```

The normal-envelope equations can be coefficient buildup:

```text
qS   = 0.5 * density * speed_squared * wing_area
lift = qS * CL(alpha, elevator, flap)
drag = qS * (CD0 + induced_drag_k * CL*CL + configuration_drag)
side = qS * CY(beta, rudder)

roll_moment  = qS * wing_span * Cl(beta, roll_rate, controls)
pitch_moment = qS * mean_chord * Cm(alpha, pitch_rate, controls)
yaw_moment   = qS * wing_span * Cn(beta, yaw_rate, controls)
```

Implement these as fixed-point staged products, not literal floating-point
source. Normalize angular-rate terms by speed with a bounded reciprocal table
or omit the normalization during the first bring-up and tune a narrow speed
range. A 16- or 32-entry density table is enough for the regional altitude
range; constant sea-level density is acceptable for the first OAK circuit if
the limitation is explicit.

The stall table should be intentionally small. Four to eight alpha knots on
each side can represent linear lift, peak lift, post-stall loss, and increased
drag. Crammond's quarter-lift regime proves that even an abrupt low-cost model
can create a recognizable stall, while Zyskowski supports interpolation where
nonlinearity matters.

### Attitude representation

The later Microsoft paper gives a sound reason for quaternions, but the project
already has a qualified signed-Q15 orientation matrix and Pingo-compatible
Euler export. Reuse it for the first light-aircraft model. Its range is adequate
for ordinary OAK circuits and it avoids introducing an unqualified normalization
and conversion stack.

Add a quaternion only if deterministic loop/vertical tests expose an actual
matrix/Euler singularity. Camera pole handling is not itself evidence that the
aircraft integrator needs a quaternion.

### Controls and trim

Keyboard controls should change a retained control-surface demand, not aircraft
angular velocity. Suggested initial policy:

- arrows change elevator/aileron demand at a fixed rate while held;
- A/D change rudder demand;
- W/S change throttle demand;
- aileron and rudder spring toward center after release;
- elevator springs toward a trim position, with separate trim keys later;
- every demand is bounded and visible in debug telemetry.

This preserves the historically important distinction between control surface,
angular acceleration, angular velocity, and attitude. A configurable coordinated
rudder mix can make initial keyboard flight approachable, but sideslip must
remain in the physics state so the aid can later be disabled.

## Streaming and scheduling implications

The historical record converges on a simple policy:

- A resident manifest says which files and sections can matter.
- Chunk/object bounds and near/far radii reject work before disk reads or
  per-vertex processing.
- Requested chunks are ordered by safety and projected importance: current
  airport/runway, current terrain, forward-near terrain, side/behind-near
  terrain, then far/coarse terrain and landmarks.
- One complete load transaction publishes into a free slot. A short load can
  fail without disturbing the old resident set.
- Under slot or frame pressure, reduce the far radius and coarse-detail layers
  deterministically. Do not evict the surface underneath or immediately ahead
  of the aircraft to show distant scenery.
- Instrument work is tiered. Attitude, airspeed, altitude, vertical speed,
  heading, and control demand refresh frequently; fuel, temperature, and
  decorative animation refresh slowly.
- Directory discovery, debug output, and hidden/far reconsideration are
  timeboxed service tasks. Physics is not.

This is Artwick's indexed overlay and degraded range combined with Crammond's
distance-first visibility and bounded background work.

## Exterior camera policy

The
[*Flight Simulator II* Amiga manual](https://www.lemonamiga.com/doc/flight-simulator-2/661)
documents cockpit, tower, ground-track, and spot-plane views. It also warns
that a spot camera located relative to a wing can switch sides as the aircraft
rolls or loops; its alternate roll preference follows heading instead. The
manual notes that removing window furniture and reducing the 3D area improves
projection speed.

The default Pingo exterior camera should therefore be computed independently
from the airplane body's roll axis:

```text
desired_camera = aircraft_position
               - horizontal_heading_forward * chase_distance
               + world_up * chase_height

look_target = aircraft_position
            + aircraft_forward * look_ahead
            + aircraft_velocity * prediction_time
```

Apply a critically damped or bounded first-order position filter, aim at the
filtered look target, and use world-up as the ordinary roll policy. At very low
speed, retain the last reliable horizontal heading rather than deriving it from
noisy velocity. Keep the existing hysteretic pole protection.

An aerobatic exterior mode may use continuous aircraft roll, but it must be an
explicit user choice. Cockpit mode uses the aircraft pose directly and places
the 2D instrument asset below the smaller 3D viewport.

## Attitude-derived sky/ground fill

### Geometry

The fill is derived from **camera attitude**, not directly from aircraft
attitude. In cockpit view those are the same; in the default exterior view the
camera's world-up policy may deliberately suppress aircraft roll.

Let `u_camera` be world-up transformed into camera space. For a camera-space
view ray `r(x, y)`, the geometric horizon satisfies:

```text
dot(u_camera, r(x, y)) = 0
```

With the renderer's usual affine screen-ray form, this becomes a 2D line:

```text
A*x + B*y + C = 0
```

Do not special-case pitch and bank into guessed endpoint formulas. Deriving
the line from the actual camera basis automatically covers rolls, inverted
flight, and camera-policy differences.

Clip the rectangular 3D viewport against each half-plane of this line with a
small Sutherland-Hodgman-style 2D clipper. Each result is a convex polygon of
at most five vertices. Classify the sky side by testing a ray in the camera's
up direction, then draw each polygon as a triangle fan with the existing VDP
filled-triangle function.

At extreme pitch the line may not cross the viewport. The clipper naturally
returns a full rectangle for one side and an empty polygon for the other; draw
the rectangle as two triangles. This avoids rolled-corner holes produced by a
naive pair of triangles joined only at two horizon endpoints.

### Render order and depth

1. Select the hidden/offscreen target.
2. Reset or clear depth according to Pingo's target contract.
3. Draw solid native-palette sky and neutral ground fans without writing a
   near depth value (or write the farthest possible background depth).
4. Render coarse then detailed terrain in a deterministic order that preserves
   near coverage if the budget is exhausted.
5. Render airport and landmark overlays.
6. Present/flip the complete target, then composite or retain the 2D panel as
   the selected display architecture requires.

The background colors should be solid and non-dithered. Their job is to cover
every pixel cheaply and provide orientation, not to imitate terrain texture.
Terrain can retain the approved patterned aesthetic. Airport hard surfaces and
markings remain solid, self-lit exceptions.

### Acceptance cases

- level attitude, horizon centered and horizontal;
- known positive/negative pitch offsets;
- 30°, 90°, 135°, and 180° bank;
- all-sky and all-ground extreme pitch;
- cockpit viewport clipping with no write into the panel;
- artificially tiny terrain budget, showing no uncovered target pixels;
- water, terrain, runway, and aircraft correctly overwrite the background;
- identical target hashes for identical camera state and resident chunks;
- depth reset verified so a prior frame cannot occlude current terrain.

## Flight-model qualification

The trace should contain tick number, input mask/demands, throttle, world
position/velocity, attitude, body rates, alpha, beta, force/moment components,
and flags for stall, contact, saturation, and arithmetic overflow. At minimum,
automate these scenarios:

1. OAK 28L idle and full-power ground-start sanity.
2. Trimmed straight flight for 60 seconds with bounded drift.
3. Elevator, aileron, and rudder step responses followed by release.
4. Power-off glide and power-on climb at fixed initial airspeed.
5. 30° coordinated turn with altitude loss measured.
6. Slow deceleration through stall, clean recovery, and no one-tick state jump.
7. High-speed dive/pull-out with bounded load and no numeric wrap.
8. Identical replay under fast, slow, and deliberately stalled rendering.
9. Regional-origin rebase with continuous position, velocity, attitude, and
   resident-set decisions.

Tune in that order. A visually exciting stall is not useful evidence if level
trim and control response are still nondeterministic.

## Claims deliberately left unmade

- The exact FS1/FSII integration scheme and fixed-point binary points have not
  been established from released source.
- Artwick's 1976 report does not contain the Apple II aerodynamic model.
- The scenery patents are not proof that every described structure shipped
  unchanged in Flight Simulator 5.
- Current X-Plane and JSBSim documentation does not describe their first
  releases byte for byte.
- Public descriptions of *Flight Unlimited* do not expose enough numerical
  implementation to validate the popular "real-time CFD" characterization.
- No direct technical influence from PLATO's *Airfight* on Artwick is assumed;
  popular histories disagree, and that relationship is unnecessary to the
  engineering conclusions here.

## Source trail

The sources below are ordered by their value to current implementation work.

1. Bruce Artwick,
   [*A Versatile Computer-Generated Dynamic Flight Display* (1976)](https://archive.org/details/AVersatileComputerGeneratedDynamicFlightDisplay).
2. Bruce Artwick/subLOGIC,
   [*A2-FS1 Flight Simulator Manual*](https://archive.org/details/a2fs1).
3. Bruce Artwick,
   [*Applied Concepts in Microcomputer Graphics* (1984)](https://archive.org/details/artwick-1984-applied-concepts-in-microcomputer-graphics).
4. subLOGIC,
   [*Flight Simulator II Pilot's Operating Handbook* (1984)](https://archive.org/details/flight-simulator-ii-pilots-operating-handbook-and-airplane-flight-manual-sublogic).
5. Bruce Artwick et al.,
   [overlay-management patent](https://patents.google.com/patent/US5604849A/en)
   and [scenery-storage patent](https://patents.google.com/patent/US5651676A/en).
6. National Air and Space Museum,
   [Artwick interview/history](https://airandspace.si.edu/air-and-space-quarterly/spring-2023/pilot-program).
7. Mark Moxon,
   [byte-identical *Aviator* reconstruction](https://aviator.bbcelite.com/),
   [flight-model analysis](https://aviator.bbcelite.com/deep_dives/the_flight_model.html),
   [visibility analysis](https://aviator.bbcelite.com/deep_dives/visibility_checks.html),
   and [scheduler analysis](https://aviator.bbcelite.com/deep_dives/scheduling_tasks_in_the_main_loop.html).
8. Michael K. Zyskowski,
   [*Aircraft Simulation Techniques Used in Low-Cost, Commercial Software*](https://doi.org/10.2514/6.2003-5818).
9. Gavan Lintern,
   [*Transfer of Landing Skill After Training with Supplementary Visual Cues*](https://doi.org/10.1177/001872088002200109).
10. X-Plane,
    [technical overview](https://www.x-plane.com/desktop/how-x-plane-works/),
    and [JSBSim source](https://github.com/JSBSim-Team/jsbsim) as later
    inspectable comparison systems.
