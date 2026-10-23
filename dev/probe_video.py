import bpy
scene = bpy.context.scene
ims = scene.render.image_settings
print("PROBE media_type" , "media_type" in ims.bl_rna.properties,
      [e.identifier for e in ims.bl_rna.properties["media_type"].enum_items] if "media_type" in ims.bl_rna.properties else None)
if "media_type" in ims.bl_rna.properties:
    ims.media_type = 'VIDEO'
print("PROBE file_format", [e.identifier for e in ims.bl_rna.properties["file_format"].enum_items])
ff = scene.render.ffmpeg
print("PROBE ffmpeg", {p: [e.identifier for e in ff.bl_rna.properties[p].enum_items][:12]
                       for p in ("format", "codec", "constant_rate_factor") if p in ff.bl_rna.properties})
se = scene.sequence_editor_create()
print("PROBE seq attrs", [a for a in ("strips", "sequences", "strips_all") if hasattr(se, a)])
