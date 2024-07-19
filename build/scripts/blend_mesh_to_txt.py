import numpy as np
import re

def read_vertices(filename):
    with open(filename, 'r') as file:
        lines = file.readlines()
    
    vertices = []
    for line in lines:
        match = re.match(r'Vertex \d+: (-?\d+\.\d+), (-?\d+\.\d+), (-?\d+\.\d+)', line)
        if match:
            x, y, z = map(float, match.groups())
            vertices.append((x, y, z))
    
    return lines, vertices

def transform_vertex(x, y, z):
    # Define the rotation matrices
    rotation_x = np.array([
        [1, 0, 0],
        [0, 0, -1],
        [0, 1, 0]
    ])

    rotation_z = np.array([
        [-1, 0, 0],
        [0, -1, 0],
        [0, 0, 1]
    ])
    
    # Apply the rotations
    v = np.array([x, y, z])
    v = np.dot(rotation_x, v)
    v = np.dot(rotation_z, v)
    
    return v

def write_vertices(lines, vertices, target_filename):
    with open(target_filename, 'w') as file:
        vertex_index = 0
        for line in lines:
            if line.startswith('Vertex'):
                x, y, z = vertices[vertex_index]
                file.write(f'Vertex {vertex_index}: {x:.1f}, {y:.1f}, {z:.1f}\n')
                vertex_index += 1
            else:
                file.write(line)

source_file = 'ez80/src/blender/cube.txt'
target_file = 'ez80/src/blender/cube_transformed.txt'

# Read the source file
lines, vertices = read_vertices(source_file)

# Transform the vertices
transformed_vertices = [transform_vertex(x, y, z) for x, y, z in vertices]

# Write the transformed vertices to the target file
write_vertices(lines, transformed_vertices, target_file)

print(f'Transformed vertices written to {target_file}')
