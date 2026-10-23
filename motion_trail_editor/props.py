"""Scene settings and the list of trails (saved with the .blend)."""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)


def _redraw(self, context):
    from . import draw
    draw.tag_redraw_all()


def _rebuild(self, context):
    from . import trails
    trails.request_rebuild()


def _window(self, context):
    # Before/After also set how many frames get evaluated around the playhead.
    from . import draw, trails
    draw.tag_redraw_all()
    trails.request_rebuild()


def _handles(self, context):
    from . import draw, trails
    trails.ensure_jacobians(context.scene)
    draw.tag_redraw_all()


def _color(name, default, description=""):
    return FloatVectorProperty(name=name, description=description, subtype='COLOR_GAMMA', size=4,
                               min=0.0, max=1.0, default=default, update=_redraw)


class MotionTrailItem(bpy.types.PropertyGroup):
    object: PointerProperty(name="Object", type=bpy.types.Object)
    bone: StringProperty(name="Bone")


class MotionTrailSettings(bpy.types.PropertyGroup):
    items: CollectionProperty(type=MotionTrailItem)

    range_mode: EnumProperty(
        name="Range",
        items=(('SCENE', "Scene", "Scene frame range (the preview range when it is enabled)"),
               ('MANUAL', "Manual", "Custom frame range")),
        default='SCENE', update=_rebuild)
    frame_start: IntProperty(name="Start", default=1, update=_rebuild)
    frame_end: IntProperty(name="End", default=250, update=_rebuild)
    frames_before: IntProperty(name="Before", description="Frames shown before the current frame (0: all)",
                               default=20, min=0, update=_window)
    frames_after: IntProperty(name="After", description="Frames shown after the current frame (0: all)",
                              default=20, min=0, update=_window)
    fade: BoolProperty(name="Fade", description="Fade the trail away from the current frame",
                       default=True, update=_redraw)
    bake_location: EnumProperty(
        name="Bone Point",
        items=(('HEADS', "Head", "Trail of the bone head (pivot)"),
               ('TAILS', "Tail", "Trail of the bone tail")),
        default='HEADS', update=_rebuild)

    line_width: FloatProperty(name="Line Width", default=2.0, min=1.0, max=10.0, update=_redraw)
    key_size: FloatProperty(name="Key Size", default=9.0, min=3.0, max=30.0, update=_redraw)
    show_frame_dots: BoolProperty(name="Frame Dots", description="Dot on every frame (shows spacing)",
                                  default=True, update=_redraw)
    frame_dot_size: FloatProperty(name="Dot Size", default=4.0, min=1.0, max=20.0, update=_redraw)
    show_key_numbers: BoolProperty(name="Key Numbers", description="Frame number next to each key",
                                   default=False, update=_redraw)
    show_on_top: BoolProperty(name="Draw On Top", description="Draw the trail in front of the geometry",
                              default=True, update=_redraw)
    show_handles: BoolProperty(name="Handles", description="Show the tangent handles (tails) of the selected keys",
                               default=True, update=_handles)

    color_before: _color("Before", (0.30, 0.65, 1.0, 1.0), "Trail color before the current frame")
    color_after: _color("After", (1.0, 0.45, 0.25, 1.0), "Trail color after the current frame")
    color_key: _color("Key", (0.95, 0.95, 0.95, 1.0))
    color_selected: _color("Selected", (1.0, 0.62, 0.0, 1.0))
    color_handle: _color("Handle", (0.8, 0.8, 0.8, 0.9))
    color_current: _color("Current Frame", (1.0, 0.9, 0.25, 1.0))

    select_owner: BoolProperty(name="Select Owner",
                               description="Clicking a key also selects its bone or object",
                               default=True)
    sync_key_selection: BoolProperty(name="Sync Key Selection",
                                     description="Select the same keys in the Graph Editor and Dope Sheet",
                                     default=True)
    jump_to_frame: BoolProperty(name="Jump to Frame", description="Clicking a key moves the playhead to it",
                                default=False)
    # Numbers keep files saved with the old on/off option working (off = 0, on = 1 = Manual).
    select_new_keys: EnumProperty(
        name="Select New Keys",
        description="Which newly inserted keys become the trail selection",
        items=(('OFF', "Off", "Never select new keys", 0),
               ('MANUAL', "Inserted by Hand",
                "Keys inserted with I / Insert Keyframe or Alt+Right click on the trail, not by Auto Keying", 1),
               ('ALL', "All New Keys", "Also keys made by Auto Keying", 2)),
        default='MANUAL')
    auto_tool: BoolProperty(name="Switch Tool",
                            description="Switch to the Motion Trail tool when a trail is enabled",
                            default=True)


def _ghost_colors(self, context):
    from . import ghosts
    ghosts.tag_redraw()


def _ghost_color(name, default):
    return FloatVectorProperty(name=name, subtype='COLOR_GAMMA', size=4, min=0.0, max=1.0, default=default,
                               update=_ghost_colors)


def _onion_frames(self, context):
    from . import ghosts, onion
    onion.request_update(0.05)
    ghosts.tag_redraw()


def _onion_mask(self, context):
    from . import ghosts, onion
    onion.request_mask()
    ghosts.tag_redraw()


def _silhouette_color(self, context):
    from . import silhouette
    if self.silhouette:
        for ob in bpy.data.objects:
            if silhouette.COLOR_KEY in ob and ob.library is None:
                ob.color = tuple(self.silhouette_color) + (1.0,)


class AnimToolsSettings(bpy.types.PropertyGroup):
    """Tween, AnimOffset, Ghosts and Silhouette settings of the scene."""
    tween_mode: EnumProperty(
        name="Tween Mode",
        items=(('TWEEN', "Tween", "In-between of the previous and the next key", 'IPO_EASE_IN_OUT', 0),
               ('NEIGHBOR', "Blend to Neighbor", "Move the pose toward the previous or the next key",
                'ARROW_LEFTRIGHT', 1),
               ('PUSH', "Push / Pull", "Exaggerate or flatten the pose relative to its neighbors",
                'FULLSCREEN_ENTER', 2)),
        default='TWEEN')

    offset_use_mask: BoolProperty(name="Mask", description="AnimOffset changes only the keys of these frames",
                                  default=False)
    offset_start: IntProperty(name="Start", default=1)
    offset_end: IntProperty(name="End", default=250)

    ghost_show: BoolProperty(name="Show Ghosts", default=True, update=_ghost_colors)
    ghost_color_before: _ghost_color("Before", (1.0, 0.35, 0.25, 0.3))
    ghost_color_after: _ghost_color("After", (0.25, 0.6, 1.0, 0.3))
    ghost_in_front: BoolProperty(name="In Front", description="Draw the ghosts over the scene", default=False,
                                 update=_ghost_colors)
    ghost_hide_current: BoolProperty(name="Hide on Its Frame",
                                     description="Hide a ghost while the playhead is on its own frame",
                                     default=True, update=_ghost_colors)

    onion_mode: EnumProperty(
        name="Onion Mode",
        items=(('KEYS', "Keys", "Poses at the previous / next keys of the character"),
               ('FRAMES', "Frames", "Poses every few frames around the current frame")),
        default='KEYS', update=_onion_frames)
    onion_before: IntProperty(name="Before", description="How many poses before the current frame",
                              default=1, min=0, max=10, update=_onion_frames)
    onion_after: IntProperty(name="After", description="How many poses after the current frame",
                             default=1, min=0, max=10, update=_onion_frames)
    onion_step: IntProperty(name="Step", description="Frames between the poses (Frames mode)",
                            default=2, min=1, max=100, update=_onion_frames)
    onion_flat: BoolProperty(name="Flat Silhouettes", description="Flat colour (off: lightly shaded)",
                             default=True, update=_ghost_colors)
    onion_behind: BoolProperty(name="Behind Character",
                               description="Onion and ghosts are not drawn over the character, so its current pose "
                                           "stays clean",
                               default=True, update=_onion_mask)

    silhouette: BoolProperty(name="Silhouette", description="Silhouette view is on", default=False)
    silhouette_color: FloatVectorProperty(name="Silhouette Color", subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
                                          default=(0.0, 0.0, 0.0), update=_silhouette_color)


classes = (MotionTrailItem, MotionTrailSettings, AnimToolsSettings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.motion_trail = PointerProperty(type=MotionTrailSettings)
    bpy.types.Scene.anim_tools = PointerProperty(type=AnimToolsSettings)


def unregister():
    del bpy.types.Scene.anim_tools
    del bpy.types.Scene.motion_trail
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
