"""Rotate an object that has a trail, in a copy of a real scene, and time every step:
blender --factory-startup --enable-event-simulate -p 40 40 1500 950 <copy.blend> --python dev/repro_underwater.py
"""
import math
import os
import sys
import time
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
bpy.context.preferences.view.show_splash = False

import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

MOUSE = [0, 0]
T0 = time.perf_counter()
LAST = [T0]


def _slow_logger(name, fn):
    def wrapper(*args, **kwargs):
        t = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            dt = (time.perf_counter() - t) * 1000
            if dt > 30:
                print(f"SLOW {name}: {dt:.0f} ms", flush=True)
    return wrapper


from motion_trail_editor import draw, handlers  # noqa: E402

for _name in ("trail_signature", "rebuild", "_external_rebuild", "ensure_jacobians", "jacobians",
              "prune_by_owner_selection", "_bake_with_paths", "_bake_with_frame_set", "sync_key_selection",
              "key_frames", "visible_handles", "_check_timer"):
    setattr(trails, _name, _slow_logger(_name, getattr(trails, _name)))
handlers.on_depsgraph_update = _slow_logger("on_depsgraph_update", handlers.on_depsgraph_update)
draw._draw_view = _slow_logger("draw_view", draw._draw_view)
draw._draw_pixel = _slow_logger("draw_pixel", draw._draw_pixel)


def log(*a):
    now = time.perf_counter()
    print("REPRO", f"{now - T0:7.2f}s (+{now - LAST[0]:.2f})", *a, flush=True)
    LAST[0] = now


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


def rotate_gesture(cx, cy, seconds=1.5):
    move(cx + 120, cy)
    yield 0.1
    ev('R', 'PRESS')
    ev('R', 'RELEASE')
    yield 0.05
    steps = int(seconds * 30)
    worst = 0.0
    for i in range(1, steps + 1):
        a = i / steps * math.pi * 1.5
        t = time.perf_counter()
        move(int(cx + 120 * math.cos(a)), int(cy + 120 * math.sin(a)))
        yield 1 / 30
        worst = max(worst, time.perf_counter() - t)
    ev('LEFTMOUSE', 'PRESS')
    ev('LEFTMOUSE', 'RELEASE')
    yield 1.5
    log(f"   slowest step during the drag: {worst * 1000:.0f} ms")


NO_ADDON = "noaddon" in sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else False


def steps():
    win, area, region, rv3d = view3d()
    log("loaded", bpy.data.filepath, "objects:", len(bpy.context.scene.objects), "addon:", not NO_ADDON)
    scene = bpy.context.scene
    ob = bpy.data.objects["Armature"]
    if bpy.context.mode != 'OBJECT':
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.object.mode_set(mode='OBJECT')
    if not NO_ADDON:
        mte.register()
        s = scene.motion_trail
        if not any(it.object == ob and not it.bone for it in s.items):
            it = s.items.add()
            it.object = ob
        log("items:", [(i.object.name if i.object else None, i.bone) for i in s.items])
        trails.rebuild()
        log("rebuild done:", {str(k): (v.frame_start, v.frame_end, v.keys) for k, v in trails.TRAILS.items()},
            f"{trails.state.last_rebuild * 1000:.0f} ms")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    scene.tool_settings.use_keyframe_insert_auto = True
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.view3d.view_selected()
    yield 1.0
    cx, cy = region.x + region.width // 2, region.y + region.height // 2

    if NO_ADDON:
        for i in range(2):
            log(f"R on Armature without the addon #{i + 1}: start")
            yield from rotate_gesture(cx, cy)
        log("ALL DONE")
        return

    for tool in ("builtin.select_box", "motion_trail.tool_object"):
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name=tool, space_type='VIEW_3D')
        trails.clear_selection()
        log(f"R on Armature, tool={tool}, autokey on: start (frame {scene.frame_current})")
        yield from rotate_gesture(cx, cy)
        log("   done; trail keys now:", {str(k): v.keys for k, v in trails.TRAILS.items()},
            "selection:", {str(k): sorted(v) for k, v in trails.SELECTION.items()})

    key = trails.item_key(ob, "")
    trails.SELECTION[key] = set(trails.TRAILS[key].keys)
    log("R with all trail keys selected: start")
    yield from rotate_gesture(cx, cy)
    log("   done")

    # Hypothesis: evaluating the trail while Blender's own transform is running is what stalls.
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
    trails.clear_selection()
    move(cx + 120, cy)
    yield 0.1
    ev('R', 'PRESS')
    ev('R', 'RELEASE')
    yield 0.05
    for i in range(1, 10):
        move(cx + 120 - i * 5, cy + i * 8)
        yield 1 / 30
    t = time.perf_counter()
    trails.rebuild()
    log(f"rebuild DURING Blender's rotate: {(time.perf_counter() - t) * 1000:.0f} ms")
    t = time.perf_counter()
    scene.frame_set(scene.frame_current + 1)
    scene.frame_set(scene.frame_current - 1)
    log(f"frame_set x2 DURING Blender's rotate: {(time.perf_counter() - t) * 1000:.0f} ms")
    ev('RIGHTMOUSE', 'PRESS')
    ev('RIGHTMOUSE', 'RELEASE')
    yield 1.0
    t = time.perf_counter()
    trails.rebuild()
    log(f"rebuild after the rotate: {(time.perf_counter() - t) * 1000:.0f} ms")
    log("ALL DONE")


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
    bpy.app.timers.register(tick, first_interval=2.0)


runner()
