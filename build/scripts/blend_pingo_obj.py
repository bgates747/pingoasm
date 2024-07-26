import bpy
import os

# Set the directory where the OBJ files will be exported
export_directory = "/home/smith/Agon/mystuff/pingoasm/src/blender"

# Ensure the directory exists
if not os.path.exists(export_directory):
    os.makedirs(export_directory)

# Save the current Blender file
original_file_path = bpy.data.filepath
temp_file_path = bpy.path.abspath("//temp_backup.blend")
bpy.ops.wm.save_as_mainfile(filepath=temp_file_path)

# Get the current collection
collection = bpy.context.collection

# Iterate through all the mesh objects in the current collection
for obj in collection.objects:
    if obj.type == 'MESH':
        # Select the object
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Check if normalization is needed
        max_coord = max(max(v.co) for v in obj.data.vertices)
        min_coord = min(min(v.co) for v in obj.data.vertices)
        if max_coord > 1 or min_coord < -1:
            # Normalize the vertex locations between -1 and 1
            for v in obj.data.vertices:
                v.co = v.co.normalized()

        # Scale by -1 along the Z axis
        bpy.ops.transform.resize(value=(1, 1, -1))
        bpy.ops.object.transform_apply(scale=True)

        # Recalculate normals
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        # Adjust UVs to account for axis inversion
        for uv_layer in obj.data.uv_layers:
            for uv in uv_layer.data:
                uv.uv[1] = 1.0 - uv.uv[1]

        # Apply all transformations
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Apply triangulation to all faces
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.quads_convert_to_tris()
        bpy.ops.object.mode_set(mode='OBJECT')

        # Construct the file path
        file_path = os.path.join(export_directory, obj.name + ".obj")

        # Export the object as an OBJ file
        bpy.ops.export_scene.obj(
            filepath=file_path,
            check_existing=False,
            axis_forward='-Z', 
            axis_up='Y',
            use_selection=True,
            use_mesh_modifiers=True,
            use_normals=True,
            use_uvs=True,
            use_materials=True,
            keep_vertex_order=True,
            path_mode='COPY'
        )

        # Deselect the object
        obj.select_set(False)

# Ensure the selection state is clean
bpy.ops.object.select_all(action='DESELECT')

# Restore the original Blender file
bpy.ops.wm.open_mainfile(filepath=temp_file_path)

print("Export completed successfully.")
