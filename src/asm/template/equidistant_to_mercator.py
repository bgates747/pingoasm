import numpy as np
import cv2
import math

def equidistant_to_mercator(image):
    height, width = image.shape[:2]
    mercator_image = np.zeros_like(image)

    for y in range(height):
        # Convert y coordinate to latitude in degrees (equidistant)
        latitude = 90 - 180 * y / height
        latitude_radians = math.radians(latitude)
        
        # Convert latitude to Mercator y coordinate
        mercator_y = int((height / 2) * (1 - math.log(math.tan(math.pi / 4 + latitude_radians / 2)) / math.pi))
        
        # Ensure mercator_y is within bounds
        mercator_y = max(0, min(height - 1, mercator_y))
        
        for x in range(width):
            mercator_image[mercator_y, x] = image[y, x]

    return mercator_image

# Load the equidistant image
image = cv2.imread('src/blender/middle_harbor_drone.png')

# Convert to Mercator projection
mercator_image = equidistant_to_mercator(image)

# Save the result
cv2.imwrite('mercator_middle_harbor_drone.png', mercator_image)

# Display the result (optional)
cv2.imshow('Mercator Projection', mercator_image)
cv2.waitKey(0)
cv2.destroyAllWindows()
