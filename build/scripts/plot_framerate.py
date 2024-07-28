import re
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import style
import matplotlib.colors as mcolors

# Sample data as a multi-line text argument (placeholder for real user input)
data = """
Title: Viking Model 240x160
Unoptimized:

10 frames in 1564 ms = 6.41 fps. Render time: 156 ms/frame = 6.41 fps
10 frames in 1548 ms = 6.49 fps. Render time: 154 ms/frame = 6.49 fps
10 frames in 1646 ms = 6.10 fps. Render time: 164 ms/frame = 6.10 fps
10 frames in 1597 ms = 6.29 fps. Render time: 159 ms/frame = 6.29 fps
10 frames in 1586 ms = 6.33 fps. Render time: 158 ms/frame = 6.33 fps
10 frames in 1569 ms = 6.41 fps. Render time: 156 ms/frame = 6.41 fps
10 frames in 1605 ms = 6.25 fps. Render time: 160 ms/frame = 6.25 fps
10 frames in 1554 ms = 6.45 fps. Render time: 155 ms/frame = 6.45 fps
10 frames in 1550 ms = 6.45 fps. Render time: 155 ms/frame = 6.45 fps
10 frames in 1623 ms = 6.17 fps. Render time: 162 ms/frame = 6.17 fps
10 frames in 1614 ms = 6.21 fps. Render time: 161 ms/frame = 6.21 fps
10 frames in 1595 ms = 6.29 fps. Render time: 159 ms/frame = 6.29 fps
10 frames in 1554 ms = 6.45 fps. Render time: 155 ms/frame = 6.45 fps
10 frames in 1620 ms = 6.17 fps. Render time: 162 ms/frame = 6.17 fps
10 frames in 1547 ms = 6.49 fps. Render time: 154 ms/frame = 6.49 fps
10 frames in 1562 ms = 6.41 fps. Render time: 156 ms/frame = 6.41 fps
10 frames in 1597 ms = 6.29 fps. Render time: 159 ms/frame = 6.29 fps
10 frames in 1631 ms = 6.13 fps. Render time: 163 ms/frame = 6.13 fps
10 frames in 1597 ms = 6.29 fps. Render time: 159 ms/frame = 6.29 fps
10 frames in 1547 ms = 6.49 fps. Render time: 154 ms/frame = 6.49 fps
10 frames in 1621 ms = 6.17 fps. Render time: 162 ms/frame = 6.17 fps
10 frames in 1551 ms = 6.45 fps. Render time: 155 ms/frame = 6.45 fps
10 frames in 1570 ms = 6.37 fps. Render time: 157 ms/frame = 6.37 fps
10 frames in 1574 ms = 6.37 fps. Render time: 157 ms/frame = 6.37 fps
10 frames in 1647 ms = 6.10 fps. Render time: 164 ms/frame = 6.10 fps
10 frames in 1597 ms = 6.29 fps. Render time: 159 ms/frame = 6.29 fps
10 frames in 1548 ms = 6.49 fps. Render time: 154 ms/frame = 6.49 fps
10 frames in 1612 ms = 6.21 fps. Render time: 161 ms/frame = 6.21 fps
10 frames in 1563 ms = 6.41 fps. Render time: 156 ms/frame = 6.41 fps
10 frames in 1568 ms = 6.41 fps. Render time: 156 ms/frame = 6.41 fps
Optimized:
10 frames in 1528 ms = 6.58 fps. Render time: 152 ms/frame = 6.58 fps
10 frames in 1453 ms = 6.90 fps. Render time: 145 ms/frame = 6.90 fps
10 frames in 1547 ms = 6.49 fps. Render time: 154 ms/frame = 6.49 fps
10 frames in 1505 ms = 6.67 fps. Render time: 150 ms/frame = 6.67 fps
10 frames in 1491 ms = 6.71 fps. Render time: 149 ms/frame = 6.71 fps
10 frames in 1479 ms = 6.80 fps. Render time: 147 ms/frame = 6.80 fps
10 frames in 1509 ms = 6.67 fps. Render time: 150 ms/frame = 6.67 fps
10 frames in 1456 ms = 6.90 fps. Render time: 145 ms/frame = 6.90 fps
10 frames in 1457 ms = 6.90 fps. Render time: 145 ms/frame = 6.90 fps
10 frames in 1525 ms = 6.58 fps. Render time: 152 ms/frame = 6.58 fps
10 frames in 1520 ms = 6.58 fps. Render time: 152 ms/frame = 6.58 fps
10 frames in 1501 ms = 6.67 fps. Render time: 150 ms/frame = 6.67 fps
"""


# Parsing the data
title_match = re.search(r"Title: (.+)", data)
title = title_match.group(1) if title_match else 'Rendering Performance'

category_pattern = r"(\w[\w\s]*):"
time_pattern = r"(\d+) frames in (\d+) ms"

category_data = {}
current_category = None
total_frames = {}
total_times = {}
for line in data.splitlines():
    if 'Title:' in line:
        continue
    category_match = re.match(category_pattern, line)
    if category_match:
        current_category = category_match.group(1)
        category_data[current_category] = []
        total_frames[current_category] = 0
        total_times[current_category] = 0
    else:
        time_match = re.search(time_pattern, line)
        if time_match and current_category:
            frames, time = int(time_match.group(1)), int(time_match.group(2))
            category_data[current_category].append(frames / (time / 1000))  # Calculate FPS
            total_frames[current_category] += frames
            total_times[current_category] += time

# Data preparation for plotting
categories = list(category_data.keys())
fps_means = [np.mean(category_data[cat]) if category_data[cat] else 0 for cat in categories]
fps_cis = [0] * len(categories)  # Removing confidence intervals

# Legend data preparation
legend_labels = [
    f"{cat}: n={total_frames[cat]}, avg={total_times[cat] // total_frames[cat]} ms {total_frames[cat] / total_times[cat] * 1000:.2f} fps"
    for cat in categories
]

# Get Tableau colors
tableau_colors = list(mcolors.TABLEAU_COLORS.values())
color_cycle = tableau_colors[:len(categories)]

# Plot settings
style.use('dark_background')

# Creating the bar chart
fig, ax = plt.subplots()
bar_locations = np.arange(len(categories))
bars = ax.bar(bar_locations, fps_means, alpha=0.7, color=color_cycle)
ax.set_ylabel('Frames Per Second (FPS)')
ax.set_title(title)
plt.legend(bars, legend_labels, loc='upper center', bbox_to_anchor=(0.5, -0.1), fancybox=True, shadow=True, ncol=1)
plt.subplots_adjust(bottom=0.2)  # Increase the bottom margin
plt.show()