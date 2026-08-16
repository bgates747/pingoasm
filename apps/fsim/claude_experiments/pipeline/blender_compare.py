"""Blender-side comparison loader: one collection per terrain variant.

Run as:
  blender --python blender_compare.py -- name1 path1.obj name2 path2.obj ...

Each OBJ lands in its own named collection. The first collection starts
visible; the rest start hidden, ready for eye-icon toggling in the
outliner. Viewport is set to material shading, top view, wide clip range.
"""

import sys

import bpy


def main() -> None:
    argv = sys.argv
    args = argv[argv.index("--") + 1 :]
    pairs = list(zip(args[0::2], args[1::2]))
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for index, (name, path) in enumerate(pairs):
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
        bpy.ops.wm.obj_import(filepath=path)
        for imported in list(bpy.context.selected_objects):
            for other in imported.users_collection:
                other.objects.unlink(imported)
            collection.objects.link(imported)
            imported.name = name
            imported.data.shade_flat()
    view_layer = bpy.context.view_layer
    for index, (name, _) in enumerate(pairs):
        layer_collection = view_layer.layer_collection.children.get(name)
        if layer_collection is not None:
            layer_collection.hide_viewport = index != 0
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.clip_start = 10.0
                    space.clip_end = 2_000_000.0
                    space.shading.type = "MATERIAL"
            region = next(r for r in area.regions if r.type == "WINDOW")
            with bpy.context.temp_override(
                window=window, area=area, region=region
            ):
                bpy.ops.view3d.view_axis(type="TOP")
                bpy.ops.view3d.view_all()


main()
