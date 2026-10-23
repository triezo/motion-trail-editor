"""Onion skin cost on a heavy character (dense skinned mesh + subdivision) and many animated objects:
blender -b --factory-startup --python dev/profile_onion.py"""
import math
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import onion  # noqa: E402

mte.register()
rig, cube, body = testrig.build(frames=240, dense=True)
scene = bpy.context.scene
# 300 more animated objects (props, crowd...): every frame jump evaluates them, the snapshot reads them.
for i in range(300):
    ob = bpy.data.objects.new(f"Prop{i}", None)
    scene.collection.objects.link(ob)
    for f in (1, 60, 120, 180, 240):
        ob.location = (math.sin(i + f), math.cos(i * f), f * 0.01)
        ob.rotation_euler = (f * 0.01, i * 0.01, 0)
        ob.keyframe_insert("location", frame=f)
        ob.keyframe_insert("rotation_euler", frame=f)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='POSE')
nverts = len(body.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices)

t = time.perf_counter()
saved = onion.snapshot(scene)
snap_ms = (time.perf_counter() - t) * 1000

t = time.perf_counter()
scene.frame_set(scene.frame_current)
frame_ms = (time.perf_counter() - t) * 1000

s = scene.anim_tools
s.onion_before = s.onion_after = 2
scene.frame_set(100)
onion.enable(bpy.context, [body])
t = time.perf_counter()
onion.update(bpy.context)
first_ms = (time.perf_counter() - t) * 1000
scene.frame_set(110)  # step to the next key: the frames that are still wanted come from the cache
t = time.perf_counter()
onion.update(bpy.context)
step_ms = (time.perf_counter() - t) * 1000
t = time.perf_counter()
onion.build_mask(bpy.context)
mask_ms = (time.perf_counter() - t) * 1000
print("ONION", {"verts": nverts, "channels": len(saved), "snapshot_ms": round(snap_ms, 1),
                "one_frame_ms": round(frame_ms, 1), "first_update_ms (4 frames)": round(first_ms, 1),
                "next_update_ms": round(step_ms, 1), "mask_ms": round(mask_ms, 1),
                "shown": onion.state.shown}, flush=True)

import numpy as np  # noqa: E402
from motion_trail_editor import ghosts  # noqa: E402
dg = bpy.context.evaluated_depsgraph_get()
t = time.perf_counter()
ghosts._mesh_arrays(body, dg)
a_ms = (time.perf_counter() - t) * 1000
t = time.perf_counter()
ob_eval = body.evaluated_get(dg)
me = ob_eval.data
nv, nt = len(me.vertices), len(me.loop_triangles)
co = np.empty(nv * 3, dtype=np.float32)
me.vertices.foreach_get("co", co)
tris = np.empty(nt * 3, dtype=np.int32)
me.loop_triangles.foreach_get("vertices", tris)
mat = np.array(ob_eval.matrix_world, dtype=np.float32)
co = co.reshape(-1, 3) @ mat[:3, :3].T + mat[:3, 3]
b_ms = (time.perf_counter() - t) * 1000
t = time.perf_counter()
scene.frame_set(150)
f_ms = (time.perf_counter() - t) * 1000
print("EXTRACT", {"to_mesh+normals_ms": round(a_ms, 1), "eval_data_no_normals_ms": round(b_ms, 1), "tris": nt,
                  "frame_jump_ms": round(f_ms, 1)}, flush=True)
