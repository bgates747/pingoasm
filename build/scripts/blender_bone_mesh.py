import bpy

# Name of the armature
armature_name = 'Armature'

# Get the armature object
armature = bpy.data.objects[armature_name]

# Get a list of all mesh objects
mesh_objects = [obj for obj in bpy.data.objects if obj.type == 'MESH']

# Save current mode
original_mode = bpy.context.object.mode

# Function to set the context for operations
def set_active_object(obj):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

# Iterate through mesh objects and parent them to corresponding bones
for mesh_obj in mesh_objects:
    bone_name = mesh_obj.name
    
    # Check if there is a bone with the same name as the mesh object
    if bone_name in armature.pose.bones:
        # Deselect all objects
        bpy.ops.object.select_all(action='DESELECT')
        
        # Set the mesh object as active and select it
        set_active_object(mesh_obj)
        
        # Set the armature as the active object and select it
        set_active_object(armature)
        
        # Enter Pose Mode
        bpy.ops.object.mode_set(mode='POSE')
        
        # Select the bone in Pose Mode
        bone = armature.pose.bones[bone_name]
        armature.data.bones.active = bone.bone
        
        # Enter Object Mode to set parent
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Parent the mesh to the bone
        bpy.ops.object.parent_set(type='BONE')
        
        print(f"Parented {mesh_obj.name} to {bone_name}")
    else:
        print(f"No corresponding bone found for {mesh_obj.name}")

# Return to the original mode
bpy.ops.object.mode_set(mode=original_mode)

print("Parenting complete!")
