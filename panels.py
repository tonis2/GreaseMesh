import bpy
import os


class GPTOOLS_PT_main(bpy.types.Panel):
    bl_label = "GPTools"
    bl_idname = "GPTOOLS_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GPTools"

    def draw(self, context):
        layout = self.layout
        props = context.scene.gptools

        # Create Section
        box = layout.box()
        box.label(text="Create", icon="GREASEPENCIL")
        box.operator("gptools.add_gpencil", text="Add New Grease Pencil", icon="ADD")
        box.operator(
            "gptools.apply_all_modifiers", text="Apply All Modifiers", icon="CHECKMARK"
        )

        # Mesh from GP Section
        box = layout.box()
        box.label(text="Mesh from GP", icon="GEOMETRY_NODES")
        col = box.column(align=True)
        col.operator("gptools.gn_solid_mesh", text="Solid Mesh", icon="MOD_SOLIDIFY")
        col.operator("gptools.gn_mirror_mesh", text="Mirror Mesh", icon="MOD_MIRROR")
        col.operator("gptools.gn_path_mesh", text="Path Mesh", icon="MOD_CURVE")

        # Boolean Section
        box = layout.box()
        box.label(text="Boolean", icon="MOD_BOOLEAN")
        box.operator("gptools.bool_cut", text="Bool Cut", icon="MOD_BOOLEAN")

        # Screw Mesh Section
        box = layout.box()
        box.label(text="Screw Mesh", icon="MOD_SCREW")
        col = box.column(align=True)
        col.operator("gptools.screw_mesh", text="Screw", icon="MOD_SCREW")
        col.operator(
            "gptools.square_screw_mesh", text="Square Screw", icon="MESH_PLANE"
        )

        # Stamp Scatter Section
        box = layout.box()
        box.label(text="Stamp Scatter", icon="OUTLINER_OB_POINTCLOUD")
        box.operator(
            "gptools.stamp_scatter",
            text="Scatter on Surface",
            icon="OUTLINER_OB_POINTCLOUD",
        )

        # Lattice Wrap Section
        box = layout.box()
        box.label(text="Lattice Wrap", icon="MOD_LATTICE")
        box.prop(props, "lattice_resolution")
        box.operator("gptools.lattice_wrap", text="Lattice Wrap", icon="MOD_LATTICE")

        # Dev Section — only visible when running from a local dev path
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        if "extensions" not in addon_dir:
            box = layout.box()
            box.label(text="Development", icon="SCRIPT")
            box.operator(
                "gptools.reload_addon", text="Reload Addon", icon="FILE_REFRESH"
            )


classes = [
    GPTOOLS_PT_main,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
