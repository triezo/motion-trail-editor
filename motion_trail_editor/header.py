"""Buttons in the Dope Sheet / Timeline header (optionally the Graph Editor header too), and the add-on
preferences that choose which groups of buttons are shown."""
import bpy
from bpy.props import BoolProperty
from bpy.types import AddonPreferences

from . import keytools, offset, onion

GROUPS = (
    ("show_trail", "Motion Trail", "Toggle the motion trail of the selection"),
    ("show_selector", "Saved Selections", "Selection Manager popover"),
    ("show_tween", "Tween", "Tween / Blend to Neighbor / Push-Pull buttons"),
    ("show_euler", "Euler Filter", "Euler Filter button"),
    ("show_offset", "AnimOffset", "AnimOffset toggle and mask"),
    ("show_ghosts", "Onion / Ghosts", "Onion skin and ghost buttons"),
    ("show_silhouette", "Silhouette", "Silhouette toggle"),
)


def _group(name, label, description):
    return BoolProperty(name=label, description=description, default=True)


class AnimToolsPreferences(AddonPreferences):
    bl_idname = __package__

    show_trail: _group(*GROUPS[0])
    show_selector: _group(*GROUPS[1])
    show_tween: _group(*GROUPS[2])
    show_euler: _group(*GROUPS[3])
    show_offset: _group(*GROUPS[4])
    show_ghosts: _group(*GROUPS[5])
    show_silhouette: _group(*GROUPS[6])
    in_graph_editor: BoolProperty(name="Graph Editor Header Too",
                                  description="Also show the buttons in the Graph Editor header", default=False)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Buttons in the Dope Sheet / Timeline header:")
        grid = layout.grid_flow(columns=4, even_columns=True)
        for name, _label, _description in GROUPS:
            grid.prop(self, name)
        layout.prop(self, "in_graph_editor")


class _Defaults:
    in_graph_editor = False

    def __getattr__(self, name):
        return True


def prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None and addon.preferences is not None else _Defaults()


def _tween_icon(factor):
    """A ruler: keys at the ends, the middle as a ring, quarters bigger than eighths."""
    if abs(factor) == 1.0:
        return 'KEYFRAME_HLT'
    if factor == 0.0:
        return 'RADIOBUT_OFF'
    return 'LAYER_ACTIVE' if abs(factor) == 0.5 else 'DOT'


def _trail_on(context):
    """The selection has a motion trail (the trail button shows pressed)."""
    items = context.scene.motion_trail.items
    if not items:
        return False
    if context.mode == 'POSE':
        owners = {(pb.id_data.name_full, pb.name) for pb in context.selected_pose_bones or ()}
    else:
        owners = {(ob.name_full, "") for ob in context.selected_objects or ()}
    return any(it.object is not None and (it.object.name_full, it.bone) in owners for it in items)


def draw_buttons(layout, context):
    p = prefs(context)
    s = context.scene.anim_tools

    if p.show_trail:
        layout.operator("motion_trail.toggle", text="", icon='TRACKING', depress=_trail_on(context))

    if p.show_selector:
        layout.popover("ANIMSEL_PT_manager", text="", icon='GROUP_BONE')

    if p.show_tween:
        row = layout.row(align=True)
        row.operator("anim_tools.tween_drag", text="", icon=keytools.MODE_ICONS[s.tween_mode])
        row.prop_menu_enum(s, "tween_mode", text="", icon='DOWNARROW_HLT')
        dots = row.row(align=True)
        dots.scale_x = 0.8
        for factor in keytools.FACTORS:
            dots.operator("anim_tools.tween", text="", icon=_tween_icon(factor)).factor = factor

    if p.show_euler:
        layout.operator("anim_tools.euler_filter", text="", icon='ORIENTATION_GIMBAL')

    if p.show_offset:
        row = layout.row(align=True)
        row.operator("anim_tools.anim_offset", text="", icon='CON_ACTION', depress=offset.is_enabled())
        row.popover("ANIMTOOLS_PT_offset", text="")

    if p.show_ghosts:
        row = layout.row(align=True)
        row.operator("anim_tools.onion", text="", icon='ONIONSKIN_ON', depress=onion.is_enabled())
        row.operator("anim_tools.ghost_add", text="", icon='GHOST_ENABLED')
        row.operator("anim_tools.ghost_clear_frame", text="", icon='GHOST_DISABLED')
        row.operator("anim_tools.ghost_clear", text="", icon='TRASH')
        row.popover("ANIMTOOLS_PT_ghosts", text="")

    if p.show_silhouette:
        layout.operator("anim_tools.silhouette", text="", icon='OUTLINER_OB_ARMATURE', depress=s.silhouette)


def draw_dopesheet_header(self, context):
    draw_buttons(self.layout, context)


def draw_graph_header(self, context):
    if prefs(context).in_graph_editor:
        draw_buttons(self.layout, context)


classes = (AnimToolsPreferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.DOPESHEET_HT_header.append(draw_dopesheet_header)
    bpy.types.GRAPH_HT_header.append(draw_graph_header)


def unregister():
    bpy.types.GRAPH_HT_header.remove(draw_graph_header)
    bpy.types.DOPESHEET_HT_header.remove(draw_dopesheet_header)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
