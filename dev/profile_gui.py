"""Measure interactive editing cost with simulated input on a scene copy:
blender --factory-startup --enable-event-simulate -p 40 40 1500 950 <copy.blend> --python dev/profile_gui.py
"""
import json
import os
import sys
import time
import traceback

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.dirname(HERE))
bpy.context.preferences.view.show_splash = False

import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import ops, trails, draw  # noqa: E402

STATS = {}


def timed(name, fn):
    def wrapper(*args, **kwargs):
        t = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            STATS.setdefault(name, []).append((time.perf_counter() - t) * 1000)
    return wrapper


trails.rebuild = timed("rebuild", trails.rebuild)
ops.MOTIONTRAIL_OT_transform._update = timed("transform_update", ops.MOTIONTRAIL_OT_transform._update)
draw._draw_view = timed("draw_view", draw._draw_view)
draw._draw_pixel = timed("draw_pixel", draw._draw_pixel)
MOUSE = [0, 0]


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
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return win, area, region, area.spaces.active.region_3d


def steps():
    mte.register()
    draw.unregister()
    draw._handles.clear()
    draw.register()  # re-register so the timed draw functions are used
    win, area, region, rv3d = view3d()
    scene = bpy.context.scene
    trails.rebuild()
    key = next(iter(trails.TRAILS))
    tr = trails.TRAILS[key]
    f = tr.keys[len(tr.keys) // 2]
    trails.SELECTION[key] = {f}
    trails.ensure_jacobians(scene)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.view3d.view_all()
        bpy.ops.wm.tool_set_by_id(name="motion_trail.tool_pose", space_type='VIEW_3D')
    yield 0.5
    print("PROFGUI tool:", bpy.context.workspace.tools.from_space_view3d_mode(bpy.context.mode).idname, flush=True)
    handles = {h[:3]: h for h in trails.visible_handles(scene, region, rv3d)}
    h = handles.get((key, f, 'R')) or next(iter(handles.values()))
    p = location_3d_to_region_2d(region, rv3d, h[4])
    x, y = int(p.x + region.x), int(p.y + region.y)
    move(x, y)
    yield 0.2
    STATS.clear()
    ev('LEFTMOUSE', 'PRESS', x, y)
    yield 0.02
    t0 = time.perf_counter()
    n = 60
    for i in range(1, n + 1):  # ~60 Hz mouse for one second
        move(x + i * 2, y + i)
        yield 1 / 60
    wall = (time.perf_counter() - t0) * 1000
    ev('LEFTMOUSE', 'RELEASE', x + n * 2, y + n)
    yield 0.5
    summary = {name: {"calls": len(v), "avg_ms": round(sum(v) / len(v), 2), "max_ms": round(max(v), 2),
                      "total_ms": round(sum(v), 1)} for name, v in STATS.items() if v}
    summary["drag_wall_ms (ideal 1000)"] = round(wall)
    summary["trail_frames"] = (tr.frame_start, tr.frame_end)
    print("PROFGUI", json.dumps(summary, indent=1), flush=True)


def runner():
    gen = steps()

    def tick():
        try:
            return next(gen)
        except StopIteration:
            os._exit(0)
        except Exception:
            print("PROFGUI error", traceback.format_exc(), flush=True)
            os._exit(1)
    bpy.app.timers.register(tick, first_interval=1.0)


runner()
