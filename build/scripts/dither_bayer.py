from PIL import Image
import numpy as np


def dither_color(data):
    '''Substitutes in color, pixel by pixel, all the image using the Bayer matrix with multiple quantization levels'''
    o_data = np.zeros(data.shape)

    bayer = [
        [ 15, 135,  45, 165],
        [195,  75, 225, 105],
        [ 60, 180,  30, 150],
        [240, 120, 210,  90]
    ]

    bayer = np.array(bayer) / 255.0  # Normalize Bayer matrix to range [0, 1]

    quant_levels = [0, 85, 170, 255]
    num_levels = len(quant_levels)
    
    for x in range(data.shape[0]):
        for y in range(data.shape[1]):
            for color in range(data.shape[2]):
                threshold = bayer[x % len(bayer), y % len(bayer)]
                normalized_pixel_value = data[x, y, color] / 255.0  # Normalize pixel value to range [0, 1]
                
                # Determine the quantization level
                level_index = int(normalized_pixel_value * (num_levels - 1))
                
                if normalized_pixel_value > threshold:
                    level_index = min(level_index + 1, num_levels - 1)
                    
                o_data[x, y, color] = quant_levels[level_index]

    return o_data

def main():
    # filename = 'ez80/src/blender/crash/crashtex.png'
    filename = 'ez80/src/blender/earth.png'
    # filename = 'ez80/src/blender/LaraCroft/Lara.png'
    # filename = 'ez80/src/blender/colors64.64x64.png'

    # Read image 
    img = Image.open(filename).convert('RGB')

    # Transform img to array
    d_img = np.array(img)

    # Transform pixel by pixel
    d_new = dither_color(d_img)
    
    # New image based on dithered data
    img_new = Image.fromarray(d_new.astype(np.uint8))

    # Saves the new image
    o_name = filename.split('.')[0] + '.byr.png'
    img_new.save(o_name)
    print(f"Dithered image saved as {o_name}")

if __name__ == '__main__':
    main()
