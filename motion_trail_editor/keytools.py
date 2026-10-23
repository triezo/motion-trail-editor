"""Key tools: Tween / Breakdowner at the current frame, and the Euler Filter.

Both act on the selected bones (Pose Mode) or selected objects (Object Mode), all their unlocked channels.
"""
import math

import bpy
from bpy.props import EnumProperty, FloatProperty
from bpy.types import Operator
from mathutils import Euler

from . import common, trails

MODES = (
    ('TWEEN', "Tween", "In-between of the previous and the next key (left end: previous key, right end: next key)",
     'IPO_EASE_IN_OUT', 0),
    ('NEIGHBOR', "Blend to Neighbor", "Move the pose toward the previous key (left) or the next key (right)",
     'ARROW_LEFTRIGHT', 1),
    ('PUSH', "Push / Pull", "Flatten the pose toward the in-between of its neighbors (left) or exaggerate it (right)",
     'FULLSCREEN_ENTER', 2),
)
MODE_ICONS = {m[0]: m[3] for m in MODES}
FACTORS = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)


def describe(mode, factor):
    if mode == 'TWEEN':
        return f"Tween {round((factor + 1.0) * 50.0)}%"
    if mode == 'NEIGHBOR':
        side = "previous" if factor < 0 else "next"
        return f"Blend {round(abs(factor) * 100.0)}% to the {side} key"
    return f"{'Pull' if factor < 0 else 'Push'} {round(abs(factor) * 100.0)}%"


class TweenJob:
    """The channels changed at the current frame, with what is needed to apply any factor and to undo."""

    def __init__(self, context, mode):
        self.mode = mode
        self.frame = context.scene.frame_current
        self.key_type = context.scene.tool_settings.keyframe_type
        self.items = []  # (fcurve, previous value, next value, in-between line value, current value, old key)
        for _ob, _bone, fc in common.channels(context):
            prev, nxt = common.neighbors(fc, self.frame)
            if (prev is None or nxt is None) and (mode != 'NEIGHBOR' or (prev is None and nxt is None)):
                continue
            p = prev.co.y if prev else None
            n = nxt.co.y if nxt else None
            line = None
            if prev and nxt:
                line = p + (n - p) * (self.frame - prev.co.x) / (nxt.co.x - prev.co.x)
            kp = trails.find_key(fc, self.frame)
            old = (tuple(kp.co), tuple(kp.handle_left), tuple(kp.handle_right)) if kp else None
            self.items.append((fc, p, n, line, fc.evaluate(self.frame), old))

    def start_factor(self):
        """Factor that matches the current pose best (Tween), so a drag starts where the pose is."""
        if self.mode != 'TWEEN':
            return 0.0
        ts = [(cur - p) / (n - p) for _fc, p, n, _line, cur, _old in self.items if abs(n - p) > 1e-6]
        return max(-1.0, min(1.0, 2.0 * sum(ts) / len(ts) - 1.0)) if ts else 0.0

    def value(self, item, factor):
        _fc, p, n, line, cur, _old = item
        if self.mode == 'TWEEN':
            return p + (n - p) * (factor + 1.0) * 0.5
        if self.mode == 'NEIGHBOR':
            target = p if factor < 0 else n
            return cur if target is None else cur + (target - cur) * abs(factor)
        return line + (cur - line) * (1.0 + factor)

    def apply(self, factor):
        for item in self.items:
            fc = item[0]
            value = self.value(item, factor)
            kp = trails.find_key(fc, self.frame)
            if kp is None:
                kp = fc.keyframe_points.insert(self.frame, value, options={'FAST'})
                kp.type = self.key_type
            else:
                common.shift_key(kp, value - kp.co.y)
            fc.update()

    def restore(self):
        for fc, _p, _n, _line, _cur, old in self.items:
            kp = trails.find_key(fc, self.frame)
            if kp is None:
                continue
            if old is None:
                fc.keyframe_points.remove(kp)
            else:
                kp.co, kp.handle_left, kp.handle_right = old
            fc.update()


def _poll(context):
    return context.mode in {'POSE', 'OBJECT'} and bool(common.targets(context))


def _no_keys(op, mode):
    if mode == 'NEIGHBOR':
        op.report({'WARNING'}, "No keys on the selected bones / objects")
    else:
        op.report({'WARNING'}, "Needs keys before and after the current frame on the selected bones / objects")


class ANIMTOOLS_OT_tween(Operator):
    """Blend the pose of the selected bones / objects at the current frame (keys it)"""
    bl_idname = "anim_tools.tween"
    bl_label = "Tween"
    bl_options = {'REGISTER', 'UNDO'}

    factor: FloatProperty(name="Factor", default=0.0, soft_min=-1.0, soft_max=1.0, min=-3.0, max=3.0)
    mode: EnumProperty(name="Mode", items=[m[:3] for m in MODES], options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _poll(context)

    @classmethod
    def description(cls, context, properties):
        return describe(context.scene.anim_tools.tween_mode, properties.factor)

    def invoke(self, context, event):
        self.mode = context.scene.anim_tools.tween_mode
        return self.execute(context)

    def execute(self, context):
        job = TweenJob(context, self.mode)
        if not job.items:
            _no_keys(self, self.mode)
            return {'CANCELLED'}
        job.apply(self.factor)
        common.redraw_all(context)
        return {'FINISHED'}


class ANIMTOOLS_OT_tween_drag(Operator):
    """Drag left / right to blend the pose (Ctrl: steps). Click or Enter: apply, right-click or Esc: cancel"""
    bl_idname = "anim_tools.tween_drag"
    bl_label = "Tween (Drag)"
    bl_options = {'REGISTER', 'UNDO'}

    PIXELS = 300.0  # mouse travel for the whole -1..1 range

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        mode = context.scene.anim_tools.tween_mode
        self.job = TweenJob(context, mode)
        if not self.job.items:
            _no_keys(self, mode)
            return {'CANCELLED'}
        self.x0 = event.mouse_x
        self.f0 = self.factor = self.job.start_factor()
        self._status(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _status(self, context):
        text = f"{describe(self.job.mode, self.factor)}   ·   drag ←/→,  Ctrl: steps,  click / Enter: apply,  " \
               f"right-click / Esc: cancel"
        context.workspace.status_text_set(text)

    def _finish(self, context):
        context.workspace.status_text_set(None)
        common.redraw_all(context)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            scale = context.preferences.system.ui_scale
            f = self.f0 + 2.0 * (event.mouse_x - self.x0) / (self.PIXELS * scale)
            if event.ctrl:
                f = round(f * 4.0) / 4.0
            self.factor = max(-1.5, min(1.5, f))
            self.job.apply(self.factor)
            self._status(context)
            common.redraw_all(context)
        elif event.value == 'PRESS' and event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'}:
            self.job.apply(self.factor)
            self._finish(context)
            return {'FINISHED'}
        elif event.value == 'PRESS' and event.type in {'RIGHTMOUSE', 'ESC'}:
            self.job.restore()
            self._finish(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


# ---------------------------------------------------------------------------
# Euler Filter
# ---------------------------------------------------------------------------

TURN = 2.0 * math.pi


def _unwrap(fc):
    """Remove jumps of whole turns between consecutive keys (like Blender's Euler Filter)."""
    prev = None
    for kp in fc.keyframe_points:
        if prev is not None:
            d = kp.co.y - prev
            if abs(d) >= math.pi:
                common.shift_key(kp, -math.floor(d / TURN + 0.5) * TURN)
        prev = kp.co.y


def _closest(e, prev, order):
    """The rotation `e` written as the Euler closest to `prev` (handles 360° jumps and gimbal flips)."""
    alt = e.to_matrix().to_euler(order, prev)
    dist = sum(abs(a - b) for a, b in zip(e, prev))
    return alt if sum(abs(a - b) for a, b in zip(alt, prev)) < dist - 1e-4 else e


def euler_filter(chans):
    """Fix the rotation_euler curves of `chans` [(object, bone, fcurve)]. Returns how many keys changed."""
    groups = {}
    for ob, bone, fc in chans:
        if fc.array_index < 3:
            groups.setdefault((ob, bone, fc.data_path), [None, None, None])[fc.array_index] = fc
    changed = 0
    for (ob, bone, _path), fcs in groups.items():
        curves = [fc for fc in fcs if fc is not None]
        before = [[kp.co.y for kp in fc.keyframe_points] for fc in curves]
        for fc in curves:
            _unwrap(fc)
        if len(curves) == 3:
            own = common.owner(ob, bone)
            order = own.rotation_mode if own is not None and own.rotation_mode in common.EULER_ORDERS else 'XYZ'
            keys = [{int(round(kp.co.x)): kp for kp in fc.keyframe_points} for fc in fcs]
            prev = None
            for frame in sorted(set(keys[0]) & set(keys[1]) & set(keys[2])):
                kps = [k[frame] for k in keys]
                e = Euler([kp.co.y for kp in kps], order)
                if prev is not None:
                    best = _closest(e, prev, order)
                    if best is not e:
                        for kp, v in zip(kps, best):
                            common.shift_key(kp, v - kp.co.y)
                        e = best
                prev = e
        for fc, old in zip(curves, before):
            changed += sum(abs(kp.co.y - v) > 1e-6 for kp, v in zip(fc.keyframe_points, old))
            fc.update()
    return changed


class ANIMTOOLS_OT_euler_filter(Operator):
    """Fix 360° jumps and gimbal flips in the Euler rotation keys of the selected bones / objects"""
    bl_idname = "anim_tools.euler_filter"
    bl_label = "Euler Filter"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        chans = common.channels(context, props={"rotation_euler"})
        if not chans:
            self.report({'WARNING'}, "No Euler rotation keys on the selected bones / objects")
            return {'CANCELLED'}
        n = euler_filter(chans)
        self.report({'INFO'}, f"Euler Filter: {n} key(s) fixed" if n else "Euler Filter: nothing to fix")
        common.redraw_all(context)
        return {'FINISHED'}


classes = (ANIMTOOLS_OT_tween, ANIMTOOLS_OT_tween_drag, ANIMTOOLS_OT_euler_filter)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
