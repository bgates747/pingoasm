# Bandai Namco motion experiments

This experiment uses `dataset-2_run_normal_001`, a 68-frame, 30 fps normal-style
running capture from Bandai-Namco Research Motiondataset 2. The motion data and
derived Blender files are licensed CC BY-NC 4.0 and are not commercially
cleared. See `NOTICE.md` for attribution and modification details.

## Layout

- `source/` — unchanged upstream BVH, JSON annotation, and license.
- `scripts/` — our reproducible Blender scene-building tools.
- `output/` — generated files; safe to replace by rerunning the scripts.
- `modified/` — hand-edited Blender assets; never overwritten by scripts.

## Build the starter scene

Run from the `pingoasm` repository root:

```sh
blender --background --python blender/anim/bandai_namco/run_normal_001/scripts/build_running_scene.py
```

By default the script reads the vendored source clip:

```text
blender/anim/bandai_namco/run_normal_001/source/dataset-2_run_normal_001.bvh
```

and writes `output/running_normal_001.blend`. Override either path:

```sh
blender --background --python blender/anim/bandai_namco/run_normal_001/scripts/build_running_scene.py -- \
  --bvh /absolute/path/to/clip.bvh \
  --output /absolute/path/to/output.blend
```

Open the resulting file and press Space to play. The scene includes the mocap
armature, a bright bone-based proxy figure, a ground plane, lighting, and a
camera. It deliberately preserves the captured forward motion.

To make a hand-edited version, copy a generated file from `output/` into
`modified/`, rename it meaningfully, and edit only that copy.

## Clean-sheet Lara retarget

Build the rigid-part Lara experiment with:

```sh
blender --background --python \
  blender/anim/bandai_namco/run_normal_001/scripts/build_lara_running_scene.py
```

This writes two deliberately separate, single-scene files:

- `output/lara_rest.blend` — the one-frame mesh-to-bone point of truth.
- `output/lara_running_normal_001.blend` — the 68-frame running animation.

The builder imports the vendored OBJ, separates its 18 disconnected islands,
deterministically combines them into 17 named rigid body parts, constructs a
new single-root armature at Lara's proportions, retargets all 68 source frames,
and bakes absolute part transforms suitable for eventual Pingo export.

This is PingoASM's first validated application of external motion capture to an
existing Blender character model. The rest mapping, hand/holster segmentation,
per-bone coordinate corrections, first-frame hierarchy evaluation, and tracking
camera have all been checked against the generated files.

`lara_rest.blend` contains only the `REST_POSE` scene. Each `REST_*` mesh is
rigidly parented to the bone named in its `driven_by_bone` custom property. The
armature is shown in front with bone names and local axes enabled.

`lara_running_normal_001.blend` contains only `RUNNING_NORMAL_001` and opens at
animation frame 1, ready to play.

The arms-down source pose places two distinct sets of disconnected mesh islands
in nearly the same location. The smaller, medial islands are `hand.l/r` and are
driven by the hand bones. The longer, outboard islands are `holster.l/r` and are
driven by the pelvis. The builder keeps all four as separate rigid objects;
neither pair remains accidentally joined to the thigh meshes.

The source OBJ's left hand island is quarter-turned relative to the mirrored
right hand. The builder records and applies that bind-pose correction
explicitly rather than modifying the provenance copy in `source/`.

The motion capture's `Chest` and `Head` frames also use a longitudinal-axis
roll convention that differs by 90 degrees from Lara's rigid bones. Their
motion-basis corrections are recorded explicitly in the builder and affect only
the running scene, not `REST_POSE`.

This is a first retargeting pass. It preserves the captured world-space run but
does not yet perform foot-contact correction, loop extraction, or hand-tuned
shoulder and wrist alignment.
