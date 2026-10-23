"""Find how to switch the sidebar to the Motion Trail tab with simulated input, and where its first button is."""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
bpy.context.preferences.view.show_splash = False
import motion_trail_editor as mte  # noqa: E402

OUT = os.path.join(ROOT, "dev", "out", "tutorial")


def steps():
    mte.register()
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screen_full_area()
    yield 0.5
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    area.spaces.active.show_region_ui = True
    yield 0.5
    ui = next(r for r in area.regions if r.type == 'UI')
    print("TABS ui region", ui.x, ui.y, ui.width, ui.height, "area", area.x, area.y, area.width, area.height,
          "category", ui.active_panel_category, flush=True)
    found = None
    for x_off in (11, 9, 14):
        for dy in range(20, ui.height, 12):
            x, y = ui.x + ui.width - x_off, ui.y + ui.height - dy
            win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
            yield 0.05
            win.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
            win.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)
            yield 0.1
            if ui.active_panel_category == "Motion Trail":
                found = (x_off, dy)
                break
        if found:
            break
    print("TABS found", found, "category", ui.active_panel_category, flush=True)
    yield 0.5
    with bpy.context.temp_override(window=win, area=area, region=ui):
        bpy.ops.screen.screenshot_area(filepath=os.path.join(OUT, "tabs.png"), check_existing=False)
    print("TABS ui top in screenshot:", area.y + area.height - (ui.y + ui.height), flush=True)
    os._exit(0)


gen = steps()


def tick():
    try:
        return next(gen)
    except StopIteration:
        os._exit(0)


bpy.app.timers.register(tick, first_interval=1.0)
