"""Which modes allow pose/object.paths_calculate via context override? And does update_tag('TIME') re-evaluate?"""
import os
import sys
import traceback
import bpy

sys.path.insert(0, os.path.dirname(__file__))
import testrig  # noqa: E402

rig, cube, body = testrig.build(dense=False)
scene = bpy.context.scene
fore = rig.pose.bones["forearm"]


def try_pose_calc(label):
    try:
        with bpy.context.temp_override(active_object=rig, object=rig, selected_pose_bones=[fore],
                                       selected_pose_bones_from_active_object=[fore]):
            ok = bpy.ops.pose.paths_calculate.poll()
            if ok:
                bpy.ops.pose.paths_calculate('EXEC_DEFAULT', False, display_type='RANGE', range='SCENE',
                                             bake_location='TAILS')
        res = (ok, fore.motion_path is not None and len(fore.motion_path.points))
        with bpy.context.temp_override(active_object=rig, object=rig, selected_pose_bones=[fore],
                                       selected_pose_bones_from_active_object=[fore]):
            if bpy.ops.pose.paths_clear.poll():
                bpy.ops.pose.paths_clear('EXEC_DEFAULT', False, only_selected=True)
        print("PROBE", label, res)
    except Exception:
        print("PROBE", label, traceback.format_exc())


def try_obj_calc(label):
    try:
        with bpy.context.temp_override(active_object=cube, object=cube, selected_objects=[cube],
                                       selected_editable_objects=[cube]):
            ok = bpy.ops.object.paths_calculate.poll()
            if ok:
                bpy.ops.object.paths_calculate('EXEC_DEFAULT', False, display_type='RANGE', range='SCENE')
        res = (ok, cube.motion_path is not None and len(cube.motion_path.points))
        with bpy.context.temp_override(active_object=cube, object=cube, selected_objects=[cube],
                                       selected_editable_objects=[cube]):
            if bpy.ops.object.paths_clear.poll():
                bpy.ops.object.paths_clear('EXEC_DEFAULT', False, only_selected=True)
        print("PROBE", label, res, "cleared:", cube.motion_path is None)
    except Exception:
        print("PROBE", label, traceback.format_exc())


bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='OBJECT')
try_pose_calc("pose calc, rig in OBJECT mode")
try_obj_calc("object calc, rig active in OBJECT mode")
bpy.ops.object.mode_set(mode='POSE')
try_pose_calc("pose calc, rig in POSE mode")
try_obj_calc("object calc, rig active in POSE mode")

# Python keyframe edits: does the current-frame pose follow without frame_set?
bpy.ops.object.mode_set(mode='OBJECT')
scene.frame_set(1)
fc = next(f for f in cube.animation_data.action.layers[0].strips[0].channelbags[0].fcurves
          if f.data_path == "location" and f.array_index == 2)
before = cube.matrix_world.translation.z
fc.keyframe_points[0].co.y += 1.0
fc.update()
bpy.context.view_layer.update()
after_plain = cube.matrix_world.translation.z
cube.update_tag(refresh={'TIME'})
bpy.context.view_layer.update()
after_tag = cube.matrix_world.translation.z
print("PROBE eval after key edit:", round(before, 3), round(after_plain, 3), round(after_tag, 3))
