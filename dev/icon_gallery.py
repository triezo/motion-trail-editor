"""Screenshot candidate icons: blender --factory-startup -p 0 0 1600 1000 --python dev/icon_gallery.py -- <out.png>"""
import os
import sys

import bpy

bpy.context.preferences.view.show_splash = False
out = sys.argv[sys.argv.index("--") + 1]
ICONS = set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())
GROUPS = {
    "Off1": "ACTION_TWEAK NLA KEYINGSET ANIM GRAPH DECORATE_ANIMATE DECORATE_KEYFRAME KEY_HLT PIVOT_ACTIVE ACTION",
    "Off2": "CON_LOCLIKE TRANSFORM_ORIGINS CON_TRANSLIKE MOD_OFFSET NLA_PUSHDOWN ANIM_DATA CON_ACTION SEQ_STRIP_DUPLICATE "
            "UV_SYNC_SELECT AUTOMERGE_ON",
    "Off3": "ARROW_LEFTRIGHT EMPTY_SINGLE_ARROW SNAP_INCREMENT SNAP_GRID FORWARD BACK TRIA_UP_BAR SORT_ASC "
            "MOD_LATTICE MOD_SIMPLEDEFORM",
}


class GALLERY_PT_icons(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Icons"
    bl_label = "Icons"

    def draw(self, context):
        for group, names in GROUPS.items():
            row = self.layout.row(align=False)
            row.label(text=group)
            for i, name in enumerate(names.split()):
                col = row.column(align=True)
                col.label(text=str(i), icon=name if name in ICONS else 'QUESTION')


bpy.utils.register_class(GALLERY_PT_icons)


def run():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    space = area.spaces.active
    space.show_region_ui = True
    for r in area.regions:
        if r.type == 'UI':
            with bpy.context.temp_override(window=win, area=area, region=r):
                pass
    bpy.context.preferences.view.ui_scale = 1.6
    yield 0.3
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.wm.context_set_string(data_path="space_data.context", value="")  # no-op if not valid
    yield 0.1


def steps():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    area.spaces.active.show_region_ui = True
    bpy.context.preferences.view.ui_scale = 1.6
    yield 0.3
    region = next(r for r in area.regions if r.type == 'UI')
    # widen the sidebar
    with bpy.context.temp_override(window=win, area=area, region=region):
        try:
            bpy.ops.wm.context_toggle(data_path="space_data.show_region_ui")
            bpy.ops.wm.context_toggle(data_path="space_data.show_region_ui")
        except Exception:
            pass
    for r in area.regions:
        if r.type == 'UI':
            r.active_panel_category = "Icons" if hasattr(r, "active_panel_category") else None
    yield 0.5
    bpy.ops.screen.screenshot(filepath=out, check_existing=False)
    os._exit(0)


gen = steps()


def tick():
    try:
        return next(gen)
    except StopIteration:
        os._exit(0)
    except Exception:
        import traceback
        print("GALLERY error", traceback.format_exc(), flush=True)
        os._exit(1)


bpy.app.timers.register(tick, first_interval=1.0)
