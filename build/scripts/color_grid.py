from PIL import Image, ImageDraw, ImageFont

# Define the grid size and image size
grid_size = 8
cell_size = 8  # Size of each cell
image_size = grid_size * cell_size

# Colors for each number from 1 to 9
colors = [
    (0, 0, 0), # 0 Black
    (170, 0, 0), # 1 Dark red
    (0, 170, 0), # 2 Dark green
    (170, 170, 0), # 3 Olive
    (0, 0, 170), # 4 Dark blue
    (170, 0, 170), # 5 Dark magenta
    (0, 170, 170), # 6 Teal
    (170, 170, 170), # 7 Light gray
    (85, 85, 85), # 8 Gray
    (255, 0, 0), # 9 Red
    (0, 255, 0), # 10 Lime
    (255, 255, 0), # 11 Yellow
    (0, 0, 255), # 12 Blue
    (255, 0, 255), # 13 Magenta
    (0, 255, 255), # 14 Aqua
    (255, 255, 255), # 15 White
    (0, 0, 85), # 16 Navy (darkest blue)
    (0, 85, 0), # 17 Dark olive green
    (0, 85, 85), # 18 Darker teal
    (0, 85, 170), # 19 Azure
    (0, 85, 255), # 20 Lighter azure
    (0, 170, 85), # 21 Spring green
    (0, 170, 255), # 22 Sky blue
    (0, 255, 85), # 23 Light spring green
    (0, 255, 170), # 24 Medium spring green
    (85, 0, 0), # 25 Maroon
    (85, 0, 85), # 26 Violet
    (85, 0, 170), # 27 Indigo
    (85, 0, 255), # 28 Electric indigo
    (85, 85, 0), # 29 Dark khaki
    (85, 85, 170), # 30 Slate blue
    (85, 85, 255), # 31 Light slate blue
    (85, 170, 0), # 32 Chartreuse
    (85, 170, 85), # 33 Medium sea green
    (85, 170, 170), # 34 Light sea green
    (85, 170, 255), # 35 Deep sky blue
    (85, 255, 0), # 36 Lawn green
    (85, 255, 85), # 37 Light green
    (85, 255, 170), # 38 Pale green
    (85, 255, 255), # 39 Pale turquoise
    (170, 0, 85), # 40 Medium violet
    (170, 0, 255), # 41 Medium blue
    (170, 85, 0), # 42 Golden brown
    (170, 85, 85), # 43 Rosy brown
    (170, 85, 170), # 44 Medium orchid
    (170, 85, 255), # 45 Medium purple
    (170, 170, 85), # 46 Tan
    (170, 170, 255), # 47 Light steel blue
    (170, 255, 0), # 48 Bright green
    (170, 255, 85), # 49 Pale lime green
    (170, 255, 170), # 50 Pale light green
    (170, 255, 255), # 51 Light cyan
    (255, 0, 85), # 52 Hot pink
    (255, 0, 170), # 53 Deep pink
    (255, 85, 0), # 54 Dark orange
    (255, 85, 85), # 55 Salmon
    (255, 85, 170), # 56 Orchid
    (255, 85, 255), # 57 Bright magenta
    (255, 170, 0), # 58 Orange
    (255, 170, 85), # 59 Light salmon
    (255, 170, 170), # 60 Light pink
    (255, 170, 255), # 61 Lavender pink
    (255, 255, 85), # 62 Pale yellow
    (255, 255, 170) # 63 Light yellow     
]

# Create a new image with a white background
image = Image.new('RGB', (image_size, image_size), (255, 255, 255))
draw = ImageDraw.Draw(image)

# Define font for drawing numbers
# Update this to the correct path for a TTF font on your system
font_path = "/Library/Fonts/Arial.ttf"
font = ImageFont.truetype(font_path, 16)

# Draw the grid with numbers and colors
for i in range(grid_size):
    for j in range(grid_size):
        # Calculate the position and number for the cell
        x = j * cell_size
        y = i * cell_size
        number = (i * grid_size + j) + 1
        
        # Draw the cell background color
        color = colors[number - 1]
        draw.rectangle([x, y, x + cell_size, y + cell_size], fill=color)
        
        # Draw the cell border
        # draw.rectangle([x, y, x + cell_size, y + cell_size], outline=(255, 255, 255))
        
        # # Draw the number in the center of the cell
        # text = str(number)
        # text_bbox = draw.textbbox((0, 0), text, font=font)
        # text_width = text_bbox[2] - text_bbox[0]
        # text_height = text_bbox[3] - text_bbox[1]
        # text_x = x + (cell_size - text_width) / 2
        # text_y = y + (cell_size - text_height) / 2
        # draw.text((text_x, text_y), text, fill=(255, 255, 255), font=font)

# Save the image as a PNG file
image.save('grid_image.png')

# Display the image (optional)
# image.show()
