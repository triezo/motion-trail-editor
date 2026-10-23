"""Core logic tests, run headless:
blender -b --factory-startup --python dev/test_core.py
"""
import math
import os
import sys
import traceback

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

results = []


def check(name, fn):
    try:
        out = fn()
        results.append(("PASS", name, out))
    except Exception:
        results.append(("FAIL", name, traceback.format_exc()))


def truth(scene, ob, pb, frame):
    cur = scene.frame_current
    scene.frame_set(frame)
    co = (ob.matrix_world @ pb.head) if pb else ob.matrix_world.translation.copy()
    scene.frame_set(cur)
    return co


def snapshot(ob):
    data = []
    for fc in trails.action_fcurves(ob):
        for kp in fc.keyframe_points:
            data.append((fc.data_path, fc.array_index, tuple(kp.co), tuple(kp.handle_left), tuple(kp.handle_right)))
    return sorted(data)


mte.register()
rig, cube, body = testrig.build(dense=False)
scene = bpy.context.scene
s = scene.motion_trail
s.frames_before = s.frames_after = 0  # evaluate all frames (the window is tested separately)

bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='POSE')
for name in ("hand_ik", "forearm"):
    it = s.items.add()
    it.object = rig
    it.bone = name
it = s.items.add()
it.object = cube

K_HAND = trails.item_key(rig, "hand_ik")
K_FORE = trails.item_key(rig, "forearm")
K_CUBE = trails.item_key(cube, "")
hand = rig.pose.bones["hand_ik"]


def t_rebuild():
    trails.rebuild()
    assert set(trails.TRAILS) == {K_HAND, K_FORE, K_CUBE}, trails.TRAILS.keys()
    tr = trails.TRAILS[K_HAND]
    worst = max((tr.position(f) - truth(scene, rig, hand, f)).length for f in (1, 7, 25, 60, 120))
    assert worst < 1e-4, worst
    return {"frames": (tr.frame_start, tr.frame_end), "hand_keys": tr.keys,
            "cube_keys": trails.TRAILS[K_CUBE].keys, "max_err": worst}


def move_point(key, ob, pb, frame, dw):
    origin = trails.TRAILS[key].position(frame).copy()
    jac = trails.jacobians(scene, [(key, frame)])
    edit = trails.KeyEdit(scene, [(key, frame)])
    edit.apply({(key, frame): jac[(key, frame)].inverted_safe() @ dw})
    got = truth(scene, ob, pb, frame)
    return edit, origin + dw, got


def t_move_bone_under_rotating_parent():
    before = snapshot(rig)
    dw = Vector((0.3, -0.2, 0.15))
    edit, target, got = move_point(K_HAND, rig, hand, 85, dw)  # root is rotated ~64 deg here
    err = (got - target).length
    assert err < 1e-4, (target, got)
    edit.cancel()
    assert snapshot(rig) == before, "cancel did not restore the keys"
    return {"err": err, "cancel_restored": True}


def t_move_special_bones():
    """Inherit Rotation/Scale off, Local Location off, Child Of constraint: the key still lands on target."""
    errors = {}
    for name in ("ctrl_options", "ctrl_childof"):
        if not any(it.bone == name for it in s.items):
            it = s.items.add()
            it.object = rig
            it.bone = name
        trails.rebuild()
        key = trails.item_key(rig, name)
        pb = rig.pose.bones[name]
        edit, target, got = move_point(key, rig, pb, 85, Vector((0.25, -0.3, 0.2)))
        errors[name] = (got - target).length
        edit.cancel()
    assert all(e < 1e-4 for e in errors.values()), errors
    return {k: round(v, 7) for k, v in errors.items()}


def t_move_object():
    dw = Vector((-0.5, 0.25, 0.4))
    _edit, target, got = move_point(K_CUBE, cube, None, 41, dw)
    err = (got - target).length
    assert err < 1e-4, (target, got)
    return {"err": err}


def t_move_point_without_location_key():
    # Frame 7 has no key: moving it creates location keys there.
    key = K_HAND
    trails.rebuild()
    dw = Vector((0.0, 0.0, 0.5))
    _edit, target, got = move_point(key, rig, hand, 7, dw)
    err = (got - target).length
    trails.rebuild()
    assert 7 in trails.TRAILS[key].keys
    assert err < 1e-4, (target, got)
    return {"err": err}


def t_insert_delete():
    trails.rebuild()
    tr = trails.TRAILS[K_HAND]
    frame = 50
    assert frame not in tr.keys
    before = [tr.position(f).copy() for f in range(40, 61)]
    assert trails.insert_keys(scene, K_HAND, frame)
    trails.rebuild()
    tr = trails.TRAILS[K_HAND]
    after = [tr.position(f).copy() for f in range(40, 61)]
    drift = max((a - b).length for a, b in zip(before, after))
    assert frame in tr.keys
    removed = trails.delete_keys(scene, [(K_HAND, frame)])
    trails.rebuild()
    assert frame not in trails.TRAILS[K_HAND].keys
    return {"shape_drift_after_insert": round(drift, 6), "removed_channels": removed}


def t_object_mode_fallback():
    trails.rebuild()
    pose_trail = trails.TRAILS[K_FORE]
    pose_positions = [p.copy() for p in pose_trail.positions]
    bpy.ops.object.mode_set(mode='OBJECT')
    sig_changed = trails.trail_signature(scene, rig, rig.pose.bones["forearm"]) != trails.state.signatures[K_FORE]
    # Out of Pose Mode an existing bone trail is kept (no slow frame stepping), marked stale.
    trails.rebuild()
    kept = trails.TRAILS[K_FORE] is pose_trail and pose_trail.stale
    # A bone trail that never existed is frame-stepped, but only around the playhead.
    del trails.TRAILS[K_FORE]
    scene.frame_set(60)
    trails.rebuild()
    window = trails.TRAILS[K_FORE]
    worst = max((window.position(f) - pose_positions[f - 1]).length for f in range(window.frame_start, window.frame_end + 1))
    bpy.ops.object.mode_set(mode='POSE')
    trails.rebuild()
    back = trails.TRAILS[K_FORE]
    scene.frame_set(1)
    assert sig_changed and kept and worst < 1e-4, (sig_changed, kept, worst)
    assert (window.frame_start, window.frame_end) == (1, 120), (window.frame_start, window.frame_end)
    assert not back.stale and (back.frame_start, back.frame_end) == (1, 120)
    left = [b.name for b in rig.pose.bones if b.motion_path]
    assert not left and cube.motion_path is None, (left, cube.motion_path)
    return {"kept_stale": kept, "window": (window.frame_start, window.frame_end), "max_diff": worst,
            "native_paths_left": left}


def t_user_path_kept():
    # A motion path the user made on another bone must survive our rebuilds.
    root = rig.pose.bones["root"]
    for b in rig.pose.bones:
        trails.select_bone(b, b == root)
    with bpy.context.temp_override(active_object=rig, object=rig, selected_pose_bones=[root],
                                   selected_pose_bones_from_active_object=[root]):
        bpy.ops.pose.paths_calculate(display_type='RANGE', range='SCENE', bake_location='HEADS')
    selection = [b.name for b in rig.pose.bones if trails.bone_selected(b)]
    trails.rebuild()
    assert root.motion_path is not None
    assert [b.name for b in rig.pose.bones if trails.bone_selected(b)] == selection
    left = sorted(b.name for b in rig.pose.bones if b.motion_path)
    assert left == ["root"], left
    return {"paths": left, "selection_kept": selection}


def t_signature():
    """A trail is outdated only by curves that can move it: its bone, parents, constraint targets."""
    hand_pb, fore_pb = rig.pose.bones["hand_ik"], rig.pose.bones["forearm"]

    def bump(bone, prop, index=0, amount=0.01):
        fc = next(f for f in trails.action_fcurves(rig)
                  if f.data_path == trails.path_prefix(bone) + prop and f.array_index == index)
        fc.keyframe_points[0].co.y += amount

    def sigs():
        return (trails.trail_signature(scene, rig, hand_pb), trails.trail_signature(scene, rig, fore_pb))

    base = sigs()
    stable = sigs() == base
    bump("ctrl_options", "location")  # unrelated control
    unrelated = sigs() == base
    bump("ctrl_options", "location", amount=-0.01)
    bump("root", "rotation_euler", 2)  # parent of both
    parent = sigs()
    bump("root", "rotation_euler", 2, -0.01)
    bump("hand_ik", "location")  # the hand itself, and the IK target of the forearm
    ik = sigs()
    bump("hand_ik", "location", amount=-0.01)
    result = {"stable": stable, "unrelated_bone_ignored": unrelated,
              "parent_counts": parent[0] != base[0] and parent[1] != base[1],
              "ik_target_counts": ik[0] != base[0] and ik[1] != base[1]}
    assert all(result.values()), result
    return result


def t_eval_window():
    """With Before/After set, only frames around the playhead are evaluated; moving the playhead re-evaluates."""
    s.frames_before = s.frames_after = 10
    try:
        scene.frame_set(60)
        trails.rebuild()
        tr = trails.TRAILS[K_HAND]
        window = (tr.frame_start, tr.frame_end)
        ok_here = trails.covers(tr, scene)
        scene.frame_set(100)
        outdated, _removed = trails.outdated_trails(scene)
        trails._external_rebuild()
        tr = trails.TRAILS[K_HAND]
        moved = (tr.frame_start, tr.frame_end)
        exact = max((tr.position(f) - truth(scene, rig, hand, f)).length for f in range(tr.frame_start, tr.frame_end + 1, 5))
        unchanged, _ = trails.outdated_trails(scene)
    finally:
        s.frames_before = s.frames_after = 0
        scene.frame_set(1)
        trails.rebuild()
    assert window == (40, 80) and ok_here and K_HAND in outdated and moved == (80, 120) and exact < 1e-4 \
        and not unchanged, (window, moved, exact, unchanged)
    return {"window_at_60": window, "window_at_100": moved, "max_err": exact}


def t_selection_sync():
    trails.rebuild()
    trails.clear_selection()
    trails.SELECTION[K_HAND] = {25}
    trails.sync_selection_to_owners(bpy.context, extend=False)
    sel = sorted({int(kp.co.x) for fc in trails.transform_fcurves(rig, "hand_ik")
                  for kp in fc.keyframe_points if kp.select_control_point})
    bones = [b.name for b in rig.pose.bones if trails.bone_selected(b)]
    assert sel == [25] and bones == ["hand_ik"], (sel, bones)
    return {"selected_keys": sel, "selected_bones": bones}


def handle_values(ob, bone, frame):
    out = []
    for i in range(3):
        kp = trails.find_key(trails.location_fcurve(ob, bone, i), frame)
        out.append((tuple(kp.co), tuple(kp.handle_left), tuple(kp.handle_right),
                    kp.handle_left_type, kp.handle_right_type))
    return out


def t_handle_move():
    trails.rebuild()
    key, f = K_HAND, 37
    trails.clear_selection()
    trails.SELECTION[key] = {f}
    trails.JACOBIANS.clear()
    trails.ensure_jacobians(scene)
    assert (key, f) in trails.JACOBIANS
    left0, right0 = trails.handle_positions(scene, key, f)
    anchor = trails.TRAILS[key].position(f)
    before = handle_values(rig, "hand_ik", f)
    target = right0 + Vector((0.1, -0.05, 0.2))
    edit = trails.HandleEdit(scene, [(key, f, 'R')])
    edit.set_offset((key, f, 'R'), trails.JACOBIANS[(key, f)].inverted_safe() @ (target - anchor))
    for fc in trails.transform_fcurves(rig, "hand_ik"):
        fc.update()  # Blender must not recompute the edited (now aligned) handles
    left1, right1 = trails.handle_positions(scene, key, f)
    err = (right1 - target).length
    assert err < 1e-4, (right1, target)
    # The opposite tail stays on the same line through the key (smooth curve).
    a, b = (left1 - anchor).normalized(), (right1 - anchor).normalized()
    assert a.dot(b) < -0.9999, a.dot(b)
    types = {t for row in handle_values(rig, "hand_ik", f) for t in row[3:]}
    assert types == {'ALIGNED'}, types
    edit.cancel()
    assert handle_values(rig, "hand_ik", f) == before, "handle cancel did not restore"
    return {"err": err, "collinear": round(a.dot(b), 6), "types": sorted(types)}


def t_handle_scale():
    trails.rebuild()
    key, f = K_HAND, 49
    trails.SELECTION[key] = {f}
    trails.ensure_jacobians(scene)
    left0, right0 = trails.handle_positions(scene, key, f)
    anchor = trails.TRAILS[key].position(f)
    edit = trails.HandleEdit(scene, [(key, f, 'R')])
    edit.scale((key, f, 'R'), 2.0)
    left1, right1 = trails.handle_positions(scene, key, f)
    ratio = (right1 - anchor).length / (right0 - anchor).length
    same_dir = (right1 - anchor).normalized().dot((right0 - anchor).normalized())
    left_kept = (left1 - left0).length
    assert abs(ratio - 2.0) < 1e-3 and same_dir > 0.9999 and left_kept < 1e-6, (ratio, same_dir, left_kept)
    trails.rebuild()
    after = trails.TRAILS[key].position(f + 3)
    edit.cancel()
    trails.rebuild()
    restored = trails.TRAILS[key].position(f + 3)
    assert (after - restored).length > 1e-4, "scaling the tail should change the trail shape"
    return {"length_ratio": round(ratio, 4), "direction_kept": round(same_dir, 6)}


def t_select_new_key():
    trails.rebuild()
    trails.clear_selection()
    trails.SELECTION[K_HAND] = {13}
    # A key inserted outside the addon (I key / auto-key) becomes the trail selection.
    scene.frame_set(31)
    hand.location.x += 0.05
    hand.keyframe_insert("location", frame=31)
    trails._external_rebuild()
    sel = {k: sorted(v) for k, v in trails.SELECTION.items() if v}
    trails.delete_keys(scene, [(K_HAND, 31)])
    scene.frame_set(1)
    trails.rebuild()
    assert sel == {K_HAND: [31]}, sel
    return sel


def t_deselect_owner_prunes():
    trails.rebuild()
    trails.clear_selection()
    trails.SELECTION[K_HAND] = {25}
    trails.HANDLE_SELECTION.add((K_HAND, 37, 'L'))
    trails.sync_selection_to_owners(bpy.context, extend=False)
    kept = not trails.prune_by_owner_selection(scene, bpy.context.mode)
    for b in rig.pose.bones:
        trails.select_bone(b, False)
    pruned = trails.prune_by_owner_selection(scene, bpy.context.mode)
    assert kept and pruned and not trails.has_selection()
    return {"kept_while_selected": kept, "pruned_after_deselect": pruned}


def rigid_transform(world):
    """Transform all cube keys with `world` (3x3) about their median; the whole path must follow."""
    from mathutils import Matrix  # noqa: F401
    trails.rebuild()
    tr = trails.TRAILS[K_CUBE]
    keys = tr.keys
    points = [(K_CUBE, f) for f in keys]
    before = {f: tr.position(f).copy() for f in range(keys[0], keys[-1] + 1)}
    pivot = sum((before[f] for f in keys), Vector()) / len(keys)
    jac = trails.jacobians(scene, points)
    inv = {p: m.inverted_safe() for p, m in jac.items()}
    edit = trails.KeyEdit(scene, points)
    deltas = {(K_CUBE, f): inv[(K_CUBE, f)] @ (pivot + world @ (before[f] - pivot) - before[f]) for f in keys}
    maps = {p: inv[p] @ world @ jac[p] for p in deltas}
    edit.apply(deltas, maps)
    trails.rebuild()
    tr = trails.TRAILS[K_CUBE]
    worst = max((tr.position(f) - (pivot + world @ (before[f] - pivot))).length for f in before)
    edit.cancel()
    trails.rebuild()
    restored = max((trails.TRAILS[K_CUBE].position(f) - before[f]).length for f in before)
    return worst, restored


def t_rotate_keeps_shape():
    from mathutils import Matrix
    worst, restored = rigid_transform(Matrix.Rotation(math.radians(90), 3, 'Z'))
    tilted, _ = rigid_transform(Matrix.Rotation(math.radians(70), 3, Vector((1.0, 0.6, 0.8)).normalized()))
    assert worst < 1e-4 and tilted < 1e-4 and restored < 1e-5, (worst, tilted, restored)
    return {"max_error_every_frame": worst, "tilted_axis_error": tilted, "cancel_restored": restored}


def t_scale_keeps_shape():
    from mathutils import Matrix
    worst, restored = rigid_transform(Matrix.Identity(3) * 1.7)
    assert worst < 1e-4 and restored < 1e-5, (worst, restored)
    return {"max_error_every_frame": worst, "cancel_restored": restored}


def t_selection_sets():
    """Saved selections: exactly the saved bones get selected (not the whole bone collection)."""
    sets = scene.anim_selection_sets
    sets.clear()

    def selected():
        return sorted(b.name for b in rig.pose.bones if trails.bone_selected(b))

    def only(*names):
        for b in rig.pose.bones:
            trails.select_bone(b, b.name in names)

    only("hand_ik", "ctrl_options")
    rig.data.bones.active = rig.data.bones["hand_ik"]
    bpy.ops.anim_sel.new(name="Lips")
    only("root")
    bpy.ops.anim_sel.new(name="Root")
    only("forearm")
    bpy.ops.anim_sel.select(index=0, mode='SET')
    replaced = selected()
    active = rig.data.bones.active.name
    bpy.ops.anim_sel.select(index=1, mode='ADD')
    added = selected()
    bpy.ops.anim_sel.select(index=0, mode='SUB')
    removed = selected()
    bpy.ops.anim_sel.move(index=1, direction='UP')
    order = [s.name for s in sets]
    bpy.ops.anim_sel.remove(index=0)
    left = [s.name for s in sets]
    bpy.ops.object.mode_set(mode='OBJECT')
    for ob in bpy.context.selected_objects:
        ob.select_set(False)
    cube.select_set(True)
    bpy.ops.anim_sel.new(name="Props")
    cube.select_set(False)
    bpy.ops.anim_sel.select(index=len(sets) - 1)
    obj_ok = cube.select_get()
    bpy.ops.object.mode_set(mode='POSE')
    sets.clear()
    result = {"replace": replaced, "active": active, "add": added, "remove": removed, "order": order,
              "after_remove": left, "objects": obj_ok}
    assert replaced == ["ctrl_options", "hand_ik"] and active == "hand_ik" and added == ["ctrl_options", "hand_ik", "root"] \
        and removed == ["root"] and order == ["Root", "Lips"] and left == ["Lips"] and obj_ok, result
    return result


def _only_bones(*names):
    for b in rig.pose.bones:
        trails.select_bone(b, b.name in names)


def _keys(fc):
    return [(round(kp.co.x, 3), round(kp.co.y, 5)) for kp in fc.keyframe_points]


def t_tween():
    """Tween / Neighbor / Push at the current frame; the drag job restores everything on cancel."""
    from motion_trail_editor import common, keytools
    _only_bones("hand_ik")
    fcs = [trails.location_fcurve(rig, "hand_ik", i) for i in range(3)]
    before = [_keys(fc) for fc in fcs]
    # A frame with no key on any channel, keys on both sides.
    frame = next(f for f in range(2, 100) if all(trails.find_key(fc, f) is None and None not in common.neighbors(fc, f)
                                               for fc in fcs))
    scene.frame_set(frame)
    sides = [common.neighbors(fc, frame) for fc in fcs]
    p = [a.co.y for a, _b in sides]
    n = [b.co.y for _a, b in sides]
    line = [a.co.y + (b.co.y - a.co.y) * (frame - a.co.x) / (b.co.x - a.co.x) for a, b in sides]

    job = keytools.TweenJob(bpy.context, 'TWEEN')
    job.apply(0.4)
    job.restore()
    restored = [_keys(fc) for fc in fcs] == before

    def here():
        return [trails.find_key(fc, frame).co.y for fc in fcs]

    bpy.ops.anim_tools.tween(factor=0.0, mode='TWEEN')
    mid = here()
    bpy.ops.anim_tools.tween(factor=-0.5, mode='TWEEN')  # 25%
    quarter = here()
    scene.frame_set(frame)
    pose = list(hand.location)
    bpy.ops.anim_tools.tween(factor=1.0, mode='NEIGHBOR')
    neighbor = here()
    bpy.ops.anim_tools.tween(factor=-1.0, mode='PUSH')  # flatten onto the in-between line
    flat = here()
    for fc in fcs:
        fc.keyframe_points.remove(trails.find_key(fc, frame))
        fc.update()
    clean = [_keys(fc) for fc in fcs] == before
    scene.frame_set(1)

    def close(a, b):
        return all(abs(x - y) < 1e-4 for x, y in zip(a, b))
    result = {"frame": frame, "restored": restored, "mid": close(mid, [(a + b) / 2 for a, b in zip(p, n)]),
              "quarter": close(quarter, [a + (b - a) * 0.25 for a, b in zip(p, n)]),
              "pose follows": close(pose, quarter), "neighbor": close(neighbor, n), "flat": close(flat, line),
              "clean": clean}
    assert all(result.values()), result
    return result


def t_euler_filter():
    """360° jumps and a gimbal flip get fixed without changing any rotation."""
    from mathutils import Euler
    bpy.ops.object.mode_set(mode='OBJECT')
    ob = bpy.data.objects.new("EulerTest", None)
    scene.collection.objects.link(ob)
    d = math.radians
    flip = lambda x, y, z: (x + math.pi, math.pi - y, z + math.pi)  # same rotation (XYZ)
    rotations = [(d(10), d(20), d(170)), (d(11), d(21), d(175)), (d(12), d(22), d(-175)),
                 flip(d(13), d(23), d(-170)), (d(14), d(24), d(-165))]
    for i, rot in enumerate(rotations):
        ob.rotation_euler = rot
        ob.keyframe_insert("rotation_euler", frame=1 + i * 5)
    fcs = sorted((fc for fc in trails.action_fcurves(ob)), key=lambda fc: fc.array_index)

    def eulers():
        return [Euler([fc.keyframe_points[k].co.y for fc in fcs], 'XYZ') for k in range(len(rotations))]
    old = eulers()
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.anim_tools.euler_filter()
    new = eulers()
    same = all((a.to_matrix() - b.to_matrix()).median_scale < 1e-4 if hasattr(a, "median_scale") else
               max(abs(x - y) for ra, rb in zip(a.to_matrix(), b.to_matrix()) for x, y in zip(ra, rb)) < 1e-4
               for a, b in zip(old, new))
    jumps = max(abs(b[i] - a[i]) for a, b in zip(new, new[1:]) for i in range(3))
    bpy.data.objects.remove(ob)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='POSE')
    result = {"same rotations": same, "max jump deg": round(math.degrees(jumps), 2)}
    assert same and jumps < d(10), result
    return result


def t_anim_offset():
    """A pose change moves all keys of the channel (or only the masked frames); auto-key is paused."""
    from motion_trail_editor import offset
    bpy.ops.object.mode_set(mode='OBJECT')
    ob = bpy.data.objects.new("OffsetTest", None)
    scene.collection.objects.link(ob)
    for f in (1, 21, 41, 61, 81):
        ob.location = (f * 0.1, 0.0, 0.0)
        ob.keyframe_insert("location", frame=f)
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    fx = trails.location_fcurve(ob, "", 0)
    fy = trails.location_fcurve(ob, "", 1)
    scene.tool_settings.use_keyframe_insert_auto = True
    scene.frame_set(21)
    offset.enable(bpy.context)
    auto_paused = not scene.tool_settings.use_keyframe_insert_auto
    ob.location.x += 0.5
    offset.apply_offsets(bpy.context)
    whole = [round(y, 4) for _x, y in _keys(fx)]
    untouched_y = all(abs(kp.co.y) < 1e-6 for kp in fy.keyframe_points)

    s = scene.anim_tools
    s.offset_use_mask, s.offset_start, s.offset_end = True, 30, 50
    scene.frame_set(41)
    pre = {f: fx.evaluate(f) for f in (30, 50)}
    ob.location.x += 1.0
    offset.apply_offsets(bpy.context)
    masked = {int(x): round(y, 4) for x, y in _keys(fx)}
    s.offset_use_mask = False
    offset.disable(bpy.context)
    auto_back = scene.tool_settings.use_keyframe_insert_auto
    scene.tool_settings.use_keyframe_insert_auto = False
    bpy.data.objects.remove(ob)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='POSE')
    scene.frame_set(1)
    result = {"auto paused": auto_paused, "whole": whole, "y untouched": untouched_y, "masked": masked,
              "auto restored": auto_back}
    assert auto_paused and auto_back and untouched_y and whole == [0.6, 2.6, 4.6, 6.6, 8.6], result
    # 30 and 50 are new keys on the old curve, moved with the frames inside the mask; 21 and 61 stay.
    expect = {21: 2.6, 30: pre[30] + 1.0, 41: 5.6, 50: pre[50] + 1.0, 61: 6.6}
    assert all(abs(masked[f] - v) < 1e-3 for f, v in expect.items()), (result, expect)
    return result


def _skinned_mesh():
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh = bpy.data.meshes.new("SkinTest")
    mesh.from_pydata([(0, 0, 1), (1, 0, 1), (0, 1, 1), (0, 0, 2)], [], [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)])
    ob = bpy.data.objects.new("SkinTest", mesh)
    scene.collection.objects.link(ob)
    ob.modifiers.new("Armature", 'ARMATURE').object = rig
    ob.vertex_groups.new(name="root").add(range(4), 1.0, 'REPLACE')
    for o in bpy.context.selected_objects:
        o.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='POSE')
    return ob


def t_ghosts_and_silhouette():
    """The rig's meshes are found from Pose Mode; ghosts capture them deformed; silhouette restores colours."""
    from motion_trail_editor import common, ghosts
    ob = _skinned_mesh()
    found = [o.name for o in common.character_meshes(bpy.context)]
    scene.frame_set(61)
    ghosts.clear()
    bpy.ops.anim_tools.ghost_add()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ob_eval = ob.evaluated_get(depsgraph)
    expect = [tuple(ob_eval.matrix_world @ v.co) for v in ob_eval.data.vertices]
    g = ghosts.GHOSTS[0] if ghosts.GHOSTS else None
    ghost_ok = g is not None and g.frame == 61 and len(g.indices) == 4 and \
        max(abs(a - b) for p, q in zip(g.positions, expect) for a, b in zip(p, q)) < 1e-4
    bpy.ops.anim_tools.ghost_add()  # same frame again: replaced, not doubled
    once = len(ghosts.GHOSTS) == 1
    bpy.ops.anim_tools.ghost_clear()
    cleared = not ghosts.GHOSTS

    ob.color = (0.2, 0.4, 0.6, 1.0)
    bpy.ops.anim_tools.silhouette()
    black = tuple(round(c, 3) for c in ob.color) == (0.0, 0.0, 0.0, 1.0) and scene.anim_tools.silhouette
    bpy.ops.anim_tools.silhouette()
    back = tuple(round(c, 3) for c in ob.color) == (0.2, 0.4, 0.6, 1.0) and not scene.anim_tools.silhouette \
        and "anim_tools_silhouette_color" not in ob
    bpy.data.objects.remove(ob)
    scene.frame_set(1)
    result = {"found": found, "ghost": ghost_ok, "replaced": once, "cleared": cleared, "black": black, "back": back}
    assert found == ["SkinTest"] and ghost_ok and once and cleared and black and back, result
    return result


def t_onion():
    """Onion skin: previous / next keys (or every few frames) evaluated and cached; the playhead and pose
    changes that are not keyed yet survive the evaluation."""
    from motion_trail_editor import onion
    ob = _skinned_mesh()
    s = scene.anim_tools
    s.onion_mode, s.onion_before, s.onion_after = 'KEYS', 2, 1
    scene.frame_set(19)  # keys at 1, 13, 25...
    _only_bones("hand_ik")
    hand.location.x += 0.3  # not keyed
    moved_x = hand.location.x
    onion.enable(bpy.context, [ob])
    keys = sorted(onion.key_frames([ob]))
    expect = (tuple(f for f in keys if f < 19)[-2:], tuple(f for f in keys if f > 19)[:1])
    onion.update(bpy.context)
    shown = onion.state.shown
    cached = sorted(onion.state.cache)
    kept = abs(hand.location.x - moved_x) < 1e-6 and scene.frame_current == 19
    g13, g25 = onion.state.cache.get(13), onion.state.cache.get(25)
    differ = g13 is not None and g25 is not None and float(abs(g13.positions - g25.positions).max()) > 1e-3
    scene.frame_set(13)
    truth13 = [tuple(ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world @ v.co)
               for v in ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices]
    exact = g13 is not None and max(abs(a - b) for p, q in zip(g13.positions, truth13) for a, b in zip(p, q)) < 1e-4

    s.onion_mode, s.onion_step, s.onion_before, s.onion_after = 'FRAMES', 3, 1, 2
    scene.frame_set(19)
    onion.update(bpy.context)
    frames_mode = onion.state.shown
    onion.state.dirty = True  # keys changed: everything is evaluated again
    onion.update(bpy.context)
    refreshed = sorted(onion.state.cache) == [16, 22, 25]
    onion.disable()
    s.onion_mode, s.onion_before, s.onion_after = 'KEYS', 1, 1
    bpy.data.objects.remove(ob)
    scene.frame_set(1)
    result = {"shown": shown, "expect": expect, "cached": cached, "kept": kept, "differ": differ,
              "exact": bool(exact), "frames": frames_mode, "refreshed": refreshed, "ms": round(onion.state.last_ms, 1)}
    assert shown == expect and expect[1] == (25,) and 13 in expect[0] and cached == sorted(expect[0] + expect[1]) \
        and kept and differ and exact and frames_mode == ((16,), (22, 25)) and refreshed, result
    return result


def t_header_draws():
    """The header buttons draw without errors (UILayout is not available headless: use a recorder)."""
    from motion_trail_editor import header

    class Rec:
        calls = []

        def __getattr__(self, name):
            def call(*args, **kwargs):
                Rec.calls.append((name, args, kwargs.get("icon")))
                return Rec()
            return call

        def __setattr__(self, name, value):
            pass
    header.draw_buttons(Rec(), bpy.context)
    icons = [c[2] for c in Rec.calls if c[2]]
    result = {"calls": len(Rec.calls), "icons": icons}
    assert icons[:3] == ["TRACKING", "GROUP_BONE", "IPO_EASE_IN_OUT"] and icons.count("DOT") == 4         and icons.count("KEYFRAME_HLT") == 2 and "CON_ACTION" in icons and icons[-1] == "OUTLINER_OB_ARMATURE", result
    return result


for name, fn in (("rebuild + accuracy", t_rebuild),
                 ("saved selections", t_selection_sets),
                 ("rotate all keys: path keeps its shape", t_rotate_keeps_shape),
                 ("scale all keys: path keeps its shape", t_scale_keeps_shape),
                 ("handle: move tail end", t_handle_move),
                 ("handle: scale tail", t_handle_scale),
                 ("new key gets selected", t_select_new_key),
                 ("deselecting the bone deselects its keys", t_deselect_owner_prunes),
                 ("move bone key (rotating parent) + cancel", t_move_bone_under_rotating_parent),
                 ("move key of bones with special options / Child Of", t_move_special_bones),
                 ("move object key", t_move_object),
                 ("move point without key", t_move_point_without_location_key),
                 ("insert / delete key", t_insert_delete),
                 ("object-mode fallback == path engine", t_object_mode_fallback),
                 ("user's own motion path kept", t_user_path_kept),
                 ("signature: only curves that move the trail", t_signature),
                 ("evaluated window follows the playhead", t_eval_window),
                 ("selection sync", t_selection_sync),
                 ("tween / neighbor / push", t_tween),
                 ("euler filter", t_euler_filter),
                 ("anim offset (+ mask)", t_anim_offset),
                 ("ghosts + silhouette", t_ghosts_and_silhouette),
                 ("onion skin", t_onion),
                 ("header buttons", t_header_draws)):
    check(name, fn)

try:
    mte.unregister()
    results.append(("PASS", "unregister", None))
except Exception:
    results.append(("FAIL", "unregister", traceback.format_exc()))

print("\n===== RESULTS =====")
for status, name, out in results:
    print(f"[{status}] {name}: {out}")
print("FAILED:", sum(r[0] == "FAIL" for r in results), "of", len(results))
