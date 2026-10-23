"""Build a deterministic test scene: animated root, IK arm, IK hand control, dense skinned mesh."""
import math
import bpy


def build(frames=120, dense=True):
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)

    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, frames
    scene.frame_set(1)

    arm_data = bpy.data.armatures.new("TestRig")
    rig = bpy.data.objects.new("TestRig", arm_data)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones
    root = eb.new("root"); root.head = (0, 0, 0); root.tail = (0, 1, 0)
    upper = eb.new("upper_arm"); upper.head = (0, 0, 1.5); upper.tail = (0.5, 0, 1.5); upper.parent = root
    fore = eb.new("forearm"); fore.head = (0.5, 0, 1.5); fore.tail = (1.0, 0, 1.45); fore.parent = upper
    fore.use_connect = True
    hand = eb.new("hand_ik"); hand.head = (1.0, 0, 1.45); hand.tail = (1.0, 0, 1.6); hand.parent = root
    # Controls whose `location` does not map through the plain pose matrix.
    tilted = eb.new("ctrl_options"); tilted.head = (-1.0, 0, 1.0); tilted.tail = (-1.0, 0.3, 1.3)
    tilted.parent = root
    tilted.roll = 0.7
    follow = eb.new("ctrl_childof"); follow.head = (0, -1.0, 1.0); follow.tail = (0, -1.0, 1.3)
    bpy.ops.object.mode_set(mode='POSE')

    options = arm_data.bones["ctrl_options"]
    options.use_inherit_rotation = False
    options.inherit_scale = 'NONE'
    options.use_local_location = False
    child_of = rig.pose.bones["ctrl_childof"].constraints.new('CHILD_OF')
    child_of.target = rig
    child_of.subtarget = "root"

    ik = rig.pose.bones["forearm"].constraints.new('IK')
    ik.target = rig
    ik.subtarget = "hand_ik"
    ik.chain_count = 2

    pb_root = rig.pose.bones["root"]
    pb_hand = rig.pose.bones["hand_ik"]
    pb_root.rotation_mode = 'XYZ'
    for f in range(1, frames + 1, 12):
        t = f / frames
        pb_root.location = (0.0, 0.0, 0.0)
        pb_root.rotation_euler = (0.0, 0.0, math.radians(90 * t))
        pb_root.keyframe_insert("rotation_euler", frame=f)
        pb_hand.location = (-0.3 * math.sin(t * 6), 0.4 * math.cos(t * 6) - 0.4, 0.2 * math.sin(t * 3))
        pb_hand.keyframe_insert("location", frame=f)
        for name in ("ctrl_options", "ctrl_childof"):
            pb = rig.pose.bones[name]
            pb.location = (0.2 * math.cos(t * 5), 0.3 * math.sin(t * 4), 0.1 * t)
            pb.keyframe_insert("location", frame=f)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Animated mesh object (object-level trail target), parented to nothing.
    bpy.ops.mesh.primitive_cube_add(size=0.3, location=(3, 0, 0))
    cube = bpy.context.active_object
    cube.name = "TestCube"
    for f in range(1, frames + 1, 20):
        cube.location = (3 + math.sin(f / 10), math.cos(f / 10), f / frames)
        cube.keyframe_insert("location", frame=f)

    body = None
    if dense:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=256, ring_count=128, radius=0.5, location=(0, 0, 1))
        body = bpy.context.active_object
        body.name = "DenseBody"
        mod = body.modifiers.new("Armature", 'ARMATURE')
        mod.object = rig
        vg = body.vertex_groups.new(name="upper_arm")
        vg.add(range(len(body.data.vertices)), 1.0, 'REPLACE')
        body.modifiers.new("Subsurf", 'SUBSURF').levels = 1

    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    scene.frame_set(1)
    return rig, cube, body
