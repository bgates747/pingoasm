"""Build a clean rigid-part Lara rig driven by the Namco running capture."""

import math
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector


EXPERIMENT_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = EXPERIMENT_DIR / "source"
RUN_OUTPUT = EXPERIMENT_DIR / "output" / "lara_running_normal_001.blend"
REST_OUTPUT = EXPERIMENT_DIR / "output" / "lara_rest.blend"
LARA_SCALE = 0.16

# The capture opens during a left-foot contact and returns to the same gait
# phase at frame 24.  A cyclic table therefore stores the 23 unique samples
# 1..23; frame 24 is retained only as a non-exported seam witness.  The local
# pose correction below begins after the portion the user selected as the
# preferred opening and reaches exact pose/first-difference constraints at
# frames 23 and 24.
LOOP_FRAME_START = 1
LOOP_FRAME_END = 23
LOOP_SUCCESSOR_FRAME = 24
LOOP_CLOSURE_START = 15
ROOT_FORWARD_LOCATION_AXIS = 2
LOOP_EPSILON = 1.0e-5

MOTION_MAP = {
    "pelvis": "Hips",
    "torso": "Chest",
    "head": "Head",
    "arm.l": "UpperArm_L",
    "forearm.l": "LowerArm_L",
    "hand.l": "Hand_L",
    "arm.r": "UpperArm_R",
    "forearm.r": "LowerArm_R",
    "hand.r": "Hand_R",
    "thigh.l": "UpperLeg_L",
    "leg.l": "LowerLeg_L",
    "foot.l": "Foot_L",
    "thigh.r": "UpperLeg_R",
    "leg.r": "LowerLeg_R",
    "foot.r": "Foot_R",
}

BONES = {
    "pelvis": (None, (0, 0, 0), (0, 0, 0.6)),
    "torso": ("pelvis", (0, 0, 0.6), (0, 0, 2.0)),
    "head": ("torso", (0, 0, 2.0), (0, 0, 2.7)),
    "arm.l": ("torso", (-0.6, 0, 2.0), (-0.7, 0, 0.9)),
    "forearm.l": ("arm.l", (-0.7, 0, 0.9), (-0.7, 0, -0.2)),
    "hand.l": ("forearm.l", (-0.7, 0, -0.2), (-0.63, 0, -0.5)),
    "arm.r": ("torso", (0.6, 0, 2.0), (0.7, 0, 0.9)),
    "forearm.r": ("arm.r", (0.7, 0, 0.9), (0.7, 0, -0.2)),
    "hand.r": ("forearm.r", (0.7, 0, -0.2), (0.63, 0, -0.5)),
    "thigh.l": ("pelvis", (-0.4, 0, -0.4), (-0.3, 0, -2.1)),
    "leg.l": ("thigh.l", (-0.3, 0, -2.1), (-0.3, 0, -4.0)),
    "foot.l": ("leg.l", (-0.3, 0, -4.0), (-0.3, 0.8, -4.4)),
    "thigh.r": ("pelvis", (0.4, 0, -0.4), (0.3, 0, -2.1)),
    "leg.r": ("thigh.r", (0.3, 0, -2.1), (0.3, 0, -4.0)),
    "foot.r": ("leg.r", (0.3, 0, -4.0), (0.3, 0.8, -4.4)),
}

# Rigid render parts do not map one-to-one with animation bones. This asset has
# small hand islands resting against the thighs plus two longer hip-holster
# islands in almost the same location. Drive the hands from their animation
# bones and both holsters from the pelvis.
PART_BONE_MAP = {
    "pelvis": "pelvis",
    "torso": "torso",
    "head": "head",
    "arm.l": "arm.l",
    "forearm.l": "forearm.l",
    "hand.l": "hand.l",
    "holster.l": "pelvis",
    "arm.r": "arm.r",
    "forearm.r": "forearm.r",
    "hand.r": "hand.r",
    "holster.r": "pelvis",
    "thigh.l": "thigh.l",
    "leg.l": "leg.l",
    "foot.l": "foot.l",
    "thigh.r": "thigh.r",
    "leg.r": "leg.r",
    "foot.r": "foot.r",
}

# The OBJ's left hand island is quarter-turned relative to its right-side
# counterpart and to the otherwise consistent character bind pose. Apply this
# after the common OBJ Y-up to Blender Z-up conversion. The origin is the model
# origin, so this corrects orientation and placement.
REST_PART_ROTATIONS = {
    "hand.l": (-math.pi / 2, 0, 0),
}

# Evaluated BVH matrices preserve the motion cleanly, but several source bones
# use the opposite local-Y basis from Lara's corresponding rigid part. Without
# these explicit conversions, the pelvis faces backward and foot.r presents
# its lace faces downward at ground contact. Chest and Head use a quarter-turn
# roll convention around that same longitudinal axis.
MOTION_BASIS_ROTATIONS = {
    "pelvis": Matrix.Rotation(math.pi, 4, "Y"),
    "torso": Matrix.Rotation(math.pi / 2, 4, "Y"),
    "head": Matrix.Rotation(math.pi / 2, 4, "Y"),
    "foot.r": Matrix.Rotation(math.pi, 4, "Y"),
}


def bounds(obj):
    return (
        Vector(tuple(min(c[i] for c in obj.bound_box) for i in range(3))),
        Vector(tuple(max(c[i] for c in obj.bound_box) for i in range(3))),
    )


def classify_island(obj):
    low, high = bounds(obj)
    center = (low + high) * 0.5
    vertex_count = len(obj.data.vertices)
    if vertex_count == 46:
        return "head"
    if low.y > 1.8:
        return "torso"
    if high.y > 2.0 and abs(center.x) < 0.4:
        return "torso"
    if low.y > 0.8:
        return "arm.l" if center.x < 0 else "arm.r"
    if high.y > 0.8 and low.y < 0:
        return "forearm.l" if center.x < 0 else "forearm.r"
    if vertex_count == 8 and high.y < 0.1:
        # Hands and holsters overlap in the arms-down source pose. The hands
        # are the shorter, more medial cuboids; holsters are longer and farther
        # outboard. Their raw vertical spans are about 0.51 and 0.94 units.
        kind = "hand" if high.y - low.y < 0.7 else "holster"
        side = "l" if center.x < 0 else "r"
        return f"{kind}.{side}"
    if low.y < -4.4:
        return "foot.l" if center.x < 0 else "foot.r"
    if low.y < -3.9:
        return "leg.l" if center.x < 0 else "leg.r"
    if low.y < -1.0:
        return "thigh.l" if center.x < 0 else "thigh.r"
    if low.x < -0.45 and high.x < 0:
        return "thigh.l"
    if high.x > 0.45 and low.x > 0:
        return "thigh.r"
    return "pelvis"


def import_and_segment_lara():
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=str(SOURCE_DIR / "LaraCroft.obj"))
    imported = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
    if len(imported) != 1:
        raise RuntimeError(f"Expected one imported Lara mesh, found {len(imported)}")
    source = imported[0]
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    islands = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if len(islands) != 18:
        raise RuntimeError(f"Expected 18 Lara mesh islands, found {len(islands)}")

    groups = {}
    for obj in islands:
        groups.setdefault(classify_island(obj), []).append(obj)
    if set(groups) != set(PART_BONE_MAP) or any(not values for values in groups.values()):
        raise RuntimeError(f"Unexpected Lara segmentation: {sorted((k, len(v)) for k, v in groups.items())}")

    parts = {}
    for name, objects in groups.items():
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        if len(objects) > 1:
            bpy.ops.object.join()
        part = bpy.context.object
        part.name = name
        part.data.name = f"lara_{name}"
        parts[name] = part

    for part in parts.values():
        part.rotation_euler = (math.pi / 2, 0, 0)
        part.scale = (LARA_SCALE,) * 3
        bpy.context.view_layer.objects.active = part
        part.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        part.select_set(False)
    for name, rotation in REST_PART_ROTATIONS.items():
        part = parts[name]
        part.rotation_euler = rotation
        bpy.context.view_layer.objects.active = part
        part.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        part.select_set(False)
    return parts


def create_target_armature():
    data = bpy.data.armatures.new("Lara_Rigid_Rig")
    rig = bpy.data.objects.new("Lara_Rigid_Rig", data)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (parent_name, head, tail) in BONES.items():
        bone = data.edit_bones.new(name)
        bone.head = Vector(head) * LARA_SCALE
        bone.tail = Vector(tail) * LARA_SCALE
        if parent_name:
            bone.parent = data.edit_bones[parent_name]
            bone.use_connect = (bone.head - bone.parent.tail).length < 1e-6
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.show_in_front = True
    data.display_type = "OCTAHEDRAL"
    return rig


def parent_parts(parts, rig):
    rest_matrices = {}
    for name, obj in parts.items():
        rest_matrices[name] = obj.matrix_world.copy()
        obj["driven_by_bone"] = PART_BONE_MAP[name]
        obj.rotation_mode = "QUATERNION"
    return rest_matrices


def configure_rest_pose_scene(parts, rig):
    """Configure the current file as the unanimated mapping point of truth."""
    scene = bpy.context.scene
    scene.name = "REST_POSE"
    scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version >= (4, 2, 0) else "BLENDER_EEVEE"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.world = bpy.data.worlds.new("Rest_Pose_World")
    scene.world.color = (0.035, 0.035, 0.035)
    scene["purpose"] = "Unanimated reference for verifying rigid mesh-to-bone mapping"

    rig.name = "REST_Lara_Rigid_Rig"
    rig.data.name = "REST_Lara_Rigid_Rig"
    rig.data.pose_position = "REST"
    rig.show_in_front = True
    rig.show_name = True
    rig.data.display_type = "STICK"
    rig.data.show_names = True
    rig.data.show_axes = True

    for name, obj in parts.items():
        world_matrix = obj.matrix_world.copy()
        obj.name = f"REST_{name}"
        bone_name = PART_BONE_MAP[name]
        obj["driven_by_bone"] = bone_name
        obj.parent = rig
        obj.parent_type = "BONE"
        obj.parent_bone = bone_name
        obj.matrix_world = world_matrix

    camera_data = bpy.data.cameras.new("REST_Camera")
    camera = bpy.data.objects.new("REST_Camera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.lens = 58
    look = Vector((0, 0, -0.12))
    camera.location = (2.7, -4.8, 1.25)
    camera.rotation_euler = (look - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    return scene


def build_rest_file():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    parts = import_and_segment_lara()
    rig = create_target_armature()
    parent_parts(parts, rig)
    scene = configure_rest_pose_scene(parts, rig)
    scene.frame_start = 1
    scene.frame_end = 1
    scene.frame_set(1)
    REST_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(REST_OUTPUT))
    return len(parts)


def bake_rigid_parts(parts, rest_matrices, rig, frame_start, frame_end):
    scene = bpy.context.scene
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        for name, obj in parts.items():
            bone_name = PART_BONE_MAP[name]
            rest_bone = rig.data.bones[bone_name]
            pose_bone = rig.pose.bones[bone_name]
            obj.matrix_world = (
                rig.matrix_world
                @ pose_bone.matrix
                @ rest_bone.matrix_local.inverted()
                @ rest_matrices[name]
            )
            obj.keyframe_insert("location", frame=frame, group=name)
            obj.keyframe_insert("rotation_quaternion", frame=frame, group=name)
            obj.keyframe_insert("scale", frame=frame, group=name)


def import_motion():
    bpy.ops.import_anim.bvh(
        filepath=str(SOURCE_DIR / "dataset-2_run_normal_001.bvh"),
        target="ARMATURE",
        global_scale=0.01,
        frame_start=1,
        use_fps_scale=False,
        use_cyclic=False,
        rotate_mode="NATIVE",
        axis_forward="-Z",
        axis_up="Y",
    )
    source = bpy.context.object
    source.name = "Namco_Run_Source"
    return source


def rotation_only(matrix):
    return matrix.to_quaternion().to_matrix().to_4x4()


def retarget(source, target, frame_start, frame_end):
    scene = bpy.context.scene
    scene.frame_set(frame_start)
    source_origin = source.pose.bones["Hips"].head.copy()
    action = bpy.data.actions.new("Lara_Run_Normal_001_First_Stride_Loop")
    target.animation_data_create()
    target.animation_data.action = action
    for pose_bone in target.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"

    ordered_names = list(BONES)
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        for name in ordered_names:
            target_bone = target.data.bones[name]
            target_pose = target.pose.bones[name]
            source_pose = source.pose.bones[MOTION_MAP[name]]
            # This dataset's declared BVH rest hierarchy is not a useful
            # humanoid bind pose. Use each evaluated source bone's pose-space
            # frame directly, retaining Lara's own segment lengths below.
            desired_rotation = rotation_only(source_pose.matrix)
            desired_rotation @= MOTION_BASIS_ROTATIONS.get(name, Matrix.Identity(4))

            parent_name = BONES[name][0]
            if parent_name:
                parent_rest = target.data.bones[parent_name]
                parent_pose = target.pose.bones[parent_name]
                local_head = parent_rest.matrix_local.inverted() @ target_bone.head_local
                desired_head = parent_pose.matrix @ local_head
            else:
                root_delta = source_pose.head - source_origin
                desired_head = target_bone.head_local + root_delta

            target_pose.matrix = Matrix.Translation(desired_head) @ desired_rotation
            target_pose.keyframe_insert("location", frame=frame, group=name)
            target_pose.keyframe_insert("rotation_quaternion", frame=frame, group=name)
            target_pose.keyframe_insert("scale", frame=frame, group=name)
            # PoseBone.matrix is assigned in armature space, but Blender does
            # not immediately propagate that assignment through the evaluated
            # hierarchy. Force evaluation before solving the next child. This
            # is essential on the first frame, where otherwise children are
            # decomposed against stale rest-pose parents and snap into place
            # only on subsequent frames.
            bpy.context.view_layer.update()
    scene.frame_set(frame_start)
    return action


def normalized_quaternion(value):
    result = value.copy()
    result.normalize()
    return result


def shortest_exponential_map(value):
    """Return the shortest signed rotation vector for a unit quaternion."""

    result = normalized_quaternion(value)
    if result.w < 0.0:
        result.negate()
    return result.to_exponential_map()


def quaternion_from_exponential_map(value):
    angle = value.length
    if angle < 1.0e-12:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    return Quaternion(value / angle, angle)


def loop_correction_weights(frame):
    """Cubic local-pose correction weights for frames 16..24.

    With x = frame - 15, A and B have zero value and derivative at x=0,
    A(8)=1/B(8)=0, and A(9)=0/B(9)=1.  The resulting channel sequence is
    untouched through frame 15 and exactly meets the periodic predecessor and
    successor constraints at frames 23 and 24.
    """

    x = float(frame - LOOP_CLOSURE_START)
    previous_weight = x * x * (9.0 - x) / 64.0
    successor_weight = x * x * (x - 8.0) / 81.0
    return previous_weight, successor_weight


def sample_local_pose_channels(target, frames):
    scene = bpy.context.scene
    samples = {}
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        samples[frame] = {
            pose_bone.name: {
                "location": pose_bone.location.copy(),
                "rotation": normalized_quaternion(pose_bone.rotation_quaternion),
                "scale": pose_bone.scale.copy(),
            }
            for pose_bone in target.pose.bones
        }
    return samples


def rotation_difference_angle(left, right):
    delta = normalized_quaternion(left).conjugated() @ normalized_quaternion(right)
    return shortest_exponential_map(delta).length


def condition_first_stride_loop(target):
    """Make frames 1..23 a discrete-C1 cycle in local bone channels.

    Frame 24 is made cycle-equivalent to frame 1 while retaining only the
    pelvis's captured forward stride distance.  Frame 23 is made the periodic
    predecessor of frame 1, so its local location/rotation/scale increment to
    the virtual frame 24 equals the unmodified frame 1 -> 2 increment.  A
    cubic correction in local pose space distributes those endpoint changes
    across the eight-frame tail without touching frames 1..15.
    """

    frames = range(LOOP_FRAME_START, LOOP_SUCCESSOR_FRAME + 1)
    raw = sample_local_pose_channels(target, frames)
    corrections = {}

    for name in BONES:
        first = raw[LOOP_FRAME_START][name]
        second = raw[LOOP_FRAME_START + 1][name]
        raw_previous = raw[LOOP_FRAME_END][name]
        raw_successor = raw[LOOP_SUCCESSOR_FRAME][name]

        successor_location = first["location"].copy()
        if name == "pelvis":
            forward_delta = (
                raw_successor["location"][ROOT_FORWARD_LOCATION_AXIS]
                - first["location"][ROOT_FORWARD_LOCATION_AXIS]
            )
            successor_location[ROOT_FORWARD_LOCATION_AXIS] += forward_delta
        previous_location = successor_location - (
            second["location"] - first["location"]
        )

        first_rotation = first["rotation"]
        second_rotation = second["rotation"].copy()
        if first_rotation.dot(second_rotation) < 0.0:
            second_rotation.negate()
        initial_rotation_step = (
            first_rotation.conjugated() @ second_rotation
        ).normalized()
        if initial_rotation_step.w < 0.0:
            initial_rotation_step.negate()
        successor_rotation = first_rotation.copy()
        previous_rotation = normalized_quaternion(
            successor_rotation @ initial_rotation_step.conjugated()
        )

        successor_scale = first["scale"].copy()
        previous_scale = successor_scale - (second["scale"] - first["scale"])
        previous_rotation_correction = (
            raw_previous["rotation"].conjugated() @ previous_rotation
        ).normalized()
        successor_rotation_correction = (
            raw_successor["rotation"].conjugated() @ successor_rotation
        ).normalized()
        corrections[name] = {
            "previous_location": previous_location - raw_previous["location"],
            "successor_location": successor_location - raw_successor["location"],
            "previous_rotation": shortest_exponential_map(
                previous_rotation_correction
            ),
            "successor_rotation": shortest_exponential_map(
                successor_rotation_correction
            ),
            "previous_scale": previous_scale - raw_previous["scale"],
            "successor_scale": successor_scale - raw_successor["scale"],
        }

    prior_rotations = {
        name: raw[LOOP_CLOSURE_START][name]["rotation"].copy() for name in BONES
    }
    scene = bpy.context.scene
    for frame in range(LOOP_CLOSURE_START + 1, LOOP_SUCCESSOR_FRAME + 1):
        previous_weight, successor_weight = loop_correction_weights(frame)
        scene.frame_set(frame)
        for name in BONES:
            pose_bone = target.pose.bones[name]
            sample = raw[frame][name]
            correction = corrections[name]
            pose_bone.location = (
                sample["location"]
                + correction["previous_location"] * previous_weight
                + correction["successor_location"] * successor_weight
            )
            rotation_vector = (
                correction["previous_rotation"] * previous_weight
                + correction["successor_rotation"] * successor_weight
            )
            rotation = normalized_quaternion(
                sample["rotation"] @ quaternion_from_exponential_map(rotation_vector)
            )
            if prior_rotations[name].dot(rotation) < 0.0:
                rotation.negate()
            pose_bone.rotation_quaternion = rotation
            pose_bone.scale = (
                sample["scale"]
                + correction["previous_scale"] * previous_weight
                + correction["successor_scale"] * successor_weight
            )
            pose_bone.keyframe_insert("location", frame=frame, group=name)
            pose_bone.keyframe_insert("rotation_quaternion", frame=frame, group=name)
            pose_bone.keyframe_insert("scale", frame=frame, group=name)
            prior_rotations[name] = rotation.copy()
        bpy.context.view_layer.update()

    conditioned = sample_local_pose_channels(
        target,
        (LOOP_FRAME_START, LOOP_FRAME_START + 1, LOOP_FRAME_END, LOOP_SUCCESSOR_FRAME),
    )
    for name in BONES:
        first = conditioned[LOOP_FRAME_START][name]
        second = conditioned[LOOP_FRAME_START + 1][name]
        previous = conditioned[LOOP_FRAME_END][name]
        successor = conditioned[LOOP_SUCCESSOR_FRAME][name]
        if (
            (successor["location"] - previous["location"])
            - (second["location"] - first["location"])
        ).length > LOOP_EPSILON:
            raise RuntimeError(f"Loop location velocity did not close for {name}")
        first_step = first["rotation"].conjugated() @ second["rotation"]
        seam_step = previous["rotation"].conjugated() @ successor["rotation"]
        if rotation_difference_angle(first_step, seam_step) > LOOP_EPSILON:
            raise RuntimeError(f"Loop rotation velocity did not close for {name}")
        if (
            (successor["scale"] - previous["scale"])
            - (second["scale"] - first["scale"])
        ).length > LOOP_EPSILON:
            raise RuntimeError(f"Loop scale velocity did not close for {name}")

    scene["loop_frame_start"] = LOOP_FRAME_START
    scene["loop_frame_end"] = LOOP_FRAME_END
    scene["loop_successor_frame"] = LOOP_SUCCESSOR_FRAME
    scene["loop_closure_start"] = LOOP_CLOSURE_START
    scene["loop_closure_space"] = "pose-bone local quaternion/location/scale"
    scene["loop_closure_order"] = "discrete C1"
    scene.frame_set(LOOP_FRAME_START)


def make_stage(target, frame_start, frame_end):
    scene = bpy.context.scene
    ground_material = bpy.data.materials.new("Ground")
    ground_material.diffuse_color = (0.025, 0.035, 0.055, 1)
    bpy.ops.mesh.primitive_plane_add(size=18, location=(0, 0, -0.73))
    ground = bpy.context.object
    ground.name = "Ground"
    ground.data.materials.append(ground_material)

    bpy.ops.object.light_add(type="AREA", location=(2.5, -3.5, 5.0))
    bpy.context.object.data.energy = 900
    bpy.context.object.data.size = 4
    bpy.ops.object.light_add(type="AREA", location=(-3.0, 1.0, 3.0))
    bpy.context.object.data.energy = 500
    bpy.context.object.data.size = 3

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "Camera"
    camera.data.lens = 58
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        pelvis = target.pose.bones["pelvis"].head
        look = pelvis + Vector((0, 0, 0.15))
        camera.location = look + Vector((2.7, -4.8, 1.4))
        camera.rotation_euler = (look - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.keyframe_insert("location", frame=frame)
        camera.keyframe_insert("rotation_euler", frame=frame)
    scene.camera = camera


def configure_scene(frame_start, frame_end):
    scene = bpy.context.scene
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    scene.render.fps = 30
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version >= (4, 2, 0) else "BLENDER_EEVEE"
    scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.006, 0.01, 0.02)
    scene["motion_source"] = "source/dataset-2_run_normal_001.bvh"
    scene["character_source"] = "source/LaraCroft.obj"
    scene["retarget_method"] = (
        "evaluated source pose frames; local-bone loop closure; "
        "rigid absolute transforms"
    )


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    parts = import_and_segment_lara()
    target = create_target_armature()
    rest_matrices = parent_parts(parts, target)
    source = import_motion()
    source_action = source.animation_data.action
    source_frame_start = max(1, math.floor(source_action.frame_range[0]))
    source_frame_end = math.ceil(source_action.frame_range[1])
    if source_frame_start != LOOP_FRAME_START or source_frame_end < LOOP_SUCCESSOR_FRAME:
        raise RuntimeError(
            f"Motion source range {source_frame_start}..{source_frame_end} does not "
            f"contain loop frames {LOOP_FRAME_START}..{LOOP_SUCCESSOR_FRAME}"
        )
    configure_scene(LOOP_FRAME_START, LOOP_FRAME_END)
    bpy.context.scene["motion_source_frame_start"] = source_frame_start
    bpy.context.scene["motion_source_frame_end"] = source_frame_end
    retarget(source, target, LOOP_FRAME_START, LOOP_SUCCESSOR_FRAME)
    condition_first_stride_loop(target)
    # Frame 24 is deliberately baked for export-time seam validation but is
    # outside the playable 1..23 scene range and is never stored in the app.
    bake_rigid_parts(
        parts,
        rest_matrices,
        target,
        LOOP_FRAME_START,
        LOOP_SUCCESSOR_FRAME,
    )
    source.hide_render = True
    source.hide_viewport = True
    make_stage(target, LOOP_FRAME_START, LOOP_FRAME_END)
    bpy.context.scene.frame_set(LOOP_FRAME_START)
    bpy.context.scene.name = "RUNNING_NORMAL_001"
    RUN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(RUN_OUTPUT))
    part_count = build_rest_file()
    print(
        f"Built {RUN_OUTPUT} with {len(parts)} rigid parts and "
        f"{LOOP_FRAME_END - LOOP_FRAME_START + 1} unique loop frames plus "
        f"successor frame {LOOP_SUCCESSOR_FRAME} from the "
        f"{source_frame_end - source_frame_start + 1}-frame capture; built "
        f"{REST_OUTPUT} with {part_count} rest parts"
    )


if __name__ == "__main__":
    main()
