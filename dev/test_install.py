"""Install the release zips into an isolated Blender and check they register.
Run with BLENDER_USER_RESOURCES pointing to a scratch folder (never the real profile):
  BLENDER_USER_RESOURCES=dev/out/userres blender -b --factory-startup --python dev/test_install.py -- <zip> <ext|legacy>
"""
import os
import sys
import traceback

import addon_utils
import bpy

zip_path, kind = sys.argv[sys.argv.index("--") + 1:][:2]
user_res = os.environ.get("BLENDER_USER_RESOURCES", "")
assert user_res and "userres" in user_res, "refusing to run against the real user profile"

out = {"kind": kind}
try:
    if kind == "ext":
        bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
        module = "bl_ext.user_default.motion_trail_editor"
    else:
        bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
        module = "motion_trail_editor"
        addon_utils.enable(module, default_set=True, handle_error=None)
    out["module"] = module
    out["enabled"] = addon_utils.check(module)
    out["installed_to"] = os.path.dirname(sys.modules[module].__file__)
    out["inside_scratch"] = os.path.normcase(os.path.abspath(user_res)) in os.path.normcase(out["installed_to"])
    out["operator"] = hasattr(bpy.ops.motion_trail, "toggle") and bpy.ops.motion_trail.toggle.idname()
    out["panel"] = hasattr(bpy.types, "VIEW3D_PT_motion_trail")
    out["scene_prop"] = hasattr(bpy.context.scene, "motion_trail")
    addon_utils.disable(module, default_set=True)
    out["disabled_cleanly"] = not hasattr(bpy.types, "VIEW3D_PT_motion_trail")
except Exception:
    out["error"] = traceback.format_exc()
print("INSTALL", out, flush=True)
