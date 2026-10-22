import bpy


def _find_surface(context):
    """Return the surface mesh object for the active mesh, or None."""
    active = context.active_object
    if active is None or active.type != 'MESH':
        return None
    for o in context.selected_objects:
        if o != active and o.type == 'MESH':
            return o
    name = active.get("gm_surface")
    if name:
        o = bpy.data.objects.get(name)
        if o is not None and o.type == 'MESH' and o != active:
            return o
    return None


def _surface_armature_modifier(surface):
    for mod in surface.modifiers:
        if mod.type == 'ARMATURE' and mod.object is not None:
            return mod
    return None


def _selected_armature(context):
    """Return the first selected armature object, or None."""
    for o in context.selected_objects:
        if o.type == 'ARMATURE':
            return o
    return None


def _is_rigged(surface):
    return (
        surface is not None
        and len(surface.vertex_groups) > 0
        and _surface_armature_modifier(surface) is not None
    )


class GPTOOLS_OT_bind_to_surface(bpy.types.Operator):
    """Copy vertex-group weights from a surface mesh onto the active mesh and
    bind it to the surface's armature. If the surface isn't rigged, a selected
    armature is used with Automatic Weights instead"""

    bl_idname = "gptools.bind_to_surface"
    bl_label = "Bind to Surface"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        active = context.active_object
        if active is None or active.type != 'MESH':
            return False
        return _find_surface(context) is not None or _selected_armature(context) is not None

    def execute(self, context):
        target = context.active_object
        surface = _find_surface(context)

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if not _is_rigged(surface):
            armature = _selected_armature(context)
            if armature is None:
                if surface is None:
                    self.report({"ERROR"}, "Select a surface mesh or an armature.")
                else:
                    self.report(
                        {"ERROR"},
                        f"Surface '{surface.name}' isn't rigged. Also select an armature "
                        "to bind with Automatic Weights.",
                    )
                return {"CANCELLED"}
            return self._bind_automatic_weights(context, target, armature)

        arm_mod = _surface_armature_modifier(surface)
        armature = arm_mod.object

        # Matching empty vertex groups on the target
        for vg in surface.vertex_groups:
            if target.vertex_groups.get(vg.name) is None:
                target.vertex_groups.new(name=vg.name)

        dt = target.modifiers.new(name="GM_BindTransfer", type='DATA_TRANSFER')
        dt.object = surface
        dt.use_vert_data = True
        dt.data_types_verts = {'VGROUP_WEIGHTS'}
        dt.vert_mapping = 'POLYINTERP_NEAREST'
        dt.layers_vgroup_select_src = 'ALL'
        dt.layers_vgroup_select_dst = 'NAME'

        # Bake through the depsgraph. new_from_object drops vertex groups,
        # so copy the evaluated weights back onto the target explicitly.
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = target.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            names = [vg.name for vg in target.vertex_groups]
            if len(eval_mesh.vertices) != len(target.data.vertices):
                target.modifiers.remove(dt)
                self.report({"ERROR"}, "Unexpected vertex count change while transferring weights.")
                return {"CANCELLED"}
            weights = []
            for v in eval_mesh.vertices:
                weights.append([(g.group, g.weight) for g in v.groups])
        finally:
            eval_obj.to_mesh_clear()

        target.modifiers.remove(dt)
        for i, ws in enumerate(weights):
            for gi, w in ws:
                if gi < len(names) and w > 0.0:
                    target.vertex_groups[names[gi]].add([i], w, 'REPLACE')

        mod = target.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = armature
        mod.use_vertex_groups = arm_mod.use_vertex_groups
        mod.use_deform_preserve_volume = arm_mod.use_deform_preserve_volume

        world = target.matrix_world.copy()
        target.parent = armature
        target.parent_type = 'OBJECT'
        target.matrix_parent_inverse = armature.matrix_world.inverted()
        target.matrix_world = world

        self.report({"INFO"}, f"Bound '{target.name}' to '{armature.name}' ({len(names)} groups).")
        return {"FINISHED"}

    def _bind_automatic_weights(self, context, target, armature):
        """Fallback for unrigged surfaces: parent to the armature with
        Automatic Weights (adds the Armature modifier and vertex groups)."""
        with context.temp_override(
            active_object=armature,
            object=armature,
            selected_objects=[target, armature],
            selected_editable_objects=[target, armature],
        ):
            result = bpy.ops.object.parent_set(type='ARMATURE_AUTO', keep_transform=True)
        if 'FINISHED' not in result:
            self.report({"ERROR"}, f"Automatic Weights failed for '{target.name}'.")
            return {"CANCELLED"}

        # Bone heat can fail silently on thin ribbons and leave every weight at zero.
        weighted = sum(1 for v in target.data.vertices if any(g.weight > 0.0 for g in v.groups))
        if weighted == 0:
            self.report(
                {"WARNING"},
                f"Bound '{target.name}' to '{armature.name}', but Automatic Weights gave no "
                "weights. Rig the surface and bind again, or weight paint by hand.",
            )
        else:
            self.report(
                {"INFO"},
                f"Bound '{target.name}' to '{armature.name}' with Automatic Weights "
                f"({weighted}/{len(target.data.vertices)} vertices weighted).",
            )
        context.view_layer.objects.active = target
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_bind_to_surface,
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
