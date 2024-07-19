import pygame
import math

# Initialize Pygame
pygame.init()

# Screen settings
screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption('Flight Simulator')

# Font settings
font = pygame.font.SysFont(None, 36)

# Flight parameters
altitude = 10000  # in feet
airspeed = 250    # in knots
roll = 0          # in degrees
pitch = 0         # in degrees
yaw = 0           # in degrees
throttle = 0      # in percentage (0 to 100)

# Control sensitivities
pitch_sensitivity = 1
roll_sensitivity = 1
yaw_sensitivity = 1
throttle_sensitivity = 5

# Main loop
running = True
clock = pygame.time.Clock()
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Key presses
    keys = pygame.key.get_pressed()
    if keys[pygame.K_DOWN]:
        pitch += pitch_sensitivity
    if keys[pygame.K_UP]:
        pitch -= pitch_sensitivity
    if keys[pygame.K_LEFT]:
        roll -= roll_sensitivity
    if keys[pygame.K_RIGHT]:
        roll += roll_sensitivity
    if keys[pygame.K_a]:
        yaw -= yaw_sensitivity
    if keys[pygame.K_d]:
        yaw += yaw_sensitivity
    if keys[pygame.K_w]:
        throttle = min(throttle + throttle_sensitivity, 100)
    if keys[pygame.K_s]:
        throttle = max(throttle - throttle_sensitivity, 0)

    # Update airspeed and altitude
    airspeed = throttle * 3  # Simplified: airspeed proportional to throttle
    altitude += pitch * 0.1  # Simplified: pitch affects altitude

    # Clear screen
    screen.fill((0, 0, 0))

    # Render text
    text = font.render(f'Altitude: {altitude:.2f} ft', True, (255, 255, 255))
    screen.blit(text, (20, 20))

    text = font.render(f'Airspeed: {airspeed:.2f} knots', True, (255, 255, 255))
    screen.blit(text, (20, 60))

    text = font.render(f'Roll: {roll:.2f} degrees', True, (255, 255, 255))
    screen.blit(text, (20, 100))

    text = font.render(f'Pitch: {pitch:.2f} degrees', True, (255, 255, 255))
    screen.blit(text, (20, 140))

    text = font.render(f'Yaw: {yaw:.2f} degrees', True, (255, 255, 255))
    screen.blit(text, (20, 180))

    text = font.render(f'Throttle: {throttle:.2f} %', True, (255, 255, 255))
    screen.blit(text, (20, 220))

    # Update display
    pygame.display.flip()

    # Cap the frame rate
    clock.tick(30)

pygame.quit()
