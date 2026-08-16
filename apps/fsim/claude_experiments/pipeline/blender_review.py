"""Blender-side import script for reviewing a generated terrain OBJ.

Run as: blender --python blender_review.py -- /path/to/mesh.obj
Loads the mesh into an empty scene, switches the viewport to material
shading with a far clip suitable for a ~130 km model, and frames the mesh.
"""

import sys

import bpy


def main() -> None:
    argv = sys.argv
    obj_path = argv[argv.index("--") + 1]
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.wm.obj_import(filepath=obj_path)
    for imported in bpy.context.selected_objects:
        imported.data.shade_flat()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.clip_start = 10.0
                    space.clip_end = 2_000_000.0
                    space.shading.type = "MATERIAL"
            region = next(
                r for r in area.regions if r.type == "WINDOW"
            )
            with bpy.context.temp_override(
                window=window, area=area, region=region
            ):
                bpy.ops.view3d.view_axis(type="TOP")
                bpy.ops.view3d.view_all()


main()
