import numpy as np
import matplotlib.pyplot as plt

# Define screen dimensions and FOV
screen_width = 320
screen_height = 160
fov = 90
aspect_ratio = screen_width / screen_height

# Define triangle vertices in world coordinates
vertices = np.array([
    [-0.939692, -1.044199, -3.836824],
    [-0.939692, 0.925417, -3.489527],
    [0.939693, 1.044199, -4.163177]
])

# Project vertices to screen space
def project_to_screen(vertex, screen_width, screen_height, fov):
    fov_rad = np.deg2rad(fov)
    scale = 1 / np.tan(fov_rad / 2)
    x = vertex[0] * scale * aspect_ratio / -vertex[2]
    y = vertex[1] * scale / -vertex[2]
    screen_x = int((x + 1) * screen_width / 2)
    screen_y = int((1 - y) * screen_height / 2)
    z = vertex[2]
    return screen_x, screen_y, z

# Project all vertices
projected_vertices = np.array([project_to_screen(v, screen_width, screen_height, fov) for v in vertices])

# Sort vertices by y to determine which scanlines to draw
projected_vertices = projected_vertices[np.argsort(projected_vertices[:, 1])]

# Define the middle scanline
scanline_y = screen_height // 2

# Find intersection points with scanline
def edge_intersection(v1, v2, scanline_y):
    if (v1[1] < scanline_y < v2[1]) or (v2[1] < scanline_y < v1[1]):
        t = (scanline_y - v1[1]) / (v2[1] - v1[1])
        x = v1[0] + t * (v2[0] - v1[0])
        z = 1 / (1 / v1[2] + t * ((1 / v2[2]) - (1 / v1[2])))  # Interpolating 1/z
        return x, scanline_y, z
    return None

# Find intersections on the scanline
intersections = []
for i in range(3):
    next_i = (i + 1) % 3
    intersect = edge_intersection(projected_vertices[i], projected_vertices[next_i], scanline_y)
    if intersect:
        intersections.append(intersect)

# Sort intersections by x
intersections = sorted(intersections, key=lambda p: p[0])

# Interpolate along the scanline using Bresenham-like method
z_values = []
if len(intersections) == 2:
    x0, _, z0 = intersections[0]
    x1, _, z1 = intersections[1]
    
    # Interpolate along the x values
    x_range = np.arange(int(x0), int(x1) + 1)
    step = (z1 / z0) ** (1 / (x1 - x0)) if x1 != x0 else 1
    
    current_z = z0
    current_1_over_z = 1 / z0
    step_1_over_z = (1 / z1) / (1 / z0) ** (1 / (x1 - x0)) if x1 != x0 else 1
    
    for x in x_range:
        z_values.append((x, scanline_y, current_z, current_1_over_z))
        current_z *= step
        current_1_over_z *= step_1_over_z

    # Plotting the triangle, scanline, and intersection points
    plt.figure(figsize=(10, 6))
    plt.plot(*zip(*[(v[0], v[1]) for v in projected_vertices]), marker='o', markersize=5, linestyle='-', color='blue')
    plt.hlines(scanline_y, 0, screen_width, colors='red', linestyles='dotted')
    plt.scatter(*zip(*[(i[0], i[1]) for i in intersections]), color='green', zorder=5)
    plt.title("Triangle and Scanline Intersection")
    plt.xlabel("Screen X")
    plt.ylabel("Screen Y")
    plt.gca().invert_yaxis()  # Invert y-axis to match screen coordinates
    plt.show()
    
    # Print vertex information
    print("Vertex World Coordinates, Camera-Relative Z, Perspective Adjusted Z, Screen X, Screen Y")
    vertex_data = []
    for i, vertex in enumerate(vertices):
        screen_x, screen_y, z = projected_vertices[i]
        perspective_adjusted_z = 1 / z if z != 0 else float('inf')
        vertex_data.append([*vertex, z, perspective_adjusted_z, screen_x, screen_y])
    headers = ["World X", "World Y", "World Z", "Camera-Relative Z", "Perspective Adjusted Z", "Screen X", "Screen Y"]
    print(",".join(headers))
    for row in vertex_data:
        print(",".join(map(str, row)))

    # Print coefficients and key values used for calculations
    coefficients = {
        "FOV": fov,
        "Screen Width": screen_width,
        "Screen Height": screen_height,
        "Aspect Ratio": aspect_ratio
    }
    print("\nCoefficients and Key Values:")
    for key, value in coefficients.items():
        print(f"{key}: {value}")

    # Print intersection points with scanline
    print("\nIntersection Points with Camera-Relative Z and Perspective Adjusted Z")
    intersection_data = [[x, y, z, 1/z] for x, y, z in intersections]
    headers = ["Intersection X", "Intersection Y", "Camera-Relative Z", "Perspective Adjusted Z"]
    print(",".join(headers))
    for row in intersection_data:
        print(",".join(map(str, row)))

    # Print step factor for depth interpolation
    step_factor = (z1 / z0) ** (1 / (x1 - x0)) if x1 != x0 else 1
    print(f"\nStep Factor for Depth Interpolation: {step_factor:.6f}")

    # Print table of interpolated values along the scanline, including 1/z
    print("\nInterpolated Z and 1/Z Values Along Scanline")
    headers = ["X", "Y", "Z", "1/Z"]
    print(",".join(headers))
    for row in z_values:
        print(",".join(map(str, row)))

else:
    print("Error: Scanline does not intersect the triangle at two points.")
