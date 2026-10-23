"""Silhouette: the character turns flat black in every 3D Viewport (Solid, Flat lighting, Object colour), to
check the readability of the pose. Toggling again restores the viewports and the object colours.

The original object colours are kept on the objects and the viewport shading on the screens (custom
properties), so turning it off still works after saving and reopening the file."""
import bpy
from bpy.types import Operator

from . import common

COLOR_KEY = "anim_tools_silhouette_color"
SHADING_KEY = "anim_tools_silhouette_shading"
SHADING_PROPS = ("type", "light", "color_type")


def _views(context):
    """(screen, index, shading) of every 3D Viewport in every window."""
    for window in context.window_manager.windows:
        screen = window.screen
        for i, area in enumerate(screen.areas):
            if area.type == 'VIEW_3D':
                yield screen, i, area.spaces.active.shading


def enable(context, meshes):
    s = context.scene.anim_tools
    for ob in meshes:
        if ob.library is not None:
            continue  # linked (not overridden): cannot be changed
        if COLOR_KEY not in ob:
            ob[COLOR_KEY] = list(ob.color)
        ob.color = tuple(s.silhouette_color) + (1.0,)
    for screen, i, shading in _views(context):
        saved = screen[SHADING_KEY].to_dict() if SHADING_KEY in screen else {}
        if str(i) not in saved:
            saved[str(i)] = {p: getattr(shading, p) for p in SHADING_PROPS}
            screen[SHADING_KEY] = saved
        shading.type = 'SOLID'
        shading.light = 'FLAT'
        shading.color_type = 'OBJECT'
    s.silhouette = True


def disable(context):
    for ob in bpy.data.objects:
        if COLOR_KEY in ob and ob.library is None:
            ob.color = tuple(ob[COLOR_KEY])
            del ob[COLOR_KEY]
    for screen, i, shading in _views(context):
        saved = screen.get(SHADING_KEY)
        if saved is None:
            continue
        old = saved.get(str(i))
        if old is not None:
            for p in SHADING_PROPS:
                try:
                    setattr(shading, p, old[p])
                except (KeyError, TypeError):
                    pass
    for window in context.window_manager.windows:
        if SHADING_KEY in window.screen:
            del window.screen[SHADING_KEY]
    context.scene.anim_tools.silhouette = False


class ANIMTOOLS_OT_silhouette(Operator):
    """Silhouette: show the character flat black in the viewports to check the pose (click again to restore)"""
    bl_idname = "anim_tools.silhouette"
    bl_label = "Silhouette"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.scene.anim_tools.silhouette:
            disable(context)
        else:
            meshes = common.character_meshes(context)
            if not meshes:
                self.report({'WARNING'}, "Select the rig (Pose Mode) or the character's meshes")
                return {'CANCELLED'}
            enable(context, meshes)
        common.redraw_all(context)
        return {'FINISHED'}


classes = (ANIMTOOLS_OT_silhouette,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
