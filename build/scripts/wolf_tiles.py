import os
from PIL import Image

# Directory containing .png files
directory = "/home/smith/Agon/mystuff/pingoasm/src/blender/wolf"

# Create a 160x160 transparent image
pillow_image = Image.new('RGBA', (160, 160), (0, 0, 0, 0))

# Get all .png files in the directory
png_files = [f for f in os.listdir(directory) if f.endswith('.png')]

# Sort files based on the filename
sorted_files = sorted(png_files)

# Process each image and tile it onto the pillow image
for file_name in sorted_files:
    image_path = os.path.join(directory, file_name)
    base_name = os.path.splitext(file_name)[0]
    try:
        position = int(base_name[-2:])
    except ValueError:
        continue

    # Skip files that do not have a valid two-digit position
    try:
        position = int(base_name[-2:])
        if position < 10 or position > 99:
            continue
    except ValueError:
        # Skip files that do not have a valid two-digit position
        continue
    
    # Open the image
    img = Image.open(image_path)
    
    # Calculate position for the tile
    position -= 10 # tiles are 10-based
    x_pos = (position % 10) * 16
    y_pos = (9 - (position // 10)) * 16  # Adjust y position to start from the bottom
    
    # Paste the image onto the pillow image
    pillow_image.paste(img, (x_pos, y_pos), img)

# Save the resulting image
output_path = "/home/smith/Agon/mystuff/pingoasm/src/blender/wolf/wolf_tex.png"
pillow_image.save(output_path)
