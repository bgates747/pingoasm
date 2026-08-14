# Marina distance-LOD control

This sibling fixture keeps the accepted natural terrain at rings 0 through 5
and adds the regular one-centre/six-triangle cell control through ring 30. Its
purpose is to answer one visual question: does a very cheap coarse annulus make
the flying view feel materially less confined?

The unchanged universal manager owns all 183 slots: 91 natural records and 92
static coarse chunks. Keys `0` through `5` vary the natural near-field disk;
the middle/far annulus remains present. Arrow keys look, `WASD` translate in
the horizontal plane, Page Up/Down translate vertically, and `-`/`=` adjust
translation speed. Escape returns through the normal fixture entry contract.

Build the generated annulus and then the fixture with:

```sh
blender --background --python scripts/export_distance_lod_control_blender.py
.venv/bin/python scripts/build_distance_lod_control.py
```

The runtime root is `build/p3dm/bay-area-distance-lod-control/`; its program is
`P3DDST.BIN`. This emulator control uses a checked relative `NAT` symlink to
the qualified complete natural corpus. It is not yet a portable SD-card
package.

This is intentionally not the final distance system. L1 and L2 presently use
the same six triangles per logical cell, the natural/regular interface does not
conform, and 64 m chunk skirts only mask same-tier cracks. Those limitations
are recorded in `MANAGER.json` and should remain visible during review.
