"""Export all visible mesh objects from the loaded blend file to OBJ.

Run inside Blender:

    blender --background scene.blend --python blend_export_obj.py -- output.obj
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy  # type: ignore


def arguments() -> list[str]:
    if "--" not in sys.argv:
        raise ValueError("expected an output OBJ path after --")
    return sys.argv[sys.argv.index("--") + 1 :]


def main() -> None:
    args = arguments()
    if len(args) != 1:
        raise ValueError("usage: blend_export_obj.py -- OUTPUT.obj")

    output = Path(args[0]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="DESELECT")
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.hide_render
    ]
    if not meshes:
        raise ValueError("blend file contains no visible mesh objects")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]

    bpy.ops.wm.obj_export(
        filepath=str(output),
        check_existing=False,
        export_selected_objects=True,
        apply_modifiers=True,
        export_eval_mode="DAG_EVAL_RENDER",
        export_triangulated_mesh=True,
        export_uv=True,
        export_normals=True,
        export_materials=True,
        path_mode="RELATIVE",
        forward_axis="NEGATIVE_Z",
        up_axis="Y",
    )
    print(f"Exported {len(meshes)} mesh object(s) to {output}")


if __name__ == "__main__":
    main()
