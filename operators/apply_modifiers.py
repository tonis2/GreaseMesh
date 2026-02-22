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


def _apply_scatter_modifier(context, scatter_obj):
    """Apply a StampScatter GN modifier by reading the exact instances
    from the depsgraph (matching what's displayed in viewport) and
    duplicating them as real objects."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    depsgraph = context.evaluated_depsgraph_get()

    # Collect all GN instances belonging to this scatter object.
    # Deduplicate by position — collection instances expand into
    # parent Empty + child Mesh at the same location in the depsgraph.
    seen_positions = {}
    for inst in depsgraph.object_instances:
        if not inst.is_instance:
            continue
        if inst.parent is None or inst.parent.original != scatter_obj:
            continue

        # Round position to group instances at the same location
        pos = inst.matrix_world.translation
        key = (round(pos.x, 3), round(pos.y, 3), round(pos.z, 3))

        src = inst.object.original
        if key not in seen_positions:
            seen_positions[key] = (src, inst.matrix_world.copy())
        elif src.type != 'MESH':
            # Prefer the Empty (collection instance) over the child mesh,
            # as it preserves the full asset hierarchy
            seen_positions[key] = (src, inst.matrix_world.copy())

    instances = list(seen_positions.values())

    if not instances:
        return None

    user_collections = list(scatter_obj.users_collection)

    # Duplicate each instance as a real object at its exact transform
    created = []
    for src_obj, matrix in instances:
        new_obj = src_obj.copy()
        if src_obj.data is not None:
            new_obj.data = src_obj.data  # linked duplicate
        new_obj.matrix_world = matrix

        for col in user_collections:
            col.objects.link(new_obj)

        created.append(new_obj)

    if not created:
        return None

    # Success — remove the scatter object
    bpy.data.objects.remove(scatter_obj, do_unlink=True)
    context.view_layer.update()

    # Select all created objects
    bpy.ops.object.select_all(action='DESELECT')
    for o in created:
        o.select_set(True)
    context.view_layer.objects.active = created[0]

    return created


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

        # Check if this is a scatter mesh (has stamp_layer attribute)
        has_stamp_layer = (
            obj.type == 'MESH'
            and obj.data.attributes.get("stamp_layer") is not None
        )

        if has_stamp_layer:
            created = _apply_scatter_modifier(context, obj)
            if created is not None:
                self.report(
                    {"INFO"},
                    f"Placed {len(created)} object(s) from scatter",
                )
                return {"FINISHED"}
            self.report({"ERROR"}, "Could not apply scatter modifier")
            return {"CANCELLED"}

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

        count = len(obj.modifiers)
        for mod in list(obj.modifiers):
            obj.modifiers.remove(mod)

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
