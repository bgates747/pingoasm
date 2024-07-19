import bpy
import bmesh
import os

# Save the current Blender file before making any modifications
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)

# Set the directory where the OBJ files will be exported
export_directory = "/home/smith/Agon/mystuff/agon-testing/ez80/src/blender"

# Ensure the directory exists
if not os.path.exists(export_directory):
    os.makedirs(export_directory)

# Get the Blender file name without extension
blend_file_path = bpy.data.filepath
blend_file_name = os.path.splitext(os.path.basename(blend_file_path))[0]
target_filename = os.path.join(export_directory, f"{blend_file_name}.obj")

# Define the grid precision for snapping vertices
grid_precision = 0.000001

# Function to snap a value to the given grid precision
def snap_to_grid(value, precision):
    return round(value / precision) * precision

# Function to snap UVs to the nearest 1/nth value
def snap_uv_to_grid(uv, width, height):
    uv.x = round(uv.x * width) / width
    uv.y = round(uv.y * height) / height

# Function to round UVs to six decimal places
def round_uv(uv):
    uv.x = round(uv.x, 6)
    uv.y = round(uv.y, 6)

# Get the current collection
collection = bpy.context.collection

# Iterate through all the mesh objects in the current collection
for obj in collection.objects:
    if obj.type == 'MESH':
        # Select the object
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        
        # Scale by -1 along the Z axis
        bpy.ops.transform.resize(value=(1, 1, -1))
        bpy.ops.object.transform_apply(scale=True)
        
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

        # Snap vertices to the grid
        bm = bmesh.from_edit_mesh(obj.data)
        for vert in bm.verts:
            vert.co.x = snap_to_grid(vert.co.x, grid_precision)
            vert.co.y = snap_to_grid(vert.co.y, grid_precision)
            vert.co.z = snap_to_grid(vert.co.z, grid_precision)

        # Merge by distance to remove duplicate vertices
        bpy.ops.mesh.remove_doubles(threshold=grid_precision)
        bmesh.update_edit_mesh(obj.data)

#        # Adjust UVs to account for axis inversion and snap to grid
#        width, height = 1, 1
#        if obj.data.materials:
#            material = obj.data.materials[0]
#            if material.use_nodes:
#                for node in material.node_tree.nodes:
#                    if node.type == 'TEX_IMAGE' and node.image:
#                        image = node.image
#                        width, height = image.size
#                        break
                    
#        # Recalculate normals
#        bpy.ops.mesh.normals_make_consistent(inside=False)
#        
#        uv_layer = bm.loops.layers.uv.active
#        if uv_layer:
#            for face in bm.faces:
#                for loop in face.loops:
#                    uv = loop[uv_layer].uv
#                    snap_uv_to_grid(uv, width, height)
#                    round_uv(uv)

#            # Merge duplicate UVs
#            bpy.ops.mesh.select_all(action='SELECT')
#            bpy.ops.uv.remove_doubles(threshold=0.000001)

        bpy.ops.object.mode_set(mode='OBJECT')

        # Apply all transformations
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Apply triangulation to all faces
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.quads_convert_to_tris()
        bpy.ops.object.mode_set(mode='OBJECT')

        # Deselect the object to prepare for the next one
        obj.select_set(False)

# Select all mesh objects for export
bpy.ops.object.select_all(action='DESELECT')
for obj in collection.objects:
    if obj.type == 'MESH':
        obj.select_set(True)

# Export all selected mesh objects to a single OBJ file
bpy.ops.export_scene.obj(
    filepath=target_filename,
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

# Ensure the selection state is clean
bpy.ops.object.select_all(action='DESELECT')

print("Export completed successfully.")

# Revert to the saved Blender file to undo any modifications made during script execution
bpy.ops.wm.revert_mainfile()
