"""Viewport drawing of the trails (GPU)."""
import math

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader

from . import trails

_handles = []


def tag_redraw_all():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _point_shader():
    try:
        return gpu.shader.from_builtin('POINT_FLAT_COLOR')
    except ValueError:  # Blender < 4.4: plain points (square)
        return gpu.shader.from_builtin('FLAT_COLOR')


def _fade(f, cur, before, after, enabled):
    if not enabled:
        return 1.0
    span = before if f <= cur else after
    if span <= 0:
        return 1.0
    return max(0.0, 1.0 - abs(f - cur) / (span + 1.0)) ** 0.8


def _draw_view():
    context = bpy.context
    scene = context.scene
    region = context.region
    if not trails.TRAILS or scene is None or region is None or not trails.shown_in(context.space_data):
        return
    s = scene.motion_trail
    cur = scene.frame_current
    scale = trails.ui_scale()

    line_shader = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
    point_shader = _point_shader()

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('NONE' if s.show_on_top else 'LESS_EQUAL')

    for key, trail in trails.TRAILS.items():
        f0, f1 = trails.visible_range(scene, trail)
        if f1 < f0:
            continue
        coords, colors = [], []
        dim = 0.4 if trail.stale else 1.0  # bone trail kept while the armature is out of Pose Mode
        for f in range(f0, f1 + 1):
            co = trail.position(f)
            base = s.color_before if f <= cur else s.color_after
            a = base[3] * dim * _fade(f, cur, s.frames_before, s.frames_after, s.fade)
            coords.append(co)
            colors.append((base[0], base[1], base[2], a))

        if len(coords) > 1:
            batch = batch_for_shader(line_shader, 'LINE_STRIP', {"pos": coords, "color": colors})
            line_shader.bind()
            line_shader.uniform_float("viewportSize", (region.width, region.height))
            line_shader.uniform_float("lineWidth", s.line_width * scale)
            batch.draw(line_shader)

        if s.show_frame_dots:
            gpu.state.point_size_set(s.frame_dot_size * scale)
            dot_colors = [(c[0], c[1], c[2], c[3] * 0.9) for c in colors]
            batch = batch_for_shader(point_shader, 'POINTS', {"pos": coords, "color": dot_colors})
            batch.draw(point_shader)

    gpu.state.point_size_set(1.0)
    gpu.state.depth_test_set('NONE')
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set('NONE')


def _circle(center, radius, segments=32):
    return [(center.x + math.cos(i / segments * math.tau) * radius,
             center.y + math.sin(i / segments * math.tau) * radius, 0.0) for i in range(segments + 1)]


_UNIT_DISC = [(math.cos(i / 16 * math.tau), math.sin(i / 16 * math.tau)) for i in range(17)]


def _add_disc(coords, colors, center, radius, color):
    for i in range(16):
        (ax, ay), (bx, by) = _UNIT_DISC[i], _UNIT_DISC[i + 1]
        coords += [(center.x, center.y, 0.0),
                   (center.x + ax * radius, center.y + ay * radius, 0.0),
                   (center.x + bx * radius, center.y + by * radius, 0.0)]
        colors += [color, color, color]


def _draw_handles(scene, region, rv3d, scale):
    """Tangent handles of the selected keys: a line from the key and a dot at the end."""
    s = scene.motion_trail
    handles = trails.visible_handles(scene, region, rv3d)
    if not handles:
        return
    hover = trails.HOVER_HANDLE[0]
    lines, flat_lines, dots, dot_colors = [], [], [], []
    radius = max(s.key_size * 0.32, 3.0) * scale
    for key, f, side, co, end, flat in handles:
        a = location_3d_to_region_2d(region, rv3d, co)
        b = location_3d_to_region_2d(region, rv3d, end)
        if a is None or b is None:
            continue
        # Flat tails (no speed through the key) are drawn faint, at a minimum length to stay grabbable.
        (flat_lines if flat else lines).extend([(a.x, a.y, 0.0), (b.x, b.y, 0.0)])
        h = (key, f, side)
        if h in trails.HANDLE_SELECTION:
            col = s.color_selected
        elif h == hover:
            col = (1.0, 1.0, 1.0, 1.0)
        else:
            col = s.color_handle
        r = radius * (1.3 if h == hover else 1.0)
        _add_disc(dots, dot_colors, b, r + 1.5 * scale, (0.0, 0.0, 0.0, 0.85))
        _add_disc(dots, dot_colors, b, r, tuple(col))
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    for coords, alpha in ((lines, 1.0), (flat_lines, 0.35)):
        if coords:
            shader.bind()
            shader.uniform_float("viewportSize", (region.width, region.height))
            shader.uniform_float("lineWidth", 1.5 * scale)
            c = s.color_handle
            shader.uniform_float("color", (c[0], c[1], c[2], c[3] * alpha))
            batch_for_shader(shader, 'LINES', {"pos": coords}).draw(shader)
    if dots:
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        batch_for_shader(shader, 'TRIS', {"pos": dots, "color": dot_colors}).draw(shader)


def _draw_keys(scene, region, rv3d, scale):
    """Key points as round discs with a dark outline (screen space, always on top)."""
    s = scene.motion_trail
    cur = scene.frame_current
    hover = trails.HOVER[0]
    radius = s.key_size * 0.5 * scale
    outline = 1.5 * scale
    coords, colors = [], []
    for key, trail in trails.TRAILS.items():
        f0, f1 = trails.visible_range(scene, trail)
        selected = trails.SELECTION.get(key, ())
        for f in trail.keys:
            if f < f0 or f > f1:
                continue
            co = trail.position(f)
            p = location_3d_to_region_2d(region, rv3d, co) if co is not None else None
            if p is None:
                continue
            if f in selected:
                col = s.color_selected
            elif hover == (key, f):
                col = (1.0, 1.0, 1.0, 1.0)
            else:
                col = s.color_key
            a = col[3] * max(0.35, _fade(f, cur, s.frames_before, s.frames_after, s.fade))
            if trail.stale:
                a *= 0.5
            r = radius * (1.25 if hover == (key, f) else 1.0)
            _add_disc(coords, colors, p, r + outline, (0.0, 0.0, 0.0, 0.85 * a))
            _add_disc(coords, colors, p, r, (col[0], col[1], col[2], a))
    if coords:
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        batch_for_shader(shader, 'TRIS', {"pos": coords, "color": colors}).draw(shader)


def _draw_pixel():
    context = bpy.context
    scene = context.scene
    region, rv3d = context.region, context.region_data
    if scene is None or region is None or rv3d is None or not trails.shown_in(context.space_data):
        return
    s = scene.motion_trail
    scale = trails.ui_scale()
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    if trails.TRAILS:
        _draw_handles(scene, region, rv3d, scale)
        _draw_keys(scene, region, rv3d, scale)
        cur = scene.frame_current
        for trail in trails.TRAILS.values():
            co = trail.position(cur)
            p = location_3d_to_region_2d(region, rv3d, co) if co is not None else None
            if p is None:
                continue
            radius = (s.key_size * 0.5 + 5.0) * scale
            batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": _circle(p, radius)})
            shader.bind()
            shader.uniform_float("viewportSize", (region.width, region.height))
            shader.uniform_float("lineWidth", 2.0 * scale)
            shader.uniform_float("color", s.color_current)
            batch.draw(shader)

        if s.show_key_numbers:
            font = 0
            blf.size(font, 11 * scale)
            blf.color(font, 1.0, 1.0, 1.0, 0.9)
            for trail in trails.TRAILS.values():
                f0, f1 = trails.visible_range(scene, trail)
                for f in trail.keys:
                    if f < f0 or f > f1:
                        continue
                    co = trail.position(f)
                    p = location_3d_to_region_2d(region, rv3d, co) if co is not None else None
                    if p is not None:
                        blf.position(font, p.x + 6 * scale, p.y + 6 * scale, 0)
                        blf.draw(font, str(f))

    box = trails.state.box
    if box is not None:
        x0, y0, x1, y1 = box
        rect = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0), (x0, y0, 0)]
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": rect})
        shader.bind()
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", 1.0 * scale)
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.8))
        batch.draw(shader)
        fill = gpu.shader.from_builtin('UNIFORM_COLOR')
        tris = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y0, 0), (x1, y1, 0), (x0, y1, 0)]
        batch = batch_for_shader(fill, 'TRIS', {"pos": tris})
        fill.bind()
        fill.uniform_float("color", (1.0, 1.0, 1.0, 0.06))
        batch.draw(fill)

    gpu.state.blend_set('NONE')


def register():
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_view, (), 'WINDOW', 'POST_VIEW'))
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_pixel, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    for handle in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _handles.clear()
