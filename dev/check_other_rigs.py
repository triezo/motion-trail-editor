"""On a copy of a real scene: cost of a trail rebuild, and whether keying other rigs/bones outdates it.
blender -b --factory-startup <copy.blend> --python dev/check_other_rigs.py
"""
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

mte.register()
scene = bpy.context.scene
s = scene.motion_trail
s.items.clear()
rig = bpy.data.objects["BumBaby RIG.001"]
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='POSE')
it = s.items.add()
it.object = rig
it.bone = "hand_ik.R"
key = trails.item_key(rig, "hand_ik.R")


def timed(fn):
    t = time.perf_counter()
    fn()
    return round((time.perf_counter() - t) * 1000)


s.frames_before = s.frames_after = 0
full = timed(trails.rebuild)
s.frames_before = s.frames_after = 20
window = timed(trails.rebuild)
tr = trails.TRAILS[key]
print(f"CHECK rebuild whole range {trails.frame_range(scene)}: {full} ms; around the playhead "
      f"{(tr.frame_start, tr.frame_end)}: {window} ms")
print("CHECK deps of hand_ik.R:", {k: sorted(p)[:12] for k, (o, p) in trails.dependencies(rig, rig.pose.bones['hand_ik.R']).items()})

# Key another rig, and other bones of the same rig.
other = next(o for o in scene.objects if o.type == 'ARMATURE' and o != rig and o.animation_data and o.animation_data.action)
cur = scene.frame_current
for pb in list(other.pose.bones)[:5]:
    pb.keyframe_insert("rotation_quaternion" if pb.rotation_mode == 'QUATERNION' else "rotation_euler", frame=cur + 3)
outdated, _ = trails.outdated_trails(scene)
print(f"CHECK keyed 5 bones of another rig ({other.name}): trail outdated -> {key in outdated}")

related = {p for o, parts in trails.dependencies(rig, rig.pose.bones['hand_ik.R']).values() if o == rig for p in parts}
unrelated = [pb for pb in rig.pose.bones if pb.name not in related][:5]
for pb in unrelated:
    pb.keyframe_insert("location", frame=cur + 3)
outdated, _ = trails.outdated_trails(scene)
print(f"CHECK keyed {[p.name for p in unrelated]} on the same rig: trail outdated -> {key in outdated}")

rig.pose.bones["hand_ik.R"].keyframe_insert("location", frame=cur + 3)
outdated, _ = trails.outdated_trails(scene)
print(f"CHECK keyed hand_ik.R itself: trail outdated -> {key in outdated}")
sig = timed(lambda: trails.trail_signature(scene, rig, rig.pose.bones['hand_ik.R']))
print(f"CHECK one signature check: {sig} ms")
