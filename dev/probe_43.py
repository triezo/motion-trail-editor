"""Which APIs the addon uses exist in this Blender version? blender -b --factory-startup --python dev/probe_43.py"""
import bpy
from bpy_extras import anim_utils

props = lambda t: set(t.bl_rna.properties.keys())  # noqa: E731
out = {
    "version": bpy.app.version_string,
    "PoseBone.select": "select" in props(bpy.types.PoseBone),
    "Bone.select": "select" in props(bpy.types.Bone),
    "AnimData.action_slot": "action_slot" in props(bpy.types.AnimData),
    "Action.fcurves": "fcurves" in props(bpy.types.Action),
    "anim_utils.channelbag": hasattr(anim_utils, "action_get_channelbag_for_slot"),
    "ActionFCurves.funcs": [f.identifier for f in bpy.types.ActionFCurves.bl_rna.functions],
    "ActionFCurves.new params": [p.identifier for p in bpy.types.ActionFCurves.bl_rna.functions["new"].parameters],
    "Window.modal_operators": "modal_operators" in props(bpy.types.Window),
    "Window.event_simulate": "event_simulate" in bpy.types.Window.bl_rna.functions,
    "Screen.is_animation_playing": "is_animation_playing" in props(bpy.types.Screen),
    "FCurve.auto_smoothing": "auto_smoothing" in props(bpy.types.FCurve),
    "View3DOverlay.show_motion_paths": "show_motion_paths" in props(bpy.types.View3DOverlay),
    "pose.paths_calculate": [p.identifier for p in bpy.ops.pose.paths_calculate.get_rna_type().properties][1:],
    "pose.paths_clear": [p.identifier for p in bpy.ops.pose.paths_clear.get_rna_type().properties][1:],
    "extensions_ops": hasattr(bpy.ops, "extensions") and hasattr(bpy.ops.extensions, "package_install_files"),
    "smoothing_default": bpy.context.preferences.edit.fcurve_new_auto_smoothing,
}
for k, v in out.items():
    print("PROBE43", k, v)
