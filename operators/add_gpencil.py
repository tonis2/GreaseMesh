import bpy
from ..utils.conversion import get_active_grease_pencil


class GPTOOLS_OT_add_gpencil(bpy.types.Operator):
    """Add a new Grease Pencil object to the scene"""

    bl_idname = "gptools.add_gpencil"
    bl_label = "Add New Grease Pencil"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # Create new grease pencil object
        gp_data = bpy.data.grease_pencils.new(name="Grease Pencil")
        gp_obj = bpy.data.objects.new(name="Grease Pencil", object_data=gp_data)
        context.collection.objects.link(gp_obj)

        # Create a default layer and frame
        layer = gp_data.layers.new(name="Lines")
        frame = layer.frames.new(context.scene.frame_current)

        # Add a black material
        mat = bpy.data.materials.new(name="GP_Black")
        bpy.data.materials.create_gpencil_data(mat)
        mat.grease_pencil.color = (0.0, 0.0, 0.0, 1.0)
        gp_data.materials.append(mat)

        # Set as active object
        context.view_layer.objects.active = gp_obj
        gp_obj.select_set(True)

        # Enter draw mode for immediate drawing
        if context.mode != 'PAINT_GREASE_PENCIL':
            bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')

        # Set brush strength
        brush = context.tool_settings.gpencil_paint.brush
        if brush:
            brush.gpencil_settings.pen_strength = 0.9

        self.report({"INFO"}, "Added new Grease Pencil - ready to draw!")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_add_gpencil,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
