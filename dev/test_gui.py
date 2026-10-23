"""Interactive test with simulated input. Opens a Blender window, runs, writes dev/out/, quits:
blender --factory-startup --enable-event-simulate -p 40 40 1500 950 --python dev/test_gui.py
Real mouse/keyboard input is ignored while it runs.
"""
import json
import math
import os
import sys
import traceback

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

log = []
bpy.context.preferences.view.show_splash = False  # the splash popup would swallow the simulated events


def note(name, ok, info=None):
    log.append({"step": name, "ok": bool(ok), "info": repr(info)})
    print(f"GUI [{'PASS' if ok else 'FAIL'}] {name}: {info}", flush=True)


def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            region = next(r for r in area.regions if r.type == 'WINDOW')
            return win, area, region, area.spaces.active.region_3d
    raise RuntimeError("no 3D view")


def screen_pos(key, frame):
    win, area, region, rv3d = view3d()
    co = trails.TRAILS[key].position(frame)
    p = location_3d_to_region_2d(region, rv3d, co)
    return int(p.x + region.x), int(p.y + region.y)


MOUSE = [0, 0]


def ev(type, value='PRESS', x=None, y=None, **mods):
    # Simulated key events without coordinates land at (0, 0), outside the viewport.
    win = bpy.context.window_manager.windows[0]
    if x is None:
        x, y = MOUSE
    win.event_simulate(type=type, value=value, x=x, y=y, **mods)


def move(x, y):
    MOUSE[:] = [x, y]
    ev('MOUSEMOVE', 'NOTHING', x, y)


def screenshot(name):
    win, area, region, rv3d = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=os.path.join(OUT, name), check_existing=False)


def location_values(ob, bone, frame):
    vals = []
    for i in range(3):
        fc = trails.location_fcurve(ob, bone, i)
        kp = trails.find_key(fc, frame) if fc else None
        vals.append(round(kp.co.y, 4) if kp else None)
    return vals


def steps():
    win, area, region, rv3d = view3d()
    mte.register()
    rig, cube, _body = testrig.build(dense=True)
    scene = bpy.context.scene
    s = scene.motion_trail
    s.frames_before = 0
    s.frames_after = 0
    scene.frame_set(25)

    # Frame the rig and cube from the front-right.
    space = area.spaces.active
    space.shading.type = 'SOLID'
    rv3d.view_perspective = 'PERSP'
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        bpy.ops.view3d.view_axis(type='FRONT')
        bpy.ops.view3d.view_selected()
        bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='POSE')
    for b in rig.pose.bones:
        trails.select_bone(b, b.name == "hand_ik")
    rig.data.bones.active = rig.pose.bones["hand_ik"].bone
    yield 0.5

    cx, cy = region.x + region.width // 2, region.y + region.height // 2
    move(cx, cy)
    yield 0.2
    ev('M', 'PRESS', alt=True)
    ev('M', 'RELEASE', alt=True)
    yield 0.6
    key = trails.item_key(rig, "hand_ik")
    tool = bpy.context.workspace.tools.from_space_view3d_mode('POSE').idname
    note("Alt+M enables trail and switches tool", key in trails.TRAILS and tool == "motion_trail.tool_pose",
         {"items": len(s.items), "tool": tool, "keys": trails.TRAILS.get(key) and trails.TRAILS[key].keys})
    screenshot("01_trail.png")
    yield 0.3

    # Click a key point.
    x, y = screen_pos(key, 37)
    move(x, y)
    yield 0.15
    note("hover highlights key", trails.HOVER[0] == (key, 37), trails.HOVER[0])
    ev('LEFTMOUSE', 'PRESS', x, y)
    yield 0.05
    ev('LEFTMOUSE', 'RELEASE', x, y)
    yield 0.3
    note("click selects key", trails.SELECTION.get(key) == {37}, {k: sorted(v) for k, v in trails.SELECTION.items()})

    # Drag the key 80 px to the right.
    before = location_values(rig, "hand_ik", 37)
    pos_before = trails.TRAILS[key].position(37).copy()
    ev('LEFTMOUSE', 'PRESS', x, y)
    yield 0.05
    for i in range(1, 9):
        move(x + i * 10, y)
        yield 0.03
    ev('LEFTMOUSE', 'RELEASE', x + 80, y)
    yield 0.6
    after = location_values(rig, "hand_ik", 37)
    nx, ny = screen_pos(key, 37)
    note("drag moves the key", before != after and abs(nx - (x + 80)) <= 3 and abs(ny - y) <= 3,
         {"loc_before": before, "loc_after": after, "screen_after": (nx, ny), "expected": (x + 80, y),
          "world_moved": round((trails.TRAILS[key].position(37) - pos_before).length, 4)})

    # G: move the selected key up 50 px, confirm with click.
    x, y = nx, ny
    move(x, y)
    yield 0.1
    ev('G', 'PRESS')
    ev('G', 'RELEASE')
    yield 0.1
    for i in range(1, 6):
        move(x, y + i * 10)
        yield 0.03
    ev('LEFTMOUSE', 'PRESS', x, y + 50)
    ev('LEFTMOUSE', 'RELEASE', x, y + 50)
    yield 0.6
    nx, ny = screen_pos(key, 37)
    note("G moves the selected key", abs(nx - x) <= 3 and abs(ny - (y + 50)) <= 3,
         {"screen_after": (nx, ny), "expected": (x, y + 50)})

    # Tails: the selected key shows its handles; drag the right tail end.
    shown = [h[:3] for h in trails.visible_handles(scene)]
    note("selected key shows its tails", (key, 37, 'R') in shown and (key, 37, 'L') in shown, shown)

    def handle_screen(side):
        left, right = trails.handle_positions(scene, key, 37)
        p = location_3d_to_region_2d(region, rv3d, right if side == 'R' else left)
        return int(p.x + region.x), int(p.y + region.y)

    def right_tail_values():
        return [tuple(round(v, 4) for v in trails.find_key(trails.location_fcurve(rig, "hand_ik", i), 37).handle_right)
                for i in range(3)]

    hx, hy = handle_screen('R')
    before = right_tail_values()
    move(hx, hy)
    yield 0.15
    note("hover highlights tail", trails.HOVER_HANDLE[0] == (key, 37, 'R'), trails.HOVER_HANDLE[0])
    ev('LEFTMOUSE', 'PRESS', hx, hy)
    yield 0.05
    for i in range(1, 7):
        move(hx + i * 5, hy + i * 5)
        yield 0.03
    ev('LEFTMOUSE', 'RELEASE', hx + 30, hy + 30)
    yield 0.5
    nhx, nhy = handle_screen('R')
    note("drag moves the tail end", abs(nhx - (hx + 30)) <= 3 and abs(nhy - (hy + 30)) <= 3
         and trails.HANDLE_SELECTION == {(key, 37, 'R')},
         {"tail_before": before, "tail_after": right_tail_values(), "screen": (nhx, nhy),
          "expected": (hx + 30, hy + 30)})

    # S on the selected tail: move the mouse away from the key to make the tail longer.
    kx, ky = screen_pos(key, 37)
    anchor = trails.TRAILS[key].position(37).copy()
    len0 = (trails.handle_positions(scene, key, 37)[1] - anchor).length
    sx, sy = nhx, nhy
    move(sx, sy)
    yield 0.1
    ev('S', 'PRESS')
    ev('S', 'RELEASE')
    yield 0.1
    tx, ty = kx + int((sx - kx) * 1.5), ky + int((sy - ky) * 1.5)
    for i in range(1, 6):
        move(sx + (tx - sx) * i // 5, sy + (ty - sy) * i // 5)
        yield 0.03
    ev('LEFTMOUSE', 'PRESS', tx, ty)
    ev('LEFTMOUSE', 'RELEASE', tx, ty)
    yield 0.5
    len1 = (trails.handle_positions(scene, key, 37)[1] - trails.TRAILS[key].position(37)).length
    note("S scales the tail", abs(len1 / len0 - 1.5) < 0.08, {"ratio": round(len1 / len0, 3)})

    # Flat tails (zero speed through the key, e.g. Auto Clamped on a pose) are still drawn and grabbable.
    for i in range(3):
        kp = trails.find_key(trails.location_fcurve(rig, "hand_ik", i), 61)
        kp.handle_left_type = kp.handle_right_type = 'FREE'
        kp.handle_left = (kp.handle_left.x, kp.co.y)
        kp.handle_right = (kp.handle_right.x, kp.co.y)
    trails.rebuild()
    fx, fy = screen_pos(key, 61)
    move(fx, fy)
    ev('LEFTMOUSE', 'PRESS', fx, fy)
    ev('LEFTMOUSE', 'RELEASE', fx, fy)
    yield 0.3
    drawn = {h[:3]: h for h in trails.visible_handles(scene, region, rv3d)}
    flat = drawn.get((key, 61, 'R'))
    note("flat tail is drawn at minimum length", flat is not None and flat[5], flat and flat[5])
    p = location_3d_to_region_2d(region, rv3d, flat[4])
    tx, ty = int(p.x + region.x), int(p.y + region.y)
    move(tx, ty)
    yield 0.1
    ev('LEFTMOUSE', 'PRESS', tx, ty)
    yield 0.05
    for i in range(1, 6):
        move(tx + i * 6, ty + i * 4)
        yield 0.03
    ev('LEFTMOUSE', 'RELEASE', tx + 30, ty + 20)
    yield 0.5
    right = trails.handle_offsets(scene, key, 61)[1]
    note("flat tail can be pulled out", right is not None and right.length > 1e-4,
         {"right_offset": right and tuple(round(v, 4) for v in right)})
    screenshot("02_edited.png")

    # I key on the bone at a frame without a key: the new key becomes the trail selection.
    scene.frame_set(31)
    for b in rig.pose.bones:
        trails.select_bone(b, b.name == "hand_ik")
    yield 0.3
    move(region.x + 60, region.y + 60)
    ev('I', 'PRESS')
    ev('I', 'RELEASE')
    yield 0.8
    note("I-key: new key is selected", trails.SELECTION.get(key) == {31} and 31 in trails.TRAILS[key].keys,
         {"selected": trails.SELECTION.get(key), "keys": trails.TRAILS[key].keys})

    # Auto Keying: a key made by moving the bone (G) is not selected; I still selects its key.
    ts = scene.tool_settings
    ts.use_keyframe_insert_auto = True
    trails.clear_selection()
    scene.frame_set(43)
    for b in rig.pose.bones:
        trails.select_bone(b, b.name == "hand_ik")
    yield 0.3
    gx, gy = region.x + 200, region.y + 200
    move(gx, gy)
    yield 0.1
    ev('G', 'PRESS')
    ev('G', 'RELEASE')
    yield 0.05
    for i in range(1, 6):
        move(gx + i * 6, gy + i * 3)
        yield 0.03
    ev('LEFTMOUSE', 'PRESS')
    ev('LEFTMOUSE', 'RELEASE')
    yield 0.8
    auto_keyed = 43 in trails.TRAILS[key].keys
    auto_selected = {k: sorted(v) for k, v in trails.SELECTION.items() if v}
    scene.frame_set(47)
    yield 0.3
    move(gx, gy)
    ev('I', 'PRESS')
    ev('I', 'RELEASE')
    yield 0.8
    note("auto-key: new key not selected; I with auto-key on: selected",
         auto_keyed and not auto_selected and trails.SELECTION.get(key) == {47},
         {"auto_key_inserted": auto_keyed, "selected_after_auto_key": auto_selected,
          "selected_after_I": trails.SELECTION.get(key)})
    ts.use_keyframe_insert_auto = False
    scene.frame_set(25)
    yield 0.3

    # Click on empty space: trail selection clears, regular click passes through.
    ex, ey = region.x + 30, region.y + 30
    move(ex, ey)
    yield 0.1
    ev('LEFTMOUSE', 'PRESS', ex, ey)
    ev('LEFTMOUSE', 'RELEASE', ex, ey)
    yield 0.3
    bones = [b.name for b in rig.pose.bones if trails.bone_selected(b)]
    note("click on nothing deselects keys, tails and bones", not trails.has_selection() and not bones,
         {"bones_selected": bones})

    # Overlays off (all, or just Motion Paths): the trail is hidden and cannot be clicked.
    overlay = area.spaces.active.overlay

    def click_key13():
        x, y = screen_pos(key, 13)
        move(x, y)
        ev('LEFTMOUSE', 'PRESS', x, y)
        ev('LEFTMOUSE', 'RELEASE', x, y)

    results = {}
    for label, show_overlays, show_paths in (("overlays off", False, True), ("motion paths off", True, False),
                                             ("both on", True, True)):
        trails.clear_selection()
        overlay.show_overlays, overlay.show_motion_paths = show_overlays, show_paths
        yield 0.2
        if label == "overlays off":
            screenshot("04_overlays_off.png")
        click_key13()
        yield 0.3
        results[label] = sorted(trails.SELECTION.get(key, ()))
    note("hidden with the overlays: not drawn, not clickable",
         results == {"overlays off": [], "motion paths off": [], "both on": [13]}, results)
    trails.clear_selection()

    # Box select over the whole trail.
    pts = [screen_pos(key, f) for f in trails.TRAILS[key].keys]
    x0 = min(p[0] for p in pts) - 20
    y0 = min(p[1] for p in pts) - 20
    x1 = max(p[0] for p in pts) + 20
    y1 = max(p[1] for p in pts) + 20
    move(x0, y0)
    yield 0.1
    ev('B', 'PRESS')
    ev('B', 'RELEASE')
    yield 0.1
    ev('LEFTMOUSE', 'PRESS', x0, y0)
    yield 0.05
    for i in range(1, 6):
        move(x0 + (x1 - x0) * i // 5, y0 + (y1 - y0) * i // 5)
        yield 0.03
    ev('LEFTMOUSE', 'RELEASE', x1, y1)
    yield 0.3
    n_sel = len(trails.SELECTION.get(key, ()))
    note("B box select", n_sel == len(trails.TRAILS[key].keys), {"selected": n_sel,
                                                                 "keys": len(trails.TRAILS[key].keys)})

    # Clear the selection, then Alt+RMB on the line midway between keys 49 and 61: insert key 55.
    move(ex, ey)
    ev('LEFTMOUSE', 'PRESS', ex, ey)
    ev('LEFTMOUSE', 'RELEASE', ex, ey)
    yield 0.2
    x, y = screen_pos(key, 55)
    move(x, y)
    yield 0.1
    ev('RIGHTMOUSE', 'PRESS', x, y, alt=True)
    ev('RIGHTMOUSE', 'RELEASE', x, y, alt=True)
    yield 0.4
    note("Alt+RMB on the line inserts a key", 55 in trails.TRAILS[key].keys and trails.SELECTION.get(key) == {55},
         {"keys": trails.TRAILS[key].keys, "selected": trails.SELECTION.get(key)})

    # Alt+RMB on an existing key deletes it.
    x, y = screen_pos(key, 73)
    move(x, y)
    yield 0.1
    ev('RIGHTMOUSE', 'PRESS', x, y, alt=True)
    ev('RIGHTMOUSE', 'RELEASE', x, y, alt=True)
    yield 0.4
    note("Alt+RMB on a key deletes it", 73 not in trails.TRAILS[key].keys, trails.TRAILS[key].keys)

    # X deletes the selected key (55).
    ev('X', 'PRESS')
    ev('X', 'RELEASE')
    yield 0.4
    note("X deletes selected key", 55 not in trails.TRAILS[key].keys, trails.TRAILS[key].keys)

    # Undo brings it back.
    ev('Z', 'PRESS', ctrl=True)
    ev('Z', 'RELEASE', ctrl=True)
    yield 0.8
    keys_now = trails.TRAILS[key].keys if key in trails.TRAILS else None
    note("Ctrl+Z restores the key", keys_now is not None and 55 in keys_now and 73 not in keys_now, keys_now)

    # A control with Inherit Rotation/Scale and Local Location off: the dragged key lands under the mouse.
    rig = bpy.data.objects["TestRig"]  # the undo above replaced the armature datablock
    trails.clear_selection()
    for b in rig.pose.bones:
        trails.select_bone(b, b.name == "ctrl_options")
    move(cx, cy)
    ev('M', 'PRESS', alt=True)
    ev('M', 'RELEASE', alt=True)
    yield 0.5
    skey = trails.item_key(rig, "ctrl_options")
    sx, sy = screen_pos(skey, 85)
    move(sx, sy)
    yield 0.1
    ev('LEFTMOUSE', 'PRESS', sx, sy)
    yield 0.05
    for i in range(1, 9):
        move(sx + i * 6, sy - i * 4)
        yield 0.03
    ev('LEFTMOUSE', 'RELEASE', sx + 48, sy - 32)
    yield 0.6
    nx, ny = screen_pos(skey, 85)
    note("special control: key lands where it was dragged", abs(nx - (sx + 48)) <= 3 and abs(ny - (sy - 32)) <= 3,
         {"screen_after": (nx, ny), "expected": (sx + 48, sy - 32)})
    for b in rig.pose.bones:
        trails.select_bone(b, b.name == "ctrl_options")
    ev('M', 'PRESS', alt=True)
    ev('M', 'RELEASE', alt=True)  # trail off again for the next steps
    yield 0.4
    trails.clear_selection()

    # Object trail in Object Mode.
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    rv3d.view_location = cube.location
    rv3d.view_distance = 6.0
    yield 0.3
    move(cx, cy)
    yield 0.2
    ev('M', 'PRESS', alt=True)
    ev('M', 'RELEASE', alt=True)
    yield 0.6
    ckey = trails.item_key(cube, "")
    tool = bpy.context.workspace.tools.from_space_view3d_mode('OBJECT').idname
    note("object trail in Object Mode", ckey in trails.TRAILS and tool == "motion_trail.tool_object",
         {"tool": tool, "keys": trails.TRAILS.get(ckey) and trails.TRAILS[ckey].keys})
    x, y = screen_pos(ckey, 41)
    move(x, y)
    yield 0.1
    ev('LEFTMOUSE', 'PRESS', x, y)
    ev('LEFTMOUSE', 'RELEASE', x, y)
    yield 0.2
    ev('G', 'PRESS')
    ev('G', 'RELEASE')
    for i in range(1, 5):
        move(x - i * 10, y - i * 5)
        yield 0.03
    ev('RET', 'PRESS')
    ev('RET', 'RELEASE')
    yield 0.6
    nx, ny = screen_pos(ckey, 41)
    note("G on object key", abs(nx - (x - 40)) <= 3 and abs(ny - (y - 20)) <= 3,
         {"screen_after": (nx, ny), "expected": (x - 40, y - 20)})
    screenshot("03_object.png")

    def r_gesture(cx, cy, again=False):
        move(cx + 100, cy)
        yield 0.1
        ev('R', 'PRESS')
        ev('R', 'RELEASE')
        yield 0.05
        if again:
            ev('R', 'PRESS')
            ev('R', 'RELEASE')
            yield 0.05
        for i in range(1, 16):
            a = i / 15 * math.pi / 2
            move(int(cx + 100 * math.cos(a)), int(cy + 100 * math.sin(a)))
            yield 0.03
        ev('LEFTMOUSE', 'PRESS')
        ev('LEFTMOUSE', 'RELEASE')
        yield 0.6

    ctrail = trails.TRAILS[ckey]
    # One key selected: R rotates the object as usual (the event is not swallowed).
    trails.clear_selection()
    trails.SELECTION[ckey] = {ctrail.keys[2]}
    rot0 = tuple(cube.rotation_euler)
    keys0 = {f: ctrail.position(f).copy() for f in ctrail.keys}
    px, py = screen_pos(ckey, ctrail.keys[2])
    yield from r_gesture(px, py)
    ctrail = trails.TRAILS[ckey]
    moved = max((ctrail.position(f) - keys0[f]).length for f in keys0)
    note("one key selected: R rotates the object", tuple(cube.rotation_euler) != rot0 and moved < 1e-6,
         {"object_rotated": tuple(cube.rotation_euler) != rot0, "trail_moved": round(moved, 6)})
    cube.rotation_euler = rot0
    yield 0.3

    # All keys selected: R rotates the whole path rigidly (in-between frames keep their distance to the pivot).
    ctrail = trails.TRAILS[ckey]
    trails.clear_selection()
    trails.SELECTION[ckey] = set(ctrail.keys)
    frames = range(ctrail.keys[0], ctrail.keys[-1] + 1)
    before = {f: ctrail.position(f).copy() for f in frames}
    curves = [trails.location_fcurve(cube, "", i) for i in range(3)]
    # After the earlier G on one key the whole trail must still match the curves (Continuous Acceleration).
    stale = max((before[f] - Vector([fc.evaluate(f) for fc in curves])).length for f in frames)
    pivot = sum((before[f] for f in ctrail.keys), Vector()) / len(ctrail.keys)
    rot0 = tuple(cube.rotation_euler)
    p = location_3d_to_region_2d(region, rv3d, pivot)
    yield from r_gesture(int(p.x + region.x), int(p.y + region.y))
    ctrail = trails.TRAILS[ckey]
    moved = max((ctrail.position(f) - before[f]).length for f in frames)
    rigid = max(abs((ctrail.position(f) - pivot).length - (before[f] - pivot).length) for f in frames)
    note("all keys selected: R rotates the whole path", stale < 1e-5 and moved > 0.1 and rigid < 1e-4
         and tuple(cube.rotation_euler) == rot0,
         {"trail_matched_curves_before": round(stale, 6), "moved": round(moved, 3),
          "distance_change": round(rigid, 6), "object_rotated": tuple(cube.rotation_euler) != rot0})

    # R R: trackball.
    before = {f: ctrail.position(f).copy() for f in frames}
    yield from r_gesture(int(p.x + region.x), int(p.y + region.y), again=True)
    ctrail = trails.TRAILS[ckey]
    moved = max((ctrail.position(f) - before[f]).length for f in frames)
    note("R R trackball rotates the path", moved > 0.05, {"moved": round(moved, 3)})
    trails.clear_selection()

    # Heavy work requested during Blender's own transform waits until the transform is over.
    calls = []
    original = trails._external_rebuild

    def recording():
        calls.append(trails.blender_busy())
        original()
    trails._external_rebuild = recording
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
    cx2, cy2 = screen_pos(ckey, scene.frame_current)
    move(cx2 + 80, cy2)
    yield 0.1
    ev('R', 'PRESS')
    ev('R', 'RELEASE')
    yield 0.05
    move(cx2 + 60, cy2 + 40)
    yield 0.1
    busy_seen = trails.blender_busy()
    trails.request_rebuild()
    for i in range(10):
        move(cx2 + 60 - i * 4, cy2 + 40 + i * 4)
        yield 0.05
    during = list(calls)
    ev('RET', 'PRESS')
    ev('RET', 'RELEASE')
    yield 0.6
    trails._external_rebuild = original
    note("no rebuild while Blender rotates, done right after", busy_seen and not during and calls and not any(calls),
         {"busy_detected": busy_seen, "rebuilds_during_rotate": len(during), "rebuilds_after": len(calls)})

    # Rebuild timing with the dense skinned mesh in the scene (both trails, 120 frames).
    import time
    t = time.perf_counter()
    for _ in range(5):
        trails.rebuild()
    obj_mode_ms = (time.perf_counter() - t) / 5 * 1000
    rig_ = bpy.data.objects["TestRig"]
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = rig_
        rig_.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')
    t = time.perf_counter()
    for _ in range(5):
        trails.rebuild()
    pose_mode_ms = (time.perf_counter() - t) / 5 * 1000
    note("rebuild timing (ms)", True, {"object_mode_bone_fallback": round(obj_mode_ms, 1),
                                       "pose_mode_path_engine": round(pose_mode_ms, 1)})


def runner():
    gen = steps()

    def tick():
        try:
            return next(gen)
        except StopIteration:
            finish()
            return None
        except Exception:
            note("exception", False, traceback.format_exc())
            finish()
        return None

    bpy.app.timers.register(tick, first_interval=1.0)


def finish():
    with open(os.path.join(OUT, "gui_results.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=1, default=str)
    print("GUI DONE", sum(not r["ok"] for r in log), "failed of", len(log), flush=True)
    # Hard exit: a normal quit would overwrite the user's session recovery file (quit.blend).
    os._exit(0)


runner()
