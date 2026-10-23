"""AnimOffset: while it is on, a pose change of the selected bones / objects at the current frame is added to
all their keys (or to the keys inside the mask frames), so the whole animation moves with it.

Auto Keying is switched off meanwhile (it would key the change at the current frame only) and restored after.
"""
import blf
import bpy
from bpy.types import Operator, Panel

from . import common, trails

OFFSET_PROPS = {"location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale"}
_ROTATION_PROP = {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}
EPS = 1e-5


class _State:
    enabled = False
    auto_key = False
    pending = False
    blocked = set()  # (object name, data path, index) channels that do not follow their curve (drivers, NLA)
    draw_handle = None


state = _State()


def is_enabled():
    return state.enabled


def _mask(scene):
    s = scene.anim_tools
    return (s.offset_start, s.offset_end) if s.offset_use_mask else None


def _evaluates_action(ob):
    """The action's value reaches the property unchanged (no NLA blending / tweak mode / partial influence)."""
    adt = ob.animation_data
    return adt is not None and adt.action is not None and not adt.use_tweak_mode \
        and adt.action_blend_type == 'REPLACE' and adt.action_influence > 0.999


def _offset_channels(context):
    """[(object, fcurve, current property value)] of the selection's transform channels."""
    out = []
    by_object = {}
    for ob, bone, fc in common.channels(context, props=OFFSET_PROPS):
        by_object.setdefault(ob, []).append((bone, fc))
    for ob, items in by_object.items():
        if not _evaluates_action(ob):
            continue
        driven = {(d.data_path, d.array_index) for d in ob.animation_data.drivers}
        for bone, fc in items:
            if (fc.data_path, fc.array_index) in driven or (ob.name, fc.data_path, fc.array_index) in state.blocked:
                continue
            own = common.owner(ob, bone)
            if own is None or len(fc.keyframe_points) == 0:
                continue
            prop = common.channel_prop(fc.data_path)
            if prop.startswith("rotation_") and prop != _ROTATION_PROP.get(own.rotation_mode, "rotation_euler"):
                continue  # not the rotation the bone uses: its value does not come from this curve
            try:
                value = getattr(own, prop)[fc.array_index]
            except (AttributeError, IndexError):
                continue
            out.append((ob, fc, value))
    return out


def _ensure_key(fc, frame):
    if trails.find_key(fc, frame) is None:
        fc.keyframe_points.insert(frame, fc.evaluate(frame), options={'FAST'})


def apply_offsets(context):
    """Move the keys of every selected channel whose value differs from its curve. Returns the channels moved."""
    scene = context.scene
    frame = scene.frame_current
    mask = _mask(scene)
    if mask and not (mask[0] <= frame <= mask[1]):
        return []
    moved = []
    for ob, fc, value in _offset_channels(context):
        delta = value - fc.evaluate(frame)
        if abs(delta) < EPS:
            continue
        if mask:
            _ensure_key(fc, mask[0])  # the animation outside the mask stays as it is
            _ensure_key(fc, mask[1])
        for kp in fc.keyframe_points:
            if mask is None or mask[0] - 0.5 < kp.co.x < mask[1] + 0.5:
                common.shift_key(kp, delta)
        fc.update()
        moved.append((ob, fc))
    if moved:
        context.view_layer.update()
        # A channel still off its curve is not driven by it (driver, constraint on the property...): leave it.
        for ob, fc, value in _offset_channels(context):
            if (ob, fc) in moved and abs(value - fc.evaluate(frame)) > 1e-3:
                state.blocked.add((ob.name, fc.data_path, fc.array_index))
    return moved


def request_apply():
    if state.enabled and not state.pending:
        state.pending = True
        bpy.app.timers.register(_apply_timer, first_interval=0.05)


def _apply_timer():
    if not state.enabled or bpy.context.scene is None:
        state.pending = False
        return None
    if trails.blender_busy():
        return 0.1  # wait until the transform is confirmed
    state.pending = False
    with bpy.context.temp_override(**common.window_override()):
        moved = apply_offsets(bpy.context)
    if moved:
        common.redraw_all()
    return None


def _draw_banner():
    context = bpy.context
    region = context.region
    if not state.enabled or region is None or not common.overlays_on(context.space_data):
        return
    mask = _mask(context.scene)
    text = "AnimOffset" + (f"  (frames {mask[0]}–{mask[1]})" if mask else "  (whole animation)")
    if mask and not (mask[0] <= context.scene.frame_current <= mask[1]):
        text += "  — current frame is outside the mask"
    scale = context.preferences.system.ui_scale
    font = 0
    blf.size(font, 13 * scale)
    w, _h = blf.dimensions(font, text)
    blf.position(font, (region.width - w) / 2, region.height - 60 * scale, 0)
    blf.color(font, 1.0, 0.55, 0.15, 1.0)
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.8)
    blf.draw(font, text)
    blf.disable(font, blf.SHADOW)


def enable(context):
    if state.enabled:
        return
    tool_settings = context.scene.tool_settings
    state.auto_key = tool_settings.use_keyframe_insert_auto
    tool_settings.use_keyframe_insert_auto = False
    state.enabled = True
    state.blocked.clear()
    if state.draw_handle is None:
        state.draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_banner, (), 'WINDOW', 'POST_PIXEL')
    request_apply()  # a change made before switching on counts too
    common.redraw_all(context)


def disable(context=None, restore=True):
    if not state.enabled:
        return
    state.enabled = False
    context = context or bpy.context
    if restore and context.scene is not None and state.auto_key:
        context.scene.tool_settings.use_keyframe_insert_auto = True
    if state.draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(state.draw_handle, 'WINDOW')
        state.draw_handle = None
    common.redraw_all(context)


class ANIMTOOLS_OT_anim_offset(Operator):
    """AnimOffset: while on, moving the selected bones / objects moves their whole animation
    (or the mask frames) instead of keying the current frame. Auto Keying is paused meanwhile"""
    bl_idname = "anim_tools.anim_offset"
    bl_label = "AnimOffset"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if state.enabled:
            disable(context)
            self.report({'INFO'}, "AnimOffset off")
        else:
            enable(context)
            self.report({'INFO'}, "AnimOffset on: move the pose, the whole animation follows")
        return {'FINISHED'}


class ANIMTOOLS_OT_offset_mask_from_preview(Operator):
    """Use the preview range (or the scene range) as the mask"""
    bl_idname = "anim_tools.offset_mask_from_preview"
    bl_label = "Mask From Range"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        s = scene.anim_tools
        if scene.use_preview_range:
            s.offset_start, s.offset_end = scene.frame_preview_start, scene.frame_preview_end
        else:
            s.offset_start, s.offset_end = scene.frame_start, scene.frame_end
        s.offset_use_mask = True
        return {'FINISHED'}


class ANIMTOOLS_PT_offset(Panel):
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "AnimOffset Mask"
    bl_ui_units_x = 10

    def draw(self, context):
        layout = self.layout
        s = context.scene.anim_tools
        layout.prop(s, "offset_use_mask")
        col = layout.column(align=True)
        col.active = s.offset_use_mask
        col.prop(s, "offset_start")
        col.prop(s, "offset_end")
        col.operator("anim_tools.offset_mask_from_preview", icon='PREVIEW_RANGE')


classes = (ANIMTOOLS_OT_anim_offset, ANIMTOOLS_OT_offset_mask_from_preview, ANIMTOOLS_PT_offset)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    disable(restore=True)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
