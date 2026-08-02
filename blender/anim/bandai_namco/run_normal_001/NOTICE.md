# Attribution, license, and changes

## Original motion

- Asset: `dataset-2_run_normal_001.bvh`
- Annotation: `dataset-2_run_normal_001.json`
- Creator, copyright holder, and licensor: **Bandai Namco Research Inc.**
- Copyright: **© 2022 Bandai Namco Research Inc. All Rights Reserved.**
- Source: https://github.com/BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset
- Dataset: Bandai-Namco-Research-Motiondataset-2
- Dataset information: https://github.com/BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset/tree/master/dataset/Bandai-Namco-Research-Motiondataset-2
- License: Creative Commons Attribution-NonCommercial 4.0 International
  (CC BY-NC 4.0), reproduced in `source/LICENSE-CC-BY-NC-4.0.txt`
- License URL: https://creativecommons.org/licenses/by-nc/4.0/

The BVH and JSON files in `source/` are unmodified copies with their original
names. Their checksums and structured provenance are recorded in
`source/dataset-2_run_normal_001.provenance.json`. The annotation identifies
content `run` and style `normal`; Dataset 2 is sampled at 30 frames per second.

## Changes in this experiment

The experiment makes the following adaptations:

- imports and rescales the BVH and retargets it to a rigid-part Lara model;
- maps the model's separate body meshes to motion-driven bones and corrects
  coordinate-basis, part-orientation, hierarchy, and texture-UV issues;
- selects source frames 1 through 23 as one stride and retains frame 24 as a
  non-stored seam witness;
- preserves frames 1 through 15, then conditions local bone channels over
  frames 16 through 24 for loop position and finite-step velocity closure;
- converts and quantizes transforms, rigid meshes, UVs, and texture data for
  the Pingo eZ80 assembly application; and
- adds project-authored scene, camera, lighting, controls, and build metadata.

The Blender scenes under `output/`, motion-derived portions of generated files
under `apps/anim/`, and demonstrations of those files are adaptations. The
machine-readable export metadata identifies their exact qualified inputs.

When sharing the original motion or an adaptation, retain this notice and the
license copy, credit Bandai Namco Research Inc., link the official source and
CC BY-NC 4.0 license, state that changes were made, and use the material only
for non-commercial purposes. Nothing here implies endorsement by Bandai Namco
Research Inc. CC BY-NC 4.0 applies to the Bandai Namco motion and adaptations
of it, not automatically to the Lara model, project code, or other material in
a mixed file.

## Requested academic citation

Bandai Namco Research asks users to consider citing:

> Makito Kobayashi, Chen-Chieh Liao, Keito Inoue, Sentaro Yojima, and Masafumi
> Takahashi. “Motion Capture Dataset for Practical Use of AI-based Motion
> Editing and Stylization.” arXiv:2306.08861, 2023.

## Lara Croft model

The files `source/LaraCroft.obj`, `source/LaraCroft.mtl`,
`source/LaraCroftOrig.blend`, and `source/Lara.png` form a local low-poly Lara
Croft model asset. The OBJ geometry matches the local `LaraCroft.blend` file:
both use `Combined_Mesh`, 300 vertices, 526 faces, material `tile0`, and texture
`Lara.png`. The OBJ and MTL headers show that they were exported from
`LaraCroft.blend` with Blender 4.0.2.

The model's origin before that Blender file, creator attribution, and license
have not been identified. Its redistribution and commercial-use status are
therefore **uncleared**. See `source/LaraCroft.provenance.json` for the
machine-readable evidence and checksums. Do not treat this model as covered by
the Bandai Namco dataset license or by the repository's main software license.
