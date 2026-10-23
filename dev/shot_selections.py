"""Screenshot the selector UI: blender --factory-startup -p 0 0 1500 900 --python dev/shot_selections.py -- <out prefix>"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
bpy.context.preferences.view.show_splash = False
import testrig  # noqa: E402
import motion_trail_editor as mte  # noqa: E402
from motion_trail_editor import trails  # noqa: E402

prefix = sys.argv[sys.argv.index("--") + 1]


def steps():
    mte.register()
    rig, _cube, _ = testrig.build(dense=False)
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='POSE')
    for name, bones in (("Mouth", ("hand_ik", "ctrl_options")), ("FingersFK", ("root",)), ("Hands", ("forearm",))):
        for b in rig.pose.bones:
            trails.select_bone(b, b.name in bones)
        bpy.ops.anim_sel.new(name=name)
    yield 0.5
    bpy.ops.screen.screenshot(filepath=prefix + "_window.png", check_existing=False)
    timeline = next(a for a in win.screen.areas if a.type == 'DOPESHEET_EDITOR')
    header = next(r for r in timeline.regions if r.type == 'HEADER')
    with bpy.context.temp_override(window=win, area=timeline, region=header):
        bpy.ops.wm.call_panel(name="ANIMSEL_PT_manager", keep_open=True)
    yield 0.6
    bpy.ops.screen.screenshot(filepath=prefix + "_popover.png", check_existing=False)
    os._exit(0)


gen = steps()


def tick():
    try:
        return next(gen)
    except StopIteration:
        os._exit(0)
    except Exception:
        import traceback
        print("SHOT error", traceback.format_exc(), flush=True)
        os._exit(1)


bpy.app.timers.register(tick, first_interval=1.0)
