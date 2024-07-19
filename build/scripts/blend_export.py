import bpy  # type: ignore
import os
import sys

def process_first_mesh(output_file, mesh_name):
    # Ensure we're in object mode
    if bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Find the first mesh object
    first_mesh = None
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and obj.name == mesh_name:
            first_mesh = obj
            break

    if not first_mesh:
        raise ValueError("No mesh object found in the blend file.")

    # Duplicate the mesh
    bpy.ops.object.select_all(action='DESELECT')
    first_mesh.select_set(True)
    bpy.ops.object.duplicate()
    temp_mesh = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = temp_mesh

    # Apply any rotation transformation
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

    # Switch to edit mode to remove doubles
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()
    bpy.ops.object.mode_set(mode='OBJECT')

    # Apply the Triangulate modifier to the duplicate
    bpy.ops.object.modifier_add(type='TRIANGULATE')
    bpy.ops.object.modifier_apply(modifier="Triangulate")

    # Generate a list of all vertices, transformed to Pingo conventions
    vertices = [[vert.co.x, -vert.co.z, vert.co.y] for vert in temp_mesh.data.vertices]

    # Generate a list of face definitions (triangulated)
    faces = [[vert for vert in poly.vertices] for poly in temp_mesh.data.polygons]

    # Generate a list of unique UV coordinates and corresponding indices
    uv_layer = temp_mesh.data.uv_layers.active.data
    uv_coords = []
    uv_indices = []

    for poly in temp_mesh.data.polygons:
        poly_uv_indices = []
        for loop_index in poly.loop_indices:
            uv = uv_layer[loop_index].uv
            uv_coord = [uv[0], uv[1]]
            if uv_coord not in uv_coords:
                uv_coords.append(uv_coord)
            poly_uv_indices.append(uv_coords.index(uv_coord))
        uv_indices.append(poly_uv_indices)

    # Delete the temporary mesh
    bpy.ops.object.delete()

    with open(output_file, 'w') as file:
        file.write("vertices = [\n")
        for vertex in vertices:
            rounded_vertex = [round(coord, 6) if 'e' not in str(coord) else 0.000000 for coord in vertex]
            file.write(f"    {rounded_vertex},\n")
        file.write("]\n\n")

        file.write("faces = [\n")
        for face in faces:
            file.write(f"    {face},\n")
        file.write("]\n")

        file.write("texture_coords = [\n")
        for coord in uv_coords:
            rounded_coord = [round(c, 6) if 'e' not in str(c) else 0.000000 for c in coord]
            file.write(f"    {rounded_coord},\n")
        file.write("]\n")

        file.write("texture_vertex_indices = [\n")
        for indices in uv_indices:
            file.write(f"    {indices},\n")
        file.write("]\n")

    print(f"Vertex and face data written to {output_file}")

if __name__ == "__main__":
    argv = sys.argv
    argv = argv[argv.index("--") + 1:]  # get all args after "--"
    output_file = argv[0]  # First argument after -- is the output file path
    mesh_name = argv[1]  # Second argument after -- is the mesh name
    process_first_mesh(output_file, mesh_name)
