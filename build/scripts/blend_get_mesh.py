import bpy
import mathutils

def apply_transforms_to_mesh(blend_file_path, object_name, transform_matrix):
    # Load the Blender file
    bpy.ops.wm.open_mainfile(filepath=blend_file_path)
    
    # Check if the specified object exists
    if object_name not in bpy.data.objects:
        raise ValueError(f"Object '{object_name}' not found in the Blender file.")
    
    obj = bpy.data.objects[object_name]

    # Ensure the object is a mesh
    if obj.type != 'MESH':
        raise ValueError(f"Object '{object_name}' is not a mesh.")
    
    # Apply the transformation matrix to the object's vertices
    mesh = obj.data
    mesh.transform(transform_matrix)
    
    # Transform UVs as well
    uv_layer = mesh.uv_layers.active.data
    for loop in mesh.loops:
        uv = uv_layer[loop.index].uv
        uv = transform_matrix @ uv.to_3d()  # Apply transform
        uv_layer[loop.index].uv = uv.xy  # Update the UV
    
    # Collect transformed vertex and UV data
    transformed_vertices = [obj.matrix_world @ v.co for v in mesh.vertices]
    transformed_uvs = [uv_layer[loop.index].uv for loop in mesh.loops]

    # Return transformed data
    return transformed_vertices, transformed_uvs

def main():
    # Specify the path to your Blender file
    blend_file_path = 'path/to/your/blendfile.blend'
    
    # Specify the object name
    object_name = 'YourMeshObject'
    
    # Define your transformation matrix (example: scale by 2)
    transform_matrix = mathutils.Matrix.Scale(2.0, 4)
    
    # Apply transformations and get transformed data
    transformed_vertices, transformed_uvs = apply_transforms_to_mesh(blend_file_path, object_name, transform_matrix)
    
    # Print the transformed data
    print("Transformed Vertices:")
    for vertex in transformed_vertices:
        print(vertex)
    
    print("Transformed UVs:")
    for uv in transformed_uvs:
        print(uv)

if __name__ == "__main__":
    main()
