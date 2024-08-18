import numpy as np
from PIL import Image

# Define the size of the image and the checkerboard pattern
image_size = 256
grid_size = 8
square_size = image_size // grid_size  # Each square will be 32x32 pixels

# Create an array to hold the image data, including the alpha channel
image = np.zeros((image_size, image_size, 4), dtype=np.uint8)

# Define colors with full alpha (opaque)
white = [255, 255, 255, 255]  # 0xFFFFFFFF
gray = [170, 170, 170, 255]   # 0xAAAAAAFF

# Fill the image with the checkerboard pattern
for y in range(image_size):
    for x in range(image_size):
        if (x // square_size) % 2 == (y // square_size) % 2:
            image[y, x] = white
        else:
            image[y, x] = gray

# Create the image from the array
img = Image.fromarray(image, 'RGBA')  # Ensure RGBA mode is used

# Save the image
img.save('src/blender/checkerboard.png')

img.show()  # Show the image for quick verification
