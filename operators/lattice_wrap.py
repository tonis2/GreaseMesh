import bpy
from mathutils import Vector


class GPTOOLS_OT_lattice_wrap(bpy.types.Operator):
    """Wrap active mesh onto another selected mesh using a flat lattice + shrinkwrap"""

    bl_idname = "gptools.lattice_wrap"
    bl_label = "Lattice Wrap"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return False
        return any(
            o for o in context.selected_objects if o != obj and o.type == "MESH"
        )

    def execute(self, context):
        # NOTE: context.active_object may change when clicking the N-panel button,
        # so we use the NON-active selected mesh as the source (gets the lattice)
        # and the active object as the target (surface to wrap onto).
        target_obj = context.active_object
        source_obj = next(
            o for o in context.selected_objects
            if o != target_obj and o.type == "MESH"
        )

        props = context.scene.gptools
        resolution = props.lattice_resolution

        # Compute local-space bounding box
        bb = source_obj.bound_box
        local_min = Vector((min(c[0] for c in bb), min(c[1] for c in bb), min(c[2] for c in bb)))
        local_max = Vector((max(c[0] for c in bb), max(c[1] for c in bb), max(c[2] for c in bb)))
        local_size = local_max - local_min
        local_center = (local_min + local_max) / 2

        # World-space bbox center and size
        world_center = source_obj.matrix_world @ local_center
        world_size = Vector((
            local_size.x * abs(source_obj.scale.x),
            local_size.y * abs(source_obj.scale.y),
            local_size.z * abs(source_obj.scale.z),
        ))

        # Thin axis = flat lattice dimension (2 points)
        axis_sizes = [(world_size.x, 0), (world_size.y, 1), (world_size.z, 2)]
        axis_sizes.sort(key=lambda d: d[0])
        thin_axis = axis_sizes[0][1]

        # Create flat lattice
        lat_data = bpy.data.lattices.new(name="LatticeWrap")
        res = [resolution, resolution, resolution]
        res[thin_axis] = 2
        lat_data.points_u = res[0]
        lat_data.points_v = res[1]
        lat_data.points_w = res[2]

        lat_obj = bpy.data.objects.new(name="LatticeWrap", object_data=lat_data)
        context.collection.objects.link(lat_obj)

        # Position and scale (default lattice is 2x2x2 so divide by 2)
        lat_obj.location = world_center
        lat_obj.rotation_euler = source_obj.rotation_euler
        lat_obj.scale = world_size / 2

        # CRITICAL: force matrix_world update before parenting
        context.view_layer.update()

        # Add Lattice modifier to source mesh
        lat_mod = source_obj.modifiers.new(name="Lattice", type="LATTICE")
        lat_mod.object = lat_obj

        # Parent source to lattice
        source_obj.parent = lat_obj
        source_obj.matrix_parent_inverse = lat_obj.matrix_world.inverted()

        # Add Shrinkwrap modifier to the lattice targeting the other mesh
        sw_mod = lat_obj.modifiers.new(name="Shrinkwrap", type="SHRINKWRAP")
        sw_mod.target = target_obj
        sw_mod.wrap_method = "TARGET_PROJECT"
        sw_mod.wrap_mode = "ABOVE_SURFACE"
        sw_mod.offset = 0.05

        # Select the lattice so user can adjust
        bpy.ops.object.select_all(action="DESELECT")
        lat_obj.select_set(True)
        context.view_layer.objects.active = lat_obj

        # Switch Properties panel to Modifiers tab
        try:
            for area in context.screen.areas:
                if area.type == "PROPERTIES":
                    for space in area.spaces:
                        if space.type == "PROPERTIES":
                            space.context = "MODIFIER"
                            break
                    break
        except TypeError:
            pass

        self.report({"INFO"}, f"Lattice wrap: {source_obj.name} → {target_obj.name}")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_lattice_wrap,
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
