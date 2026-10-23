"""Record the video tutorial as frames (simulated input + on-screen captions and pointers):
blender --factory-startup --enable-event-simulate --window-maximized --python dev/tutorial/record.py
Frames go to dev/out/tutorial/frames; then run encode.py. The window runs faster than the video:
holds are written as repeated frames.
"""
import math
import os
import shutil
import sys
import traceback

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "dev", "out", "tutorial", "frames")
sys.path.insert(0, ROOT)
bpy.context.preferences.view.show_splash = False

import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

FPS = 12
UI = {"title": None, "card": None, "caption": "", "keys": "", "mouse": None, "pressed": False, "button": "",
      "ripple": 0, "target": None, "pulse": 0}
FRAME = [0]
MOUSE = [0, 0]
YELLOW = (1.0, 0.84, 0.2, 1.0)


# ---------------------------------------------------------------------------
# Overlay: title/cards, captions, key badge, target pointer, cursor
# ---------------------------------------------------------------------------

def _tris(coords, color):
    gpu.state.blend_set('ALPHA')  # blf drawing resets it
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'TRIS', {"pos": coords}).draw(shader)


def _rect(x0, y0, x1, y1, color):
    _tris([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y0, 0), (x1, y1, 0), (x0, y1, 0)], color)


def _disc(cx, cy, r, color, seg=28):
    pts = []
    for i in range(seg):
        a0, a1 = i / seg * math.tau, (i + 1) / seg * math.tau
        pts += [(cx, cy, 0), (cx + math.cos(a0) * r, cy + math.sin(a0) * r, 0),
                (cx + math.cos(a1) * r, cy + math.sin(a1) * r, 0)]
    _tris(pts, color)


def _ring(cx, cy, r, width, color, region):
    gpu.state.blend_set('ALPHA')
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    pts = [(cx + math.cos(i / 40 * math.tau) * r, cy + math.sin(i / 40 * math.tau) * r, 0) for i in range(41)]
    batch_for_shader(shader, 'LINE_STRIP', {"pos": pts}).draw(shader)


def _text(text, size, x, y, color):
    blf.size(0, size)
    blf.position(0, x, y, 0)
    blf.color(0, *color)
    blf.draw(0, text)


def _text_box(text, size, cy, fg, bg, region, pad=14, x=None):
    blf.size(0, size)
    tw, th = blf.dimensions(0, text)
    x0 = (region.width - tw) / 2 if x is None else x
    if bg[3] > 0:
        _rect(x0 - pad, cy - pad, x0 + tw + pad, cy + th + pad, bg)
    _text(text, size, x0, cy, fg)
    return tw, th


def overlay():
    region = bpy.context.region
    if region is None:
        return
    main = region.type == 'WINDOW'
    _w, area, _r, _rv = view3d()
    k = max(1.0, area.width / 1280.0)  # sizes are designed for a 1280 px wide frame
    gpu.state.blend_set('ALPHA')
    if main and (UI["title"] or UI["card"]):
        _rect(0, 0, region.width, region.height, (0.07, 0.07, 0.09, 0.9))
        if UI["title"]:
            title, sub = UI["title"]
            _text_box(title, 46 * k, region.height / 2 + 10 * k, (1, 1, 1, 1), (0, 0, 0, 0), region)
            _text_box(sub, 22 * k, region.height / 2 - 44 * k, (1.0, 0.62, 0.22, 1), (0, 0, 0, 0), region)
        else:
            heading, lines = UI["card"]
            y = region.height / 2 + (30 * len(lines) / 2 + 40) * k
            _text_box(heading, 34 * k, y, (1.0, 0.62, 0.22, 1), (0, 0, 0, 0), region)
            blf.size(0, 22 * k)
            width = max(blf.dimensions(0, line)[0] for line in lines)
            for i, line in enumerate(lines):
                _text(line, 22 * k, (region.width - width) / 2, y - (60 + i * 36) * k, (1, 1, 1, 1))
        gpu.state.blend_set('NONE')
        return
    if main and UI["caption"]:
        _text_box(UI["caption"], 22 * k, 36 * k, (1, 1, 1, 1), (0.0, 0.0, 0.0, 0.8), region, pad=14 * k)
    if main and UI["keys"]:
        _text_box(UI["keys"], 30 * k, 112 * k, (0.08, 0.06, 0.04, 1), (1.0, 0.62, 0.15, 0.97), region,
                  pad=12 * k)
    if UI["target"] is not None:
        tx, ty, label = UI["target"]
        x, y = tx - region.x, ty - region.y
        r = (20 + 5 * math.sin(UI["pulse"] * 0.9)) * k
        _ring(x, y, r + 2 * k, 5.0 * k, (0, 0, 0, 0.6), region)
        _ring(x, y, r, 3.0 * k, YELLOW, region)
        if label and main:
            blf.size(0, 19 * k)
            lw, lh = blf.dimensions(0, label)
            lx = x + 34 * k if x + 34 * k + lw + 16 * k < region.width else x - 34 * k - lw
            ly = y + 18 * k
            _rect(lx - 8 * k, ly - 7 * k, lx + lw + 8 * k, ly + lh + 7 * k, (0.0, 0.0, 0.0, 0.82))
            _text(label, 19 * k, lx, ly, YELLOW)
    if UI["mouse"] is not None:
        x, y = UI["mouse"][0] - region.x, UI["mouse"][1] - region.y
        if UI["ripple"] > 0:
            _ring(x, y, (10 + (6 - UI["ripple"]) * 6) * k, 2.0 * k, (1.0, 0.8, 0.3, UI["ripple"] / 6), region)
        _disc(x, y, 9 * k, (0, 0, 0, 0.8))
        _disc(x, y, 7 * k, (1, 1, 1, 0.95))
        if UI["pressed"]:
            _disc(x, y, 4 * k, (1.0, 0.45, 0.1, 1))
        if UI["button"] and main:
            blf.size(0, 17 * k)
            bw, bh = blf.dimensions(0, UI["button"])
            _rect(x + 14 * k, y - 32 * k, x + 26 * k + bw, y - 32 * k + bh + 10 * k, (1.0, 0.45, 0.1, 0.95))
            _text(UI["button"], 17 * k, x + 20 * k, y - 27 * k, (1, 1, 1, 1))
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------

def view3d():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return win, area, region, area.spaces.active.region_3d


def region_of(kind):
    _w, area, _r, _rv = view3d()
    return next(r for r in area.regions if r.type == kind)


def redraw():
    _w, area, _r, _rv = view3d()
    area.tag_redraw()


def snap(hold=1):
    win, area, region, _rv3d = view3d()
    UI["pulse"] += 1
    if UI["ripple"] > 0:
        UI["ripple"] -= 1
    path = os.path.join(OUT, f"f_{FRAME[0]:05d}.png")
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=path, check_existing=False)
    FRAME[0] += 1
    for _ in range(hold - 1):
        shutil.copyfile(path, os.path.join(OUT, f"f_{FRAME[0]:05d}.png"))
        FRAME[0] += 1


def step():
    """Let Blender handle the events and redraw, then grab a frame (real time: one video frame)."""
    redraw()
    yield 1.0 / FPS
    snap()


def hold(seconds):
    """A still pause (frame repeated); the window waits as long, so it shows the real pace."""
    redraw()
    yield seconds
    snap(max(1, int(seconds * FPS)))


def live(seconds):
    """A pause with every frame captured (the pointer pulses)."""
    for _ in range(max(1, int(seconds * FPS))):
        yield from step()


def say(caption=None, keys=None, title=None, card=None):
    if caption is not None:
        UI["caption"] = caption
    if keys is not None:
        UI["keys"] = keys
    UI["title"] = title
    UI["card"] = card
    redraw()


def read(caption, extra=0.0):
    """Show a caption and wait long enough to read it before anything happens."""
    say(caption=caption)
    yield from hold(max(4.5, 0.09 * len(caption)) + extra)


def point(x, y, label, seconds=3.0):
    """Ring the place to click (window coords) with a short label, before the cursor goes there."""
    UI["target"] = (x, y, label)
    yield from live(seconds)


def unpoint():
    UI["target"] = None


def ev(type, value='PRESS', **mods):
    win = bpy.context.window_manager.windows[0]
    win.event_simulate(type=type, value=value, x=MOUSE[0], y=MOUSE[1], **mods)


def move(x, y, frames=24):
    x0, y0 = MOUSE
    for i in range(1, frames + 1):
        t = i / frames
        t = t * t * (3 - 2 * t)  # ease in/out
        MOUSE[:] = [int(x0 + (x - x0) * t), int(y0 + (y - y0) * t)]
        UI["mouse"] = tuple(MOUSE)
        ev('MOUSEMOVE', 'NOTHING')
        yield from step()


def click(button='LEFTMOUSE', label="ЛКМ", **mods):
    UI["button"] = label
    UI["pressed"] = True
    UI["ripple"] = 6
    ev(button, 'PRESS', **mods)
    yield from step()
    yield from step()
    ev(button, 'RELEASE', **mods)
    UI["pressed"] = False
    yield from live(0.5)
    UI["button"] = ""


def drag(x, y, frames=36, label="тянуть ЛКМ"):
    UI["button"] = label
    UI["pressed"] = True
    UI["ripple"] = 6
    ev('LEFTMOUSE', 'PRESS')
    yield from step()
    yield from step()
    yield from move(x, y, frames)
    ev('LEFTMOUSE', 'RELEASE')
    UI["pressed"] = False
    UI["button"] = ""
    yield from step()


def key(type, label, before=1.8, **mods):
    """Show the key badge, then press it."""
    say(keys=label)
    yield from hold(before)
    ev(type, 'PRESS', **mods)
    ev(type, 'RELEASE', **mods)
    yield from step()


def turn(cx, cy, radius, degrees, frames=36):
    """Move the mouse along an arc around (cx, cy) (for R)."""
    for i in range(1, frames + 1):
        a = i / frames * math.radians(degrees)
        MOUSE[:] = [int(cx + radius * math.cos(a)), int(cy + radius * math.sin(a))]
        UI["mouse"] = tuple(MOUSE)
        ev('MOUSEMOVE', 'NOTHING')
        yield from step()


def screen_of(co):
    _win, _area, region, rv3d = view3d()
    p = location_3d_to_region_2d(region, rv3d, co)
    return int(p.x + region.x), int(p.y + region.y)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------

def build_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 96
    arm = bpy.data.armatures.new("Arm")
    arm.display_type = 'OCTAHEDRAL'
    rig = bpy.data.objects.new("ArmRig", arm)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.edit_bones
    root = eb.new("root"); root.head = (0, 0, 0); root.tail = (0, 0.6, 0)
    upper = eb.new("upper_arm"); upper.head = (0, 0, 1.2); upper.tail = (0.55, 0, 1.15); upper.parent = root
    fore = eb.new("forearm"); fore.head = (0.55, 0, 1.15); fore.tail = (1.05, 0, 1.2); fore.parent = upper
    fore.use_connect = True
    hand = eb.new("hand_ik"); hand.head = (1.05, 0, 1.2); hand.tail = (1.05, 0, 1.45); hand.parent = root
    bpy.ops.object.mode_set(mode='POSE')
    ik = rig.pose.bones["forearm"].constraints.new('IK')
    ik.target, ik.subtarget, ik.chain_count = rig, "hand_ik", 2
    pb = rig.pose.bones["hand_ik"]
    for f in range(1, 97, 8):
        t = (f - 1) / 96
        pb.location = (-0.35 + 0.35 * math.cos(t * math.tau), 0.25 * math.sin(t * math.tau),
                       0.3 * math.sin(t * 2 * math.tau))
        pb.keyframe_insert("location", frame=f)
    for b in rig.pose.bones:
        trails.select_bone(b, False)
    scene.frame_set(1)
    return rig


# ---------------------------------------------------------------------------
# Story
# ---------------------------------------------------------------------------

def story():
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        os.remove(os.path.join(OUT, name))
    mte.register()
    win, area, region, rv3d = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screen_full_area()
    yield 0.5
    rig = build_scene()
    scene = bpy.context.scene
    s = scene.motion_trail
    s.frames_before = s.frames_after = 0
    s.key_size = 11
    s.line_width = 2.5
    for kind in ('WINDOW', 'TOOLS', 'UI'):
        bpy.types.SpaceView3D.draw_handler_add(overlay, (), kind, 'POST_PIXEL')
    win, area, region, rv3d = view3d()
    area.spaces.active.show_region_ui = False
    rv3d.view_perspective = 'PERSP'
    rv3d.view_rotation = Euler((math.radians(68), 0, math.radians(18))).to_quaternion()
    rv3d.view_location = Vector((0.55, 0.0, 1.05))
    rv3d.view_distance = 3.2
    MOUSE[:] = [region.x + region.width // 2 + 200, region.y + region.height // 2 - 120]
    UI["mouse"] = tuple(MOUSE)
    empty = (region.x + 110, region.y + 200)
    yield 0.5

    say(title=("Motion Trail Editor", "редактируемая траектория анимации • Blender 4.3+"))
    yield from hold(3.5)
    say(card=("Установка", [
        "1.  Edit → Preferences → вкладка Get Extensions",
        "2.  Кнопка ▾ справа вверху → Install from Disk…",
        "3.  Выберите файл motion_trail_editor-….zip",
        "     (или просто перетащите zip в окно Blender)",
        "",
        "Аддон работает в Pose Mode (кости) и Object Mode (объекты)",
    ]))
    yield from hold(9.0)
    say()

    # Step 1: select a bone
    yield from read("Шаг 1.  В Pose Mode кликните по кости, траекторию которой хотите видеть")
    pb = rig.pose.bones["hand_ik"]
    bx, by = screen_of(rig.matrix_world @ ((pb.head + pb.tail) / 2))
    yield from point(bx, by, "ЛКМ: выделить кость")
    yield from move(bx, by)
    yield from click()
    unpoint()
    yield from hold(1.5)

    # Step 2: Alt+M
    yield from read("Шаг 2.  Нажмите Alt + M — появится траектория")
    yield from key('M', "Alt + M", before=1.5, alt=True)
    yield 0.4
    yield from hold(2.5)
    say(keys="")
    tools = region_of('TOOLS')
    tool_x, tool_y = tools.x + 28, area.y + area.height - 302  # the Motion Trail tool button
    yield from read("Инструмент Motion Trail в тулбаре включился сам — клики ниже работают с ним", extra=0.5)
    yield from point(tool_x, tool_y, "", seconds=2.5)
    unpoint()

    key_ = trails.item_key(rig, "hand_ik")
    yield from read("Синяя линия — прошлое, оранжевая — будущее. Белые кружки — ключи, мелкие точки — кадры")
    for f in range(1, 50):
        scene.frame_set(f)
        yield from step()
    yield from hold(2.5)

    # Step 3: drag a key, then G
    yield from read("Шаг 3.  Наведите курсор на ключ и тяните его, зажав ЛКМ")
    trail = trails.TRAILS[key_]
    k = trail.keys[8]
    x, y = screen_of(trail.position(k))
    yield from point(x, y, "тяни ключ ЛКМ")
    yield from move(x, y)
    unpoint()
    yield from drag(x + 70, y + 45)
    yield from hold(2.5)

    yield from read("Выделенный ключ можно двигать и клавишей G (как в Blender), подтвердить — ЛКМ")
    trail = trails.TRAILS[key_]
    x, y = screen_of(trail.position(k))
    yield from move(x + 20, y - 10, frames=10)
    yield from key('G', "G")
    yield from move(x - 30, y - 50, frames=22)
    yield from click(label="ЛКМ: подтвердить")
    say(keys="")
    yield from hold(2.5)

    # Step 4: box select + R
    yield from read("Шаг 4.  Несколько ключей: зажмите ЛКМ на пустом месте и обведите их рамкой")
    trail = trails.TRAILS[key_]
    pts = [screen_of(trail.position(f)) for f in trail.keys[1:6]]
    x0, y0 = min(p[0] for p in pts) - 25, min(p[1] for p in pts) - 25
    x1, y1 = max(p[0] for p in pts) + 25, max(p[1] for p in pts) + 25
    yield from point(x0, y0, "начало рамки")
    yield from move(x0, y0)
    unpoint()
    yield from drag(x1, y1, label="рамка ЛКМ")
    yield from hold(2.5)
    yield from read("R — повернуть выделенный кусок траектории целиком (S — масштаб). Подтвердить — ЛКМ")
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    yield from move(cx + 110, cy, frames=12)
    yield from key('R', "R")
    yield from turn(cx, cy, 110, 40)
    yield from click(label="ЛКМ: подтвердить")
    say(keys="")
    yield from hold(2.5)

    # Step 5: tails
    yield from read("Шаг 5.  Клик ЛКМ по ключу — у него появятся хвостики (касательные)")
    yield from move(*empty, frames=12)
    yield from click(label="ЛКМ: снять выделение")
    trail = trails.TRAILS[key_]
    k = trail.keys[3]
    x, y = screen_of(trail.position(k))
    yield from point(x, y, "ЛКМ: выделить ключ")
    yield from move(x, y)
    yield from click()
    unpoint()
    yield 0.3
    yield from hold(1.5)
    drawn = {h[:3]: h for h in trails.visible_handles(scene, region, rv3d)}
    h = drawn.get((key_, k, 'R'))
    if h is not None:
        yield from read("Тяните серую точку на конце хвостика — меняется направление и скорость движения")
        hx, hy = screen_of(h[4])
        yield from point(hx, hy, "тяни конец хвостика")
        yield from move(hx, hy)
        unpoint()
        yield from drag(hx + 40, hy - 55)
        yield from hold(2.5)
        yield from read("S на выделенном хвостике — его длина: ключ проходится мягче или резче")
        hx, hy = hx + 40, hy - 55
        yield from key('S', "S")
        x, y = screen_of(trails.TRAILS[key_].position(k))
        yield from move(int(hx + (hx - x) * 0.8), int(hy + (hy - y) * 0.8), frames=22)
        yield from click(label="ЛКМ: подтвердить")
        say(keys="")
        yield from hold(2.5)

    # Step 6: insert / delete keys
    yield from read("Шаг 6.  Alt + правый клик по линии — вставить ключ в этом месте")
    trail = trails.TRAILS[key_]
    fa, fb = trail.keys[9], trail.keys[10]
    x, y = screen_of(trail.position((fa + fb) // 2))
    yield from point(x, y, "Alt + ПКМ по линии")
    yield from move(x, y)
    unpoint()
    say(keys="Alt + ПКМ")
    yield from hold(1.5)
    yield from click('RIGHTMOUSE', label="Alt + ПКМ", alt=True)
    say(keys="")
    yield from hold(2.5)
    yield from read("Alt + правый клик по ключу — удалить ключ (X — удалить все выделенные)")
    trail = trails.TRAILS[key_]
    x, y = screen_of(trail.position(fb))
    yield from point(x, y, "Alt + ПКМ по ключу")
    yield from move(x, y)
    unpoint()
    say(keys="Alt + ПКМ")
    yield from hold(1.5)
    yield from click('RIGHTMOUSE', label="Alt + ПКМ", alt=True)
    say(keys="")
    yield from hold(2.5)

    yield from read("Любое действие отменяется Ctrl + Z")
    yield from key('Z', "Ctrl + Z", ctrl=True)
    yield 0.4
    say(keys="")
    yield from hold(2.5)
    yield from read("Клик ЛКМ по пустому месту — снять выделение")
    yield from point(*empty, "ЛКМ в пустоту")
    yield from move(*empty)
    unpoint()
    yield from click()
    yield from hold(1.5)

    # Step 7: sidebar
    yield from read("Шаг 7.  Клавиша N → вкладка Motion Trail: кнопка вкл/выкл, диапазон, цвета")
    yield from key('N', "N")
    yield 0.4
    ui = region_of('UI')
    tab_x = ui.x + ui.width - 11
    tab_y = None
    for dy in [224] + list(range(20, ui.height, 12)):  # find the tab (clicks not recorded)
        MOUSE[:] = [tab_x, ui.y + ui.height - dy]
        ev('MOUSEMOVE', 'NOTHING')
        yield 0.05
        ev('LEFTMOUSE', 'PRESS')
        ev('LEFTMOUSE', 'RELEASE')
        yield 0.12
        if ui.active_panel_category == "Motion Trail":
            tab_y = ui.y + ui.height - dy
            break
    MOUSE[:] = list(UI["mouse"])
    say(keys="")
    if tab_y is not None:
        yield from point(tab_x, tab_y, "", seconds=2.5)
        unpoint()
    toggle_x, toggle_y = ui.x + 130, ui.y + ui.height - 45
    say(caption="Кнопка «Toggle for Selected» делает то же, что Alt + M")
    yield from point(toggle_x, toggle_y, "", seconds=3.0)
    unpoint()
    yield from read("Before / After — сколько кадров траектории видно вокруг плейхеда (0 — все)")
    yield from point(ui.x + 177, ui.y + ui.height - 160, "", seconds=3.0)
    unpoint()
    s.frames_before = s.frames_after = 12
    yield 0.3
    for f in range(30, 72):
        scene.frame_set(f)
        yield from step()
    yield from hold(1.5)
    yield from read("Траектория прячется вместе с оверлеями (кнопка Overlays в шапке вьюпорта)")
    area.spaces.active.overlay.show_overlays = False
    yield from hold(1.5)
    area.spaces.active.overlay.show_overlays = True
    yield from hold(1.5)

    UI["caption"] = ""
    say(card=("Кратко", [
        "Alt + M  —  вкл/выкл траекторию выделенных костей / объектов",
        "ЛКМ по ключу  —  выделить,  тянуть  —  двигать",
        "G / R / S  —  двигать / вращать / масштабировать ключи и хвостики",
        "Рамка ЛКМ или B  —  выделить несколько ключей",
        "Alt + ПКМ  —  вставить ключ на линии / удалить ключ",
        "X  —  удалить выделенные ключи,   Ctrl + Z  —  отмена",
    ]))
    yield from hold(10.0)
    print("RECORD DONE frames:", FRAME[0], f"({FRAME[0] / FPS:.0f} s)", flush=True)


def runner():
    gen = story()

    def tick():
        try:
            return next(gen)
        except StopIteration:
            os._exit(0)
        except Exception:
            print("RECORD error\n" + traceback.format_exc(), flush=True)
            os._exit(1)
    bpy.app.timers.register(tick, first_interval=1.0)


runner()
