"""Profile the addon on a real scene (a copy):
blender -b <copy.blend> --python dev/profile_scene.py
"""
import cProfile
import os
import pstats
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


def ms(fn, n=1):
    t = time.perf_counter()
    for _ in range(n):
        out = fn()
    return (time.perf_counter() - t) / n * 1000, out


print("PROF file:", bpy.data.filepath, "frames:", trails.frame_range(scene), "cur:", scene.frame_current)
print("PROF objects:", [(o.name, o.type, o.mode) for o in scene.objects][:20])
print("PROF saved trail items:", [(it.object.name if it.object else None, it.bone) for it in s.items])

if not s.items:
    ob = bpy.context.active_object
    if ob and ob.type == 'ARMATURE' and ob.mode == 'POSE':
        for pb in ob.pose.bones:
            if pb.select:
                it = s.items.add(); it.object = ob; it.bone = pb.name
    elif ob:
        it = s.items.add(); it.object = ob
    print("PROF added items:", [(it.object.name, it.bone) for it in s.items])

t_rebuild, _ = ms(trails.rebuild, 3)
print(f"PROF rebuild (all): {t_rebuild:.1f} ms")
for key, tr in trails.TRAILS.items():
    print("PROF trail", key, "frames", tr.frame_start, tr.frame_end, "keys", len(tr.keys))
t_sig, _ = ms(lambda: [trails.trail_signature(scene, ob, pb) for _k, ob, pb in trails.iter_items(scene)], 5)
print(f"PROF trail signatures: {t_sig:.1f} ms")
n_fc = sum(len(trails.action_fcurves(o)) for o in scene.objects if o.animation_data)
print("PROF fcurves in scene actions:", n_fc)

key = next(iter(trails.TRAILS))
tr = trails.TRAILS[key]
mid = tr.keys[len(tr.keys) // 2]
t_jac, jac = ms(lambda: trails.jacobians(scene, [(key, mid)]))
print(f"PROF jacobians (1 key): {t_jac:.1f} ms")
cur = scene.frame_current
t_fs, _ = ms(lambda: (scene.frame_set(cur + 1), scene.frame_set(cur)), 3)
print(f"PROF frame_set x2: {t_fs:.1f} ms")

edit = trails.KeyEdit(scene, [(key, mid)])
from mathutils import Vector  # noqa: E402
inv = jac[(key, mid)].inverted_safe()
t_apply, _ = ms(lambda: edit.apply({(key, mid): inv @ Vector((0.01, 0.0, 0.0))}), 20)
print(f"PROF KeyEdit.apply (1 key): {t_apply:.2f} ms")
t_ui, _ = ms(lambda: bpy.context.view_layer.update(), 5)
print(f"PROF view_layer.update after edit: {t_ui:.1f} ms")
t_part, _ = ms(lambda: trails.rebuild({key}), 3)
print(f"PROF rebuild (one trail): {t_part:.1f} ms")
edit.cancel()

pr = cProfile.Profile()
pr.enable()
trails.rebuild()
pr.disable()
st = pstats.Stats(pr)
st.sort_stats("cumulative").print_stats(12)
