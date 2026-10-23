"""GUI test of the animation tools (header buttons, Tween drag, AnimOffset with a real G move, Ghosts, Silhouette):
blender --factory-startup --enable-event-simulate -p 0 0 1500 900 --python dev/test_tools_gui.py -- <out prefix>
Writes screenshots <prefix>_*.png and prints TOOLS [PASS]/[FAIL] lines. Real input is ignored while it runs.
"""
import math
import os
import sys
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
bpy.context.preferences.view.show_splash = False  # the splash would swallow the simulated events
import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import ghosts, offset, trails  # noqa: E402

prefix = sys.argv[sys.argv.index("--") + 1]
failed = []
MOUSE = [0, 0]


def note(name, ok, info=None):
    if not ok:
        failed.append(name)
    print(f"TOOLS [{'PASS' if ok else 'FAIL'}] {name}: {info}", flush=True)


def win():
    return bpy.context.window_manager.windows[0]


def area_of(kind):
    return max((a for a in win().screen.areas if a.type == kind), key=lambda a: a.width * a.height)


def region_of(area, kind):
    return next(r for r in area.regions if r.type == kind)


def ev(type, value='PRESS', x=None, y=None, **mods):
    if x is None:
        x, y = MOUSE
    win().event_simulate(type=type, value=value, x=x, y=y, **mods)


def move(x, y):
    MOUSE[:] = [x, y]
    ev('MOUSEMOVE', 'NOTHING', x, y)


def shot(name, kind=None):
    path = f"{prefix}_{name}.png"
    if kind is None:
        bpy.ops.screen.screenshot(filepath=path, check_existing=False)
        return
    area = area_of(kind)
    with bpy.context.temp_override(window=win(), area=area, region=region_of(area, 'WINDOW')):
        bpy.ops.screen.screenshot_area(filepath=path, check_existing=False)


def body_mesh(rig):
    """A simple capsule deformed by the root bone (which turns over time) and the arm."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.35, location=(0.4, 0, 1.2))
    body = bpy.context.active_object
    body.name = "Body"
    body.scale = (1.0, 0.6, 1.6)
    bpy.ops.object.transform_apply(scale=True)
    body.modifiers.new("Armature", 'ARMATURE').object = rig
    body.vertex_groups.new(name="root").add(range(len(body.data.vertices)), 1.0, 'REPLACE')
    return body


def loc_keys(ob, bone):
    return [[round(kp.co.y, 4) for kp in trails.location_fcurve(ob, bone, i).keyframe_points] for i in range(3)]


def steps():
    mte.register()
    rig, _cube, _ = testrig.build(dense=False)
    body = body_mesh(rig)
    scene = bpy.context.scene
    v3d = area_of('VIEW_3D')
    vwin = region_of(v3d, 'WINDOW')
    space = v3d.spaces.active
    with bpy.context.temp_override(window=win(), area=v3d, region=vwin):
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        body.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.view3d.view_axis(type='FRONT')
        bpy.ops.view3d.view_selected()
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='POSE')
    space.region_3d.view_perspective = 'PERSP'
    for b in rig.pose.bones:
        trails.select_bone(b, b.name == "hand_ik")
    rig.data.bones.active = rig.data.bones["hand_ik"]
    scene.frame_set(19)  # keys at 13 and 25
    yield 0.6
    shot("window")
    timeline = area_of('DOPESHEET_EDITOR')
    header = region_of(timeline, 'HEADER')
    shot("timeline", 'DOPESHEET_EDITOR')

    # --- Tween drag: invoke from the timeline header, drag right, click.
    fcs = [trails.location_fcurve(rig, "hand_ik", i) for i in range(3)]
    p = [fc.evaluate(13) for fc in fcs]
    n = [fc.evaluate(25) for fc in fcs]
    hx, hy = header.x + header.width // 2, header.y + header.height // 2
    move(hx, hy)
    yield 0.2
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.tween_drag('INVOKE_DEFAULT')
    yield 0.2
    running = any(op.bl_idname.upper().startswith("ANIM_TOOLS_OT_TWEEN_DRAG") for op in win().modal_operators)
    busy = trails.blender_busy()
    scale = bpy.context.preferences.system.ui_scale
    for dx in range(0, int(76 * scale) + 1, int(19 * scale)):  # +0.5 of the -1..1 range
        move(hx + dx, hy)
        yield 0.05
    ev('LEFTMOUSE', 'PRESS')
    ev('LEFTMOUSE', 'RELEASE')
    yield 0.3
    keyed = [trails.find_key(fc, 19) for fc in fcs]
    values = [kp.co.y if kp else None for kp in keyed]
    t = None
    if None not in values and abs(n[0] - p[0]) > 1e-6:
        t = (values[0] - p[0]) / (n[0] - p[0])
    consistent = None not in values and all(abs(v - (a + (b - a) * t)) < 1e-3 for v, a, b in zip(values, p, n))
    note("tween drag: modal runs, trails wait, key at the frame", running and busy and consistent,
         {"t": t and round(t, 3), "running": running, "busy": busy})
    for fc in fcs:
        fc.keyframe_points.remove(trails.find_key(fc, 19))
        fc.update()

    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.tween_drag('INVOKE_DEFAULT')
    yield 0.2
    move(hx + 120, hy)
    yield 0.1
    ev('ESC', 'PRESS')
    ev('ESC', 'RELEASE')
    yield 0.3
    note("tween drag: Esc leaves no key", all(trails.find_key(fc, 19) is None for fc in fcs))

    # --- AnimOffset: G-move the hand in the viewport, the whole animation follows.
    before = loc_keys(rig, "hand_ik")
    scene.frame_set(25)
    scene.tool_settings.use_keyframe_insert_auto = True
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.anim_offset()
    yield 0.3
    cx, cy = vwin.x + vwin.width // 2, vwin.y + vwin.height // 2
    move(cx, cy)
    yield 0.2
    ev('G')
    ev('G', 'RELEASE')
    yield 0.1
    ev('Z')
    ev('Z', 'RELEASE')
    yield 0.1
    for dy in range(0, 61, 15):
        move(cx, cy + dy)
        yield 0.05
    yield 0.2
    shot("offset_banner", 'VIEW_3D')
    ev('LEFTMOUSE', 'PRESS')
    ev('LEFTMOUSE', 'RELEASE')
    yield 0.6
    rig = bpy.data.objects["TestRig"]  # the transform pushed an undo step: old references are stale
    after = loc_keys(rig, "hand_ik")
    shifts = [[a - b for a, b in zip(ca, cb)] for ca, cb in zip(after, before)]
    uniform = all(max(sh) - min(sh) < 1e-3 for sh in shifts)
    moved = [round(sh[0], 4) for sh in shifts if abs(sh[0]) > 1e-3]
    shifts = [(round(min(sh), 4), round(max(sh), 4)) for sh in shifts]
    auto_off = not scene.tool_settings.use_keyframe_insert_auto
    no_new_key = [len(c) for c in after] == [len(c) for c in before]
    note("AnimOffset: G Z shifts all keys of the moved channel equally", uniform and len(moved) >= 1 and auto_off
         and no_new_key, {"shifts": shifts, "auto_off": auto_off})
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.anim_offset()
    note("AnimOffset off: auto key restored", scene.tool_settings.use_keyframe_insert_auto and not offset.is_enabled())
    scene.tool_settings.use_keyframe_insert_auto = False

    # --- Onion skin: previous / next keys follow the playhead.
    from motion_trail_editor import onion
    scene.frame_set(19)
    rig = bpy.data.objects["TestRig"]
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.onion()
    yield 0.6
    first = onion.state.shown
    shot("onion", 'VIEW_3D')
    scene.frame_set(31)
    yield 0.6
    second = onion.state.shown
    note("onion: previous / next keys follow the playhead",
         first == ((13,), (25,)) and second == ((25,), (37,)) and scene.frame_current == 31,
         {"first": first, "second": second, "ms": round(onion.state.last_ms, 1)})
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.onion()
    note("onion off", not onion.is_enabled() and not onion.state.cache)

    # --- Ghosts at 1 and 61, look from 31.
    for f in (1, 61):
        scene.frame_set(f)
        with bpy.context.temp_override(window=win(), area=timeline, region=header):
            bpy.ops.anim_tools.ghost_add()
    scene.frame_set(31)
    yield 0.5
    shot("ghosts", 'VIEW_3D')
    note("ghosts captured", sorted(g.frame for g in ghosts.GHOSTS) == [1, 61], [g.frame for g in ghosts.GHOSTS])

    # --- Silhouette on / off.
    old = (space.shading.type, space.shading.light, space.shading.color_type)
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.silhouette()
    yield 0.4
    shot("silhouette", 'VIEW_3D')
    on = (space.shading.light, space.shading.color_type) == ('FLAT', 'OBJECT') and body.color[0] == 0.0
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.silhouette()
    yield 0.3
    back = (space.shading.type, space.shading.light, space.shading.color_type) == old and body.color[0] == 1.0
    note("silhouette on and back", on and back, {"old": old})
    with bpy.context.temp_override(window=win(), area=timeline, region=header):
        bpy.ops.anim_tools.ghost_clear()
    yield 0.2


def tick_factory():
    gen = steps()

    def tick():
        try:
            return next(gen)
        except StopIteration:
            pass
        except Exception:
            note("exception", False, traceback.format_exc())
        print("TOOLS DONE", len(failed), "failed", flush=True)
        os._exit(0)  # a normal quit would overwrite quit.blend
    return tick


bpy.app.timers.register(tick_factory(), first_interval=1.0)
