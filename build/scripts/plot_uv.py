import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Input text
input_text = """
2028 REM -- TEXTURE UV COORDINATES --
2030 DATA 0.875, 0.5
2032 DATA 0.625, 0.75
2034 DATA 0.625, 0.5
2036 DATA 0.375, 0.5
2038 DATA 0.125, 0.75
2040 DATA 0.125, 0.5
2042 DATA 0.875, 0.75
2044 DATA 0.375, 0.75
2046 REM -- TEXTURE VERTEX INDICES --
2048 DATA 0, 1, 2
2050 DATA 3, 4, 5
2052 DATA 0, 6, 1
2054 DATA 3, 7, 4
"""

# Parse the input text
uv_coords = []
triangle_indices = []

lines = input_text.strip().split('\n')
is_uv_section = False
is_indices_section = False

for line in lines:
    if "TEXTURE UV COORDINATES" in line:
        is_uv_section = True
        is_indices_section = False
        continue
    elif "TEXTURE VERTEX INDICES" in line:
        is_uv_section = False
        is_indices_section = True
        continue
    
    if is_uv_section and "DATA" in line:
        _, data = line.split(" DATA ")
        u, v = map(float, data.split(', '))
        uv_coords.append((u, 1 - v))  # Invert the y-axis
    elif is_indices_section and "DATA" in line:
        _, data = line.split(" DATA ")
        triangle_indices.append(list(map(int, data.split(', '))))

# Colors for each triangle
colors = ['red', 'green', 'blue', 'orange']

# Create a plot
fig, ax = plt.subplots(figsize=(8, 8))

# Add each triangle to the plot
for i, indices in enumerate(triangle_indices):
    triangle = [uv_coords[idx] for idx in indices]
    polygon = patches.Polygon(triangle, closed=True, color=colors[i], alpha=0.5, edgecolor='black')
    ax.add_patch(polygon)

# Set the range for x and y axis
ax.set_xlim(0, 1)
ax.set_ylim(1, 0)

# Set major grid lines at 0.25 intervals
ax.grid(True, which='both', linestyle='--', linewidth=0.5)
ax.set_xticks([i * 0.25 for i in range(5)])
ax.set_yticks([i * 0.25 for i in range(5)])

# Set labels and title
ax.set_xlabel('U')
ax.set_ylabel('V')
ax.set_title('UV Coordinates Triangles Plot')

# Show plot
plt.show()
