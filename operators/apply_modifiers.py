import bpy


class GPTOOLS_OT_apply_all_modifiers(bpy.types.Operator):
    """Apply all modifiers on the active object"""

    bl_idname = "gptools.apply_all_modifiers"
    bl_label = "Apply All Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and len(obj.modifiers) > 0

    def execute(self, context):
        obj = context.active_object
        count = 0

        for modifier in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
                count += 1
            except Exception as e:
                self.report({"WARNING"}, f"Could not apply '{modifier.name}': {e}")

        self.report({"INFO"}, f"Applied {count} modifier(s)")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_apply_all_modifiers,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
