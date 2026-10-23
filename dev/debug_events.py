"""Debug simulated events: blender --factory-startup --enable-event-simulate --python dev/debug_events.py"""
import bpy

bpy.context.preferences.view.show_splash = False


class DBG_OT_logger(bpy.types.Operator):
    bl_idname = "wm.dbg_event_logger"
    bl_label = "Event Logger"

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        print("DBG logger started")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type not in {'TIMER', 'TIMER_REPORT', 'NONE'}:
            print("DBG event", event.type, event.value, event.mouse_x, event.mouse_y, "alt" if event.alt else "",
                  "area:", context.area.type if context.area else None)
        return {'PASS_THROUGH'}


bpy.utils.register_class(DBG_OT_logger)


def steps():
    wm = bpy.context.window_manager
    win = wm.windows[0]
    area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    print("DBG window", win.width, win.height, "region", region.x, region.y, region.width, region.height,
          "pixel_size", bpy.context.preferences.system.pixel_size)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.dbg_event_logger('INVOKE_DEFAULT')
    yield 0.3
    cx, cy = region.x + region.width // 2, region.y + region.height // 2
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=cx, y=cy)
    yield 0.3
    win.event_simulate(type='A', value='PRESS')
    win.event_simulate(type='A', value='RELEASE')
    yield 0.3
    print("DBG after A:", [o.name for o in bpy.context.selected_objects])


gen = steps()


def tick():
    try:
        return next(gen)
    except StopIteration:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=1.0)
