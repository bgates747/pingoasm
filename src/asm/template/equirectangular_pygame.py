import pygame
import numpy as np
import math

# Initialize pygame
pygame.init()

# Set up the display
screen_width, screen_height = 600, 300
screen = pygame.display.set_mode((screen_width, screen_height))
pygame.display.set_caption('Equirectangular Visualizer')

# Load the equirectangular texture
texture = pygame.image.load('src/blender/middle_harbor_drone.png')
texture_width, texture_height = texture.get_size()

# Initial camera angles
yaw = 0.0
pitch = 0.0

def spherical_to_uv(yaw, pitch):
    # Adjust the yaw by 90 degrees (π/2) to correct the phase issue
    u = ((yaw + math.pi / 2) + math.pi) / (2 * math.pi)
    v = (pitch + math.pi / 2) / math.pi
    return u, v

def draw_frame():
    for y in range(screen_height):
        for x in range(screen_width):
            # Convert screen coordinates to normalized device coordinates
            nx = (x / screen_width) * 2 - 1
            ny = (y / screen_height) * 2 - 1

            # Calculate the spherical coordinates (yaw and pitch)
            phi = math.atan2(nx, 1)
            theta = math.atan2(ny, 1)

            # Adjust for camera yaw and pitch
            adj_yaw = yaw + phi
            adj_pitch = pitch + theta

            # Clamp pitch to prevent flipping
            adj_pitch = np.clip(adj_pitch, -math.pi/2, math.pi/2)

            # Convert spherical coordinates to texture coordinates
            u, v = spherical_to_uv(adj_yaw, adj_pitch)

            # Map to texture coordinates
            tex_x = int(u * texture_width) % texture_width
            tex_y = int(v * texture_height) % texture_height

            # Get the pixel color from the texture
            color = texture.get_at((tex_x, tex_y))

            # Draw the pixel to the screen
            screen.set_at((x, y), color)

    pygame.display.flip()


# Main loop
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Check key presses for panning and pitching
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]:
        yaw -= math.radians(5)
    if keys[pygame.K_RIGHT]:
        yaw += math.radians(5)
    if keys[pygame.K_UP]:
        pitch += math.radians(5)
    if keys[pygame.K_DOWN]:
        pitch -= math.radians(5)

    # Ensure yaw wraps around
    yaw %= 2 * math.pi

    # Draw the current frame
    draw_frame()

# Clean up
pygame.quit()
