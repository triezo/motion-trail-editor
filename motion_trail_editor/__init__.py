bl_info = {
    "name": "Motion Trail Editor",
    "author": "Beku",
    "version": (0, 6, 0),
    "blender": (4, 3, 0),
    "location": "Dope Sheet / Timeline header, 3D Viewport > Sidebar > Motion Trail, Alt+M",
    "description": "Editable motion trails, saved selections, tween, AnimOffset, onion skin, ghosts, silhouette",
    "category": "Animation",
}

_MODULES = ("trails", "common", "props", "draw", "ops", "tool", "ui", "ghosts", "onion", "offset", "handlers",
            "selections", "keytools", "silhouette", "header")

if "bpy" in locals():
    # Reload Scripts / re-enable / upgrade: reload every module, not only this file. Modules that are new in
    # this version are not loaded yet: the import below loads them.
    import importlib
    for _name in _MODULES:
        if _name in globals():
            importlib.reload(globals()[_name])

from . import (common, draw, ghosts, handlers, header, keytools, offset, onion, ops, props, selections,  # noqa
               silhouette, tool, trails, ui)

import bpy

_keymaps = []


def _register_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # background mode
        return
    for name in ("Pose", "Object Mode"):
        km = kc.keymaps.new(name=name, space_type='EMPTY')
        kmi = km.keymap_items.new("motion_trail.toggle", 'M', 'PRESS', alt=True)
        _keymaps.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()


def register():
    if hasattr(bpy.types.Scene, "motion_trail"):
        raise RuntimeError("Motion Trail Editor is already enabled from another location "
                           "(add-on and extension at the same time?). Disable the other copy first.")
    props.register()
    selections.register()
    keytools.register()
    offset.register()
    ghosts.register()
    onion.register()
    silhouette.register()
    header.register()
    ops.register()
    ui.register()
    tool.register()
    draw.register()
    handlers.register()
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    handlers.unregister()
    draw.unregister()
    tool.unregister()
    ui.unregister()
    ops.unregister()
    header.unregister()
    silhouette.unregister()
    onion.unregister()
    ghosts.unregister()
    offset.unregister()
    keytools.unregister()
    selections.unregister()
    props.unregister()
