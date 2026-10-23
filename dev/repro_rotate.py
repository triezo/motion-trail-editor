"""Reproduce freezes while rotating things that have a trail:
blender --factory-startup --enable-event-simulate -p 40 40 1500 950 --python dev/repro_rotate.py
Prints a line per step (flushed), so a freeze shows where it stopped.
"""
import math
import os
import sys
import time
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
bpy.context.preferences.view.show_splash = False

import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

MOUSE = [0, 0]


def log(*a):
    print("REPRO", f"{time.perf_counter() - T0:7.2f}s", *a, flush=True)


def ev(type, value='PRESS', x=None, y=None, **mods):
    win = bpy.context.window_manager.windows[0]
    if x is None:
        x, y = MOUSE
    win.event_simulate(type=type, value=value, x=x, y=y, **mods)


def move(x, y):
    MOUSE[:] = [x, y]
    ev('MOUSEMOVE', 'NOTHING', x, y)


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return win, area, region, area.spaces.active.region_3d


def rotate_gesture(cx, cy, key='R', seconds=1.5):
    """Press R, circle the mouse around (cx, cy), confirm."""
    move(cx + 120, cy)
    yield 0.1
    ev(key, 'PRESS')
    ev(key, 'RELEASE')
    yield 0.05
    steps = int(seconds * 30)
    for i in range(1, steps + 1):
        a = i / steps * math.pi * 1.5
        move(int(cx + 120 * math.cos(a)), int(cy + 120 * math.sin(a)))
        yield 1 / 30
    ev('LEFTMOUSE', 'PRESS')
    ev('LEFTMOUSE', 'RELEASE')
    yield 0.6


def steps():
    win, area, region, rv3d = view3d()
    mte.register()
    rig, cube, _body = testrig.build(dense=True)
    scene = bpy.context.scene
    s = scene.motion_trail
    ts = scene.tool_settings
    cx, cy = region.x + region.width // 2, region.y + region.height // 2
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.view3d.view_selected()
        bpy.ops.object.select_all(action='DESELECT')
    yield 0.3

    # Object trail on the cube.
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    move(cx, cy)
    ev('M', 'PRESS', alt=True)
    ev('M', 'RELEASE', alt=True)
    yield 0.5
    log("cube trail:", trails.item_key(cube, "") in trails.TRAILS)

    for autokey in (False, True):
        ts.use_keyframe_insert_auto = autokey
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
        log(f"A: R on cube, default tool, autokey={autokey}: start")
        yield from rotate_gesture(cx, cy)
        log(f"A: done, rot={tuple(round(v, 2) for v in cube.rotation_euler)}")

        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name="motion_trail.tool_object", space_type='VIEW_3D')
        log(f"B: R on cube, Motion Trail tool, nothing selected on trail, autokey={autokey}: start")
        trails.clear_selection()
        yield from rotate_gesture(cx, cy)
        log("B: done")

    ts.use_keyframe_insert_auto = False
    log("C: R with all cube trail keys selected (rotates keys): start")
    key = trails.item_key(cube, "")
    trails.SELECTION[key] = set(trails.TRAILS[key].keys)
    yield from rotate_gesture(cx, cy)
    log("C: done")

    log("D: same with handles: select tails of one key, R: start")
    trails.clear_selection()
    f = trails.TRAILS[key].keys[2]
    trails.HANDLE_SELECTION.update({(key, f, 'L'), (key, f, 'R')})
    trails.ensure_jacobians(scene)
    yield from rotate_gesture(cx, cy)
    log("D: done")

    # Bone trail: rotate the bone, then the whole armature object.
    trails.clear_selection()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='POSE')
    for b in rig.pose.bones:
        b.select = b.name == "hand_ik"
    move(cx, cy)
    ev('M', 'PRESS', alt=True)
    ev('M', 'RELEASE', alt=True)
    yield 0.5
    for autokey in (False, True):
        ts.use_keyframe_insert_auto = autokey
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
        log(f"E: R on bone, autokey={autokey}: start")
        yield from rotate_gesture(cx, cy)
        log("E: done")
    ts.use_keyframe_insert_auto = False
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
    log("F: R on the armature object (bone trail on): start")
    yield from rotate_gesture(cx, cy)
    log("F: done")
    log("ALL DONE")


T0 = time.perf_counter()


def runner():
    gen = steps()

    def tick():
        try:
            return next(gen)
        except StopIteration:
            os._exit(0)
        except Exception:
            log("error", traceback.format_exc())
            os._exit(1)
    bpy.app.timers.register(tick, first_interval=1.0)


runner()
