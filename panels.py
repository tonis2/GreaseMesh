import bpy
from .operators.gn_path_mesh import get_stage
from .operators.edit_drawing import get_edit_layer, is_greasemesh_gp
from .utils.conversion import get_active_grease_pencil


class GPTOOLS_PT_main(bpy.types.Panel):
    bl_label = "GMesh"
    bl_idname = "GPTOOLS_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GMesh"

    def draw(self, context):
        layout = self.layout

        gp_obj = get_active_grease_pencil(context)
        stage = get_stage(gp_obj)
        if stage is not None:
            self._draw_path_steps(layout, stage)
        elif is_greasemesh_gp(gp_obj):
            self._draw_edit_drawing(layout, gp_obj)

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
        grid = box.grid_flow(row_major=True, columns=2, align=False)
        grid.operator("gptools.gn_solid_mesh", text="Solid", icon="MOD_SOLIDIFY")
        grid.operator("gptools.gn_mirror_mesh", text="Mirror", icon="MOD_MIRROR")
        grid.operator("gptools.gn_path_mesh", text="Path", icon="MOD_CURVE")
        grid.operator("gptools.gn_blocks_mesh", text="Blocks", icon="MOD_ARRAY")
        grid.operator("gptools.gn_wall_mesh", text="Wall", icon="MOD_BUILD")
        grid.operator("gptools.gn_stroke_mesh", text="Stroke", icon="STROKE")
        grid.operator("gptools.gn_scatter", text="Scatter", icon="OUTLINER_OB_POINTCLOUD")

        # Screw Mesh Section
        box = layout.box()
        box.label(text="Screw Mesh", icon="MOD_SCREW")
        col = box.column(align=True)
        col.operator("gptools.screw_mesh", text="Screw", icon="MOD_SCREW")

        # Other Section
        box = layout.box()
        box.label(text="Other", icon="TOOL_SETTINGS")
        grid = box.grid_flow(row_major=True, columns=2, align=False)
        grid.operator("gptools.bool_cut", text="Bool Cut", icon="MOD_BOOLEAN")
        grid.operator("gptools.array_on_curve", text="Array on Pencil", icon="MOD_ARRAY")
        grid.operator("gptools.knife_cut", text="Knife", icon="MOD_EDGESPLIT")
        grid.operator("gptools.bind_to_surface", text="Bind to Surface", icon="ARMATURE_DATA")

    def _draw_path_steps(self, layout, stage):
        box = layout.box()
        box.alert = True
        if stage == 'PATH':
            box.label(text="Path Mesh  1/2", icon="MOD_CURVE")
            box.label(text="Draw the path to sweep along")
            next_text, next_icon = "Next", "FORWARD"
        else:
            box.label(text="Path Mesh  2/2", icon="MOD_CURVE")
            box.label(text="Draw one or more profiles across the path")
            next_text, next_icon = "Done", "CHECKMARK"
        row = box.row(align=True)
        row.scale_y = 1.4
        row.alert = False
        row.operator("gptools.gn_path_next", text=next_text, icon=next_icon)
        row.operator("gptools.gn_path_cancel", text="", icon="X")

    def _draw_edit_drawing(self, layout, gp_obj):
        editing = get_edit_layer(gp_obj)
        box = layout.box()
        box.alert = editing is not None
        box.label(text="Edit Drawing", icon="GREASEPENCIL")
        grid = box.grid_flow(row_major=True, columns=2, align=True)
        grid.alert = False
        for layer in gp_obj.data.layers:
            grid.operator(
                "gptools.edit_drawing", text=layer.name,
                depress=(layer.name == editing),
            ).layer = layer.name
        if editing is not None:
            row = box.row()
            row.scale_y = 1.4
            row.alert = False
            row.operator("gptools.edit_drawing_done", text="Done", icon="CHECKMARK")


classes = [
    GPTOOLS_PT_main,
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
