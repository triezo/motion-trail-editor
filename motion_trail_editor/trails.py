"""Trail data: evaluation of world-space positions, key frames, selection and key editing helpers."""
import bisect
import time

import bpy
import numpy as np
from bpy_extras import anim_utils
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d
from mathutils import Matrix, Vector

TRANSFORM_PROPS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")


class Trail:
    """Evaluated motion of one object or pose bone, in world space, one position per frame."""

    __slots__ = ("key", "frame_start", "positions", "keys", "stale")

    def __init__(self, key, frame_start, positions, keys):
        self.key = key  # (object name, bone name or "")
        self.frame_start = frame_start
        self.positions = positions  # list[Vector]
        self.keys = keys  # sorted list[int] of frames with transform keys
        self.stale = False  # bone trail kept from Pose Mode while the armature is in another mode

    @property
    def frame_end(self):
        return self.frame_start + len(self.positions) - 1

    def position(self, frame):
        i = frame - self.frame_start
        if 0 <= i < len(self.positions):
            return self.positions[i]
        return None


class _State:
    building = False
    transforming = False
    rebuild_pending = False
    check_pending = False
    jacobians_pending = False
    signatures = {}  # key -> trail_signature() when the trail was last built
    exact = {}  # key -> signature (without mode) of the last real evaluation, to un-stale bone trails for free
    box = None  # (x0, y0, x1, y1) region coords while box-selecting
    last_rebuild = 0.0  # seconds the last rebuild took
    first_change = 0.0  # time.monotonic() of the first / last change since the last check
    last_change = 0.0


TRAILS = {}  # key -> Trail
SELECTION = {}  # key -> set of selected key frames
HANDLE_SELECTION = set()  # {(key, frame, 'L' | 'R')} selected handle ends
HOVER = [None]  # [(key, frame)] key point under the mouse
HOVER_HANDLE = [None]  # [(key, frame, side)] handle end under the mouse
JACOBIANS = {}  # (key, frame) -> 3x3 world change per unit of local location, for drawing/editing handles
MAX_HANDLE_KEYS = 24  # handles need one frame evaluation per key: cap it for heavy scenes
state = _State()


def reset():
    TRAILS.clear()
    SELECTION.clear()
    HANDLE_SELECTION.clear()
    JACOBIANS.clear()
    HOVER[0] = None
    HOVER_HANDLE[0] = None
    state.signatures.clear()
    state.exact.clear()
    state.box = None
    state.transforming = False


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def item_key(ob, bone_name):
    return (ob.name_full, bone_name or "")


def iter_items(scene):
    """Yield (key, object, pose bone or None) for every valid trail item of the scene."""
    for item in scene.motion_trail.items:
        ob = item.object
        if ob is None or scene.objects.get(ob.name) is None:
            continue
        pb = None
        if item.bone:
            if ob.type != 'ARMATURE':
                continue
            pb = ob.pose.bones.get(item.bone)
            if pb is None:
                continue
        yield item_key(ob, item.bone), ob, pb


def resolve(scene, key):
    """(object, pose bone or None) for a trail key, or (None, None)."""
    for k, ob, pb in iter_items(scene):
        if k == key:
            return ob, pb
    return None, None


def frame_range(scene):
    s = scene.motion_trail
    if s.range_mode == 'MANUAL':
        return s.frame_start, max(s.frame_end, s.frame_start)
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


def needed_range(scene):
    """Frames drawn right now: around the playhead, or the whole range when Before/After is 0 ("all")."""
    r0, r1 = frame_range(scene)
    s = scene.motion_trail
    cur = scene.frame_current
    n0 = r0 if s.frames_before == 0 else max(r0, cur - s.frames_before)
    n1 = r1 if s.frames_after == 0 else min(r1, cur + s.frames_after)
    return n0, n1


def eval_range(scene):
    """Frames to evaluate: what is drawn plus a margin, so moving the playhead a bit needs no new evaluation."""
    r0, r1 = frame_range(scene)
    s = scene.motion_trail
    cur = min(max(scene.frame_current, r0), r1)
    margin = max(s.frames_before, s.frames_after, 10)
    e0 = r0 if s.frames_before == 0 else max(r0, cur - s.frames_before - margin)
    e1 = r1 if s.frames_after == 0 else min(r1, cur + s.frames_after + margin)
    return e0, max(e0, e1)


def covers(trail, scene):
    n0, n1 = needed_range(scene)
    return n0 > n1 or (trail.frame_start <= n0 and trail.frame_end >= n1)


def shown_in(space):
    """Trails follow the viewport overlays: hidden with all overlays or with the Motion Paths overlay."""
    overlay = getattr(space, "overlay", None)
    return overlay is None or (overlay.show_overlays and overlay.show_motion_paths)


def visible_range(scene, trail):
    """Frames of the trail that are drawn and editable (around the playhead)."""
    s = scene.motion_trail
    cur = scene.frame_current
    f0, f1 = trail.frame_start, trail.frame_end
    if s.frames_before > 0:
        f0 = max(f0, cur - s.frames_before)
    if s.frames_after > 0:
        f1 = min(f1, cur + s.frames_after)
    return f0, f1


# ---------------------------------------------------------------------------
# Blender version differences
# ---------------------------------------------------------------------------

SLOTTED_ACTIONS = "action_slot" in bpy.types.AnimData.bl_rna.properties  # Blender 4.4+
POSE_BONE_SELECT = "select" in bpy.types.PoseBone.bl_rna.properties  # Blender 5.0+ (before: Bone.select)


def bone_selected(pb):
    return pb.select if POSE_BONE_SELECT else pb.bone.select


def select_bone(pb, value):
    if POSE_BONE_SELECT:
        pb.select = value
    else:
        pb.bone.select = value


# ---------------------------------------------------------------------------
# F-Curves
# ---------------------------------------------------------------------------

def action_fcurves(ob, ensure=False):
    """F-Curves of the object's action (its active slot since Blender 4.4); empty tuple when there are none."""
    adt = ob.animation_data
    if adt is None or adt.action is None:
        return ()
    if not SLOTTED_ACTIONS:
        return adt.action.fcurves
    if adt.action_slot is None:
        return ()
    if ensure:
        return anim_utils.action_ensure_channelbag_for_slot(adt.action, adt.action_slot).fcurves
    channelbag = anim_utils.action_get_channelbag_for_slot(adt.action, adt.action_slot)
    return channelbag.fcurves if channelbag else ()


def path_prefix(bone_name):
    if bone_name:
        return f'pose.bones["{bpy.utils.escape_identifier(bone_name)}"].'
    return ""


def transform_fcurves(ob, bone_name, props=TRANSFORM_PROPS):
    prefix = path_prefix(bone_name)
    n = len(prefix)
    return [fc for fc in action_fcurves(ob)
            if fc.data_path.startswith(prefix) and fc.data_path[n:] in props]


def location_fcurve(ob, bone_name, index, create=False):
    data_path = path_prefix(bone_name) + "location"
    fcurves = action_fcurves(ob, ensure=create)
    if not hasattr(fcurves, "find"):
        return None
    fc = fcurves.find(data_path, index=index)
    if fc is None and create:
        group = bone_name if bone_name else "Object Transforms"
        if SLOTTED_ACTIONS:
            fc = fcurves.ensure(data_path, index=index, group_name=group)
        else:
            fc = fcurves.new(data_path, index=index, action_group=group)
    return fc


def key_frames(ob, bone_name):
    frames = set()
    for fc in transform_fcurves(ob, bone_name):
        n = len(fc.keyframe_points)
        if n:
            co = np.empty(n * 2, dtype=np.float32)
            fc.keyframe_points.foreach_get("co", co)
            frames.update(int(round(x)) for x in co[0::2])
    return sorted(frames)


def find_key_index(fc, frame):
    for i, kp in enumerate(fc.keyframe_points):
        if abs(kp.co.x - frame) < 0.5:
            return i
    return None


def find_key(fc, frame):
    i = find_key_index(fc, frame)
    return None if i is None else fc.keyframe_points[i]


# ---------------------------------------------------------------------------
# What a trail depends on (so editing other bones or rigs does not rebuild it)
# ---------------------------------------------------------------------------

_OBJECT = ""  # the object's own channels (its location/rotation/scale), as opposed to a bone


def _constraint_targets(owner):
    for c in owner.constraints:
        if c.mute:
            continue
        for target_attr, sub_attr in (("target", "subtarget"), ("pole_target", "pole_subtarget")):
            target = getattr(c, target_attr, None)
            if isinstance(target, bpy.types.Object):
                yield target, getattr(c, sub_attr, "")
        for t in getattr(c, "targets", ()):  # Armature constraint (e.g. Rigify parent switching)
            if isinstance(getattr(t, "target", None), bpy.types.Object):
                yield t.target, getattr(t, "subtarget", "")


def dependencies(ob, pb):
    """{object name: (object, parts)} whose animation can move this trail.

    parts holds bone names and _OBJECT for the object's own channels: the bone, its parents, the targets of
    its constraints (IK, Child Of, Armature...), the armature object, its parents and their constraint targets.
    """
    deps = {}
    pending = [(ob, pb.name if pb is not None else _OBJECT)]
    while pending:
        o, part = pending.pop()
        parts = deps.setdefault(o.name_full, (o, set()))[1]
        if part in parts:
            continue
        parts.add(part)
        if part == _OBJECT:
            if o.parent is not None:
                bone_parent = o.parent_type == 'BONE' and o.parent_bone
                pending.append((o.parent, o.parent_bone if bone_parent else _OBJECT))
            for target, sub in _constraint_targets(o):
                pending.append((target, sub if sub and target.type == 'ARMATURE' else _OBJECT))
            continue
        pbone = o.pose.bones.get(part) if o.type == 'ARMATURE' and o.pose else None
        if pbone is None:
            continue
        pending.append((o, _OBJECT))
        if pbone.parent is not None:
            pending.append((o, pbone.parent.name))
        for target, sub in _constraint_targets(pbone):
            pending.append((target, sub if sub and target.type == 'ARMATURE' else _OBJECT))
    return deps


def _fingerprint(fc):
    n = len(fc.keyframe_points)
    if not n:
        return 0.0
    buf = np.empty(n * 2, dtype=np.float64)
    fc.keyframe_points.foreach_get("co", buf)
    total = float(buf.sum())
    fc.keyframe_points.foreach_get("handle_left", buf)
    total += float(buf.sum()) * 1.37
    fc.keyframe_points.foreach_get("handle_right", buf)
    total += float(buf.sum()) * 2.11
    return total + n * 7.0 + len(fc.data_path) * 0.013 + fc.array_index * 0.17


def trail_signature(scene, ob, pb):
    """Fingerprint of everything that shapes this trail: only the curves it depends on."""
    total = 0.0
    for o, parts in dependencies(ob, pb).values():
        prefixes = tuple(path_prefix(p) for p in parts if p != _OBJECT)
        own = _OBJECT in parts
        for fc in action_fcurves(o):
            dp = fc.data_path
            if dp.startswith('pose.bones["'):
                if not (prefixes and dp.startswith(prefixes)):
                    continue
            elif not own:
                continue
            total += _fingerprint(fc)
    s = scene.motion_trail
    mode = ob.mode if pb is not None else None  # bone trails are evaluated in Pose Mode only
    return (frame_range(scene), s.bake_location, mode, round(total, 6))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

_VIZ_PROPS = ("type", "range", "bake_location", "frame_start", "frame_end", "frame_step")


def _bake_with_paths(ob, pose_bones, f0, f1, bake_location):
    """Evaluate with Blender's motion path engine (fast, includes constraints and IK).

    Paths that did not exist before are cleared again so Blender does not draw them.
    """
    viz = (ob.pose if pose_bones else ob).animation_visualization.motion_path
    saved = {p: getattr(viz, p) for p in _VIZ_PROPS}
    targets = pose_bones if pose_bones else [ob]
    had_path = [t.motion_path is not None for t in targets]
    try:
        viz.frame_start, viz.frame_end, viz.frame_step = f0, f1, 1
        if pose_bones:
            override = dict(active_object=ob, object=ob, selected_pose_bones=pose_bones,
                            selected_pose_bones_from_active_object=pose_bones)
            with bpy.context.temp_override(**override):
                bpy.ops.pose.paths_calculate('EXEC_DEFAULT', False, display_type='RANGE', range='MANUAL',
                                             bake_location=bake_location)
        else:
            override = dict(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob])
            with bpy.context.temp_override(**override):
                bpy.ops.object.paths_calculate('EXEC_DEFAULT', False, display_type='RANGE', range='MANUAL')

        result = {}
        for t in targets:
            path = t.motion_path
            if path is None:
                raise RuntimeError("motion path was not created")
            key = item_key(ob, t.name if pose_bones else "")
            result[key] = (path.frame_start, [p.co.copy() for p in path.points])

        to_clear = [t for t, had in zip(targets, had_path) if not had]
        if to_clear:
            if pose_bones:
                # paths_clear reads the real bone selection, not the context: select only our bones meanwhile.
                # Only bones whose state differs are touched (big rigs have hundreds of bones).
                clear_names = {pb.name for pb in to_clear}
                changed = [(pb, bone_selected(pb)) for pb in ob.pose.bones
                           if bone_selected(pb) != (pb.name in clear_names)]
                try:
                    for pb, sel in changed:
                        select_bone(pb, not sel)
                    with bpy.context.temp_override(active_object=ob, object=ob):
                        bpy.ops.pose.paths_clear('EXEC_DEFAULT', False, only_selected=True)
                finally:
                    for pb, sel in changed:
                        select_bone(pb, sel)
            else:
                with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=to_clear,
                                               selected_editable_objects=to_clear):
                    bpy.ops.object.paths_clear('EXEC_DEFAULT', False, only_selected=True)
        return result
    finally:
        for p, v in saved.items():
            try:
                setattr(viz, p, v)
            except (AttributeError, TypeError, ValueError):
                pass


def _bake_with_frame_set(scene, targets, f0, f1, use_tail):
    """Fallback: step through the frames. targets: list of (key, object, pose bone or None)."""
    cur, sub = scene.frame_current, scene.frame_subframe
    result = {key: (f0, []) for key, _ob, _pb in targets}
    try:
        for f in range(f0, f1 + 1):
            scene.frame_set(f)
            for key, ob, pb in targets:
                if pb is not None:
                    co = ob.matrix_world @ (pb.tail if use_tail else pb.head)
                else:
                    co = ob.matrix_world.translation
                result[key][1].append(co.copy())
    finally:
        scene.frame_set(cur, subframe=sub)
    return result


def rebuild(keys=None, frames=None):
    """Re-evaluate trails (all, or only `keys`).

    frames: (first, last) re-evaluates only that part of trails that already exist (after a local edit).
    Returns {key: set of frames} of keys that appeared inside the previously evaluated range.
    """
    scene = bpy.context.scene
    if scene is None:
        return {}
    started = time.perf_counter()
    s = scene.motion_trail
    before = {k: (set(t.keys), t.frame_start, t.frame_end) for k, t in TRAILS.items()}
    items = [(k, ob, pb) for k, ob, pb in iter_items(scene) if keys is None or k in keys]
    valid = {k for k, _ob, _pb in iter_items(scene)}
    signatures = {k: trail_signature(scene, ob, pb) for k, ob, pb in items}

    # Evaluate only around the playhead (plus a margin); a local edit only re-evaluates its stretch.
    f0, f1 = eval_range(scene)
    partial = False
    if frames is not None and items and all(k in TRAILS for k, _ob, _pb in items):
        partial = True
        f0 = max(frames[0], max(TRAILS[k].frame_start for k, _ob, _pb in items))
        f1 = min(frames[1], min(TRAILS[k].frame_end for k, _ob, _pb in items))

    state.building = True
    try:
        evaluated = {}
        pose_groups = {}
        objects = []
        fallback = []
        kept = []
        for key, ob, pb in items:
            trail = TRAILS.get(key)
            if partial and f1 < f0:
                kept.append(key)  # the edit is outside the evaluated frames: only the key list changes
            elif pb is not None:
                if ob.mode == 'POSE':
                    if trail is not None and trail.stale and covers(trail, scene) and frames is None \
                            and state.exact.get(key) == signatures[key][:2] + signatures[key][3:]:
                        trail.stale = False  # nothing changed while it was out of Pose Mode
                        kept.append(key)
                    else:
                        pose_groups.setdefault(ob.name_full, (ob, []))[1].append(pb)
                elif trail is not None:
                    # Outside Pose Mode only frame stepping could evaluate bones, which takes seconds in big
                    # scenes: keep the last trail (drawn faded) until the armature is back in Pose Mode.
                    trail.stale = True
                    kept.append(key)
                else:
                    fallback.append((key, ob, pb))
            else:
                objects.append((key, ob, pb))
        for key, ob, pb in items:
            if key in kept:
                TRAILS[key].keys = key_frames(ob, pb.name if pb else "")
                state.signatures[key] = signatures[key]

        for ob, pbs in pose_groups.values():
            try:
                evaluated.update(_bake_with_paths(ob, pbs, f0, f1, s.bake_location))
            except Exception as e:  # noqa: BLE001 - any failure falls back to frame stepping
                print(f"Motion Trail: path engine failed for {ob.name} ({e}), using frame stepping")
                fallback.extend((item_key(ob, pb.name), ob, pb) for pb in pbs)
        for key, ob, pb in objects:
            try:
                evaluated.update(_bake_with_paths(ob, None, f0, f1, s.bake_location))
            except Exception as e:  # noqa: BLE001
                print(f"Motion Trail: path engine failed for {ob.name} ({e}), using frame stepping")
                fallback.append((key, ob, pb))
        if fallback:
            # First evaluation of a bone outside Pose Mode: frame stepping (slow), at most 300 frames around
            # the playhead. The whole range is evaluated once the armature is in Pose Mode.
            cur = scene.frame_current
            w0, w1 = max(f0, cur - 150), min(f1, cur + 150)
            evaluated.update(_bake_with_frame_set(scene, fallback, w0, max(w0, w1), s.bake_location == 'TAILS'))

        for key, ob, pb in items:
            if key not in evaluated:
                continue
            start, positions = evaluated[key]
            frames_with_keys = key_frames(ob, pb.name if pb else "")
            if partial:
                trail = TRAILS[key]
                i = start - trail.frame_start
                trail.positions[i:i + len(positions)] = positions
                trail.keys = frames_with_keys
            else:
                TRAILS[key] = Trail(key, start, positions, frames_with_keys)
            state.signatures[key] = signatures[key]
            state.exact[key] = signatures[key][:2] + signatures[key][3:]

        for key in list(TRAILS):
            if key not in valid:
                del TRAILS[key]
        for key in list(state.signatures):
            if key not in valid:
                state.signatures.pop(key, None)
                state.exact.pop(key, None)
        for key in list(SELECTION):
            if key not in TRAILS:
                del SELECTION[key]
            else:
                SELECTION[key] &= set(TRAILS[key].keys)
        HANDLE_SELECTION.intersection_update(
            {h for h in HANDLE_SELECTION if h[0] in TRAILS and h[1] in TRAILS[h[0]].keys})

        added = {}
        for key, trail in TRAILS.items():
            if key in before:
                old_keys, b0, b1 = before[key]
                new = {f for f in trail.keys if f not in old_keys and b0 <= f <= b1}
                if new:
                    added[key] = new
        return added
    finally:
        state.building = False
        state.last_rebuild = time.perf_counter() - started


def request_rebuild(delay=0.02):
    """Rebuild on the next timer tick (coalesces many requests)."""
    if state.rebuild_pending:
        return
    state.rebuild_pending = True
    bpy.app.timers.register(_rebuild_timer, first_interval=delay)


_INSERT_KEY_OPS = ("ANIM_OT_keyframe_insert", "GRAPH_OT_keyframe_insert", "ACTION_OT_keyframe_insert",
                   "MOTION_TRAIL_OT")


def keys_from_auto_keying(scene):
    """New keys came from Auto Keying: it is on and the last operator was not an Insert Keyframe one."""
    if not scene.tool_settings.use_keyframe_insert_auto:
        return False
    operators = bpy.context.window_manager.operators
    last = operators[-1].bl_idname if len(operators) else ""
    return not last.startswith(_INSERT_KEY_OPS)


def outdated_trails(scene):
    """Keys of trails to rebuild: their curves/parents/constraint targets changed, or the playhead moved
    out of the evaluated frames. Also True when trails were removed (undo)."""
    items = list(iter_items(scene))
    outdated = set()
    for key, ob, pb in items:
        trail = TRAILS.get(key)
        if trail is None or not covers(trail, scene) or state.signatures.get(key) != trail_signature(scene, ob, pb):
            outdated.add(key)
    removed = set(TRAILS) - {key for key, _ob, _pb in items}
    return outdated, bool(removed)


def _external_rebuild(keys=None):
    """Rebuild after a change made outside the addon (keying, Graph Editor, undo...): only outdated trails."""
    scene = bpy.context.scene
    if keys is None:
        keys, removed = outdated_trails(scene)
        if not keys and not removed:
            return
    for jac_key in [k for k in JACOBIANS if k[0] in keys]:
        del JACOBIANS[jac_key]  # parents or constraints may have changed
    added = rebuild(keys)
    mode = scene.motion_trail.select_new_keys
    if added and (mode == 'ALL' or (mode == 'MANUAL' and not keys_from_auto_keying(scene))):
        # Keys that just appeared (I, auto-key, undo) become the selection, like in the Graph Editor.
        SELECTION.clear()
        HANDLE_SELECTION.clear()
        for key, frames in added.items():
            SELECTION[key] = set(frames)
        sync_key_selection(bpy.context)
    ensure_jacobians(scene)
    from . import draw
    draw.tag_redraw_all()


def _rebuild_timer():
    if bpy.context.scene is None:
        state.rebuild_pending = False
        return None
    if state.transforming or blender_busy():
        return 0.1  # try again once the transform / playback is over
    state.rebuild_pending = False
    _external_rebuild()
    return None


CHECK_DELAY = 0.2  # rebuild once changes made elsewhere (Graph Editor drag...) stop for this long


def blender_busy():
    """True while Blender runs a transform / gizmo / tween drag or plays the animation: no heavy work then."""
    wm = bpy.context.window_manager
    if wm is None:
        return False
    for window in wm.windows:
        screen = window.screen
        if screen is not None and screen.is_animation_playing:
            return True
        for op in window.modal_operators:
            idname = op.bl_idname.upper()
            if idname.startswith(("TRANSFORM_OT", "TRANSFORM.", "GIZMOGROUP_OT", "GIZMOGROUP.",
                                  "ANIM_TOOLS_OT_TWEEN_DRAG", "ANIM_TOOLS.TWEEN_DRAG")):
                return True
    return False


def request_check():
    """Rebuild later if the animation changed. Debounced: waits until the changes settle."""
    now = time.monotonic()
    state.last_change = now
    if state.check_pending:
        return
    state.first_change = now
    state.check_pending = True
    bpy.app.timers.register(_check_timer, first_interval=CHECK_DELAY)


def _check_timer():
    scene = bpy.context.scene
    if scene is None:
        state.check_pending = False
        return None
    now = time.monotonic()
    # During a long drag elsewhere, still refresh now and then: less often when rebuilding is slow.
    max_wait = max(0.4, state.last_rebuild * 4.0)
    quiet = now - state.last_change
    if state.transforming or state.building or (quiet < CHECK_DELAY and now - state.first_change < max_wait):
        return max(0.02, CHECK_DELAY - quiet)
    if blender_busy():
        return 0.1
    state.check_pending = False
    _external_rebuild()
    return None


def request_jacobians():
    """Evaluate the handle matrices on the next tick, so a click does not wait for it."""
    if state.jacobians_pending:
        return
    state.jacobians_pending = True
    bpy.app.timers.register(_jacobians_timer, first_interval=0.01)


def _jacobians_timer():
    scene = bpy.context.scene
    if scene is not None and blender_busy():
        return 0.1
    state.jacobians_pending = False
    if scene is not None and not state.transforming:
        ensure_jacobians(scene)
        from . import draw
        draw.tag_redraw_all()
    return None


# ---------------------------------------------------------------------------
# Selection and picking
# ---------------------------------------------------------------------------

def has_key_selection():
    return any(SELECTION.values())


def has_handle_selection():
    return bool(HANDLE_SELECTION)


def has_selection():
    return has_key_selection() or has_handle_selection()


def clear_selection():
    SELECTION.clear()
    HANDLE_SELECTION.clear()


def selected_points():
    """[(key, frame)] sorted for stable iteration."""
    return sorted((key, f) for key, frames in SELECTION.items() for f in frames)


def selected_owner_keys():
    return {key for key, frames in SELECTION.items() if frames} | {h[0] for h in HANDLE_SELECTION}


def prune_by_owner_selection(scene, mode):
    """Drop trail selection of bones/objects that are no longer selected (deselect all, other tools...).

    Returns True when something was dropped.
    """
    if not scene.motion_trail.select_owner or not has_selection():
        return False
    drop = set()
    for key in selected_owner_keys():
        ob, pb = resolve(scene, key)
        if ob is None:
            drop.add(key)
        elif pb is not None:
            if ob.mode == 'POSE' and not bone_selected(pb):
                drop.add(key)
        elif mode == 'OBJECT' and not ob.select_get():
            drop.add(key)
    for key in drop:
        SELECTION.pop(key, None)
    HANDLE_SELECTION.difference_update({h for h in HANDLE_SELECTION if h[0] in drop})
    return bool(drop)


def ui_scale():
    return bpy.context.preferences.system.ui_scale


def _nearest_key(context, mouse, radius):
    region, rv3d = context.region, context.region_data
    scene = context.scene
    best = None
    for key, trail in TRAILS.items():
        f0, f1 = visible_range(scene, trail)
        for f in trail.keys:
            if f < f0 or f > f1:
                continue
            co = trail.position(f)
            p = location_3d_to_region_2d(region, rv3d, co) if co is not None else None
            if p is None:
                continue
            d = (p - mouse).length
            if d <= radius and (best is None or d < best[0]):
                best = (d, (key, f))
    return best


def _nearest_handle(context, mouse, radius):
    region, rv3d = context.region, context.region_data
    best = None
    for key, f, side, _co, end, _flat in visible_handles(context.scene, region, rv3d):
        p = location_3d_to_region_2d(region, rv3d, end)
        if p is None:
            continue
        d = (p - mouse).length
        if d <= radius and (best is None or d < best[0]):
            best = (d, (key, f, side))
    return best


def hit_test(context, mouse, radius=None):
    """Nearest visible key point to `mouse` (region coords) within `radius` px: (key, frame) or None."""
    if context.region is None or context.region_data is None:
        return None
    if radius is None:
        radius = max(context.scene.motion_trail.key_size, 8.0) * ui_scale()
    best = _nearest_key(context, Vector(mouse), radius)
    return best[1] if best else None


def pick(context, mouse):
    """What is under the mouse: ('KEY', (key, frame)), ('HANDLE', (key, frame, side)) or None."""
    if context.region is None or context.region_data is None:
        return None
    mouse = Vector(mouse)
    size = context.scene.motion_trail.key_size
    key = _nearest_key(context, mouse, max(size, 8.0) * ui_scale())
    handle = _nearest_handle(context, mouse, max(size * 0.8, 7.0) * ui_scale())
    if handle is not None and (key is None or handle[0] < key[0]):
        return 'HANDLE', handle[1]
    if key is not None:
        return 'KEY', key[1]
    return None


def hit_test_line(context, mouse, radius=None):
    """Nearest point on a visible trail line: (key, frame rounded to an integer) or None."""
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return None
    scene = context.scene
    if radius is None:
        radius = 10.0 * ui_scale()
    mouse = Vector(mouse)
    best = None
    for key, trail in TRAILS.items():
        f0, f1 = visible_range(scene, trail)
        prev = None
        for f in range(f0, f1 + 1):
            co = trail.position(f)
            p = location_3d_to_region_2d(region, rv3d, co) if co is not None else None
            if p is not None and prev is not None:
                a, fa = prev
                ab = p - a
                denom = ab.length_squared
                t = 0.0 if denom == 0.0 else max(0.0, min(1.0, (mouse - a).dot(ab) / denom))
                d = (a + ab * t - mouse).length
                if d <= radius and (best is None or d < best[0]):
                    best = (d, key, int(round(fa + t)))
            prev = (p, f) if p is not None else None
    return (best[1], best[2]) if best else None


def points_in_rect(context, rect):
    region, rv3d = context.region, context.region_data
    x0, y0, x1, y1 = rect
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    scene = context.scene
    found = []
    for key, trail in TRAILS.items():
        f0, f1 = visible_range(scene, trail)
        for f in trail.keys:
            if f < f0 or f > f1:
                continue
            co = trail.position(f)
            p = location_3d_to_region_2d(region, rv3d, co) if co is not None else None
            if p is not None and x0 <= p.x <= x1 and y0 <= p.y <= y1:
                found.append((key, f))
    return found


def deselect_owners(context):
    """Deselect all bones (Pose Mode) or objects (Object Mode), like a click on nothing."""
    if context.mode == 'POSE':
        for ob in context.objects_in_mode:
            for pb in ob.pose.bones:
                select_bone(pb, False)
    elif context.mode == 'OBJECT':
        for ob in context.selected_objects:
            ob.select_set(False)


def sync_selection_to_owners(context, extend):
    """Select the objects/bones whose trail keys are selected, and mirror key selection to the F-Curves."""
    select_owners(context, extend)
    sync_key_selection(context)


def select_owners(context, extend):
    scene = context.scene
    s = scene.motion_trail
    selected_keys = selected_owner_keys()

    if s.select_owner and selected_keys:
        for key in selected_keys:
            ob, pb = resolve(scene, key)
            if ob is None:
                continue
            if pb is not None and ob.mode == 'POSE':
                if not extend:
                    for other in ob.pose.bones:
                        select_bone(other, False)
                for k2 in selected_keys:
                    ob2, pb2 = resolve(scene, k2)
                    if ob2 == ob and pb2 is not None:
                        select_bone(pb2, True)
                ob.data.bones.active = pb.bone
            elif pb is None and context.mode == 'OBJECT':
                if not extend:
                    for other in context.view_layer.objects:
                        if other.select_get() and (other.name_full, "") not in selected_keys:
                            other.select_set(False)
                ob.select_set(True)
                context.view_layer.objects.active = ob


def sync_key_selection(context):
    """Mirror the trail selection to the keyframes (Graph Editor / Dope Sheet)."""
    scene = context.scene
    if not scene.motion_trail.sync_key_selection:
        return
    for key in TRAILS:
        ob, pb = resolve(scene, key)
        if ob is None:
            continue
        frames = SELECTION.get(key, set())
        for fc in transform_fcurves(ob, pb.name if pb else ""):
            for kp in fc.keyframe_points:
                f = int(round(kp.co.x))
                sel = f in frames
                kp.select_control_point = sel
                kp.select_left_handle = sel or (key, f, 'L') in HANDLE_SELECTION
                kp.select_right_handle = sel or (key, f, 'R') in HANDLE_SELECTION

    wm = context.window_manager
    if wm is not None:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type in {'GRAPH_EDITOR', 'DOPESHEET_EDITOR', 'TIMELINE'}:
                    area.tag_redraw()


# ---------------------------------------------------------------------------
# Handles ("tails"): the Bezier handles of the location keys, shown in 3D
# ---------------------------------------------------------------------------

def handle_keys():
    """Keys whose handles are shown: selected keys and keys with a selected handle."""
    keys = {(k, f) for k, frames in SELECTION.items() for f in frames}
    keys.update((k, f) for k, f, _side in HANDLE_SELECTION)
    return keys


def ensure_jacobians(scene):
    """Evaluate the matrices needed to show the handles of the selected keys (only missing ones)."""
    if not scene.motion_trail.show_handles:
        return
    wanted = sorted(p for p in handle_keys() if p[0] in TRAILS)[:MAX_HANDLE_KEYS]
    missing = [p for p in wanted if p not in JACOBIANS]
    if missing:
        JACOBIANS.update(jacobians(scene, missing))


def handle_offsets(scene, key, frame):
    """Handle offsets of the key in local `location` values: (left, right); None for a side without effect."""
    ob, pb = resolve(scene, key)
    if ob is None:
        return None, None
    bone = pb.name if pb else ""
    left, right = Vector(), Vector()
    found = has_prev = has_next = False
    for i in range(3):
        fc = location_fcurve(ob, bone, i)
        idx = find_key_index(fc, frame) if fc else None
        if idx is None:
            continue
        kp = fc.keyframe_points[idx]
        found = True
        left[i] = kp.handle_left.y - kp.co.y
        right[i] = kp.handle_right.y - kp.co.y
        has_prev = has_prev or idx > 0
        has_next = has_next or idx < len(fc.keyframe_points) - 1
    if not found:
        return None, None
    return (left if has_prev else None), (right if has_next else None)


def handle_positions(scene, key, frame):
    """World positions of the left/right handle ends, None when not shown."""
    trail = TRAILS.get(key)
    jac = JACOBIANS.get((key, frame))
    co = trail.position(frame) if trail else None
    if co is None or jac is None:
        return None, None
    left, right = handle_offsets(scene, key, frame)
    return (co + jac @ left if left is not None else None), (co + jac @ right if right is not None else None)


MIN_TAIL_PX = 24  # flat (zero-length) tails are still drawn this long so they can be grabbed


def _trail_direction_2d(region, rv3d, trail, frame, side, origin_2d):
    """Screen direction of the trail leaving the key towards `side` (for drawing flat tails)."""
    step = 1 if side == 'R' else -1
    for d in range(1, 8):
        co = trail.position(frame + step * d)
        if co is None:
            break
        p = location_3d_to_region_2d(region, rv3d, co)
        if p is not None and (p - origin_2d).length > 0.5:
            return (p - origin_2d).normalized()
    return Vector((float(step), 0.0))


def visible_handles(scene, region=None, rv3d=None):
    """[(key, frame, side, key position, handle end position, flat)] of the handles currently drawn.

    With a region, tails shorter than MIN_TAIL_PX on screen (e.g. flat Auto Clamped handles on a pose)
    are extended to that length along the trail, and marked `flat`.
    """
    if not scene.motion_trail.show_handles:
        return []
    min_px = MIN_TAIL_PX * ui_scale()
    out = []
    for key, f in sorted(handle_keys()):
        trail = TRAILS.get(key)
        if trail is None:
            continue
        f0, f1 = visible_range(scene, trail)
        if f < f0 or f > f1:
            continue
        co = trail.position(f)
        for side, end in zip("LR", handle_positions(scene, key, f)):
            if end is None:
                continue
            flat = False
            if region is not None and rv3d is not None:
                a = location_3d_to_region_2d(region, rv3d, co)
                b = location_3d_to_region_2d(region, rv3d, end)
                if a is not None and b is not None and (b - a).length < min_px:
                    if (b - a).length > 0.5:
                        direction = (b - a).normalized()
                    else:
                        direction = _trail_direction_2d(region, rv3d, trail, f, side, a)
                    end = region_2d_to_location_3d(region, rv3d, a + direction * min_px, co)
                    flat = True
            out.append((key, f, side, co, end, flat))
    return out


# ---------------------------------------------------------------------------
# Key editing
# ---------------------------------------------------------------------------

def _has_constraints(owner):
    return any(not c.mute and c.influence > 0.0 for c in owner.constraints)


def _measured_jacobian(ob, pb, use_tail, step=0.01):
    """Move `location` a little on each axis and look where the point really goes (exact with constraints)."""
    owner = pb if pb is not None else ob
    view_layer = bpy.context.view_layer

    def point():
        if pb is not None:
            return ob.matrix_world @ (pb.tail if use_tail else pb.head)
        return ob.matrix_world.translation.copy()

    original = owner.location.copy()
    origin = point()
    columns = []
    try:
        for i in range(3):
            moved = original.copy()
            moved[i] += step
            owner.location = moved
            view_layer.update()
            columns.append((point() - origin) / step)
    finally:
        owner.location = original
        view_layer.update()
    return Matrix((columns[0], columns[1], columns[2])).transposed()


def location_jacobian(ob, pb, use_tail):
    """3x3: world motion of the trail point per unit of the item's `location`, in the current pose."""
    if _has_constraints(pb if pb is not None else ob):
        return _measured_jacobian(ob, pb, use_tail)
    if pb is None:
        return (ob.matrix_world @ ob.matrix_basis.inverted_safe()).to_3x3()
    # Blender's own Local -> World conversion honours Inherit Rotation / Inherit Scale / Local Location.
    origin = ob.convert_space(pose_bone=pb, matrix=Matrix.Identity(4), from_space='LOCAL', to_space='WORLD')
    columns = []
    for i in range(3):
        offset = Vector((1.0 if j == i else 0.0 for j in range(3)))
        m = ob.convert_space(pose_bone=pb, matrix=Matrix.Translation(offset), from_space='LOCAL', to_space='WORLD')
        columns.append(m.translation - origin.translation)
    return Matrix((columns[0], columns[1], columns[2])).transposed()


def jacobians(scene, points):
    """World-space change of the trail point per unit of local `location`, at each point's frame.

    points: [(key, frame)] -> {(key, frame): Matrix 3x3}. Steps through the needed frames once.
    """
    by_frame = {}
    for key, f in points:
        by_frame.setdefault(f, []).append(key)
    cur, sub = scene.frame_current, scene.frame_subframe
    use_tail = scene.motion_trail.bake_location == 'TAILS'
    result = {}
    try:
        for f in sorted(by_frame):
            if f != cur or sub != 0.0:
                scene.frame_set(f)
            for key in by_frame[f]:
                ob, pb = resolve(scene, key)
                if ob is not None:
                    result[(key, f)] = location_jacobian(ob, pb, use_tail)
    finally:
        if scene.frame_current != cur or scene.frame_subframe != sub:
            scene.frame_set(cur, subframe=sub)
    return result


class KeyEdit:
    """Moves the location keys of trail points; remembers originals so it can be cancelled."""

    def __init__(self, scene, points):
        self.scene = scene
        self.points = points  # [(key, frame)]
        self.locks = {}
        # (key, index, frame) -> (co.y, handle_left.y, handle_right.y, left type, right type) or None (new key)
        self.originals = {}
        self.base_values = {}  # (key, index, frame) -> evaluated value before editing
        self.created_fcurves = []  # (key, index)
        for key, f in points:
            ob, pb = resolve(scene, key)
            if ob is None:
                continue
            owner = pb if pb is not None else ob
            locked = tuple(owner.lock_location)
            if pb is not None and pb.bone.use_connect:
                locked = (True, True, True)  # connected bones ignore location
            self.locks[key] = locked
            bone = pb.name if pb else ""
            for i in range(3):
                fc = location_fcurve(ob, bone, i)
                kp = find_key(fc, f) if fc else None
                if kp is not None:
                    self.originals[(key, i, f)] = (kp.co.y, kp.handle_left.y, kp.handle_right.y,
                                                   kp.handle_left_type, kp.handle_right_type)
                    self.base_values[(key, i, f)] = kp.co.y
                else:
                    self.originals[(key, i, f)] = None
                    self.base_values[(key, i, f)] = fc.evaluate(f) if fc else owner.location[i]

    _FIXED_TYPE = {'AUTO': 'ALIGNED', 'AUTO_CLAMPED': 'ALIGNED', 'VECTOR': 'FREE'}

    def _handle_offsets(self, key, f):
        """Original handle offsets (left, right) of the key, in local location values."""
        left, right = Vector(), Vector()
        for i in range(3):
            orig = self.originals.get((key, i, f))
            if orig is not None:
                left[i], right[i] = orig[1] - orig[0], orig[2] - orig[0]
        return left, right

    def apply(self, deltas, handle_maps=None):
        """deltas: {(key, frame): local location delta Vector}. Always applied relative to the originals.

        handle_maps: {(key, frame): 3x3 local matrix} turns/scales the handles too (rotating or scaling
        several keys keeps the shape of the path). Those handles are fixed (auto types become aligned),
        otherwise Blender would recompute them.
        """
        touched = set()
        for (key, f), d in deltas.items():
            ob, pb = resolve(self.scene, key)
            if ob is None:
                continue
            bone = pb.name if pb else ""
            locks = self.locks.get(key, (False, False, False))
            m = handle_maps.get((key, f)) if handle_maps else None
            if m is not None:
                old_left, old_right = self._handle_offsets(key, f)
                new_left, new_right = m @ old_left, m @ old_right
            for i in range(3):
                if locks[i]:
                    continue
                orig = self.originals.get((key, i, f))
                fc = location_fcurve(ob, bone, i)
                if orig is None and abs(d[i]) < 1e-9 and (fc is None or find_key(fc, f) is None):
                    continue
                if fc is None:
                    fc = location_fcurve(ob, bone, i, create=True)
                    if fc is None:
                        continue
                    self.created_fcurves.append((key, i))
                kp = find_key(fc, f)
                value = self.base_values[(key, i, f)] + d[i]
                if kp is None:
                    kp = fc.keyframe_points.insert(f, value, options={'FAST'})
                if orig is None:
                    kp.co.y = value
                    kp.handle_left.y = value
                    kp.handle_right.y = value
                else:
                    co, hl, hr, lt, rt = orig
                    kp.co.y = co + d[i]
                    if m is None:
                        kp.handle_left.y = hl + d[i]
                        kp.handle_right.y = hr + d[i]
                    else:
                        kp.handle_left_type = self._FIXED_TYPE.get(lt, lt)
                        kp.handle_right_type = self._FIXED_TYPE.get(rt, rt)
                        kp.handle_left.y = co + d[i] + new_left[i]
                        kp.handle_right.y = co + d[i] + new_right[i]
                touched.add(fc)
        for fc in touched:
            fc.update()

    def cancel(self):
        for (key, i, f), orig in self.originals.items():
            ob, pb = resolve(self.scene, key)
            if ob is None:
                continue
            fc = location_fcurve(ob, pb.name if pb else "", i)
            if fc is None:
                continue
            kp = find_key(fc, f)
            if kp is None:
                continue
            if orig is None:
                fc.keyframe_points.remove(kp, fast=True)
            else:
                co, hl, hr, lt, rt = orig
                kp.handle_left_type, kp.handle_right_type = lt, rt
                kp.co.y, kp.handle_left.y, kp.handle_right.y = co, hl, hr
            fc.update()
        for key, i in self.created_fcurves:
            ob, pb = resolve(self.scene, key)
            if ob is None:
                continue
            fc = location_fcurve(ob, pb.name if pb else "", i)
            if fc is not None and len(fc.keyframe_points) == 0:
                action_fcurves(ob).remove(fc)


class HandleEdit:
    """Edits the Bezier handles of location keys; remembers originals so it can be cancelled.

    handles: [(key, frame, side)]. Only axes that have a key at that frame are edited.
    """

    def __init__(self, scene, handles):
        self.scene = scene
        self.axes = {}  # (key, frame, side) -> [(axis, original, prev_x, next_x)]
        self.snapshot = {}  # (key, axis, frame) -> (handle_left, handle_right, left type, right type)
        for key, f, side in handles:
            ob, pb = resolve(scene, key)
            if ob is None:
                continue
            axes = []
            for i in range(3):
                fc = location_fcurve(ob, pb.name if pb else "", i)
                idx = find_key_index(fc, f) if fc else None
                if idx is None:
                    continue
                points = fc.keyframe_points
                kp = points[idx]
                original = (kp.co.x, kp.co.y, tuple(kp.handle_left), tuple(kp.handle_right),
                            kp.handle_left_type, kp.handle_right_type)
                prev_x = points[idx - 1].co.x if idx > 0 else None
                next_x = points[idx + 1].co.x if idx + 1 < len(points) else None
                axes.append((i, original, prev_x, next_x))
                self.snapshot.setdefault((key, i, f), original[2:])
            self.axes[(key, f, side)] = axes

    def _key(self, key, axis, frame):
        ob, pb = resolve(self.scene, key)
        fc = location_fcurve(ob, pb.name if pb else "", axis) if ob else None
        return find_key(fc, frame) if fc else None

    @staticmethod
    def _editable_types(kp, original):
        # Edited handles must not be recomputed by Blender: auto types become aligned, the rest free.
        for attr, old in (("handle_left_type", original[4]), ("handle_right_type", original[5])):
            setattr(kp, attr, 'FREE' if old in {'FREE', 'VECTOR'} else 'ALIGNED')

    def set_offset(self, handle, delta, keep_aligned=True):
        """Move the handle end to `delta` (local location values, relative to the key).

        The opposite handle keeps its timing and stays on the same line, so the curve stays smooth.
        """
        key, f, side = handle
        for i, original, _prev_x, _next_x in self.axes.get(handle, ()):
            kp = self._key(key, i, f)
            if kp is None:
                continue
            co_x, co_y, hl, hr = original[:4]
            self._editable_types(kp, original)
            aligned = keep_aligned and not {original[4], original[5]} & {'FREE', 'VECTOR'}
            near, far = (hr, hl) if side == 'R' else (hl, hr)
            dt_near = max(abs(near[0] - co_x), 1e-6)
            dt_far = abs(far[0] - co_x)
            new_near = (near[0], co_y + delta[i])
            new_far = (far[0], co_y - delta[i] * dt_far / dt_near) if aligned else far
            if side == 'R':
                kp.handle_right, kp.handle_left = new_near, new_far
            else:
                kp.handle_left, kp.handle_right = new_near, new_far

    def scale(self, handle, factor):
        """Scale the handle length (timing and value together): same direction, longer or shorter tail."""
        key, f, side = handle
        factor = max(factor, 0.0)
        for i, original, prev_x, next_x in self.axes.get(handle, ()):
            kp = self._key(key, i, f)
            if kp is None:
                continue
            co_x, co_y, hl, hr = original[:4]
            self._editable_types(kp, original)
            hx, hy = hr if side == 'R' else hl
            dx, dy = hx - co_x, hy - co_y
            limit = (next_x - co_x) if side == 'R' and next_x is not None else (
                (co_x - prev_x) if side == 'L' and prev_x is not None else None)
            k = factor
            if limit is not None and abs(dx) * k > limit:
                k = limit / abs(dx)  # a handle may not reach past the neighbouring key
            new = (co_x + dx * k, co_y + dy * k)
            if side == 'R':
                kp.handle_right = new
            else:
                kp.handle_left = new

    def cancel(self):
        for (key, i, f), (hl, hr, lt, rt) in self.snapshot.items():
            kp = self._key(key, i, f)
            if kp is None:
                continue
            kp.handle_left_type, kp.handle_right_type = lt, rt
            kp.handle_left, kp.handle_right = hl, hr


class LivePreview:
    """Moves the trail line while dragging, without evaluating the scene.

    A position changes by J @ (change of the location curves) near the edited keys, with J the matrix of
    the nearest edited key. That is exact for a still parent; the exact positions come from a rebuild of
    `span` when the drag ends.
    """

    def __init__(self, scene, edited):
        """edited: {key: set of frames whose keys or handles are being edited}."""
        self.scene = scene
        self.items = []
        spans = []
        for key, frames in edited.items():
            trail = TRAILS.get(key)
            ob, pb = resolve(scene, key)
            jac = sorted((f, JACOBIANS[(key, f)]) for f in frames if (key, f) in JACOBIANS)
            if trail is None or ob is None or not jac:
                continue
            bone = pb.name if pb else ""
            owner = pb if pb is not None else ob
            keys = sorted(set(trail.keys) | set(frames))
            curves = [location_fcurve(ob, bone, i) for i in range(3)]
            if any(fc is not None and fc.auto_smoothing != 'NONE' for fc in curves):
                # "Continuous Acceleration" smoothing (default in Blender 5) recomputes auto handles along the
                # whole curve when one key moves.
                lo, hi = keys[0], keys[-1]
            else:
                # Otherwise a key changes the curve up to two keys away (auto handles of the neighbours).
                lo = min(keys[max(bisect.bisect_left(keys, f) - 2, 0)] for f in frames)
                hi = max(keys[min(bisect.bisect_left(keys, f) + 2, len(keys) - 1)] for f in frames)
            f0, f1 = max(lo, trail.frame_start), min(hi, trail.frame_end)
            if f1 < f0:
                continue
            span = range(f0, f1 + 1)
            jac_frames = [f for f, _m in jac]
            mats = []
            for f in span:
                i = bisect.bisect_left(jac_frames, f)
                near = min((j for j in (i - 1, i) if 0 <= j < len(jac)), key=lambda j: abs(jac_frames[j] - f))
                mats.append(jac[near][1])
            base = [trail.positions[f - trail.frame_start].copy() for f in span]
            self.items.append({"key": key, "trail": trail, "ob": ob, "bone": bone, "owner": owner,
                               "span": span, "base": base, "mats": mats, "loc0": self._locations(ob, bone, owner, span)})
            spans.append((f0, f1))
        self.span = (min(s[0] for s in spans), max(s[1] for s in spans)) if spans else None
        self.keys = {item["key"] for item in self.items}

    @staticmethod
    def _locations(ob, bone, owner, span):
        out = []
        curves = [location_fcurve(ob, bone, i) for i in range(3)]
        static = tuple(owner.location)
        for f in span:
            out.append(Vector([fc.evaluate(f) if fc else static[i] for i, fc in enumerate(curves)]))
        return out

    def update(self):
        for item in self.items:
            trail, start = item["trail"], item["trail"].frame_start
            loc1 = self._locations(item["ob"], item["bone"], item["owner"], item["span"])
            for f, base, mat, a, b in zip(item["span"], item["base"], item["mats"], item["loc0"], loc1):
                trail.positions[f - start] = base + mat @ (b - a)


def insert_keys(scene, key, frame):
    """Key all animated transform channels of the item at `frame` without changing the motion."""
    ob, pb = resolve(scene, key)
    if ob is None:
        return False
    bone = pb.name if pb else ""
    fcurves = transform_fcurves(ob, bone)
    if not fcurves:
        owner = pb if pb is not None else ob
        for i in range(3):
            fc = location_fcurve(ob, bone, i, create=True)
            if fc is None:
                return False
            fc.keyframe_points.insert(frame, owner.location[i])
            fc.update()
        return True
    for fc in fcurves:
        if find_key(fc, frame) is None:
            fc.keyframe_points.insert(frame, fc.evaluate(frame))
            fc.update()
    return True


def delete_keys(scene, points):
    """Delete transform keys of the items at the given frames. Returns how many key points went away."""
    removed = 0
    for key, f in points:
        ob, pb = resolve(scene, key)
        if ob is None:
            continue
        for fc in transform_fcurves(ob, pb.name if pb else ""):
            kp = find_key(fc, f)
            if kp is not None:
                fc.keyframe_points.remove(kp)
                removed += 1
    return removed
