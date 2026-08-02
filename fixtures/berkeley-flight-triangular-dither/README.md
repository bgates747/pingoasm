# Berkeley triangular dither fixture

This is the scene-lit flat-pattern counterpart to the accepted
`berkeley-flight-triangular` self-lit control. It preserves the same continuous
32-chunk triangular lattice, 2,696 vertices, 4,140 triangles, Campanile start,
due-east 30-degree sun, and 95/127 ambient floor.

Each face selects one of the 15 compact Berkeley terrain material IDs through
the row-major position of a UV in `terrain-material-ids.rgba2`. Experimental
Pingo shading mode 2 then combines that material with one of 16 illumination
bands through `terrain-pattern-lookup.bin` and repeats the selected 4x4 tile
from `terrain-patterns.rgba2` in global screen space.

Runways, pavement, markings, and other hard surfaces are a deliberate
exception: future objects must remain separate from terrain, use ordinary
solid-flat shading mode 1, and begin self-illuminated. This fixture contains no
hard-surface objects yet, but retains both app-local constants so that policy
does not get folded into the patterned terrain generator.

Run `scripts/build_berkeley_flight_triangular_dither.py` from the repository
root to regenerate the mesh source, vendor the current offline pattern build,
and assemble `tgt/berkeley-flight-triangular-dither.bin`.

## Camera survey sibling

`src/berkeley-camera-survey.asm` is a separate executable over these exact
same scene inputs. It deliberately starts at fixture 3's camera position
`(0,-1144,16384)`, attitude `(0,0,0)`, full-screen viewport, light, and
ambient value so its first frame can be compared directly with entry 3.
It does not contain an aircraft object, flight dynamics, collision detection,
cockpit, or regional streamer.

Its direct camera controls are:

| Keys | Command |
|---|---|
| Arrow Up / Down | Look up / down at the fixed 152-word angular quantum |
| Arrow Left / Right | Yaw left / right; roll remains exactly zero |
| W / S | Move forward / backward in the horizontal plane |
| A / D | Strafe left / right in the horizontal plane |
| Page Up / Page Down | Move along world +Y / -Y, independent of attitude |
| Minus / Equals | Select the next slower / faster translation rate |
| Escape | Return to FSIM, or to MOS after a direct RUN |

Pitch is clamped to `-8191..8191`, one Pingo angle word short of either
vertical. WASD is transformed only by camera yaw through the proven
`p3d_vec3_rotate_y16` path; pitch is never part of translation. The rising-edge
speed ladder is 8, 16, 32, 64, 128, and 256 translation counts per 30 Hz
quantum, initially 32. Since one count is 1/16 metre here, even the minimum is
a visible 0.5 metre commanded step.

Build this sibling without touching the accepted mesh source with:

```bash
.venv/bin/python scripts/build_berkeley_camera_survey.py
```

Pass `--regenerate-scene` only when the fixture-3 terrain and shared runtime
resources intentionally need to be rebuilt. The resulting
`tgt/berkeley-camera-survey.bin` is retained as the fixed direct-RUN oracle;
FSIM entry 0 now runs the full-region survey.

Both executables require the experimental Pingo subcommand 49 firmware. Invoke
the accepted flight fixture as entry 3 in the `fsim` MOSlet menu, or LOAD/RUN
either binary directly from this `tgt/` directory. They proceed directly into
graphics and do not add a redundant second keypress gate after the explicit
launch.
