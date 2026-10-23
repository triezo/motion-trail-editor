"""Does installing a newer zip over an enabled extension load the new code of every module?
Run with BLENDER_USER_RESOURCES pointing to a scratch folder:
  blender -b --factory-startup --python dev/test_upgrade.py -- <zip v1> <zip v2>
"""
import os
import sys

import addon_utils
import bpy

zip_a, zip_b = sys.argv[sys.argv.index("--") + 1:][:2]
assert "userres" in os.environ.get("BLENDER_USER_RESOURCES", ""), "refusing to run against the real profile"
name = "bl_ext.user_default.motion_trail_editor"

bpy.ops.extensions.package_install_files(filepath=zip_a, repo="user_default", enable_on_install=True)
before = getattr(sys.modules[name + ".trails"], "UPGRADE_MARKER", None)
bpy.ops.extensions.package_install_files(filepath=zip_b, repo="user_default", enable_on_install=True)
trails_mod = sys.modules.get(name + ".trails")
after = getattr(trails_mod, "UPGRADE_MARKER", None)
print("UPGRADE", {"enabled": addon_utils.check(name), "marker_before": before, "marker_after": after,
                  "submodules_reloaded": after == "B"}, flush=True)
