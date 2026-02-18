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
        box.label(text="Adjust in 'GP Mesh' modifier", icon="INFO")

        # Screw Mesh Section
        box = layout.box()
        box.label(text="Screw Mesh", icon="MOD_SCREW")

        props = context.scene.gptools
        col = box.column(align=True)
        col.prop(props, "screw_axis")
        col.prop(props, "screw_segments")
        col.separator()
        col.operator("gptools.screw_mesh", text="Create Screw Mesh", icon="MOD_SCREW")

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
