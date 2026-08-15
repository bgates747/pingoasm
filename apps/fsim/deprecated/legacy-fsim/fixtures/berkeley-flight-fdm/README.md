# Berkeley light-flight dynamics fixture

This is a distinct derivative of the visually accepted
`berkeley-flight-triangular-dither` fixture. The accepted fixture and its
generated terrain remain untouched so patterned-terrain qualification can be
compared directly with the flight experiment.

The eZ80 now owns a deterministic 30 Hz point-mass state with explicit
position, velocity, force, attitude, angular-rate, throttle, and runway-support
fields. It reuses the qualified PingoASM Q15 matrix and object-pose routines.
The first force vocabulary is intentionally small: propulsive thrust, body-up
lift, world-axis drag, and gravity. Low forward speed loses lift smoothly, and
a body-Y/forward-speed test reduces lift at high angle of attack. The only
ground behavior is a one-plane runway support constraint for a future KOAK
start; regional terrain collision remains TODO C1.

The exterior target is 320×148. The authored 320×92 `fsimpanel.png` is
converted deterministically to RGBA2222 and painted into both display buffers.
Before each completed Pingo target is composited, four ordinary VDP filled
triangles paint a pale sky and a pitch/roll-derived neutral-ground fallback.
Pingo's untouched transparent target pixels reveal that fallback wherever no
terrain is available.

Build without touching the accepted terrain fixture:

```bash
.venv/bin/python scripts/build_berkeley_fdm.py
```

Controls remain W/S throttle, Up/Down pitch, Left/Right roll, A/D rudder, and
Escape to return to MOS. This fixture begins in exact level-flight trim at
33.75 m/s, cruise throttle 160, and 120 m above the Campanile so dynamics can
be judged immediately. Cruise still produces the original 18 Q8 thrust; full
throttle now produces 28 so a separate stationary runway start can accelerate
and rotate without changing Berkeley's exact trim state. KOAK runway 28L
remains the required start for the regional streaming fixture.
