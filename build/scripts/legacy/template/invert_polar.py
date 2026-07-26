from PIL import Image
import numpy as np

def create_reverse_polar_projection(input_image_path, output_image_path):
    # Open the input image
    img = Image.open(input_image_path)
    img = img.convert('RGB')

    # Get image dimensions and compute the maximum radius
    width, height = img.size
    r_max = width // 2

    # Create an empty array for the output image
    output = Image.new('RGB', (width, height))
    output_pixels = output.load()

    # Calculate the angle step in radians for one pixel step, with oversampling
    angle_step = np.arctan(1 / r_max) / 2

    # Number of steps needed to complete a full circle
    num_steps = int(2 * np.pi / angle_step)

    # Iterate over angles from 0 to 2*pi
    for i in range(num_steps):
        phi = i * angle_step

        # Iterate over radii from 0 to r_max
        for j in range(r_max*2):
            r = j / 2
            # Adjust the radius using a cosine relationship for the source
            r_src = int(r_max * np.cos(np.pi * r / (2 * r_max)))

            # Convert polar coordinates (r_src, phi) to Cartesian coordinates (x, y) for the source
            src_x = int(r_max + r_src * np.cos(phi))
            src_y = int(r_max + r_src * np.sin(phi))

            # Invert the radius and adjust using a cosine relationship for the destination
            r_dest = r_max - r
            r_dest = int(r_max * np.cos(np.pi * r_dest / (2 * r_max)))

            # Compute the destination pixel location based on adjusted radius
            dest_x = int(r_max + r_dest * np.cos(phi))
            dest_y = int(r_max + r_dest * np.sin(phi))

            # Ensure that the calculated coordinates are within bounds
            if 0 <= src_x < width and 0 <= src_y < height and 0 <= dest_x < width and 0 <= dest_y < height:
                output_pixels[dest_x, dest_y] = img.getpixel((src_x, src_y))

    # Save the output image
    output.save(output_image_path)
    output.show()

# Example usage
create_reverse_polar_projection('src/blender/flyingfield2.png', 'src/blender/flyingfield2inv.png')
