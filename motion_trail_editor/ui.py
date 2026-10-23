"""Sidebar panel (N panel > Motion Trail)."""
import bpy
from bpy.types import Panel

from . import trails


class VIEW3D_PT_motion_trail(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Trail"
    bl_label = "Motion Trail"

    def draw(self, context):
        layout = self.layout
        s = context.scene.motion_trail

        col = layout.column(align=True)
        col.operator("motion_trail.toggle", text="Toggle for Selected (Alt+M)", icon='TRACKING')
        row = col.row(align=True)
        row.operator("motion_trail.refresh", text="Refresh", icon='FILE_REFRESH')
        row.operator("motion_trail.clear_all", text="Remove All", icon='X')

        if s.items:
            box = layout.box()
            for i, item in enumerate(s.items):
                row = box.row(align=True)
                if item.object is None:
                    row.label(text="(missing object)", icon='ERROR')
                elif item.bone:
                    row.label(text=f"{item.object.name} : {item.bone}", icon='BONE_DATA')
                else:
                    row.label(text=item.object.name, icon='OBJECT_DATA')
                row.operator("motion_trail.remove", text="", icon='X', emboss=False).index = i

        selected = sum(len(v) for v in trails.SELECTION.values())
        handles = len(trails.HANDLE_SELECTION)
        if selected or handles:
            row = layout.row(align=True)
            row.label(text=f"{selected} key(s) selected" if selected else f"{handles} tail(s) selected")
            row.operator("motion_trail.select_all", text="", icon='X').action = 'DESELECT'


class VIEW3D_PT_motion_trail_range(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Trail"
    bl_label = "Range"
    bl_parent_id = "VIEW3D_PT_motion_trail"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = context.scene.motion_trail
        layout.prop(s, "range_mode")
        if s.range_mode == 'MANUAL':
            col = layout.column(align=True)
            col.prop(s, "frame_start")
            col.prop(s, "frame_end")
        col = layout.column(align=True)
        col.prop(s, "frames_before")
        col.prop(s, "frames_after")
        layout.prop(s, "fade")
        layout.prop(s, "bake_location")


class VIEW3D_PT_motion_trail_display(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Trail"
    bl_label = "Display"
    bl_parent_id = "VIEW3D_PT_motion_trail"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = context.scene.motion_trail
        layout.prop(s, "line_width")
        layout.prop(s, "key_size")
        layout.prop(s, "show_frame_dots")
        sub = layout.row()
        sub.active = s.show_frame_dots
        sub.prop(s, "frame_dot_size")
        layout.prop(s, "show_key_numbers")
        layout.prop(s, "show_handles")
        layout.prop(s, "show_on_top")
        col = layout.column(align=True)
        col.prop(s, "color_before")
        col.prop(s, "color_after")
        col.prop(s, "color_key")
        col.prop(s, "color_selected")
        col.prop(s, "color_handle")
        col.prop(s, "color_current")


class VIEW3D_PT_motion_trail_editing(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Trail"
    bl_label = "Editing"
    bl_parent_id = "VIEW3D_PT_motion_trail"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.motion_trail
        col = layout.column()
        col.prop(s, "select_owner")
        col.prop(s, "sync_key_selection")
        col.prop(s, "jump_to_frame")
        col.prop(s, "select_new_keys")
        col.prop(s, "auto_tool")
        col = layout.column(align=True)
        col.label(text="Motion Trail tool:", icon='INFO')
        col.label(text="Click / drag key: select, move")
        col.label(text="Click nothing: deselect all")
        col.label(text="B / drag empty: box select")
        col.label(text="G R S: move, rotate, scale keys")
        col.label(text="Tails of selected keys: drag, G R S")
        col.label(text="Alt+Right click: insert / delete key")
        col.label(text="X: delete selected keys")


classes = (
    VIEW3D_PT_motion_trail,
    VIEW3D_PT_motion_trail_range,
    VIEW3D_PT_motion_trail_display,
    VIEW3D_PT_motion_trail_editing,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
