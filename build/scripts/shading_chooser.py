import colorsys
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
from collections import defaultdict

# Define the color palette
palette = [
    (0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255),
    (255, 170, 170), (170, 85, 85), (255, 85, 85), (85, 0, 0),
    (170, 0, 0), (255, 0, 0), (255, 85, 0), (255, 170, 85),
    (170, 85, 0), (255, 170, 0), (255, 255, 170), (170, 170, 85),
    (255, 255, 85), (85, 85, 0), (170, 170, 0), (255, 255, 0),
    (170, 255, 0), (170, 255, 85), (85, 170, 0), (85, 255, 0),
    (170, 255, 170), (85, 170, 85), (85, 255, 85), (0, 85, 0),
    (0, 170, 0), (0, 255, 0), (0, 255, 85), (85, 255, 170),
    (0, 170, 85), (0, 255, 170), (170, 255, 255), (85, 170, 170),
    (85, 255, 255), (0, 85, 85), (0, 170, 170), (0, 255, 255),
    (0, 170, 255), (85, 170, 255), (0, 85, 170), (0, 85, 255),
    (170, 170, 255), (85, 85, 170), (85, 85, 255), (0, 0, 85),
    (0, 0, 170), (0, 0, 255), (85, 0, 255), (170, 85, 255),
    (85, 0, 170), (170, 0, 255), (255, 170, 255), (170, 85, 170),
    (255, 85, 255), (85, 0, 85), (170, 0, 170), (255, 0, 255),
    (255, 0, 170), (255, 85, 170), (170, 0, 85), (255, 0, 85)
]

# Convert RGB to HSV
hsv_palette = [colorsys.rgb_to_hsv(r/255, g/255, b/255) for r, g, b in palette]

# Function to bucketize by hue
def bucketize_by_hue(hsv_palette, num_buckets):
    hue_buckets = defaultdict(list)
    for hsv in hsv_palette:
        hue_bucket = int(hsv[0] * num_buckets)
        hue_buckets[hue_bucket].append(hsv)
    return hue_buckets

# Function to sort by value within each hue bucket
def sort_by_value(hue_buckets):
    sorted_buckets = {}
    for k, v in hue_buckets.items():
        sorted_buckets[k] = sorted(v, key=lambda x: x[2])
    return sorted_buckets

# Function to find the closest color match by hue and value
def closest_color_match(hue, value, hue_bucket):
    closest_color = None
    min_distance = float('inf')
    for color in hue_bucket:
        hue_diff = abs(hue - color[0])
        value_diff = abs(value - color[2])
        distance = hue_diff + value_diff
        if distance < min_distance:
            min_distance = distance
            closest_color = color
    return closest_color

# Function to display the colors in a grid
def display_color_grid(hue_buckets, num_buckets, value_levels):
    fig, ax = plt.subplots()
    for i in range(num_buckets):
        hue = i / num_buckets
        for j in range(value_levels):
            value = j / (value_levels - 1)
            if hue in hue_buckets:
                color = closest_color_match(hue, value, hue_buckets[hue])
                if color:
                    rgb = colorsys.hsv_to_rgb(color[0], color[1], color[2])
                    ax.add_patch(Rectangle((i, j), 1, 1, color=rgb))
    plt.xlim(0, num_buckets)
    plt.ylim(0, value_levels)
    plt.gca().invert_yaxis()
    plt.show()

# Interactive part
num_hue_buckets = int(input("Enter the number of hue buckets: "))
value_levels = int(input("Enter the number of value levels: "))

hue_buckets = bucketize_by_hue(hsv_palette, num_hue_buckets)
sorted_buckets = sort_by_value(hue_buckets)
display_color_grid(sorted_buckets, num_hue_buckets, value_levels)
