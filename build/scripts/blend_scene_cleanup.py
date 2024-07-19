import bpy
import math
#from PIL import Image
#import os

# Comprehensive scene cleanup
def full_scene_cleanup():
# Loop over Blender's data collections and remove items
    for collection in [bpy.data.meshes, 
        bpy.data.lights, bpy.data.cameras,
        bpy.data.materials, bpy.data.textures, bpy.data.curves, 
        bpy.data.metaballs, bpy.data.armatures, bpy.data.grease_pencils, 
        bpy.data.lattices, bpy.data.libraries, bpy.data.lightprobes, 
        bpy.data.linestyles, bpy.data.masks, bpy.data.node_groups, 
        bpy.data.particles, bpy.data.sounds, bpy.data.speakers, 
        bpy.data.volumes, bpy.data.worlds]:
        for item in collection:
            collection.remove(item)

# Call the cleanup function
full_scene_cleanup()

# Scene setup
scene = bpy.context.scene

# Adjust the scene's render resolution
bpy.context.scene.render.resolution_x = 320
bpy.context.scene.render.resolution_y = 160
bpy.context.scene.render.resolution_percentage = 100

# Set render engine to Workbench
bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'

# Disable anti-aliasing
bpy.context.scene.display.render_aa = 'OFF'
bpy.context.scene.display.viewport_aa = 'OFF'

# Create camera
bpy.ops.object.camera_add(location=(0, -4, 0))
camera = bpy.context.object
camera.data.type = 'PERSP'
camera.data.sensor_width = 35  # Sensor width 35mm
camera.data.angle = math.radians(90)  # 90 degrees FOV
camera.rotation_euler[0] = math.radians(90)  # Point camera along the positive Y-axis
camera.name = 'MyCamera'

## Ensure camera is active
#bpy.context.view_layer.objects.active = camera
#bpy.context.scene.camera = camera