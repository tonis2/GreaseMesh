import bpy
from .. import reload_modules


class GPTOOLS_OT_reload_addon(bpy.types.Operator):
    """Reload Grease Mesh addon (for development)"""

    bl_idname = "gptools.reload_addon"
    bl_label = "Reload Grease Mesh"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        # Reload all modules
        reload_modules()

        self.report({"INFO"}, "Grease Mesh addon reloaded")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_reload_addon,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
