import math

# Define the radius and half-length of the cylinder
radius = 1
half_length = 0.5

# Calculate the vertices for the octagon in the YZ plane
angles = [math.radians(45 * i) for i in range(8)]
vertices_positive_x = [(half_length, radius * math.cos(angle), radius * math.sin(angle)) for angle in angles]
vertices_negative_x = [(-half_length, radius * math.cos(angle), radius * math.sin(angle)) for angle in angles]

# Round all vertex coordinates to 6 decimal places
vertices_positive_x = [(round(x, 6), round(y, 6), round(z, 6)) for x, y, z in vertices_positive_x]
vertices_negative_x = [(round(x, 6), round(y, 6), round(z, 6)) for x, y, z in vertices_negative_x]

# Combine vertices for both ends of the cylinder
vertices = vertices_positive_x + vertices_negative_x

# Format the vertices in the given DATA format
vertex_data_lines = []
base_line_number = 2000
line_step = 2

for i, vertex in enumerate(vertices):
    line_number = base_line_number + line_step * (i + 1)
    vertex_data = f"{line_number} DATA {vertex[0]}, {vertex[1]}, {vertex[2]}"
    vertex_data_lines.append(vertex_data)

# Print the formatted vertex data
formatted_vertex_data = "2000 REM -- VERTICES --\n" + "\n".join(vertex_data_lines)
print(formatted_vertex_data)
