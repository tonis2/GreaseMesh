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
        box.label(text="Convert", icon="IMPORT")

        col = box.column(align=True)
        col.operator("gptools.convert_curve", text="To Curve", icon="CURVE_BEZCURVE")
        col.operator("gptools.convert_mesh", text="To Mesh", icon="MESH_DATA")
        col.operator(
            "gptools.convert_line", text="To Line", icon="TRACKING_BACKWARDS_SINGLE"
        )

        # Solid Mesh Section
        box = layout.box()
        box.label(text="Solid Mesh", icon="MESH_CUBE")
        box.operator(
            "gptools.solid_mesh", text="Create Solid Mesh", icon="MOD_SOLIDIFY"
        )

        # Screw Mesh Section
        box = layout.box()
        box.label(text="Screw Mesh", icon="MOD_SCREW")
        col = box.column(align=True)
        col.operator("gptools.screw_mesh", text="Screw", icon="MOD_SCREW")
        col.operator("gptools.square_screw_mesh", text="Square Screw", icon="MESH_PLANE")

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
