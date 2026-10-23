"""Shared helpers of the animation tools: what is selected, its F-Curves, the character's meshes."""
import re

import bpy

from . import trails

_BONE_PATH = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)*)"\]')
_UNESCAPE = re.compile(r'\\(.)')
EULER_ORDERS = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}


def bone_of_path(data_path):
    """Bone name of a `pose.bones["name"]...` path, "" for the object's own channels."""
    m = _BONE_PATH.match(data_path)
    return _UNESCAPE.sub(r'\1', m.group(1)) if m else ""


def targets(context):
    """{object: set of bone names} the tools act on: selected bones in Pose Mode, else selected objects ("")."""
    out = {}
    if context.mode == 'POSE':
        for pb in context.selected_pose_bones or ():
            out.setdefault(pb.id_data, set()).add(pb.name)
    elif context.mode == 'OBJECT':
        for ob in context.selected_objects or ():
            out.setdefault(ob, set()).add("")
    return out


def channels(context, props=None):
    """[(object, bone name, F-Curve)] of the selection, unlocked. `props`: only these properties
    (e.g. {"rotation_euler"}); a channel's property is its data path without the bone part."""
    out = []
    for ob, bones in targets(context).items():
        for fc in trails.action_fcurves(ob):
            if fc.lock:
                continue
            bone = bone_of_path(fc.data_path)
            if bone not in bones:
                continue
            if props is not None and channel_prop(fc.data_path) not in props:
                continue
            out.append((ob, bone, fc))
    return out


def channel_prop(data_path):
    """`location` for both `location` and `pose.bones["x"].location`."""
    m = _BONE_PATH.match(data_path)
    rest = data_path[m.end():] if m else data_path
    return rest[1:] if rest.startswith(".") else rest


def owner(ob, bone):
    return ob.pose.bones.get(bone) if bone else ob


def shift_key(kp, delta):
    """Move a key's value and its handles together (keeps the curve's shape around it)."""
    kp.co.y += delta
    kp.handle_left.y += delta
    kp.handle_right.y += delta


def neighbors(fc, frame):
    """(previous key, next key) around `frame`, a key exactly on `frame` excluded; None when missing."""
    prev = nxt = None
    for kp in fc.keyframe_points:
        x = kp.co.x
        if x < frame - 0.5:
            prev = kp
        elif x > frame + 0.5:
            nxt = kp
            break
    return prev, nxt


def _deformed_by(ob, armatures):
    for mod in ob.modifiers:
        if mod.type == 'ARMATURE' and mod.object in armatures:
            return True
    parent = ob.parent
    while parent is not None:
        if parent in armatures:
            return True
        parent = parent.parent
    return False


def character_meshes(context):
    """Visible meshes of the character: deformed by / parented to the rig in Pose Mode or the selected
    rigs, plus selected meshes."""
    if context.mode == 'POSE':
        armatures = {ob for ob in context.objects_in_mode if ob.type == 'ARMATURE'}
        meshes = set()
    else:
        selected = context.selected_objects or ()
        armatures = {ob for ob in selected if ob.type == 'ARMATURE'}
        meshes = {ob for ob in selected if ob.type == 'MESH'}
    if armatures:
        meshes.update(ob for ob in context.view_layer.objects if ob.type == 'MESH' and _deformed_by(ob, armatures))
    return sorted((ob for ob in meshes if ob.visible_get()), key=lambda ob: ob.name)


def redraw_all(context=None):
    wm = (context or bpy.context).window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'TIMELINE'}:
                area.tag_redraw()


def overlays_on(space):
    overlay = getattr(space, "overlay", None)
    return overlay is None or overlay.show_overlays


def window_override():
    """temp_override() arguments for code run from timers (no window there, so no selected_pose_bones...):
    the first 3D Viewport of the first window that has one."""
    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return {}
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                return {"window": window, "area": area, "region": region}
    return {"window": wm.windows[0]}
