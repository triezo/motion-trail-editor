"""Rotate all cube keys after one key was moved: is the path still rotated rigidly?"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

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


def rotate_all(world, steps=1, select=False):
    tr = trails.TRAILS[key]
    keys = tr.keys
    pts = [(key, f) for f in keys]
    if select:
        trails.SELECTION[key] = set(keys)
        trails.sync_key_selection(bpy.context)
    before = {f: tr.position(f).copy() for f in range(keys[0], keys[-1] + 1)}
    pivot = sum((before[f] for f in keys), Vector()) / len(keys)
    jac = trails.jacobians(scene, pts)
    inv = {p: m.inverted_safe() for p, m in jac.items()}
    edit = trails.KeyEdit(scene, pts)
    angle, axis = world.to_quaternion().angle, world.to_quaternion().axis
    for s in range(1, steps + 1):  # like mouse moves: growing angle, always from the originals
        w = Matrix.Rotation(angle * s / steps, 3, axis)
        deltas = {(key, f): inv[(key, f)] @ (pivot + w @ (before[f] - pivot) - before[f]) for f in keys}
        edit.apply(deltas, {p: inv[p] @ w @ jac[p] for p in deltas})
    trails.rebuild()
    tr = trails.TRAILS[key]
    errs = {f: (tr.position(f) - (pivot + world @ (before[f] - pivot))).length for f in before}
    worst = max(errs, key=errs.get)
    return errs[worst], worst


# 1. Move key 41 like the GUI G step does.
tr = trails.TRAILS[key]
p = [(key, 41)]
jac = trails.jacobians(scene, p)
edit = trails.KeyEdit(scene, p)
edit.apply({(key, 41): jac[(key, 41)].inverted_safe() @ Vector((-0.4, 0.0, -0.2))})
trails.rebuild()
for i in range(3):
    fc = trails.location_fcurve(cube, "", i)
    print("DBG axis", i, [(round(k.co.x), round(k.handle_left.x - k.co.x, 3), round(k.handle_right.x - k.co.x, 3),
                           k.handle_left_type) for k in fc.keyframe_points])
R = Matrix.Rotation(math.radians(30), 3, Vector((0.3, -0.5, 0.8)).normalized())
for steps, select in ((1, False), (15, False), (1, True), (15, True)):
    err, frame = rotate_all(R, steps, select)
    print(f"DBG steps={steps:2d} selected={select}: rigid error {err:.6f} at frame {frame}")
    bpy.ops.ed.undo_push(message="x")
