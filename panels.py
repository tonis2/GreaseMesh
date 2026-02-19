import bpy


class GPTOOLS_PT_main(bpy.types.Panel):
    bl_label = "GPTools"
    bl_idname = "GPTOOLS_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GPTools"

    def draw(self, context):
        layout = self.layout

        # Create Section
        box = layout.box()
        box.label(text="Create", icon="GREASEPENCIL")
        box.operator("gptools.add_gpencil", text="Add New Grease Pencil", icon="ADD")
        box.operator(
            "gptools.apply_all_modifiers", text="Apply All Modifiers", icon="CHECKMARK"
        )

        # Convert Section
        box = layout.box()
        row = box.row(align=True)
        row.label(text="Convert", icon="IMPORT")
        row.operator("gptools.convert_curve", text="", icon="CURVE_BEZCURVE")
        row.operator("gptools.convert_mesh", text="", icon="MESH_DATA")
        row.operator("gptools.convert_line", text="", icon="TRACKING_BACKWARDS_SINGLE")

        # Solid Mesh Section
        box = layout.box()
        box.label(text="Solid Mesh", icon="MESH_CUBE")
        props = context.scene.gptools
        box.prop(props, "solid_round")
        col = box.column(align=True)
        col.operator(
            "gptools.solid_mesh", text="Solid Mesh", icon="MOD_SOLIDIFY"
        )
        col.operator(
            "gptools.mirror_mesh", text="Mirror Mesh", icon="MOD_MIRROR"
        )
        col.operator(
            "gptools.lathe_mesh", text="Lathe Mesh", icon="MOD_SCREW"
        )

        # Screw Mesh Section
        box = layout.box()
        box.label(text="Screw Mesh", icon="MOD_SCREW")
        col = box.column(align=True)
        col.operator("gptools.screw_mesh", text="Screw", icon="MOD_SCREW")
        col.operator("gptools.square_screw_mesh", text="Square Screw", icon="MESH_PLANE")

        # Lattice Wrap Section
        box = layout.box()
        box.label(text="Lattice Wrap", icon="MOD_LATTICE")
        box.prop(props, "lattice_resolution")
        box.operator("gptools.lattice_wrap", text="Lattice Wrap", icon="MOD_LATTICE")

        # Dev Section (for easy reload during development)
        box = layout.box()
        box.label(text="Development", icon="SCRIPT")
        box.operator("gptools.reload_addon", text="Reload Addon", icon="FILE_REFRESH")


classes = [
    GPTOOLS_PT_main,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
