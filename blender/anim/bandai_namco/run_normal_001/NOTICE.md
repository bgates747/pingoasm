# Third-party asset notice

## Original motion

- Asset: `dataset-2_run_normal_001.bvh`
- Annotation: `dataset-2_run_normal_001.json`
- Creator and licensor: Bandai Namco Research Inc.
- Source: https://github.com/BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset
- Dataset: Bandai-Namco-Research-Motiondataset-2
- License: Creative Commons Attribution-NonCommercial 4.0 International
  (CC BY-NC 4.0), reproduced in `source/LICENSE-CC-BY-NC-4.0.txt`
- License URL: https://creativecommons.org/licenses/by-nc/4.0/

The BVH and JSON files in `source/` are unmodified copies. Their original names
have been retained.

## Changes in this experiment

`scripts/build_running_scene.py` imports the BVH into Blender at a normalized
scale and generates a Blender scene containing a polygonal proxy figure, ground
plane, materials, lighting, and an animated tracking camera. Files under
`output/` are generated adaptations. Files under `modified/` may contain later
hand edits and should document those edits alongside the asset.

All use and redistribution of the source motion and derived animation assets
must remain non-commercial and comply with CC BY-NC 4.0. Nothing in this notice
implies endorsement by Bandai Namco Research Inc.

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
