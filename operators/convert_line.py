import bpy
from ..utils.conversion import get_active_grease_pencil


class GPTOOLS_OT_convert_line(bpy.types.Operator):
    """Convert Grease Pencil to simple line representation"""

    bl_idname = "gptools.convert_line"
    bl_label = "GP to Line"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        # Create mesh
        mesh_data = bpy.data.meshes.new(name="GP_Line")
        line_obj = bpy.data.objects.new(name="GP_Line", object_data=mesh_data)
        context.collection.objects.link(line_obj)

        # Convert all strokes to single continuous line
        vertices = []
        edges = []

        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.drawing.strokes:
                    if len(stroke.points) > 0:
                        stroke_start = len(vertices)
                        for i, pt in enumerate(stroke.points):
                            vertices.append(pt.position)
                            if i > 0:
                                edges.append((stroke_start + i - 1, stroke_start + i))

        # Create mesh from data
        mesh_data.from_pydata(vertices, edges, [])
        mesh_data.update()

        # Set active
        context.view_layer.objects.active = line_obj
        line_obj.select_set(True)
        gp_obj.select_set(False)

        self.report({"INFO"}, f"Converted to Line with {len(vertices)} points")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_convert_line,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
