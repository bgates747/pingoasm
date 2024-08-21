from svgpathtools import svg2paths
import os

# File path to the SVG file
svg_file_path = '/home/smith/Agon/mystuff/pingoasm/src/blender/Runway_landing_designator_marking-Numbers.svg'
obj_file_path = '/home/smith/Agon/mystuff/pingoasm/src/blender/Runway_landing_designator_marking-Numbers.obj'

# Parse the SVG file
paths, attributes = svg2paths(svg_file_path)

vertices = []
faces = []
vertex_count = 1

# Extract coordinates and prepare vertices and faces for the OBJ file
for i, path in enumerate(paths):
    path_vertices = []
    for segment in path:
        start = segment.start
        end = segment.end
        
        # Convert complex numbers to real and imaginary parts
        x1, z1 = start.real, start.imag
        x2, z2 = end.real, end.imag
        
        # Add vertices to the list
        vertices.append((x1, 0, z1))  # Using 0 as the y-coordinate
        vertices.append((x2, 0, z2))
        
        # Add indices for the face
        path_vertices.append(vertex_count)
        vertex_count += 1
        path_vertices.append(vertex_count)
        vertex_count += 1
    
    # Create faces from the path vertices
    for j in range(1, len(path_vertices), 2):
        if j + 1 < len(path_vertices):
            faces.append((path_vertices[j-1], path_vertices[j], path_vertices[j+1]))
    
    # Close the path by connecting the last and first vertices
    if len(path_vertices) > 2:
        faces.append((path_vertices[-1], path_vertices[-2], path_vertices[0]))

# Write to OBJ file
with open(obj_file_path, 'w') as obj_file:
    for vertex in vertices:
        obj_file.write(f"v {vertex[0]} {vertex[1]} {vertex[2]}\n")
    
    for face in faces:
        obj_file.write(f"f {face[0]} {face[1]} {face[2]}\n")

print(f"OBJ file generated at: {obj_file_path}")
