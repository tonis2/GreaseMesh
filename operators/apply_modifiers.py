import bpy


def _apply_gp_modifiers(context, gp_obj):
    """Extract evaluated mesh from a GP object's GN modifiers via depsgraph."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    depsgraph = context.evaluated_depsgraph_get()

    # GN modifiers on GP objects create mesh instances in the depsgraph.
    # Extract vertex/face data before any scene changes invalidate references.
    verts = []
    faces = []
    smooth_flags = []
    eval_inst_obj = None

    for inst in depsgraph.object_instances:
        if inst.object.original == gp_obj and inst.is_instance:
            eval_inst_obj = inst.object
            mesh_data = eval_inst_obj.to_mesh()
            if mesh_data and len(mesh_data.vertices) > 0:
                verts = [v.co[:] for v in mesh_data.vertices]
                faces = [list(p.vertices) for p in mesh_data.polygons]
                smooth_flags = [p.use_smooth for p in mesh_data.polygons]
            eval_inst_obj.to_mesh_clear()
            break

    if not verts:
        return None

    # Collect GP object properties before removing it
    name = gp_obj.name
    matrix = gp_obj.matrix_world.copy()
    collections = list(gp_obj.users_collection)
    materials = list(gp_obj.data.materials)

    # Remove the original GP object
    bpy.data.objects.remove(gp_obj, do_unlink=True)

    # Build a standalone mesh from the extracted data
    new_mesh = bpy.data.meshes.new(name=name)
    new_mesh.from_pydata(verts, [], faces)
    new_mesh.update()

    for flag, poly in zip(smooth_flags, new_mesh.polygons):
        poly.use_smooth = flag

    # Create new mesh object at the same transform
    new_obj = bpy.data.objects.new(name=name, object_data=new_mesh)
    for col in collections:
        col.objects.link(new_obj)
    new_obj.matrix_world = matrix

    for mat in materials:
        if mat and mat.node_tree is None:
            # GP materials lack a shader node tree — replace with a mesh
            # material so renderers and painting addons work correctly.
            mesh_mat = bpy.data.materials.new(name=mat.name)
            mesh_mat.use_nodes = True
            # Copy the GP surface colour to the Principled BSDF base colour
            principled = mesh_mat.node_tree.nodes.get("Principled BSDF")
            if principled and hasattr(mat, "grease_pencil"):
                gp_mat = mat.grease_pencil
                col = gp_mat.color
                principled.inputs["Base Color"].default_value = (col[0], col[1], col[2], col[3])
            new_obj.data.materials.append(mesh_mat)
        else:
            new_obj.data.materials.append(mat)

    # Select the new object
    context.view_layer.objects.active = new_obj
    new_obj.select_set(True)

    return new_obj


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
            new_obj = _apply_gp_modifiers(context, obj)
            if new_obj is None:
                self.report({"ERROR"}, "No mesh geometry produced by modifiers.")
                return {"CANCELLED"}
            self.report(
                {"INFO"},
                f"Converted '{name}' to mesh ({len(new_obj.data.vertices)} verts).",
            )
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
                curve_obj = mod.get("Socket_27")
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
