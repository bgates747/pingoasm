import re
import matplotlib.pyplot as plt

# Initialize variables
data = {}
current_title = None
render_times = []
fps_values = []

# Read the file and parse the data
with open('src/asm/fpscomparisons3.txt', 'r') as file:
    for line in file:
        title_match = re.match(r"Title: (.*)", line)
        if title_match:
            if current_title and render_times:
                # Store the averages for the previous title
                data[current_title] = {
                    "avg_time": sum(render_times) / len(render_times),
                    "avg_fps": sum(fps_values) / len(fps_values),
                }
            current_title = title_match.group(1)
            render_times = []
            fps_values = []
        else:
            render_match = re.match(r".*took (\d+) ms \(([\d\.]+) FPS\)", line)
            if render_match:
                render_times.append(int(render_match.group(1)))
                fps_values.append(float(render_match.group(2)))

    # Store the last series
    if current_title and render_times:
        data[current_title] = {
            "avg_time": sum(render_times) / len(render_times),
            "avg_fps": sum(fps_values) / len(fps_values),
        }

# Prepare data for plotting
titles = list(data.keys())
avg_fps = [data[title]['avg_fps'] for title in titles]

# Calculate percentage differences for FPS
first_fps = avg_fps[0]
fps_diffs_first = [(fps - first_fps) / first_fps * 100 for fps in avg_fps]
fps_diffs_previous = [0] + [(avg_fps[i] - avg_fps[i - 1]) / avg_fps[i - 1] * 100 for i in range(1, len(avg_fps))]

# Plotting the bar chart for FPS only
fig, ax = plt.subplots()

bar_width = 0.35
index = range(len(titles))

bars = ax.bar(index, avg_fps, bar_width, label='Avg FPS', color='g')
ax.set_xlabel('Test Titles')
ax.set_ylabel('Avg FPS')
ax.set_title('FPS Comparison Across Different Tests')
ax.set_xticks(index)
ax.set_xticklabels(titles, rotation=45, ha='right')

# Add data labels for FPS
for i, rect in enumerate(bars):
    height = rect.get_height()
    label = f"{avg_fps[i]:.2f} FPS\n" \
            f"Δ prev: {fps_diffs_previous[i]:.2f}%\n" \
            f"Δ first: {fps_diffs_first[i]:.2f}%"
    ax.text(rect.get_x() + rect.get_width() / 2, height, label, ha='center', va='bottom', fontsize=8)

ax.set_ylim(0, max(avg_fps) * 1.2)

# Show plot
plt.tight_layout()
plt.show()
