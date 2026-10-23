"""Onion skin: the character at the previous / next keys (or every few frames) around the playhead, drawn as
see-through silhouettes (before: one colour, after: another, fading with distance).

Other frames can only be evaluated by moving the scene there (frame_set), so this happens once per frame and
is cached until the animation changes; never during playback or a drag. Pose changes that are not keyed yet are
put back after the evaluation (a frame change would otherwise drop them).
"""
import time

import bpy
import numpy as np
from bpy.types import Operator

from . import common, ghosts, trails

MAX_CACHE = 24


class _State:
    enabled = False
    objects = ()  # names of the meshes
    cache = {}  # frame -> Ghost
    shown = ((), ())  # (frames before, frames after) the playhead, nearest last / first
    dirty = False  # the animation changed: cached frames are outdated
    building = False
    pending = False
    last_request = 0.0
    last_ms = 0.0  # how long the last update took
    mask = None  # Ghost of the character as it is now: the onion is hidden where the character is
    mask_pending = False


state = _State()


def is_enabled():
    return state.enabled


def meshes():
    return [ob for ob in (bpy.data.objects.get(name) for name in state.objects) if ob is not None]


def _animated(objects):
    """The objects whose animation moves the meshes: the meshes, the rigs deforming them, their parents."""
    out = set()
    for ob in objects:
        chain = [ob] + [m.object for m in ob.modifiers if m.type == 'ARMATURE' and m.object is not None]
        for item in chain:
            while item is not None and item not in out:
                out.add(item)
                item = item.parent
    return out


def key_frames(objects):
    frames = set()
    for ob in _animated(objects):
        for fc in trails.action_fcurves(ob):
            n = len(fc.keyframe_points)
            if n:
                co = np.empty(n * 2, dtype=np.float32)
                fc.keyframe_points.foreach_get("co", co)
                frames.update(int(round(x)) for x in co[0::2])
    return frames


def wanted_frames(scene, objects):
    s = scene.anim_tools
    cur = scene.frame_current
    if s.onion_mode == 'KEYS':
        keys = sorted(key_frames(objects))
        before = [f for f in keys if f < cur][-s.onion_before:] if s.onion_before else []
        after = [f for f in keys if f > cur][:s.onion_after]
    else:
        before = [cur - s.onion_step * i for i in range(s.onion_before, 0, -1)]
        after = [cur + s.onion_step * i for i in range(1, s.onion_after + 1)]
    return before, after


# ---------------------------------------------------------------------------
# Keeping not-yet-keyed pose changes across the frame jumps
# ---------------------------------------------------------------------------

def _resolve(ob, path, index):
    value = ob.path_resolve(path)
    if hasattr(value, "__len__") and not isinstance(value, str):
        return value[index]
    return value


def _assign(ob, path, index, value):
    if path.endswith('"]'):
        i = path.rfind('["')
        owner = ob.path_resolve(path[:i]) if i > 0 else ob
        key = path[i + 2:-2].replace('\\"', '"').replace('\\\\', '\\')
        current = owner[key]
        if hasattr(current, "__len__") and not isinstance(current, str):
            current[index] = value
        else:
            owner[key] = value
        return
    i = path.rfind('.')
    owner = ob.path_resolve(path[:i]) if i > 0 else ob
    attr = path[i + 1:]
    current = getattr(owner, attr)
    if hasattr(current, "__len__") and not isinstance(current, str):
        current[index] = value
    else:
        setattr(owner, attr, value)


def snapshot(scene):
    """[(object, path, index, value)] of every animated property in the scene, as it is now."""
    out = []
    for ob in scene.objects:
        for fc in trails.action_fcurves(ob):
            try:
                out.append((ob, fc.data_path, fc.array_index, _resolve(ob, fc.data_path, fc.array_index)))
            except (ValueError, AttributeError, IndexError, KeyError, TypeError):
                pass
    return out


def restore(saved):
    """Put back the values that the frame jumps changed (= the changes that were not keyed)."""
    restored = 0
    for ob, path, index, value in saved:
        try:
            if _resolve(ob, path, index) != value:
                _assign(ob, path, index, value)
                restored += 1
        except (ValueError, AttributeError, IndexError, KeyError, TypeError):
            pass
    return restored


# ---------------------------------------------------------------------------
# Updating
# ---------------------------------------------------------------------------

def update(context):
    """Evaluate the onion frames that are not cached yet (moves the scene there and back)."""
    scene = context.scene
    objects = meshes()
    if not objects:
        state.shown = ((), ())
        return
    if state.dirty:
        state.cache.clear()
        state.dirty = False
    before, after = wanted_frames(scene, objects)
    needed = [f for f in after + before[::-1] if f not in state.cache]  # nearest first
    if needed:
        t0 = time.perf_counter()
        cur, sub = scene.frame_current, scene.frame_subframe
        saved = snapshot(scene)
        state.building = True
        try:
            for f in needed:
                scene.frame_set(f)
                ghost = ghosts.make_ghost(context, objects, f)
                if ghost is not None:
                    state.cache[f] = ghost
        finally:
            scene.frame_set(cur, subframe=sub)
            if restore(saved):
                context.view_layer.update()
            state.building = False
        state.last_ms = (time.perf_counter() - t0) * 1000.0
    build_mask(context, objects)
    state.shown = (tuple(before), tuple(after))
    if len(state.cache) > MAX_CACHE:
        keep = set(before) | set(after)
        far = sorted((f for f in state.cache if f not in keep), key=lambda f: -abs(f - scene.frame_current))
        for f in far[:len(state.cache) - MAX_CACHE]:
            del state.cache[f]


def build_mask(context, objects=None):
    if context.scene.anim_tools.onion_behind:
        state.mask = ghosts.make_ghost(context, objects or meshes(), context.scene.frame_current)
    else:
        state.mask = None


def request_mask():
    if state.enabled and not state.mask_pending:
        state.mask_pending = True
        bpy.app.timers.register(_mask_timer, first_interval=0.08)


def _mask_timer():
    if not state.enabled or bpy.context.scene is None:
        state.mask_pending = False
        return None
    if _busy():
        return 0.1
    state.mask_pending = False
    with bpy.context.temp_override(**common.window_override()):
        build_mask(bpy.context)
    common.redraw_all()
    return None


def _busy():
    return trails.blender_busy() or trails.state.transforming or trails.state.building or \
        bpy.app.is_job_running('RENDER')


def request_update(delay=0.12):
    if not state.enabled:
        return
    state.last_request = time.monotonic()
    if not state.pending:
        state.pending = True
        bpy.app.timers.register(_timer, first_interval=delay)


def _timer():
    if not state.enabled or bpy.context.scene is None:
        state.pending = False
        return None
    if _busy() or time.monotonic() - state.last_request < 0.1:
        return 0.1  # scrubbing / playing / dragging: wait until it settles
    state.pending = False
    with bpy.context.temp_override(**common.window_override()):
        update(bpy.context)
    common.redraw_all()
    return None


def on_frame_change(scene):
    if state.enabled and not state.building:
        request_update()


def on_depsgraph_update(depsgraph):
    if not state.enabled or state.building:
        return
    watched = None
    for u in depsgraph.updates:
        if isinstance(u.id, bpy.types.Action):
            state.dirty = True  # keys changed: evaluate the onion frames again
            request_update(0.25)
            return
        if isinstance(u.id, bpy.types.Object):
            if watched is None:
                watched = {ob.name for ob in _animated(meshes())}
            if u.id.name in watched:
                request_mask()  # the character moved: where the onion is hidden changes too


def enable(context, objects):
    state.enabled = True
    state.objects = tuple(ob.name for ob in objects)
    state.cache.clear()
    state.shown = ((), ())
    state.dirty = False
    state.mask = None
    request_update(0.01)


def disable():
    state.enabled = False
    state.cache.clear()
    state.shown = ((), ())
    state.mask = None


def draw_mask(context):
    """The current silhouette of the character, for hiding the onion behind it (None: draw over everything)."""
    if not state.enabled or not context.scene.anim_tools.onion_behind:
        return None
    return state.mask


def draw_items(context):
    """[(ghost, colour, flat)] to draw now, farthest first."""
    if not state.enabled or context.screen is None or context.screen.is_animation_playing:
        return []
    s = context.scene.anim_tools
    before, after = state.shown
    items = []
    for frames, color in ((before, s.ghost_color_before), (after[::-1], s.ghost_color_after)):
        n = len(frames)
        for i, f in enumerate(frames):  # i == n - 1 is the nearest
            ghost = state.cache.get(f)
            if ghost is None:
                continue
            fade = 1.0 if n == 1 else 0.45 + 0.55 * i / (n - 1)
            items.append((ghost, (color[0], color[1], color[2], color[3] * fade), s.onion_flat))
    return items


class ANIMTOOLS_OT_onion(Operator):
    """Onion Skin: show the character at the previous and next keys (or every few frames) as see-through
    silhouettes. Uses the rig in Pose Mode or the selected rigs / meshes"""
    bl_idname = "anim_tools.onion"
    bl_label = "Onion Skin"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if state.enabled:
            disable()
        else:
            objects = common.character_meshes(context)
            if not objects:
                self.report({'WARNING'}, "Select the rig (Pose Mode) or the character's meshes")
                return {'CANCELLED'}
            enable(context, objects)
        common.redraw_all(context)
        return {'FINISHED'}


class ANIMTOOLS_OT_onion_retarget(Operator):
    """Show the onion skin for the current selection (the rig in Pose Mode or the selected rigs / meshes)"""
    bl_idname = "anim_tools.onion_retarget"
    bl_label = "Use Selection"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        objects = common.character_meshes(context)
        if not objects:
            self.report({'WARNING'}, "Select the rig (Pose Mode) or the character's meshes")
            return {'CANCELLED'}
        enable(context, objects)
        return {'FINISHED'}


classes = (ANIMTOOLS_OT_onion, ANIMTOOLS_OT_onion_retarget)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    disable()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
