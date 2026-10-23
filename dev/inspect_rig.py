"""List bone settings that change how `location` maps to world space:
blender -b <file.blend> --factory-startup --python dev/inspect_rig.py
"""
import bpy

for ob in bpy.data.objects:
    if ob.type != 'ARMATURE':
        continue
    animated = set()
    adt = ob.animation_data
    if adt and adt.action:
        fcurves = adt.action.fcurves if "fcurves" in adt.action.bl_rna.properties else []
        for fc in fcurves:
            if fc.data_path.startswith('pose.bones["') and fc.data_path.endswith('"].location'):
                animated.add(fc.data_path.split('"')[1])
    print(f"RIG {ob.name}: bones {len(ob.pose.bones)}, scale {tuple(round(v, 3) for v in ob.scale)}, "
          f"parent {ob.parent.name if ob.parent else None}, animated location: {len(animated)}")
    for pb in ob.pose.bones:
        b = pb.bone
        special = []
        if not b.use_inherit_rotation:
            special.append("inherit_rotation=OFF")
        if b.inherit_scale != 'FULL':
            special.append(f"inherit_scale={b.inherit_scale}")
        if not b.use_local_location:
            special.append("local_location=OFF")
        if pb.constraints:
            special.append("constraints=" + ",".join(c.type for c in pb.constraints))
        if special and (pb.name in animated or not animated):
            print(f"RIG   {pb.name}{' (location animated)' if pb.name in animated else ''}: {'; '.join(special)}")
