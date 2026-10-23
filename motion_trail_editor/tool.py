"""Toolbar tool for editing trail keys. Its keymap only applies while the tool is active;
anything that is not on a trail key passes through to the usual selection."""
import bpy
from bpy.types import WorkSpaceTool

from .ops import TOOL_OBJECT, TOOL_POSE

KEYMAP = (
    ("motion_trail.hover", {"type": 'MOUSEMOVE', "value": 'ANY'}, None),
    ("motion_trail.click", {"type": 'LEFTMOUSE', "value": 'PRESS'},
     {"properties": [("extend", False)]}),
    ("motion_trail.click", {"type": 'LEFTMOUSE', "value": 'PRESS', "shift": True},
     {"properties": [("extend", True)]}),
    ("motion_trail.select_box", {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG'},
     {"properties": [("wait_for_input", False), ("mode", 'SET')]}),
    ("motion_trail.select_box", {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG', "shift": True},
     {"properties": [("wait_for_input", False), ("mode", 'ADD')]}),
    ("motion_trail.select_box", {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG', "ctrl": True},
     {"properties": [("wait_for_input", False), ("mode", 'SUB')]}),
    ("motion_trail.select_box", {"type": 'B', "value": 'PRESS'},
     {"properties": [("wait_for_input", True)]}),
    ("motion_trail.transform", {"type": 'G', "value": 'PRESS'}, {"properties": [("mode", 'TRANSLATE')]}),
    ("motion_trail.transform", {"type": 'R', "value": 'PRESS'}, {"properties": [("mode", 'ROTATE')]}),
    ("motion_trail.transform", {"type": 'S', "value": 'PRESS'}, {"properties": [("mode", 'SCALE')]}),
    ("motion_trail.delete_keys", {"type": 'X', "value": 'PRESS'}, None),
    ("motion_trail.delete_keys", {"type": 'DEL', "value": 'PRESS'}, None),
    ("motion_trail.key_at_mouse", {"type": 'RIGHTMOUSE', "value": 'PRESS', "alt": True}, None),
    ("motion_trail.select_all", {"type": 'A', "value": 'PRESS', "alt": True},
     {"properties": [("action", 'DESELECT')]}),
)


def _draw_settings(context, layout, tool):
    s = context.scene.motion_trail
    layout.prop(s, "frames_before")
    layout.prop(s, "frames_after")
    layout.prop(s, "show_on_top", text="On Top")


class MotionTrailToolPose(WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'POSE'
    bl_idname = TOOL_POSE
    bl_label = "Motion Trail"
    bl_description = ("Edit motion trail keys in the viewport.\n"
                      "Click/drag keys, B box select, G/R/S transform,\n"
                      "selected keys show tails: drag them, G/R/S (S scales the tail),\n"
                      "Alt+Right click: insert or delete a key, X delete keys, click nothing: deselect")
    bl_icon = "ops.curve.draw"
    bl_widget = None
    bl_keymap = KEYMAP
    draw_settings = _draw_settings


class MotionTrailToolObject(WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = TOOL_OBJECT
    bl_label = "Motion Trail"
    bl_description = MotionTrailToolPose.bl_description
    bl_icon = "ops.curve.draw"
    bl_widget = None
    bl_keymap = KEYMAP
    draw_settings = _draw_settings


TOOLS = (MotionTrailToolPose, MotionTrailToolObject)


def register():
    for tool in TOOLS:
        bpy.utils.register_tool(tool, after={"builtin.transform"}, separator=True)


def unregister():
    for tool in reversed(TOOLS):
        bpy.utils.unregister_tool(tool)
