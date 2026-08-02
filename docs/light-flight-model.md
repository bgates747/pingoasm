# Deterministic light-flight model

Status: **experimental F2 specification**. The force model and visual fallback
are implemented in the distinct `berkeley-flight-fdm` fixture. They are not yet
accepted, promoted to PingoASM, or coupled to regional terrain collision.

## Purpose and boundary

The first model should feel like a stable light propeller aircraft while being
cheap enough to run at a fixed 30 Hz on the eZ80 independently of renderer
cadence. It is a deterministic point-mass and attitude model, not a type
certificate or a claim of six-degree-of-freedom aerodynamic fidelity.

F2 owns thrust, lift, drag, gravity, linear inertia, angular moments and rates,
the cockpit view, and the attitude-aware background. C1 separately owns
regional terrain collision. The only initial ground rule is a support plane for
starting on one known runway: it cancels downward velocity until the aircraft
has both positive vertical inertia and takeoff airspeed.

## Proven implementation base

The target reuses the maintained PingoASM `tests/apps/moveair-local` donor:

- `agon/3d.inc` supplies signed 16×16 multiplication, Q15 normalization,
  matrix/vector transforms, intrinsic object rotation, Euler export, angular
  residuals, and transactional vector translation;
- its four-MOS-tick scheduler supplies the 30 Hz simulation contract; and
- its one-render-in-flight foreground state machine allows simulation to keep
  advancing while visual poses are coalesced.

The toy donor's persistent local-Z position delta is not retained as physics.
The new model owns an explicit world velocity and derives each next position
from force, acceleration, and inertia.

## Numeric domains

One Pingo translation count is approximately 0.0625 m under the accepted
8-metre world-unit contract. State uses these fixed domains:

| Quantity | Encoding | Initial/useful range |
|---|---|---:|
| local position | signed 16.8 translation counts in an exact 24-bit field | one floating-origin window |
| world velocity | signed Q8 translation counts per 30 Hz tick, per axis | clamped to ±8192 |
| normalized force | signed Q8, per axis | normally tens of counts |
| linear acceleration | signed Q8 velocity change per step | unit-mass copy in the first fixture |
| angular acceleration | signed angle-rate change per step | derived from control/stability moments |
| orientation matrix | signed Q15 | `-32767..32767` |
| Pingo Euler angle/rate | signed angle words | full turn = 32768 words |
| throttle | unsigned byte | `0..255`; exact cruise trim at `160` |

At 30 Hz, velocity `4608` represents 18 translation counts per tick, or
33.75 m/s. Position fields are intentionally `dl`; every 16-bit state and VDU
field is read or written bytewise so ADL register width cannot overrun it.
Regional travel still requires J1's whole-chunk floating-origin rebasing before
the signed local position reaches its limit.

## Fixed-step equations

For each simulation quantum:

```text
control demand -> angular moment -> damped body angular rate -> P3D attitude
world velocity -> transpose(attitude) -> body velocity
body forward speed -> lift and high-angle-of-attack factor
local (0, lift, -thrust) -> attitude -> world aerodynamic force
world force += component drag + gravity
acceleration = force / mass
world velocity = clamp(world velocity + acceleration)
local position += world velocity
```

Forward is local `-Z` and lift is local `+Y`. Current integer laws are:

```text
thrust = (throttle >> 3) - (throttle >> 6)
drag[axis] = -(world_velocity[axis] >> 8)
lift = (forward_speed >> 7) + (forward_speed >> 9)
gravity_y = -45
```

Cruise throttle 160 gives thrust 18. At forward speed 4608, drag is 18 and
lift is 45, preserving the original exact, testable level-flight trim at
identity attitude. Full throttle gives thrust 28, providing a discrete
full-power reserve for the stationary runway start. The earlier map capped at
18; signed integer drag reached 18 at velocity -4353, where lift was only 42
against gravity 45. No modest pitch could supply the missing vertical force,
so the supported KOAK aircraft could never take off.

Lift falls smoothly below gravity with speed; this supplies the first
low-speed stall behavior without a discontinuity. As a cheap angle-of-attack proxy,
`abs(body_y) >= forward/2` halves lift and `abs(body_y) >= forward` quarters
it. This deliberately leaves room for a later squared-speed lift curve and a
better coefficient-of-lift table after the integer model is flown and measured.
The first aircraft's normalized mass is one, so force and acceleration contain
the same integer components but remain distinct retained vectors. A later
aircraft profile can introduce one reciprocal-mass scale at that boundary
without changing force construction or velocity integration.

Pitch, roll, and yaw use signed `-1/0/+1` demands. Rates lose approximately
1/16 magnitude per step with a one-count minimum decay, then receive moments
12, 24, and 8 respectively and clamp to ±512. Above takeoff speed, bank angle
adds a restrained yaw moment so a bank produces a plausible coordinated turn
instead of indefinite sideslip. The P3D object's linear delta remains zero;
only the new world inertia vector translates it.

The bank proxy is the world-Y component of the retained local-right basis
vector (`orientation[r1c0] >> 12`), not the exported Euler Z word. P3D may
legitimately choose an equivalent Euler branch near ±180 degrees after
combining runway yaw and pitch. Feeding that representational discontinuity
back into physics created a false full-bank yaw moment even though the
orientation matrix itself remained valid. Matrix-basis feedback is continuous
through that branch change.

## Cockpit and fallback horizon

The authored `assets/cockpit/fsimpanel.png` occupies rows 148–239. The Pingo
target and graphics viewport are reduced to 320×148, avoiding work behind the
panel.

Pingo clears untouched RGBA2222 target pixels to transparent. Before the
completed target is composited, the eZ80 emits four ordinary VDP filled
triangles:

1. two triangles cover the viewport with pale sky; and
2. two form an oversized neutral-ground quadrilateral below a horizon derived
   from the active camera's retained orientation matrix.

The camera local-to-world matrix's world-up row supplies branch-free screen
attitude: `pitch = asin(-r1c2)` and `roll = atan2(r1c0,r1c1)`, using the proven
P3D inverse-trig tables. This matters for the same reason as matrix-based
coordinated-turn feedback: an equivalent complete Euler triple may place X and
Z near 180 degrees even for shallow flight, and consuming either component in
isolation would invert the cheap horizon. The horizon direction is
`(cos roll, sin roll)` at a 512-pixel radius. Its downward normal
`(-sin roll, cos roll)` extends 1024 pixels, so ordinary VDP clipping covers
the viewport at any roll without a polygon clipper or divide. Pitch shifts the
horizon by `pitch_word >> 6`. Terrain, airports, and landmarks then overlay
this fallback; unloaded or distant scenery reveals a coherent sky and ground
instead of black. Chase mode uses its upright look-at camera matrix rather
than inheriting the aircraft's bank.

## Qualification contract

Host tests must preserve exact integer trim at cruise throttle for at least one
simulated minute, show speed/lift loss and descent at idle, prove high-angle
lift reduction, bound and damp angular rates, constrain runway support to its
explicit flag, and verify horizon coverage under pitch and roll. A stationary
supported trace must ramp W by the target's four-byte throttle steps, rotate to
a modest eight-degree nose-up attitude at takeoff speed, and leave support with
positive vertical inertia. The assembly fixture must build from the
project-local environment and pass source guards for the fixed step, explicit
24-bit position fields, bytewise 16-bit VDU patching, 320×148 target, panel
checksum, and four-triangle backdrop.

Headless emulator runs can establish that the binary loads, advances, and
renders without a VDP reset. Cockpit appearance, control feel, takeoff/trim,
and any emulator-coupled behavior still require the Author's explicit human
validation before commit or promotion.
