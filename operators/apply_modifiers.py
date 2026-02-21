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
        new_obj.data.materials.append(mat)

    # Select the new object
    context.view_layer.objects.active = new_obj
    new_obj.select_set(True)

    return new_obj


def _apply_mesh_via_depsgraph(context, mesh_obj):
    """Apply GN modifiers that output instances by making instances real,
    then joining into a single mesh."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Ensure only our object is selected
    bpy.ops.object.select_all(action='DESELECT')
    context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)

    # Make instances real — converts GN instances to actual objects
    bpy.ops.object.duplicates_make_real()

    # Collect all newly created objects (they'll be selected)
    realized = [o for o in context.selected_objects if o != mesh_obj]

    if not realized:
        return None

    # Delete the original scatter mesh (just vertices, no materials)
    name = mesh_obj.name
    collections = list(mesh_obj.users_collection)
    bpy.data.objects.remove(mesh_obj, do_unlink=True)

    # Select all realized objects, join with one as active
    bpy.ops.object.select_all(action='DESELECT')
    for o in realized:
        o.select_set(True)
    active = realized[0]
    context.view_layer.objects.active = active

    if len(realized) > 1:
        bpy.ops.object.join()

    active.name = name
    return active


class GPTOOLS_OT_apply_all_modifiers(bpy.types.Operator):
    """Apply all modifiers on the active object. For Grease Pencil objects
    with geometry-changing modifiers, converts to mesh."""

    bl_idname = "gptools.apply_all_modifiers"
    bl_label = "Apply All Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or len(obj.modifiers) == 0:
            return False
        return obj.type in {"MESH", "GREASEPENCIL"}

    def execute(self, context):
        obj = context.active_object

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

        count = 0
        for modifier in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
                count += 1
            except RuntimeError:
                # GN modifiers that output instances can't be applied directly.
                # Use depsgraph to extract the evaluated mesh instead.
                new_obj = _apply_mesh_via_depsgraph(context, obj)
                if new_obj is not None:
                    count = len(obj.modifiers)
                    self.report(
                        {"INFO"},
                        f"Applied {count} modifier(s) via depsgraph"
                        f" ({len(new_obj.data.vertices)} verts).",
                    )
                    return {"FINISHED"}
                self.report(
                    {"WARNING"},
                    f"Could not apply '{modifier.name}'",
                )

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
        bpy.utils.unregister_class(cls)
