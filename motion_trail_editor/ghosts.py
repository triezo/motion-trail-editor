"""Ghosts (onion skin): snapshots of the character's deformed meshes at a frame, drawn see-through in the
viewport. Ghosts before the current frame and after it get their own colour. Kept in memory only."""
import bpy
import gpu
import numpy as np
from bpy.types import Operator, Panel
from gpu_extras.batch import batch_for_shader

from . import common

LIGHT = np.array((0.35, -0.45, 0.82), dtype=np.float32) / np.linalg.norm((0.35, -0.45, 0.82))


class Ghost:
    def __init__(self, frame, objects, positions, shade, indices):
        self.frame = frame
        self.objects = objects  # names of the captured objects
        self.positions = positions  # (N, 3) world space
        self.shade = shade  # (N,) simple lighting, 0..1
        self.indices = indices  # (T, 3)
        self._batches = {}  # colour -> shaded GPU batch (built on first draw)
        self._flat = None  # positions-only batch: one colour (uniform), any alpha

    def batch(self, shader, color):
        key = tuple(round(c, 4) for c in color)
        batch = self._batches.get(key)
        if batch is None:
            rgb = np.asarray(color[:3], dtype=np.float32)
            colors = np.empty((len(self.shade), 4), dtype=np.float32)
            colors[:, :3] = self.shade[:, None] * rgb[None, :]
            colors[:, 3] = color[3]
            batch = batch_for_shader(shader, 'TRIS', {"pos": self.positions, "color": colors}, indices=self.indices)
            self._batches = {key: batch} if len(self._batches) > 3 else {**self._batches, key: batch}
        return batch

    def flat_batch(self, shader):
        if self._flat is None:
            self._flat = batch_for_shader(shader, 'TRIS', {"pos": self.positions}, indices=self.indices)
        return self._flat


GHOSTS = []
_handle = [None]


def _mesh_arrays(ob, depsgraph):
    ob_eval = ob.evaluated_get(depsgraph)
    mesh = ob_eval.to_mesh()
    try:
        mesh.calc_loop_triangles()
        nv, nt = len(mesh.vertices), len(mesh.loop_triangles)
        if nv == 0 or nt == 0:
            return None
        co = np.empty(nv * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        normals = np.empty(nv * 3, dtype=np.float32)
        mesh.vertex_normals.foreach_get("vector", normals)
        tris = np.empty(nt * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", tris)
    finally:
        ob_eval.to_mesh_clear()
    mat = np.array(ob_eval.matrix_world, dtype=np.float32)
    co = co.reshape(-1, 3) @ mat[:3, :3].T + mat[:3, 3]
    normal_mat = np.linalg.inv(mat[:3, :3]).T
    normals = normals.reshape(-1, 3) @ normal_mat.T
    normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-8)[:, None]
    shade = 0.55 + 0.45 * np.clip(normals @ LIGHT, 0.0, 1.0)
    return co.astype(np.float32), shade.astype(np.float32), tris.reshape(-1, 3)


def make_ghost(context, objects, frame):
    """The evaluated (deformed) `objects` as they are now, as one Ghost tagged with `frame`; None if empty."""
    depsgraph = context.evaluated_depsgraph_get()
    parts, offset = [], 0
    for ob in objects:
        arrays = _mesh_arrays(ob, depsgraph)
        if arrays is None:
            continue
        co, shade, tris = arrays
        parts.append((co, shade, tris + offset))
        offset += len(co)
    if not parts:
        return None
    return Ghost(frame, tuple(sorted(ob.name for ob in objects)), np.concatenate([p[0] for p in parts]),
                 np.concatenate([p[1] for p in parts]), np.concatenate([p[2] for p in parts]))


def capture(context, objects):
    """Snapshot `objects` at the current frame as one ghost (replaces a ghost of the same objects there)."""
    ghost = make_ghost(context, objects, context.scene.frame_current)
    if ghost is None:
        return None
    GHOSTS[:] = [g for g in GHOSTS if not (g.frame == ghost.frame and g.objects == ghost.objects)]
    GHOSTS.append(ghost)
    return ghost


def _draw_depth(ghost, shader, near):
    """Write the ghost into the depth buffer only: at its own depth, or (near) in front of everything."""
    batch = ghost.flat_batch(shader)
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.0))
    gpu.state.color_mask_set(False, False, False, False)
    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set('ALWAYS')
    if near:
        proj = gpu.matrix.get_projection_matrix()
        squashed = proj.copy()
        squashed[2] = -0.999 * proj[3]  # every point lands on the near plane
        with gpu.matrix.push_pop_projection():
            gpu.matrix.load_projection_matrix(squashed)
            batch.draw(shader)
    else:
        batch.draw(shader)
    gpu.state.color_mask_set(True, True, True, True)


def draw_list(items, in_front, mask=None):
    """Draw [(ghost, colour, flat)]. Each ghost is drawn as one clean layer: a depth pass first, then the colour
    only where the ghost is the nearest surface (no darker spots where it overlaps itself).
    `mask`: a ghost of the character as it is now; nothing is drawn over it (the onion stays behind it)."""
    smooth = gpu.shader.from_builtin('SMOOTH_COLOR')
    uniform = gpu.shader.from_builtin('UNIFORM_COLOR')
    if mask is not None:
        _draw_depth(mask, uniform, near=True)
    gpu.state.blend_set('ALPHA')
    gpu.state.face_culling_set('BACK')
    for ghost, color, flat in items:
        shader = uniform if flat else smooth
        batch = ghost.flat_batch(shader) if flat else ghost.batch(shader, color)
        shader.bind()
        if flat:
            shader.uniform_float("color", tuple(color))
        if in_front:
            gpu.state.depth_test_set('NONE')
            gpu.state.depth_mask_set(False)
        else:
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(True)
            gpu.state.color_mask_set(False, False, False, False)
            batch.draw(shader)
            gpu.state.color_mask_set(True, True, True, True)
            gpu.state.depth_mask_set(False)
        batch.draw(shader)
    gpu.state.face_culling_set('NONE')
    if mask is not None:
        _draw_depth(mask, uniform, near=False)  # give the character back its own depth for what is drawn later
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _draw():
    context = bpy.context
    scene = context.scene
    if scene is None or not common.overlays_on(context.space_data):
        return
    from . import onion
    s = scene.anim_tools
    cur = scene.frame_current
    items = onion.draw_items(context)
    if s.ghost_show:
        for ghost in GHOSTS:
            if ghost.frame == cur and s.ghost_hide_current:
                continue
            items.append((ghost, s.ghost_color_before if ghost.frame <= cur else s.ghost_color_after, False))
    if items:
        draw_list(items, s.ghost_in_front, None if s.ghost_in_front else onion.draw_mask(context))


def tag_redraw():
    common.redraw_all()


def clear(frame=None):
    GHOSTS[:] = [] if frame is None else [g for g in GHOSTS if g.frame != frame]


class ANIMTOOLS_OT_ghost_add(Operator):
    """Ghost: keep a see-through copy of the character at the current frame
    (the rig in Pose Mode, or the selected rigs / meshes)"""
    bl_idname = "anim_tools.ghost_add"
    bl_label = "Add Ghost"
    bl_options = {'REGISTER'}

    def execute(self, context):
        meshes = common.character_meshes(context)
        if not meshes:
            self.report({'WARNING'}, "Select the rig (Pose Mode) or the character's meshes")
            return {'CANCELLED'}
        if capture(context, meshes) is None:
            self.report({'WARNING'}, "Nothing to capture")
            return {'CANCELLED'}
        context.scene.anim_tools.ghost_show = True
        tag_redraw()
        return {'FINISHED'}


class ANIMTOOLS_OT_ghost_clear_frame(Operator):
    """Remove the ghosts of the current frame"""
    bl_idname = "anim_tools.ghost_clear_frame"
    bl_label = "Remove Ghosts of This Frame"
    bl_options = {'REGISTER'}

    def execute(self, context):
        clear(context.scene.frame_current)
        tag_redraw()
        return {'FINISHED'}


class ANIMTOOLS_OT_ghost_clear(Operator):
    """Remove all ghosts"""
    bl_idname = "anim_tools.ghost_clear"
    bl_label = "Remove All Ghosts"
    bl_options = {'REGISTER'}

    def execute(self, context):
        clear()
        tag_redraw()
        return {'FINISHED'}


class ANIMTOOLS_PT_ghosts(Panel):
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "Onion Skin / Ghosts"
    bl_ui_units_x = 12

    def draw(self, context):
        from . import onion
        layout = self.layout
        s = context.scene.anim_tools

        layout.label(text="Onion Skin", icon='ONIONSKIN_ON')
        row = layout.row(align=True)
        row.operator("anim_tools.onion", text="On" if not onion.is_enabled() else "Off",
                     depress=onion.is_enabled())
        row.operator("anim_tools.onion_retarget", icon='RESTRICT_SELECT_OFF')
        col = layout.column(align=True)
        col.active = onion.is_enabled()
        if onion.state.objects:
            names = ", ".join(onion.state.objects[:3]) + (" …" if len(onion.state.objects) > 3 else "")
            col.label(text=names, icon='OUTLINER_OB_ARMATURE')
        col.row(align=True).prop(s, "onion_mode", expand=True)
        row = col.row(align=True)
        row.prop(s, "onion_before")
        row.prop(s, "onion_after")
        if s.onion_mode == 'FRAMES':
            col.prop(s, "onion_step")
        col.prop(s, "onion_flat")
        col.prop(s, "onion_behind")

        layout.separator()
        row = layout.row(align=True)
        row.prop(s, "ghost_color_before", text="")
        row.prop(s, "ghost_color_after", text="")
        layout.prop(s, "ghost_in_front")

        layout.separator()
        layout.label(text="Ghosts", icon='GHOST_ENABLED')
        layout.prop(s, "ghost_show")
        col = layout.column()
        col.active = s.ghost_show
        col.prop(s, "ghost_hide_current")
        frames = sorted({g.frame for g in GHOSTS})
        if frames:
            col.label(text="Frames: " + ", ".join(str(f) for f in frames[:12]) + (" …" if len(frames) > 12 else ""))
        col.operator("anim_tools.ghost_clear", icon='TRASH')


classes = (ANIMTOOLS_OT_ghost_add, ANIMTOOLS_OT_ghost_clear_frame, ANIMTOOLS_OT_ghost_clear, ANIMTOOLS_PT_ghosts)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if _handle[0] is None:
        _handle[0] = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def unregister():
    if _handle[0] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle[0], 'WINDOW')
        _handle[0] = None
    clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
