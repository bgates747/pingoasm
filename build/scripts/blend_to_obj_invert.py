import bpy # type: ignore
import os

def ensure_mesh_data(obj):
    if obj.type != 'MESH':
        raise ValueError("Object is not a mesh.")
    return obj

def duplicate_object_to_new_collection(obj, collection_name):
    # Create a new collection
    new_collection = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(new_collection)

    # Duplicate the object and link it to the new collection
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    new_collection.objects.link(new_obj)
    return new_obj

def apply_transformations(obj, rotation, mirror_axis):
    # Apply rotation
    obj.rotation_euler = rotation
    
    # Apply mirroring
    if mirror_axis == 'X':
        obj.scale.x *= -1
    elif mirror_axis == 'Y':
        obj.scale.y *= -1
    elif mirror_axis == 'Z':
        obj.scale.z *= -1
    
    # Apply all transformations
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

def format_num(num):
    return f"{0 if abs(num) < 1e-6 else num:.6f}"

def export_obj(obj, base_filename, obj_filepath, mtl_filepath=None, texture_filepath=None):
    def format_num(num):
        return f"{0 if abs(num) < 1e-6 else num:.6f}"
    
    def write_obj_file(obj, base_filename, obj_filepath):
        with open(obj_filepath, 'w') as obj_file:
            # Write header information
            obj_file.write(f"mtllib {base_filename}.mtl\n")
            obj_file.write(f"o {obj.name}\n")
            
            # Write vertices
            for v in obj.data.vertices:
                x, y, z = map(format_num, v.co)
                obj_file.write(f"v {x} {y} {z}\n")
            
            # Write unique UVs
            uv_layer = obj.data.uv_layers.active.data if obj.data.uv_layers.active else None
            if uv_layer:
                unique_uvs = {}
                uv_indices = []
                for face in obj.data.polygons:
                    for loop_index in face.loop_indices:
                        uv = uv_layer[loop_index].uv
                        uv_key = (format_num(uv.x), format_num(uv.y))
                        if uv_key not in unique_uvs:
                            unique_uvs[uv_key] = len(unique_uvs) + 1
                        uv_indices.append(unique_uvs[uv_key])
                
                for uv in unique_uvs:
                    obj_file.write(f"vt {uv[0]} {uv[1]}\n")
            
            # Add shading and material information
            obj_file.write("s 0\n")
            obj_file.write("usemtl Material\n")
            
            # Write faces
            for face in obj.data.polygons:
                face_verts = []
                for loop_index in face.loop_indices:
                    vert_index = obj.data.loops[loop_index].vertex_index + 1
                    uv_index = uv_indices[loop_index] if uv_layer else ""
                    face_verts.append(f"{vert_index}/{uv_index}" if uv_layer else f"{vert_index}")
                obj_file.write("f " + " ".join(face_verts) + "\n")
    
    def write_mtl_file(mtl_filepath, texture_filepath):
        with open(mtl_filepath, 'w') as mtl_file:
            mtl_file.write("newmtl Material\n")
            mtl_file.write("Ns 250.000000\n")
            mtl_file.write("Ka 1.000000 1.000000 1.000000\n")
            mtl_file.write("Ks 0.500000 0.500000 0.500000\n")
            mtl_file.write("Ke 0.000000 0.000000 0.000000\n")
            mtl_file.write("Ni 1.450000\n")
            mtl_file.write("d 1.000000\n")
            mtl_file.write("illum 2\n")
            if texture_filepath:
                mtl_file.write(f"map_Kd {os.path.basename(texture_filepath)}\n")
    
    # Write OBJ file
    write_obj_file(obj, base_filename, obj_filepath)
    
    # Optionally write MTL file
    if mtl_filepath:
        write_mtl_file(mtl_filepath, texture_filepath)
    
    print(f"Object exported to '{obj_filepath}' successfully.")
    if mtl_filepath:
        print(f"Material file exported to '{mtl_filepath}'.")

if __name__ == "__main__":
    if bpy.context.active_object and bpy.context.active_object.type == 'MESH':
        original_obj = bpy.context.active_object
        
        # Ensure we have mesh data
        original_obj = ensure_mesh_data(original_obj)
        
        # Duplicate the object into a new collection
        new_obj = duplicate_object_to_new_collection(original_obj, "TransformedObjects")

        # Define the desired transformations
        rotation = (0, 0, 0)  # No rotation needed in this specific case
        mirror_axis = 'Y'  # Mirroring along the Y axis

        # Apply the transformations
        apply_transformations(new_obj, rotation, mirror_axis)
        
        # Get the directory containing the current Blender file
        blend_dir = os.path.dirname(bpy.data.filepath)
        
        # Define the output paths relative to the blend file directory
        base_filename = "cube_inv"
        obj_filepath = os.path.join(blend_dir, f"{base_filename}.obj")
        mtl_filepath = os.path.join(blend_dir, f"{base_filename}.mtl")  # Optional
        texture_filepath = os.path.join(blend_dir, "blenderaxes.png")  # Optional texture file

        # Export the object to OBJ format with transformations
        export_obj(new_obj, base_filename, obj_filepath, mtl_filepath, texture_filepath)

    else:
        print("Please select a mesh object.")
