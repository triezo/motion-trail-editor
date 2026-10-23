"""Operators: enabling trails and editing trail keys in the viewport."""
import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty
from bpy.types import Operator
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d
from mathutils import Matrix, Vector

from . import draw, trails

TOOL_POSE = "motion_trail.tool_pose"
TOOL_OBJECT = "motion_trail.tool_object"


def _mouse(event):
    return Vector((event.mouse_region_x, event.mouse_region_y))


def _in_view3d(context):
    """A 3D viewport where the trails are shown (overlays on): hidden trails cannot be clicked or moved."""
    return (context.area is not None and context.area.type == 'VIEW_3D' and context.region_data is not None
            and trails.shown_in(context.space_data))


def _refresh(context, keys=None):
    trails.rebuild(keys)
    draw.tag_redraw_all()


def _selection_changed(context, extend):
    trails.sync_selection_to_owners(context, extend)
    trails.request_jacobians()  # handles appear a moment later instead of delaying the click
    draw.tag_redraw_all()


# ---------------------------------------------------------------------------
# Trail management
# ---------------------------------------------------------------------------

class MOTIONTRAIL_OT_toggle(Operator):
    """Show or hide the motion trail of the selected bones (Pose Mode) or objects"""
    bl_idname = "motion_trail.toggle"
    bl_label = "Toggle Motion Trail"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'POSE', 'OBJECT'}

    def execute(self, context):
        s = context.scene.motion_trail
        if context.mode == 'POSE':
            targets = [(pb.id_data, pb.name) for pb in (context.selected_pose_bones or [])]
        else:
            targets = [(ob, "") for ob in context.selected_objects]
        if not targets:
            self.report({'WARNING'}, "Select bones (Pose Mode) or objects")
            return {'CANCELLED'}

        existing = {}
        for i, item in enumerate(s.items):
            if item.object is not None:
                existing[(item.object.name_full, item.bone)] = i
        keys = [(ob.name_full, bone) for ob, bone in targets]

        if all(k in existing for k in keys):
            for i in sorted((existing[k] for k in keys), reverse=True):
                s.items.remove(i)
            _refresh(context)
            self.report({'INFO'}, f"Motion trail off ({len(keys)})")
            return {'FINISHED'}

        for ob, bone in targets:
            if (ob.name_full, bone) not in existing:
                item = s.items.add()
                item.object = ob
                item.bone = bone
        _refresh(context)

        if s.auto_tool:
            tool = TOOL_POSE if context.mode == 'POSE' else TOOL_OBJECT
            try:
                bpy.ops.wm.tool_set_by_id(name=tool, space_type='VIEW_3D')
            except RuntimeError:
                pass

        static = [ob.name for ob, _bone in targets if not (ob.animation_data and ob.animation_data.action)]
        if static:
            self.report({'WARNING'}, f"No animation on: {', '.join(sorted(set(static)))}")
        else:
            self.report({'INFO'}, f"Motion trail on ({len(keys)})")
        return {'FINISHED'}


class MOTIONTRAIL_OT_remove(Operator):
    """Remove this motion trail"""
    bl_idname = "motion_trail.remove"
    bl_label = "Remove Motion Trail"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    index: IntProperty()

    def execute(self, context):
        s = context.scene.motion_trail
        if 0 <= self.index < len(s.items):
            s.items.remove(self.index)
        _refresh(context)
        return {'FINISHED'}


class MOTIONTRAIL_OT_clear_all(Operator):
    """Remove all motion trails"""
    bl_idname = "motion_trail.clear_all"
    bl_label = "Remove All Motion Trails"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.motion_trail.items.clear()
        trails.clear_selection()
        _refresh(context)
        return {'FINISHED'}


class MOTIONTRAIL_OT_refresh(Operator):
    """Recalculate all motion trails"""
    bl_idname = "motion_trail.refresh"
    bl_label = "Refresh Motion Trails"

    def execute(self, context):
        _refresh(context)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

class MOTIONTRAIL_OT_hover(Operator):
    """Highlight the trail key under the mouse"""
    bl_idname = "motion_trail.hover"
    bl_label = "Highlight Trail Key"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return bool(trails.TRAILS) and _in_view3d(context)

    def invoke(self, context, event):
        hit = trails.pick(context, _mouse(event))
        key_hit = hit[1] if hit and hit[0] == 'KEY' else None
        handle_hit = hit[1] if hit and hit[0] == 'HANDLE' else None
        if key_hit != trails.HOVER[0] or handle_hit != trails.HOVER_HANDLE[0]:
            trails.HOVER[0] = key_hit
            trails.HOVER_HANDLE[0] = handle_hit
            context.area.tag_redraw()
        return {'PASS_THROUGH'}


class MOTIONTRAIL_OT_click(Operator):
    """Select a trail key or handle (drag to move it). A click on nothing deselects everything"""
    bl_idname = "motion_trail.click"
    bl_label = "Select Trail Key"
    bl_options = {'REGISTER', 'UNDO'}

    extend: BoolProperty(name="Extend", description="Toggle in the selection", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(trails.TRAILS) and _in_view3d(context)

    def invoke(self, context, event):
        hit = trails.pick(context, _mouse(event))
        if hit is None:
            if not self.extend:
                # Click on nothing: deselect trail keys and bones/objects. The click still passes through,
                # so a bone or object under the mouse gets selected by Blender as usual.
                trails.clear_selection()
                trails.deselect_owners(context)
                trails.sync_key_selection(context)
                draw.tag_redraw_all()
            return {'PASS_THROUGH'}

        kind, item = hit
        self.kind, self.item = kind, item
        if kind == 'KEY':
            key, frame = item
            selected = trails.SELECTION.setdefault(key, set())
            self.was_selected = frame in selected
            if self.extend:
                selected.symmetric_difference_update({frame})
            elif not self.was_selected:
                trails.clear_selection()
                trails.SELECTION[key] = {frame}
        else:
            self.was_selected = item in trails.HANDLE_SELECTION
            if self.extend:
                trails.HANDLE_SELECTION.symmetric_difference_update({item})
            elif not self.was_selected:
                trails.clear_selection()
                trails.HANDLE_SELECTION.add(item)
        self._apply(context)

        self.start = _mouse(event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _select_only(self):
        trails.clear_selection()
        if self.kind == 'KEY':
            trails.SELECTION[self.item[0]] = {self.item[1]}
        else:
            trails.HANDLE_SELECTION.add(self.item)

    def _apply(self, context):
        _selection_changed(context, self.extend)
        if self.kind == 'KEY' and context.scene.motion_trail.jump_to_frame and not self.extend:
            context.scene.frame_set(self.item[1])

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            threshold = context.preferences.inputs.drag_threshold_mouse * trails.ui_scale()
            if (_mouse(event) - self.start).length > threshold:
                if trails.has_selection():
                    bpy.ops.motion_trail.transform('INVOKE_DEFAULT', mode='TRANSLATE', release_confirm=True,
                                                   use_start_mouse=True, start_mouse=self.start)
                return {'FINISHED'}
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self.extend and self.was_selected:
                self._select_only()
                self._apply(context)
            return {'FINISHED'}
        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class MOTIONTRAIL_OT_select_box(Operator):
    """Box select trail keys"""
    bl_idname = "motion_trail.select_box"
    bl_label = "Box Select Trail Keys"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=(('SET', "Set", "Replace the selection"),
               ('ADD', "Extend", "Add to the selection"),
               ('SUB', "Subtract", "Remove from the selection")),
        default='SET', options={'SKIP_SAVE'})
    wait_for_input: BoolProperty(default=True, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return bool(trails.TRAILS) and _in_view3d(context)

    def invoke(self, context, event):
        self.start = None
        if not self.wait_for_input:
            region = context.region
            self.start = (event.mouse_prev_press_x - region.x, event.mouse_prev_press_y - region.y)
            trails.state.box = (*self.start, event.mouse_region_x, event.mouse_region_y)
        context.window.cursor_modal_set('CROSSHAIR')
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _end(self, context):
        trails.state.box = None
        context.window.cursor_modal_restore()
        context.area.tag_redraw()

    def modal(self, context, event):
        x, y = event.mouse_region_x, event.mouse_region_y
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if self.start is not None:
                trails.state.box = (*self.start, x, y)
                context.area.tag_redraw()
        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS' and self.start is None:
                self.start = (x, y)
                if event.shift:
                    self.mode = 'ADD'
                elif event.ctrl:
                    self.mode = 'SUB'
                trails.state.box = (x, y, x, y)
            elif event.value == 'RELEASE' and self.start is not None:
                box = trails.state.box
                self._end(context)
                found = trails.points_in_rect(context, box)
                if self.mode == 'SET':
                    trails.clear_selection()
                for key, f in found:
                    frames = trails.SELECTION.setdefault(key, set())
                    if self.mode == 'SUB':
                        frames.discard(f)
                    else:
                        frames.add(f)
                _selection_changed(context, extend=self.mode != 'SET')
                return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._end(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class MOTIONTRAIL_OT_select_all(Operator):
    """Select or deselect all visible trail keys"""
    bl_idname = "motion_trail.select_all"
    bl_label = "(De)select All Trail Keys"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('TOGGLE', "Toggle", ""), ('SELECT', "Select", ""), ('DESELECT', "Deselect", "")),
                         default='TOGGLE')

    @classmethod
    def poll(cls, context):
        return bool(trails.TRAILS)

    def invoke(self, context, event):
        if self.action == 'DESELECT':
            # From the keymap (Alt+A): clear the trail selection and let Blender deselect the bones too.
            trails.clear_selection()
            trails.sync_key_selection(context)
            draw.tag_redraw_all()
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        action = self.action
        if action == 'TOGGLE':
            action = 'DESELECT' if trails.has_selection() else 'SELECT'
        trails.clear_selection()
        if action == 'SELECT':
            scene = context.scene
            for key, trail in trails.TRAILS.items():
                f0, f1 = trails.visible_range(scene, trail)
                trails.SELECTION[key] = {f for f in trail.keys if f0 <= f <= f1}
        _selection_changed(context, extend=True)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------

AXES = {'X': Vector((1.0, 0.0, 0.0)), 'Y': Vector((0.0, 1.0, 0.0)), 'Z': Vector((0.0, 0.0, 1.0))}


class MOTIONTRAIL_OT_transform(Operator):
    """Move, rotate or scale the selected trail keys or handles.
    Handles: G moves the tail end, R turns it, S scales its length. X/Y/Z: world axis, Shift: precision"""
    bl_idname = "motion_trail.transform"
    bl_label = "Transform Trail Keys"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    mode: EnumProperty(
        name="Mode",
        items=(('TRANSLATE', "Move", ""), ('ROTATE', "Rotate", ""), ('SCALE', "Scale", "")),
        default='TRANSLATE')
    release_confirm: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'})
    use_start_mouse: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'})
    start_mouse: FloatVectorProperty(size=2, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _in_view3d(context) and trails.has_selection()

    def _init_keys(self, scene):
        points = [(k, f) for k, f in trails.selected_points()
                  if k in trails.TRAILS and trails.TRAILS[k].position(f) is not None]
        if not points:
            return False
        jac = trails.jacobians(scene, points)
        trails.JACOBIANS.update(jac)  # the handles of the moving keys follow them
        self.keys = {k for k, _f in points}
        self.origins = {p: trails.TRAILS[p[0]].position(p[1]).copy() for p in points}
        self.anchors = None
        self.jac = jac
        self.inverse = {p: m.inverted_safe() for p, m in jac.items()}
        self.edit = trails.KeyEdit(scene, points)
        # Turn/scale around Blender's Pivot Point (header of the viewport).
        values = list(self.origins.values())
        self.depth = sum(values, Vector()) / len(values)
        if self.pivot_mode == 'CURSOR':
            self.pivot = scene.cursor.location.copy()
        elif self.pivot_mode == 'BOUNDING_BOX_CENTER':
            lo = Vector([min(v[i] for v in values) for i in range(3)])
            hi = Vector([max(v[i] for v in values) for i in range(3)])
            self.pivot = (lo + hi) / 2.0
        else:
            self.pivot = self.depth.copy()
        return True

    def _init_handles(self, scene, region, rv3d):
        handles = sorted(h for h in trails.HANDLE_SELECTION if h[0] in trails.TRAILS)
        need = sorted({(k, f) for k, f, _s in handles if (k, f) not in trails.JACOBIANS})
        if need:
            trails.JACOBIANS.update(trails.jacobians(scene, need))
        # Start from what is drawn: flat tails start at their minimum drawn length.
        drawn = {(k, f, side): (co, end, flat)
                 for k, f, side, co, end, flat in trails.visible_handles(scene, region, rv3d)}
        self.origins, self.anchors, self.inverse, self.flat = {}, {}, {}, set()
        for h in handles:
            if h not in drawn or (h[0], h[1]) not in trails.JACOBIANS:
                continue
            co, end, flat = drawn[h]
            self.origins[h] = end.copy()
            self.anchors[h] = co.copy()
            self.inverse[h] = trails.JACOBIANS[(h[0], h[1])].inverted_safe()
            if flat:
                self.flat.add(h)
        if not self.origins:
            return False
        self.keys = {h[0] for h in self.origins}
        # Both tails of a key selected: move them independently instead of keeping them in line.
        self.both = {(k, f) for k, f, s in self.origins if (k, f, 'L' if s == 'R' else 'R') in self.origins}
        self.edit = trails.HandleEdit(scene, list(self.origins))
        self.pivot = sum(self.origins.values(), Vector()) / len(self.origins)
        self.depth = self.pivot
        return True

    def invoke(self, context, event):
        scene = context.scene
        self.region, self.rv3d = context.region, context.region_data
        self.handle_mode = not trails.has_key_selection()
        self.pivot_mode = scene.tool_settings.transform_pivot_point
        if (not self.handle_mode and self.mode != 'TRANSLATE' and len(trails.selected_points()) == 1
                and self.pivot_mode not in {'CURSOR', 'INDIVIDUAL_ORIGINS'}):
            # Turning or scaling one point around itself changes nothing: R/S go to Blender as usual
            # (rotate/scale the object or bone).
            return {'PASS_THROUGH'}
        if self.handle_mode:
            ok = self._init_handles(scene, self.region, self.rv3d)
        else:
            ok = self._init_keys(scene)
        if not ok:
            return {'PASS_THROUGH'}  # nothing to transform here: let Blender have the key
        center = self.pivot
        if self.handle_mode and self.mode != 'TRANSLATE':
            center = sum(self.anchors.values(), Vector()) / len(self.anchors)
        self.pivot_2d = location_3d_to_region_2d(self.region, self.rv3d, center) or _mouse(event)
        self.trackball = False
        # A drag starts where the button was pressed, not where the drag threshold was crossed.
        self.start = Vector(self.start_mouse) if self.use_start_mouse else _mouse(event)
        self.mouse = _mouse(event)
        self.last = self.mouse.copy()
        self.axis = None

        edited = {}
        for p in self.origins:
            edited.setdefault(p[0], set()).add(p[1])
        self.preview = trails.LivePreview(scene, edited)

        trails.state.transforming = True
        context.window_manager.modal_handler_add(self)
        self._update(context)
        return {'RUNNING_MODAL'}

    def _center(self, p):
        # Handles turn/scale around their own key; keys around the pivot (or each around itself with
        # Individual Origins, which then only turns/scales their tails).
        if self.handle_mode:
            return self.anchors[p]
        if self.pivot_mode == 'INDIVIDUAL_ORIGINS':
            return self.origins[p]
        return self.pivot

    def _targets(self):
        """(world targets per element, header text, scale factor, world 3x3 for the tails or None)."""
        axis = AXES.get(self.axis)
        if self.mode == 'TRANSLATE':
            a = region_2d_to_location_3d(self.region, self.rv3d, self.start, self.depth)
            b = region_2d_to_location_3d(self.region, self.rv3d, self.mouse, self.depth)
            delta = b - a
            if axis is not None:
                delta = axis * delta.dot(axis)
            text = f"Move  {delta.x:.4f}  {delta.y:.4f}  {delta.z:.4f}"
            return {p: o + delta for p, o in self.origins.items()}, text, 1.0, None

        if self.mode == 'ROTATE':
            if self.trackball:
                d = (self.mouse - self.start) * 0.01
                view = self.rv3d.view_rotation
                rot = (Matrix.Rotation(d.x, 3, view @ Vector((0.0, 1.0, 0.0))) @
                       Matrix.Rotation(-d.y, 3, view @ Vector((1.0, 0.0, 0.0))))
                text = f"Trackball  {math.degrees(d.x):.1f}°  {math.degrees(-d.y):.1f}°"
            else:
                v0, v1 = self.start - self.pivot_2d, self.mouse - self.pivot_2d
                angle = 0.0
                if v0.length > 1.0 and v1.length > 1.0:
                    angle = math.atan2(v0.x * v1.y - v0.y * v1.x, v0.dot(v1))
                toward_viewer = self.rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
                rot_axis = toward_viewer if axis is None else axis
                if axis is not None and axis.dot(toward_viewer) < 0.0:
                    angle = -angle
                rot = Matrix.Rotation(angle, 3, rot_axis)
                text = f"Rotate  {math.degrees(angle):.1f}°   (R again: trackball)"
            return ({p: self._center(p) + rot @ (o - self._center(p)) for p, o in self.origins.items()},
                    text, 1.0, rot)

        d0 = (self.start - self.pivot_2d).length
        factor = (self.mouse - self.pivot_2d).length / d0 if d0 > 1.0 else 1.0
        if axis is None or self.handle_mode:
            world = Matrix.Identity(3) * factor
        else:
            along = Matrix([[axis[i] * axis[j] for j in range(3)] for i in range(3)])
            world = Matrix.Identity(3) + along * (factor - 1.0)
        result = {p: self._center(p) + world @ (o - self._center(p)) for p, o in self.origins.items()}
        label = "Scale tails" if self.handle_mode else "Scale"
        return result, f"{label}  {factor:.3f}", factor, world

    def _update(self, context):
        targets, text, factor, world = self._targets()
        if self.handle_mode:
            for h, t in targets.items():
                if self.mode == 'SCALE' and h not in self.flat:
                    self.edit.scale(h, factor)
                else:
                    local = self.inverse[h] @ (t - self.anchors[h])
                    self.edit.set_offset(h, local, keep_aligned=(h[0], h[1]) not in self.both)
        else:
            deltas = {p: self.inverse[p] @ (t - self.origins[p]) for p, t in targets.items() if p in self.inverse}
            # Rotating/scaling keys also turns/scales their tails, so the path keeps its shape.
            maps = None
            if world is not None:
                maps = {p: self.inverse[p] @ world @ self.jac[p] for p in deltas}
            self.edit.apply(deltas, maps)
        # The line follows at mouse speed without evaluating the scene; exact positions on release.
        self.preview.update()
        if not self.handle_mode:
            for (key, f), t in targets.items():
                trail = trails.TRAILS.get(key)
                if trail is not None:
                    i = f - trail.frame_start
                    if 0 <= i < len(trail.positions):
                        trail.positions[i] = t.copy()
        if self.axis:
            text += f"   along {self.axis}"
        context.area.header_text_set(text + "   (X/Y/Z axis, Shift precision)")
        context.area.tag_redraw()

    def _finish(self, context):
        context.area.header_text_set(None)
        trails.state.transforming = False
        # Exact positions, but only for the stretch of the trail that the edit can change.
        if self.preview.span is not None:
            trails.rebuild(self.preview.keys | self.keys, frames=self.preview.span)
        else:
            trails.rebuild(self.keys)
        trails.sync_selection_to_owners(context, extend=True)
        trails.request_jacobians()
        draw.tag_redraw_all()

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            m = _mouse(event)
            self.mouse += (m - self.last) * (0.1 if event.shift else 1.0)
            self.last = m
            self._update(context)
            return {'RUNNING_MODAL'}

        if event.value == 'PRESS' and event.type in AXES:
            self.axis = None if self.axis == event.type else event.type
            self._update(context)
            return {'RUNNING_MODAL'}

        if event.value == 'PRESS' and event.type == 'R' and self.mode == 'ROTATE':
            self.trackball = not self.trackball  # R R: trackball, like Blender (starts from zero again)
            self.start = self.mouse.copy()
            self._update(context)
            return {'RUNNING_MODAL'}

        confirm = event.value == 'PRESS' and event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'}
        if self.release_confirm and event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            confirm = True
        if confirm:
            self._finish(context)
            return {'FINISHED'}

        if event.value == 'PRESS' and event.type in {'RIGHTMOUSE', 'ESC'}:
            self.edit.cancel()
            self._finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


class MOTIONTRAIL_OT_key_at_mouse(Operator):
    """Delete the key under the mouse, or insert a key where the mouse is on the trail"""
    bl_idname = "motion_trail.key_at_mouse"
    bl_label = "Insert/Delete Trail Key"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(trails.TRAILS) and _in_view3d(context)

    def invoke(self, context, event):
        scene = context.scene
        mouse = _mouse(event)
        hit = trails.hit_test(context, mouse)
        if hit is not None:
            trails.delete_keys(scene, [hit])
            trails.SELECTION.get(hit[0], set()).discard(hit[1])
            _refresh(context)
            self.report({'INFO'}, f"Deleted key at frame {hit[1]}")
            return {'FINISHED'}

        hit = trails.hit_test_line(context, mouse)
        if hit is None:
            return {'PASS_THROUGH'}
        key, frame = hit
        if frame not in trails.TRAILS[key].keys:
            if not trails.insert_keys(scene, key, frame):
                self.report({'WARNING'}, "This item has no action to key")
                return {'CANCELLED'}
            self.report({'INFO'}, f"Inserted key at frame {frame}")
        _refresh(context)
        trails.clear_selection()
        trails.SELECTION[key] = {frame}
        _selection_changed(context, extend=False)
        return {'FINISHED'}


class MOTIONTRAIL_OT_delete_keys(Operator):
    """Delete the selected trail keys (all transform channels of the item at that frame)"""
    bl_idname = "motion_trail.delete_keys"
    bl_label = "Delete Trail Keys"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return trails.has_key_selection() and _in_view3d(context)

    def execute(self, context):
        points = trails.selected_points()
        trails.delete_keys(context.scene, points)
        trails.clear_selection()
        _refresh(context)
        self.report({'INFO'}, f"Deleted {len(points)} trail key(s)")
        return {'FINISHED'}


classes = (
    MOTIONTRAIL_OT_toggle,
    MOTIONTRAIL_OT_remove,
    MOTIONTRAIL_OT_clear_all,
    MOTIONTRAIL_OT_refresh,
    MOTIONTRAIL_OT_hover,
    MOTIONTRAIL_OT_click,
    MOTIONTRAIL_OT_select_box,
    MOTIONTRAIL_OT_select_all,
    MOTIONTRAIL_OT_transform,
    MOTIONTRAIL_OT_key_at_mouse,
    MOTIONTRAIL_OT_delete_keys,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
