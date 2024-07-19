import bpy
import bmesh

# Get the active object
obj = bpy.context.object

# Ensure we are in edit mode and have a valid mesh object
if obj and obj.type == 'MESH':
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Create a bmesh object from the edit mesh
    bm = bmesh.from_edit_mesh(obj.data)
    
    material_vertices = {}
    
    # Loop through each material in the object
    for material_index, material in enumerate(obj.data.materials):
        material_name = material.name
        
        # Collect vertices associated with the material
        vertices = set()
        
        for face in bm.faces:
            if face.material_index == material_index:
                for vert in face.verts:
                    vertices.add(vert.index)
        
        material_vertices[material_name] = vertices
    
    # Update the bmesh to reflect any changes
    bmesh.update_edit_mesh(obj.data)
    
    # Switch back to object mode to assign vertex groups and materials
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Ensure there is a default material, creating one if necessary
    default_material_name = "DefaultMaterial"
    if default_material_name not in [mat.name for mat in obj.data.materials]:
        default_material = bpy.data.materials.new(name=default_material_name)
        obj.data.materials.append(default_material)
    else:
        default_material = bpy.data.materials[default_material_name]
    
    # Assign vertices to vertex groups and remap faces to the default material
    for material_name, vertices in material_vertices.items():
        # Create a new vertex group for the material
        vertex_group = obj.vertex_groups.new(name=material_name)
        # Add vertices to the vertex group
        vertex_group.add(list(vertices), 1.0, 'ADD')
    
    # Assign the default material to all faces
    for poly in obj.data.polygons:
        poly.material_index = obj.data.materials.find(default_material_name)
    
    print("Vertices organized into vertex groups and remapped to the default material.")
else:
    print("No valid mesh object selected.")
