"""Keep the trails in sync with the animation (edits, undo, file loading)."""
import bpy
from bpy.app.handlers import persistent

from . import ghosts, offset, onion, trails


@persistent
def on_depsgraph_update(scene, depsgraph):
    if offset.is_enabled():
        offset.request_apply()
    onion.on_depsgraph_update(depsgraph)
    if not trails.TRAILS or trails.state.building or trails.state.transforming:
        return
    if trails.prune_by_owner_selection(scene, bpy.context.mode):
        from . import draw
        draw.tag_redraw_all()
    for update in depsgraph.updates:
        if isinstance(update.id, (bpy.types.Action, bpy.types.Object, bpy.types.Scene)):
            trails.request_check()
            return


@persistent
def on_frame_change(scene, *_args):
    onion.on_frame_change(scene)
    # Trails are evaluated around the playhead: evaluate more once it moved past the evaluated frames.
    if not trails.TRAILS or trails.state.building or trails.state.transforming:
        return
    if not all(trails.covers(t, scene) for t in trails.TRAILS.values()):
        trails.request_check()


@persistent
def on_load_pre(*_args):
    offset.disable()
    onion.disable()
    ghosts.clear()
    trails.reset()


@persistent
def on_load_post(*_args):
    trails.request_rebuild()


@persistent
def on_undo_redo(*_args):
    trails.request_rebuild()


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, on_depsgraph_update),
    (bpy.app.handlers.frame_change_post, on_frame_change),
    (bpy.app.handlers.load_pre, on_load_pre),
    (bpy.app.handlers.load_post, on_load_post),
    (bpy.app.handlers.undo_post, on_undo_redo),
    (bpy.app.handlers.redo_post, on_undo_redo),
)


def register():
    for handler_list, func in _HANDLERS:
        if func not in handler_list:
            handler_list.append(func)
    trails.request_rebuild()


def unregister():
    for handler_list, func in _HANDLERS:
        if func in handler_list:
            handler_list.remove(func)
    trails.reset()
