# Complete natural post-partition terrain manager survey

This fixture streams the accepted full-region natural master through the same
topology-neutral manager used by the regular N=5 control. Geometry lives under
the `NAT` namespace and preserves whole master triangles, irregular physical
partition edges, and all fifteen semantic material IDs. The provider now clips
only at the true 50,183-cell Bay Area corpus boundary; the historical bounded
Campanile and Marina extractions remain separate ignored comparison artifacts.

The fixture starts 500 m above the Berkeley Marina in actual containing cell
`(80,125)`, local position `(4275,8000,466)`, facing almost due south and
pitched down twenty degrees. Arrow keys look; WASD translates in the
yaw-rotated horizontal plane; Page Up/Down moves on world Y; Minus/Equals
changes translation speed; top-row 0 through 5 changes the desired ring; and
Escape returns to MOS/FSIM. The initial ring is the accepted maximum five, or
91 resident objects. Pingo command 53 sets the projection far distance to its
maximum unsigned value `65535` immediately after control creation.

The complete loose corpus contains 50,183 independently loadable components,
842,903 component-local vertex instances, and 992,477 triangles in 25,251,544
container bytes. Individual records are 196 through 1,384 bytes, and the
largest encoded coordinate magnitude is 30,720, safely inside signed 16-bit.
There are no skirts. Post-container validation proves 294,948 internal seam
edges, 3,105 outer-corpus edges, 128,259 physical component pairs, 78,271
boundary vertices shared by at least three owners, at most seven owners at one
vertex, and zero exact integer reconstruction mismatches.

The fifteen semantic IDs use only three exact opaque Agon base pixels: palette
20 lighter azure for water, palette 7 light gray for developed classes, and
palette 21 spring green for all remaining land. Illumination band 15 is a solid
4x4 pattern for every ID. Scene illumination remains enabled, so darker value
bands may dither.

Build from the repository root:

```text
blender --background --python scripts/export_natural_runtime_corpus_blender.py
.venv/bin/python scripts/build_natural_terrain_corpus.py
blender --background --python scripts/build_natural_runtime_review_blender.py
.venv/bin/python scripts/capture_natural_terrain_manager_survey.py \
  --output /tmp/pingo-natural-manager-full
```

The compact extraction bridge is
`build/source/bay-area-natural-post-partition-v2`; the runtime working
directory is `build/p3dm/bay-area-natural-full-l0`; invoke `P3DNAT.BIN` there.
The mandatory review artifact is
`build/visualization/bay-area-natural-three-class-runtime-review.blend`.

The silent qualification publishes all 91 initial ring-five meshes, observes
all 91 exact command-52 transforms, confirms the command-53 far value at
65,535, renders with all 91 objects traversed, captures the first and complete
frames, and shuts down without audio. Explicit physical-adjacency containment,
mixed LOD, distant terrain, indexed SD bundles, collision, airports, and
physical-hardware behavior remain separate gates.
