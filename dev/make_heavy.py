"""Save a heavy test scene for profiling: blender -b --factory-startup --python dev/make_heavy.py"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402

mte.register()
rig, cube, body = testrig.build(frames=1200, dense=True)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='POSE')
for b in rig.pose.bones:
    b.select = b.name == "hand_ik"
item = bpy.context.scene.motion_trail.items.add()
item.object = rig
item.bone = "hand_ik"
bpy.context.scene.frame_set(600)
out = os.path.join(HERE, "out", "prof", "heavy.blend")
bpy.ops.wm.save_as_mainfile(filepath=out)
print("saved", out)
