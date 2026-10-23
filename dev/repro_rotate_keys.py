"""R on selected trail keys (key mode): does the trail rotate? Does the event get stuck?
blender --factory-startup --enable-event-simulate -p 40 40 1500 950 --python dev/repro_rotate_keys.py
"""
import math
import os
import sys
import traceback

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
bpy.context.preferences.view.show_splash = False

import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import ops, trails  # noqa: E402

MOUSE = [0, 0]
_invoke = ops.MOTIONTRAIL_OT_transform.invoke


def traced_invoke(self, context, event):
    try:
        result = _invoke(self, context, event)
        print("REPRO transform.invoke ->", result, "mode", self.mode, flush=True)
        return result
    except Exception:
        print("REPRO transform.invoke raised:\n" + traceback.format_exc(), flush=True)
        raise


ops.MOTIONTRAIL_OT_transform.invoke = traced_invoke


def ev(type, value='PRESS', x=None, y=None, **mods):
    win = bpy.context.window_manager.windows[0]
    if x is None:
        x, y = MOUSE
    win.event_simulate(type=type, value=value, x=x, y=y, **mods)


def move(x, y):
    MOUSE[:] = [x, y]
    ev('MOUSEMOVE', 'NOTHING', x, y)


def steps():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    rv3d = area.spaces.active.region_3d
    mte.register()
    rig, cube, _ = testrig.build(dense=False)
    scene = bpy.context.scene
    bpy.ops.object.select_all(action='DESELECT')
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.view3d.view_axis(type='TOP')
        bpy.ops.view3d.view_selected()
    rv3d.view_distance = 6.0
    it = scene.motion_trail.items.add()
    it.object = cube
    trails.rebuild()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.tool_set_by_id(name="motion_trail.tool_object", space_type='VIEW_3D')
    yield 0.4
    key = trails.item_key(cube, "")
    trail = trails.TRAILS[key]

    for label, frames in (("all keys", set(trail.keys)), ("one key", {trail.keys[2]})):
        trails.clear_selection()
        trails.SELECTION[key] = set(frames)
        before = {f: trail.position(f).copy() for f in trail.keys}
        before_all = {f: trail.position(f).copy() for f in range(trail.keys[0], trail.keys[-1] + 1)}
        rot_before = tuple(cube.rotation_euler)
        pivot = sum((before[f] for f in frames), before[trail.keys[0]] * 0) / len(frames)
        p = location_3d_to_region_2d(region, rv3d, pivot)
        cx, cy = int(p.x + region.x), int(p.y + region.y)
        move(cx + 100, cy)
        yield 0.1
        ev('R', 'PRESS')
        ev('R', 'RELEASE')
        yield 0.1
        for i in range(1, 16):
            a = i / 15 * math.pi / 2
            move(int(cx + 100 * math.cos(a)), int(cy + 100 * math.sin(a)))
            yield 0.03
        ev('LEFTMOUSE', 'PRESS')
        ev('LEFTMOUSE', 'RELEASE')
        yield 0.5
        trail = trails.TRAILS[key]
        moved = max((trail.position(f) - before[f]).length for f in before)
        rigid = max(abs((trail.position(f) - pivot).length - (before_all[f] - pivot).length)
                    for f in before_all) if len(frames) > 1 else 0.0
        print(f"REPRO {label}: trail keys moved max {moved:.4f}, rigid error {rigid:.6f}, cube rotation changed:",
              tuple(cube.rotation_euler) != rot_before, flush=True)
    os._exit(0)


def runner():
    gen = steps()

    def tick():
        try:
            return next(gen)
        except StopIteration:
            os._exit(0)
        except Exception:
            print("REPRO error", traceback.format_exc(), flush=True)
            os._exit(1)
    bpy.app.timers.register(tick, first_interval=1.0)


runner()
