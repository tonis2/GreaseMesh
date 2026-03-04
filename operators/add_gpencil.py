import bpy


class GPTOOLS_OT_add_gpencil(bpy.types.Operator):
    """Add a new Grease Pencil object and enter Draw mode"""

    bl_idname = "gptools.add_gpencil"
    bl_label = "Add New Grease Pencil"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        bpy.ops.object.grease_pencil_add(type='EMPTY')
        bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_add_gpencil,
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
