# Universal-manager hex terrain survey

This camera-only fixture is the first client of the fixture-independent eZ80
terrain manager. It uses the flat-top axial Bay Area corpus and exercises the
same manager contract intended for flight simulators and arbitrary future
clients. The accepted rectangular regional camera survey remains a historical
visual and control oracle; this fixture does not use its rectangular loader.

The visual presentation remains the accepted survey: a full 320x240 exterior
view, Campanile start facing east, flat-pattern terrain, scene lighting, and an
attitude-aware sky/ground backdrop. There is no aircraft, flight model, or
collision response. Arrow keys look, WASD moves in the yaw-rotated horizontal
plane, Page Up/Down moves on world Y, and Minus/Equals changes translation
speed.

The initial regional cell is axial `(q,r) = (90,121)`, containing the
Campanile. Top-row keys 0 through 5 select a complete axial hex disk at run
time. Radius 2 is the default.

| Key/radius | Desired cells |
|---:|---:|
| 0 | 1 |
| 1 | 7 |
| 2 | 19 |
| 3 | 37 |
| 4 | 61 |
| 5 | 91 |

The fixture reserves 91 stable terrain mesh/object slots. It loads the
current cell as the first-frame barrier, then allows the manager to perform at
most one read/validate/upload/publication or deactivation operation between
completed renders. Radius changes alter policy rather than destroying the
manager. Existing desired residents retain their slots; failed replacement
keeps the prior complete resident.

Terrain uses Pingo command 52 for signed 24-bit translations. Axial placement
is rebuilt from the manifest's exact integer basis vectors rather than by
repeated floating-point steps. The old regional survey's shared `+12288` Z
bias is therefore unnecessary: camera and objects use the canonical local
frame while preserving exactly the same Campanile pose.

The provider retains the current origin through a 16 m outward hysteresis band
around all six cell sides. Exact outer ties remain in the current cell; the
first count beyond the band selects a neighbor. Reapplying the same band around
the new origin makes recrossing chatter impossible without a real 32 m
round-trip displacement.

The accepted `fixtures/regional-camera-survey` remains unchanged as the
fixed 8x4 direct-mapped oracle. This fixture is a sibling, not a rewrite of
that evidence.

Build the complete hex L0 corpus and this appliance from the repository root:

```text
.venv/bin/python scripts/build_regional_hex_terrain.py \
  --selection full --output build/p3dm/bay-area-hex-full-l0
.venv/bin/python scripts/build_terrain_manager_survey.py
```

For the bounded first visual test, build `--selection campanile-r5` with
`--output build/p3dm/bay-area-hex-campanile-r5`, then give that directory to
the survey builder with `--corpus`.

The full-corpus runtime executable is
`build/p3dm/bay-area-hex-full-l0/P3DHXMG.BIN`.
Emulator-coupled work remains uncommitted until explicit human visual
qualification.
