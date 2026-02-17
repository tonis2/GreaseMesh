import bpy
from ..utils.conversion import get_active_grease_pencil


class GPTOOLS_OT_convert_mesh(bpy.types.Operator):
    """Convert Grease Pencil strokes to a Mesh object"""

    bl_idname = "gptools.convert_mesh"
    bl_label = "GP to Mesh"
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
        mesh_data = bpy.data.meshes.new(name="GP_Mesh")
        mesh_obj = bpy.data.objects.new(name="GP_Mesh", object_data=mesh_data)
        context.collection.objects.link(mesh_obj)

        # Convert strokes to mesh edges
        vertices = []
        edges = []
        vertex_offset = 0

        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.strokes:
                    stroke_start = len(vertices)
                    for i, pt in enumerate(stroke.points):
                        vertices.append(pt.co)
                        if i > 0:
                            edges.append((stroke_start + i - 1, stroke_start + i))

        # Create mesh from data
        mesh_data.from_pydata(vertices, edges, [])
        mesh_data.update()

        # Set active
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)
        gp_obj.select_set(False)

        self.report(
            {"INFO"},
            f"Converted to Mesh with {len(vertices)} vertices, {len(edges)} edges",
        )
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_convert_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
