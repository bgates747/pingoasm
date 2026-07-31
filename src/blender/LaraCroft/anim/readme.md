# Lara Croft animation workspace

This directory holds the articulated Lara source files:

- `Lara6.blend` is the neutral-pose master.
- `Lara7.blend` preserves an earlier hand-authored pose and is a useful
  validation example for the bone pivots and rigid-part parenting.

Both scenes contain a 19-bone armature. Lara is not a conventionally skinned
character: the pelvis, torso, head, upper and lower limbs, hands, and feet are
separate rigid meshes parented directly to their corresponding bones. There
are no vertex groups, armature modifiers, or weight-painted deformation.

The texture path in each scene is `../Lara.png`, relative to this directory.

## Source discussion

The motion-library discussion that prompted this workspace is archived at:

<https://chatgpt.com/share/6a6c2f4f-3d80-83ea-8441-d44b4231cfd0>

Relevant conclusions from that discussion:

> For animation assets, “openly licensed motion library” is usually the more
> accurate term.

> Animated BVH or FBX clips are therefore much more portable; you retarget
> them once and then save the resulting Actions—or individual frames—as your
> own Blender assets.

The suggested source libraries were:

- Quaternius Universal Animation Libraries for clean, game-oriented,
  consistently rigged CC0 animation clips.
- 100STYLE for natural locomotion in ordinary 60 fps BVH under CC BY 4.0.
- The CMU Motion Capture Database for a broader collection requiring more
  conversion and cleanup.

## Proposed Lara pipeline

Lara's rigid-part armature makes the runtime problem simpler than conventional
skeletal animation:

1. Preserve `Lara6.blend` as the neutral master and do new animation work in
   separate files.
2. Import one clean humanoid running clip, probably Quaternius first.
3. Map its principal bones onto Lara's 19-bone hierarchy.
4. Retarget and bake one running cycle into a Lara Action.
5. Correct joint axes, stride length, foot contact, pelvis motion, and Lara's
   deliberately exaggerated proportions by hand.
6. Use `Lara7.blend` as a sanity check that complex poses retain correct rigid
   mesh parenting and joint pivots.

Rigify, skin weights, and runtime vertex deformation are not required. The
useful animation payload is principally rotation tracks for roughly 15 joints,
with optional pelvis translation and vertical motion.

For the first Pingo implementation, sample the authored cycle into perhaps
8–12 poses and emit rigid limb transforms. A later implementation can store
compact joint-angle keyframes and interpolate them on the eZ80. Animation time
should advance with simulation ticks, independently of the render callback;
only the latest dirty world transforms need to be sent to Pingo for a frame.

