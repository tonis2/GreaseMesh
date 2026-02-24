import bpy


class GPTOOLS_OT_reload_addon(bpy.types.Operator):
    """Reload Grease Mesh addon (for development)"""

    bl_idname = "gptools.reload_addon"
    bl_label = "Reload Grease Mesh"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        bpy.ops.preferences.addon_disable(module="GreaseMesh")

        # Clear cached modules
        import sys
        to_remove = [
            k for k in sys.modules
            if k == "GreaseMesh" or k.startswith("GreaseMesh.")
        ]
        for k in to_remove:
            del sys.modules[k]

        bpy.ops.preferences.addon_enable(module="GreaseMesh")

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
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
