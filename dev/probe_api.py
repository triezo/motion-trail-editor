"""Probe Blender APIs needed by the addon. Run: blender -b --factory-startup --python dev/probe_api.py"""
import time
import addon_utils
import bpy
import gpu

out = {}

# GPU built-in shaders available in this version.
names = ["UNIFORM_COLOR", "FLAT_COLOR", "SMOOTH_COLOR", "POLYLINE_SMOOTH_COLOR", "POLYLINE_FLAT_COLOR",
         "POLYLINE_UNIFORM_COLOR", "POINT_FLAT_COLOR", "POINT_UNIFORM_COLOR"]
ok = []
for n in names:
    try:
        gpu.shader.from_builtin(n)
        ok.append(n)
    except Exception as e:  # background mode may not have a GPU backend
        ok.append(f"{n}: {e}")
out["shaders"] = ok

# Default keymap conflicts for Alt+M.
kc = bpy.context.window_manager.keyconfigs.default
conf = []
for km in kc.keymaps:
    for kmi in km.keymap_items:
        if kmi.type == 'M' and kmi.alt and not kmi.ctrl and not kmi.shift:
            conf.append(f"{km.name}: {kmi.idname}")
out["alt_m"] = conf

# Channelbag F-Curve collection API.
out["channelbag_fcurves_funcs"] = [f.identifier for f in bpy.types.ActionChannelbagFCurves.bl_rna.functions]
out["motionpath_props"] = [p.identifier for p in bpy.types.MotionPath.bl_rna.properties]
out["animviz_mp_props"] = [p.identifier for p in bpy.types.AnimVizMotionPaths.bl_rna.properties]

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import testrig

rig, cube, body = testrig.build()
scene = bpy.context.scene
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='POSE')
hand = rig.pose.bones["forearm"]  # IK-driven bone: path must include IK + animated root
for b in rig.pose.bones:
    b.select = False
hand.select = True
rig.data.bones.active = hand.bone


def eval_frame_set():
    pts = []
    t = time.perf_counter()
    cur = scene.frame_current
    for f in range(1, 121):
        scene.frame_set(f)
        pts.append((rig.matrix_world @ hand.head).copy())
    scene.frame_set(cur)
    return pts, time.perf_counter() - t


def eval_paths():
    t = time.perf_counter()
    mp = rig.pose.animation_visualization.motion_path
    mp.type = 'RANGE'
    mp.frame_start, mp.frame_end = 1, 120
    with bpy.context.temp_override(active_object=rig, object=rig, selected_pose_bones=[hand],
                                   selected_pose_bones_from_active_object=[hand]):
        bpy.ops.pose.paths_calculate('EXEC_DEFAULT', False, display_type='RANGE', range='MANUAL',
                                     bake_location='HEADS')
    path = hand.motion_path
    pts = [p.co.copy() for p in path.points] if path else []
    info = (path.frame_start, path.frame_end, len(pts)) if path else None
    with bpy.context.temp_override(active_object=rig, object=rig, selected_pose_bones=[hand],
                                   selected_pose_bones_from_active_object=[hand]):
        bpy.ops.pose.paths_clear('EXEC_DEFAULT', False, only_selected=True)
    other_paths = [b.name for b in rig.pose.bones if b.motion_path]
    return pts, time.perf_counter() - t, info, other_paths


try:
    p_paths, t_paths, info, others = eval_paths()
    out["paths"] = {"time": round(t_paths, 3), "info": info, "other_bones_with_paths": others[:5],
                    "cleared": hand.motion_path is None}
except Exception as e:
    import traceback
    out["paths_err"] = traceback.format_exc()
    p_paths = []

p_fs, t_fs = eval_frame_set()
out["frame_set_time"] = round(t_fs, 3)
if p_paths:
    out["max_diff"] = max((a - b).length for a, b in zip(p_paths, p_fs))
out["undo_steps_note"] = "background: n/a"

for k, v in out.items():
    print(f"PROBE {k}: {v}")
