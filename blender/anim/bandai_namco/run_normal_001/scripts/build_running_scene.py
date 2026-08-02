"""Build a viewable Blender scene from a Bandai Namco running BVH clip.

Run with Blender, not system Python. See README.md for examples.
"""

import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


EXPERIMENT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BVH = EXPERIMENT_DIR / "source" / "dataset-2_run_normal_001.bvh"


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bvh", type=Path, default=DEFAULT_BVH)
    parser.add_argument("--output", type=Path, default=EXPERIMENT_DIR / "output" / "running_normal_001.blend")
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(args)


def material(name, color, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return mat


def import_motion(path):
    if not path.is_file():
        raise FileNotFoundError(f"BVH clip not found: {path}")
    bpy.ops.import_anim.bvh(
        filepath=str(path),
        target="ARMATURE",
        global_scale=0.01,
        frame_start=1,
        use_fps_scale=False,
        use_cyclic=False,
        rotate_mode="NATIVE",
        axis_forward="-Z",
        axis_up="Y",
    )
    armature = bpy.context.object
    armature.name = "Mocap_Run"
    armature.data.name = "Mocap_Run_Skeleton"
    armature.show_in_front = True
    armature.data.display_type = "STICK"
    action = armature.animation_data.action
    action.name = "Run_Normal_001"
    return armature, action


def make_bone_proxy(armature, bone, mat):
    length = bone.length
    if length < 0.015 or bone.name == "joint_Root":
        return
    radius = max(0.018, min(0.055, length * 0.10))
    midpoint = (bone.head_local + bone.tail_local) * 0.5
    direction = bone.tail_local - bone.head_local
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=radius, depth=length, location=midpoint)
    obj = bpy.context.object
    obj.name = f"Proxy_{bone.name}"
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(direction.normalized())
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    obj.data.materials.append(mat)
    group = obj.vertex_groups.new(name=bone.name)
    group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
    modifier = obj.modifiers.new("Follow mocap", "ARMATURE")
    modifier.object = armature
    obj.parent = armature


def make_proxy(armature):
    proxy_mat = material("Runner orange", (1.0, 0.16, 0.025), metallic=0.05, roughness=0.32)
    for bone in armature.data.bones:
        make_bone_proxy(armature, bone, proxy_mat)
    head = armature.data.bones.get("Head")
    if head:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.115, location=head.tail_local)
        obj = bpy.context.object
        obj.name = "Proxy_Head"
        obj.data.materials.append(proxy_mat)
        group = obj.vertex_groups.new(name="Head")
        group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
        modifier = obj.modifiers.new("Follow mocap", "ARMATURE")
        modifier.object = armature
        obj.parent = armature


def evaluated_bounds(armature, frame):
    bpy.context.scene.frame_set(frame)
    points = [armature.matrix_world @ pose_bone.head for pose_bone in armature.pose.bones]
    return (
        Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points))),
        Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points))),
    )


def aim_camera(camera, target):
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def build_stage(armature, frame_start, frame_end):
    bounds = [evaluated_bounds(armature, frame) for frame in (frame_start, (frame_start + frame_end) // 2, frame_end)]
    low = Vector(tuple(min(item[0][axis] for item in bounds) for axis in range(3)))
    high = Vector(tuple(max(item[1][axis] for item in bounds) for axis in range(3)))
    center = (low + high) * 0.5
    extent = high - low

    ground_mat = material("Ground", (0.035, 0.045, 0.065), metallic=0.0, roughness=0.82)
    bpy.ops.mesh.primitive_plane_add(size=max(12.0, max(extent.x, extent.y) + 5.0), location=(center.x, center.y, low.z - 0.02))
    ground = bpy.context.object
    ground.name = "Ground"
    ground.data.materials.append(ground_mat)

    bpy.ops.object.light_add(type="AREA", location=(center.x - 3.0, center.y - 4.0, high.z + 5.0))
    key = bpy.context.object
    key.name = "Key_Light"
    key.data.energy = 1300
    key.data.shape = "DISK"
    key.data.size = 5.0

    bpy.ops.object.light_add(type="AREA", location=(center.x + 4.0, center.y + 2.0, high.z + 2.0))
    fill = bpy.context.object
    fill.name = "Fill_Light"
    fill.data.energy = 650
    fill.data.size = 4.0

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "Camera"
    camera.data.lens = 58
    body_extent = bounds[1][1] - bounds[1][0]
    distance = max(7.0, max(body_extent.x, body_extent.y, body_extent.z) * 3.8)
    offset = Vector((distance * 0.62, -distance, distance * 0.24))
    # Key the camera to the moving skeleton rather than framing the entire root
    # trajectory. This keeps the runner readable while preserving world motion.
    for frame in range(frame_start, frame_end + 1):
        frame_low, frame_high = evaluated_bounds(armature, frame)
        target = (frame_low + frame_high) * 0.5
        camera.location = target + offset
        aim_camera(camera, target)
        camera.keyframe_insert("location", frame=frame)
        camera.keyframe_insert("rotation_euler", frame=frame)
    bpy.context.scene.camera = camera


def configure_scene(action):
    scene = bpy.context.scene
    scene.frame_start = max(1, math.floor(action.frame_range[0]))
    scene.frame_end = math.ceil(action.frame_range[1])
    scene.render.fps = 30
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version >= (4, 2, 0) else "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "PNG"
    scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.008, 0.012, 0.025)
    scene.frame_set(scene.frame_start)
    return scene


def main():
    args = arguments()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature, action = import_motion(args.bvh.resolve())
    scene = configure_scene(action)
    make_proxy(armature)
    build_stage(armature, scene.frame_start, scene.frame_end)
    scene["motion_source"] = str(args.bvh.resolve())
    scene["motion_license"] = "CC BY-NC 4.0"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    print(f"Built {args.output.resolve()} ({scene.frame_start}-{scene.frame_end})")


if __name__ == "__main__":
    main()
