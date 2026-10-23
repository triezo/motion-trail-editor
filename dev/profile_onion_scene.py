"""Onion skin cost on a real scene (run on a COPY): blender -b <copy.blend> --python dev/profile_onion_scene.py"""
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import common, onion  # noqa: E402

mte.register()
scene = bpy.context.scene
view_layer = bpy.context.view_layer

# The rig that deforms the most vertices (the main character).
best = None
for rig in (ob for ob in view_layer.objects if ob.type == 'ARMATURE' and ob.animation_data and ob.animation_data.action):
    meshes = [ob for ob in view_layer.objects if ob.type == 'MESH' and ob.visible_get() and common._deformed_by(ob, {rig})]
    verts = sum(len(m.data.vertices) for m in meshes)
    if meshes and (best is None or verts > best[2]):
        best = (rig, meshes, verts)
rig, meshes, verts = best
animated = sum(1 for ob in scene.objects if ob.animation_data and ob.animation_data.action)

t = time.perf_counter()
saved = onion.snapshot(scene)
snap_ms = (time.perf_counter() - t) * 1000
t = time.perf_counter()
restored = onion.restore(saved)
restore_ms = (time.perf_counter() - t) * 1000

cur = scene.frame_current
t = time.perf_counter()
scene.frame_set(cur + 1)
scene.frame_set(cur)
jump_ms = (time.perf_counter() - t) * 1000 / 2

s = scene.anim_tools
s.onion_before = s.onion_after = 1
onion.enable(bpy.context, meshes)
t = time.perf_counter()
onion.update(bpy.context)
first_ms = (time.perf_counter() - t) * 1000
first = onion.state.shown
keys = sorted(onion.key_frames(meshes))
nxt = next((f for f in keys if f > cur), None)
step_ms = None
if nxt is not None:
    scene.frame_set(nxt)
    t = time.perf_counter()
    onion.update(bpy.context)
    step_ms = (time.perf_counter() - t) * 1000
t = time.perf_counter()
onion.build_mask(bpy.context, meshes)
mask_ms = (time.perf_counter() - t) * 1000
print("SCENE", {"rig": rig.name, "meshes": len(meshes), "verts": verts, "animated_objects": animated,
                "channels": len(saved), "snapshot_ms": round(snap_ms, 1), "restore_check_ms": round(restore_ms, 1),
                "restored": restored, "frame_jump_ms": round(jump_ms, 1), "first_update_ms (2 poses)": round(first_ms, 1),
                "step_update_ms": step_ms and round(step_ms, 1), "mask_ms": round(mask_ms, 1),
                "shown": (first, onion.state.shown)}, flush=True)
