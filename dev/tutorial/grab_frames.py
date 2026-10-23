"""Save some frames of a video as PNG: blender -b --factory-startup --python grab_frames.py -- <video> <out dir> f1 f2 ..."""
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
video, out_dir, frames = args[0], args[1], [int(a) for a in args[2:]]
os.makedirs(out_dir, exist_ok=True)
scene = bpy.context.scene
seq = scene.sequence_editor_create()
strip = seq.strips.new_movie(name="v", filepath=video, channel=1, frame_start=1)
w, h = strip.elements[0].orig_width, strip.elements[0].orig_height
r = scene.render
r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
r.image_settings.file_format = 'PNG'
for f in frames:
    scene.frame_set(f)
    r.filepath = os.path.join(out_dir, f"video_{f:05d}.png")
    bpy.ops.render.render(write_still=True)
print("GRAB", w, h, frames)
