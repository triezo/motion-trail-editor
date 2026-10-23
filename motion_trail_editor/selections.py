"""Saved selections: store a set of bones (or objects) and select exactly them again with one click.

UI: a "Selection Manager" popover in the Dope Sheet / Timeline header (header.py), and one coloured button per
selection in the 3D Viewport tool header (click: select, Shift: add, Ctrl: remove).
"""
import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

from . import trails

_ICONS = bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys()
_COLOR_ICON = "STRIP_COLOR_0{}" if "STRIP_COLOR_01" in _ICONS else "SEQUENCE_COLOR_0{}"  # 4.4+ / 4.3
COLORS = 9


def color_icon(color):
    return _COLOR_ICON.format(min(max(color, 1), COLORS))


class SelectionMember(PropertyGroup):
    name: StringProperty()


class SelectionSet(PropertyGroup):
    name: StringProperty(name="Name", default="Selection")
    color: IntProperty(name="Color", default=1, min=1, max=COLORS)
    kind: EnumProperty(items=(('BONE', "Bone", ""), ('OBJECT', "Object", "")), default='BONE')
    armature: PointerProperty(type=bpy.types.Object)
    members: CollectionProperty(type=SelectionMember)
    active: StringProperty()


def sets(context):
    return context.scene.anim_selection_sets


def visible_sets(context):
    """(index, set) usable now: bone sets of armatures in Pose Mode, or object sets in Object Mode."""
    if context.mode == 'POSE':
        armatures = {ob.name_full for ob in context.objects_in_mode}
        return [(i, s) for i, s in enumerate(sets(context))
                if s.kind == 'BONE' and s.armature is not None and s.armature.name_full in armatures]
    if context.mode == 'OBJECT':
        return [(i, s) for i, s in enumerate(sets(context)) if s.kind == 'OBJECT']
    return []


def apply_selection(context, sel, mode='SET'):
    """Select the members of `sel`: SET replaces the selection, ADD adds, SUB removes. Returns how many."""
    value = mode != 'SUB'
    if sel.kind == 'BONE':
        ob = sel.armature
        if ob is None or ob.type != 'ARMATURE':
            return 0
        if mode == 'SET':
            for other in context.objects_in_mode or [ob]:
                if other.type == 'ARMATURE':
                    for pb in other.pose.bones:
                        trails.select_bone(pb, False)
        count = 0
        for m in sel.members:
            pb = ob.pose.bones.get(m.name)
            if pb is not None:
                trails.select_bone(pb, value)
                count += 1
        if value and sel.active in ob.data.bones:
            ob.data.bones.active = ob.data.bones[sel.active]
        return count
    if mode == 'SET':
        for other in context.selected_objects:
            other.select_set(False)
    count = 0
    for m in sel.members:
        ob = context.view_layer.objects.get(m.name)
        if ob is not None:
            ob.select_set(value)
            count += 1
    if value and sel.active in context.view_layer.objects:
        context.view_layer.objects.active = context.view_layer.objects[sel.active]
    return count


def _redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


class _IndexOp:
    index: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def item(self, context):
        items = sets(context)
        return items[self.index] if 0 <= self.index < len(items) else None


class ANIMSEL_OT_new(Operator):
    """Save the selected bones (Pose Mode) or objects as a selection button"""
    bl_idname = "anim_sel.new"
    bl_label = "New Selection"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name")

    @classmethod
    def poll(cls, context):
        if context.mode == 'POSE':
            return bool(context.selected_pose_bones)
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def invoke(self, context, event):
        self.name = f"Selection {len(sets(context)) + 1}"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        sel = sets(context).add()
        sel.name = self.name.strip() or f"Selection {len(sets(context))}"
        sel.color = (len(sets(context)) - 1) % COLORS + 1
        if context.mode == 'POSE':
            sel.kind = 'BONE'
            active = context.active_pose_bone
            sel.armature = active.id_data if active else context.selected_pose_bones[0].id_data
            for pb in context.selected_pose_bones:
                if pb.id_data == sel.armature:
                    sel.members.add().name = pb.name
            sel.active = active.name if active and active.id_data == sel.armature else ""
        else:
            sel.kind = 'OBJECT'
            for ob in context.selected_objects:
                sel.members.add().name = ob.name
            sel.active = context.view_layer.objects.active.name if context.view_layer.objects.active else ""
        _redraw(context)
        return {'FINISHED'}


class ANIMSEL_OT_select(_IndexOp, Operator):
    """Select this saved selection (Shift: add to the selection, Ctrl: remove from it)"""
    bl_idname = "anim_sel.select"
    bl_label = "Select Saved Selection"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(('SET', "Set", ""), ('ADD', "Add", ""), ('SUB', "Remove", "")), default='SET',
                       options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.mode = 'ADD' if event.shift else 'SUB' if event.ctrl else 'SET'
        return self.execute(context)

    def execute(self, context):
        sel = self.item(context)
        if sel is None:
            return {'CANCELLED'}
        if sel.kind == 'BONE' and sel.armature is not None and context.mode != 'POSE':
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            for ob in context.selected_objects:
                ob.select_set(False)
            sel.armature.select_set(True)
            context.view_layer.objects.active = sel.armature
            bpy.ops.object.mode_set(mode='POSE')
        if apply_selection(context, sel, self.mode) == 0:
            self.report({'WARNING'}, f"Nothing of «{sel.name}» found")
        _redraw(context)
        return {'FINISHED'}


class ANIMSEL_OT_rename(_IndexOp, Operator):
    """Rename this selection"""
    bl_idname = "anim_sel.rename"
    bl_label = "Rename Selection"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name")

    def invoke(self, context, event):
        sel = self.item(context)
        if sel is None:
            return {'CANCELLED'}
        self.name = sel.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        sel = self.item(context)
        if sel is not None and self.name.strip():
            sel.name = self.name.strip()
        _redraw(context)
        return {'FINISHED'}


class ANIMSEL_OT_remove(_IndexOp, Operator):
    """Delete this selection button (the bones/objects are not touched)"""
    bl_idname = "anim_sel.remove"
    bl_label = "Remove Selection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if self.item(context) is not None:
            sets(context).remove(self.index)
        _redraw(context)
        return {'FINISHED'}


class ANIMSEL_OT_move(_IndexOp, Operator):
    """Move this selection up or down in the list"""
    bl_idname = "anim_sel.move"
    bl_label = "Move Selection"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=(('UP', "Up", ""), ('DOWN', "Down", "")))

    def execute(self, context):
        target = self.index + (-1 if self.direction == 'UP' else 1)
        if self.item(context) is not None and 0 <= target < len(sets(context)):
            sets(context).move(self.index, target)
        _redraw(context)
        return {'FINISHED'}


class ANIMSEL_OT_set_color(_IndexOp, Operator):
    """Colour of this selection button"""
    bl_idname = "anim_sel.set_color"
    bl_label = "Selection Color"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    color: IntProperty(min=1, max=COLORS, default=1)

    def execute(self, context):
        sel = self.item(context)
        if sel is not None:
            sel.color = self.color
        _redraw(context)
        return {'FINISHED'}


class ANIMSEL_OT_pick_color(_IndexOp, Operator):
    """Choose the colour of this selection"""
    bl_idname = "anim_sel.pick_color"
    bl_label = "Choose Color"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        index = self.index

        def draw(menu, _context):
            row = menu.layout.row(align=True)
            for color in range(1, COLORS + 1):
                op = row.operator("anim_sel.set_color", text="", icon=color_icon(color))
                op.index, op.color = index, color

        context.window_manager.popup_menu(draw, title="Color")
        return {'FINISHED'}


class ANIMSEL_PT_manager(Panel):
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "Selection Manager"
    bl_ui_units_x = 14

    def draw(self, context):
        layout = self.layout
        layout.operator("anim_sel.new", text="New Selection", icon='ADD')
        if sets(context):
            layout.label(text="Saved Selections:")
        col = layout.column(align=True)
        for i, sel in enumerate(sets(context)):
            row = col.row(align=True)
            row.operator("anim_sel.move", text="", icon='TRIA_UP').index = i
            op = row.operator("anim_sel.move", text="", icon='TRIA_DOWN')
            op.index, op.direction = i, 'DOWN'
            row.operator("anim_sel.rename", text="", icon='GREASEPENCIL').index = i
            row.operator("anim_sel.pick_color", text="", icon=color_icon(sel.color)).index = i
            kind = "Bone" if sel.kind == 'BONE' else "Object"
            row.operator("anim_sel.select", text=f"{sel.name} ({kind})").index = i
            row.operator("anim_sel.remove", text="", icon='X').index = i


def draw_view3d_header(self, context):
    usable = visible_sets(context)
    if not usable:
        return
    row = self.layout.row(align=True)
    for i, sel in usable:
        row.operator("anim_sel.select", text=sel.name, icon=color_icon(sel.color)).index = i


classes = (SelectionMember, SelectionSet, ANIMSEL_OT_new, ANIMSEL_OT_select, ANIMSEL_OT_rename,
           ANIMSEL_OT_remove, ANIMSEL_OT_move, ANIMSEL_OT_set_color, ANIMSEL_OT_pick_color, ANIMSEL_PT_manager)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.anim_selection_sets = CollectionProperty(type=SelectionSet)
    bpy.types.VIEW3D_HT_tool_header.append(draw_view3d_header)


def unregister():
    bpy.types.VIEW3D_HT_tool_header.remove(draw_view3d_header)
    del bpy.types.Scene.anim_selection_sets
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
