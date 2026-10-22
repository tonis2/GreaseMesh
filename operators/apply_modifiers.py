import bpy

from ..utils.modifier_io import get_input
from .edit_drawing import end_edit


def _surface_from_stroke_mesh(gp_obj):
    """Name of the 'Surface Object' set on a StrokeMesh modifier, if any."""
    mod = gp_obj.modifiers.get("StrokeMesh")
    if mod is None or mod.type != 'NODES' or mod.node_group is None:
        return None
    try:
        items = mod.node_group.interface.items_tree
    except AttributeError:
        return None
    for item in items:
        if (getattr(item, "item_type", None) == 'SOCKET'
                and item.in_out == 'INPUT' and item.name == "Surface Object"):
            surf = get_input(mod, item.identifier)
            if isinstance(surf, bpy.types.Object):
                return surf.name
    return None


def _convert_gp_material(mat, has_vertex_color):
    """Return a mesh-friendly material for a GP material (GP materials either
    have no node tree or are flagged is_grease_pencil)."""
    if mat is None or not (mat.is_grease_pencil or mat.node_tree is None):
        return mat
    mesh_mat = bpy.data.materials.new(name=mat.name)
    if hasattr(mesh_mat, "use_nodes") and not mesh_mat.use_nodes:
        try:
            mesh_mat.use_nodes = True
        except Exception:
            pass
    nt = mesh_mat.node_tree
    if nt is None:
        return mesh_mat
    principled = nt.nodes.get("Principled BSDF")
    if principled is None:
        return mesh_mat
    col = (1.0, 1.0, 1.0, 1.0)
    if hasattr(mat, "grease_pencil"):
        c = mat.grease_pencil.color
        col = (c[0], c[1], c[2], c[3])
    principled.inputs["Base Color"].default_value = col
    if has_vertex_color:
        attr = nt.nodes.new("ShaderNodeVertexColor")
        attr.layer_name = "vertex_color"
        attr.location = (principled.location.x - 700, principled.location.y - 200)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = 'RGBA'
        mix.blend_type = 'MIX'
        mix.location = (principled.location.x - 350, principled.location.y)
        mix.inputs["A"].default_value = col
        nt.links.new(attr.outputs["Alpha"], mix.inputs["Factor"])
        nt.links.new(attr.outputs["Color"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], principled.inputs["Base Color"])
    return mesh_mat


def _apply_gp_modifiers(context, gp_obj):
    """Convert a GP object's GN output into real data.

    Generated geometry becomes one mesh object; real-object instances (e.g.
    Scatter props) become linked duplicates. Returns a list of created objects
    (mesh object first, if any) and the number of placed props, or None.
    """
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    end_edit(gp_obj)

    depsgraph = context.evaluated_depsgraph_get()
    gp_inv = gp_obj.matrix_world.inverted()

    pieces = []          # meshes in GP-local space
    props = {}           # rounded position -> (source object, matrix)
    for inst in depsgraph.object_instances:
        if not inst.is_instance or inst.parent is None or inst.parent.original != gp_obj:
            continue
        src = inst.object.original
        if src == gp_obj:
            if inst.object.type != 'MESH':
                continue  # leftover GP strokes are ignored
            mesh = bpy.data.meshes.new_from_object(
                inst.object, preserve_all_data_layers=True, depsgraph=depsgraph)
            if mesh is None or len(mesh.vertices) == 0:
                if mesh is not None:
                    bpy.data.meshes.remove(mesh)
                continue
            mesh.transform(gp_inv @ inst.matrix_world)
            pieces.append(mesh)
        else:
            pos = inst.matrix_world.translation
            key = (round(pos.x, 3), round(pos.y, 3), round(pos.z, 3))
            if key not in props or src.type != 'MESH':
                # Prefer the Empty (collection instance) over its child mesh
                props[key] = (src, inst.matrix_world.copy())

    if not pieces and not props:
        return None

    name = gp_obj.name
    matrix = gp_obj.matrix_world.copy()
    collections = list(gp_obj.users_collection)
    materials = list(gp_obj.data.materials)
    surface_name = _surface_from_stroke_mesh(gp_obj)

    new_mesh_obj = None
    if pieces:
        import bmesh
        bm = bmesh.new()
        for piece in pieces:
            bm.from_mesh(piece)
            bpy.data.meshes.remove(piece)
        new_mesh = bpy.data.meshes.new(name=name)
        bm.to_mesh(new_mesh)
        bm.free()
        new_mesh.update()
        # Only Stroke Mesh is meant to look like the drawing; the other tools
        # would just inherit the GP's (usually black) stroke material.
        if gp_obj.modifiers.get("StrokeMesh") is not None:
            has_vcol = "vertex_color" in new_mesh.attributes
            for mat in materials:
                new_mesh.materials.append(_convert_gp_material(mat, has_vcol))
        elif "material_index" in new_mesh.attributes:
            new_mesh.attributes.remove(new_mesh.attributes["material_index"])
        new_mesh_obj = bpy.data.objects.new(name=name, object_data=new_mesh)
        for col in collections:
            col.objects.link(new_mesh_obj)
        new_mesh_obj.matrix_world = matrix
        if surface_name:
            new_mesh_obj["gm_surface"] = surface_name

    duplicates = []
    for src_obj, mat_w in props.values():
        dup = src_obj.copy()
        if src_obj.data is not None:
            dup.data = src_obj.data  # linked duplicate
        for col in collections:
            col.objects.link(dup)
        dup.matrix_world = mat_w
        duplicates.append(dup)

    bpy.data.objects.remove(gp_obj, do_unlink=True)
    context.view_layer.update()
    if new_mesh_obj is not None:
        new_mesh_obj.name = name
        new_mesh_obj.data.name = name

    created = ([new_mesh_obj] if new_mesh_obj else []) + duplicates
    for o in context.view_layer.objects:
        o.select_set(False)
    for o in created:
        o.select_set(True)
    context.view_layer.objects.active = created[0]
    return created, len(duplicates)


class GPTOOLS_OT_apply_all_modifiers(bpy.types.Operator):
    """Apply all modifiers on the active object. For Grease Pencil objects
    with geometry-changing modifiers, converts to mesh."""

    bl_idname = "gptools.apply_all_modifiers"
    bl_label = "Apply All Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def _find_target(cls, context):
        """Return the object to apply modifiers on.
        Prefers active object, falls back to first selected with modifiers."""
        obj = context.active_object
        if obj and obj.type in {"MESH", "GREASEPENCIL"} and len(obj.modifiers) > 0:
            return obj
        for obj in context.selected_objects:
            if obj.type in {"MESH", "GREASEPENCIL"} and len(obj.modifiers) > 0:
                return obj
        return None

    @classmethod
    def poll(cls, context):
        return cls._find_target(context) is not None

    def execute(self, context):
        obj = self._find_target(context)

        if obj.type == "GREASEPENCIL":
            name = obj.name
            result = _apply_gp_modifiers(context, obj)
            if result is None:
                self.report({"ERROR"}, "No mesh geometry or instances produced by modifiers.")
                return {"CANCELLED"}
            created, n_props = result
            msg = f"Converted '{name}'"
            if created and created[0].type == 'MESH' and n_props < len(created):
                msg += f": mesh ({len(created[0].data.vertices)} verts)"
            if n_props:
                msg += f", {n_props} prop(s) placed"
            self.report({"INFO"}, msg)
            return {"FINISHED"}

        # Apply all modifiers by evaluating the final mesh from depsgraph.
        # Using bpy.ops.object.modifier_apply() in a loop creates nested
        # undo steps that break Ctrl+Z, so we use the low-level approach.
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        new_mesh = bpy.data.meshes.new_from_object(eval_obj)

        if new_mesh is None or len(new_mesh.vertices) == 0:
            self.report({"ERROR"}, "No mesh geometry produced by modifiers.")
            return {"CANCELLED"}

        old_mesh = obj.data
        new_mesh.name = old_mesh.name
        obj.data = new_mesh
        # Don't remove old_mesh — bpy.data.meshes.remove() bypasses undo.
        # The orphaned mesh is auto-cleaned on file save.

        # Collect curve objects referenced by Array GN modifiers (from Array on Pencil)
        cleanup_objects = []
        for mod in obj.modifiers:
            if mod.type == 'NODES' and mod.node_group and mod.node_group.name == 'Array':
                curve_obj = get_input(mod, "Socket_27")
                if curve_obj and isinstance(curve_obj, bpy.types.Object) and curve_obj.type == 'CURVE':
                    cleanup_objects.append(curve_obj)

        count = len(obj.modifiers)
        for mod in list(obj.modifiers):
            obj.modifiers.remove(mod)

        # Remove curve objects and their hidden source GP objects
        for curve_obj in cleanup_objects:
            # Find the matching hidden GP (name without "_Curve" suffix)
            gp_name = curve_obj.name.removesuffix("_Curve")
            gp_obj = bpy.data.objects.get(gp_name)
            if gp_obj and gp_obj.type == 'GREASEPENCIL':
                bpy.data.objects.remove(gp_obj, do_unlink=True)
            bpy.data.objects.remove(curve_obj, do_unlink=True)

        self.report({"INFO"}, f"Applied {count} modifier(s)")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_apply_all_modifiers,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
