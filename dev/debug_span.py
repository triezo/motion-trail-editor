"""After moving one key, does the curve change outside the LivePreview span (keys +-2)?"""
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

mte.register()
rig, cube, _ = testrig.build(dense=False)
scene = bpy.context.scene
it = scene.motion_trail.items.add()
it.object = cube
key = trails.item_key(cube, "")
trails.rebuild()
curves = [trails.location_fcurve(cube, "", i) for i in range(3)]
print("DBG smoothing:", [fc.auto_smoothing for fc in curves], "pref:",
      bpy.context.preferences.edit.fcurve_new_auto_smoothing)
before = {f: Vector([fc.evaluate(f) for fc in curves]) for f in range(1, 121)}

trails.JACOBIANS.update(trails.jacobians(scene, [(key, 41)]))
edit = trails.KeyEdit(scene, [(key, 41)])
preview = trails.LivePreview(scene, {key: {41}})
edit.apply({(key, 41): Vector((-0.4, 0.0, -0.2))})
after = {f: Vector([fc.evaluate(f) for fc in curves]) for f in range(1, 121)}
changed = [f for f in range(1, 121) if (after[f] - before[f]).length > 1e-6]
print("DBG preview span:", preview.span, "curve changed on frames:", changed[0], "..", changed[-1])
assert preview.span[0] <= changed[0] and preview.span[1] >= changed[-1], "span misses changed frames"
preview.update()
trail = trails.TRAILS[key]
approx = max((trail.position(f) - after[f]).length for f in range(1, 121))
print(f"DBG live preview error vs real curve: {approx:.6f}")
