"""Build release zips into dist/:
  motion_trail_editor-<ver>.zip         extension (Blender 4.2+: drag & drop, or Install from Disk)
  motion_trail_editor-<ver>-legacy.zip  classic add-on (folder with __init__.py)
Run: python dev/package.py
"""
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "motion_trail_editor")
DIST = os.path.join(ROOT, "dist")
BLENDER = os.environ.get("BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")


def version():
    with open(os.path.join(SRC, "blender_manifest.toml"), encoding="utf-8") as f:
        manifest_version = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    with open(os.path.join(SRC, "__init__.py"), encoding="utf-8") as f:
        bl_version = re.search(r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)', f.read())
    bl_version = ".".join(bl_version.groups())
    if bl_version != manifest_version:
        sys.exit(f"Version mismatch: bl_info {bl_version} vs manifest {manifest_version}")
    return manifest_version


def sources():
    for name in sorted(os.listdir(SRC)):
        path = os.path.join(SRC, name)
        if os.path.isfile(path) and name.endswith((".py", ".toml")):
            yield name, path


def main():
    ver = version()
    os.makedirs(DIST, exist_ok=True)

    ext = os.path.join(DIST, f"motion_trail_editor-{ver}.zip")
    if os.path.exists(ext):
        os.remove(ext)
    subprocess.run([BLENDER, "--factory-startup", "--command", "extension", "build",
                    "--source-dir", SRC, "--output-dir", DIST], check=True)

    legacy = os.path.join(DIST, f"motion_trail_editor-{ver}-legacy.zip")
    with zipfile.ZipFile(legacy, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path in sources():
            if name.endswith(".py"):
                z.write(path, f"motion_trail_editor/{name}")

    for path in (ext, legacy):
        with zipfile.ZipFile(path) as z:
            print(os.path.basename(path), os.path.getsize(path), "bytes:", z.namelist())


if __name__ == "__main__":
    main()
