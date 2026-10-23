"""Encode recorded frames to MP4 with Blender's sequencer:
blender -b --factory-startup --python dev/tutorial/encode.py -- <frames dir> <out.mp4> [fps]
"""
import os
import struct
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
frames_dir, out_path = args[0], args[1]
fps = int(args[2]) if len(args) > 2 else 12
files = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
assert files, "no frames"


def png_size(path):
    with open(path, "rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


# The sequencer applies one transform to a whole strip, so frames of another size (window resized while
# recording) would zoom and crop the picture: scale them to the most common size first.
sizes = {}
for f in files:
    size = png_size(os.path.join(frames_dir, f))
    sizes.setdefault(size, []).append(f)
common = max(sizes, key=lambda s: len(sizes[s]))
for size, names in sizes.items():
    if size == common:
        continue
    for f in names:
        img = bpy.data.images.load(os.path.join(frames_dir, f), check_existing=False)
        img.scale(*common)
        img.save()
        bpy.data.images.remove(img)
    print("rescaled", len(names), "frames from", size, "to", common)
w, h = common[0] - common[0] % 2, common[1] - common[1] % 2  # H.264 needs even sizes

scene = bpy.context.scene
seq = scene.sequence_editor_create()
strip = seq.strips.new_image(name="frames", filepath=os.path.join(frames_dir, files[0]), channel=1, frame_start=1,
                             fit_method='ORIGINAL')
for f in files[1:]:
    strip.elements.append(f)

r = scene.render
r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
r.fps, r.fps_base = fps, 1.0
scene.frame_start, scene.frame_end = 1, len(files)
ims = r.image_settings
if "media_type" in ims.bl_rna.properties:
    ims.media_type = 'VIDEO'
ims.file_format = 'FFMPEG'
r.ffmpeg.format = 'MPEG4'
r.ffmpeg.codec = 'H264'
r.ffmpeg.constant_rate_factor = 'HIGH'
r.ffmpeg.ffmpeg_preset = 'GOOD'
r.ffmpeg.audio_codec = 'NONE'
r.filepath = out_path
r.use_file_extension = False
bpy.ops.render.render(animation=True)
print("ENCODED", out_path, len(files), "frames", f"{len(files) / fps:.1f}s", (w, h))
