import bpy
import bmesh
from ..utils.conversion import get_active_grease_pencil


class GPTOOLS_OT_solid_mesh(bpy.types.Operator):
    """Create solid mesh from Grease Pencil strokes using extrusion"""

    bl_idname = "gptools.solid_mesh"
    bl_label = "Create Solid Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        thickness = context.scene.gptools.solid_thickness

        # First convert GP to curve for better control
        curve_data = bpy.data.curves.new(name="GP_Solid_Curve", type="CURVE")
        curve_data.dimensions = "3D"
        curve_data.bevel_depth = thickness / 2
        curve_data.bevel_resolution = 4
        curve_data.use_fill_caps = True

        curve_obj = bpy.data.objects.new(name="GP_Solid_Curve", object_data=curve_data)
        context.collection.objects.link(curve_obj)

        # Convert strokes to Bezier splines
        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.strokes:
                    spline = curve_data.splines.new("BEZIER")
                    spline.bezier_points.add(len(stroke.points) - 1)

                    for i, pt in enumerate(stroke.points):
                        bp = spline.bezier_points[i]
                        bp.co = pt.co
                        bp.handle_left = pt.co
                        bp.handle_right = pt.co

        # Convert curve to mesh
        context.view_layer.objects.active = curve_obj
        bpy.ops.object.convert(target="MESH")
        mesh_obj = context.active_object
        mesh_obj.name = "GP_Solid_Mesh"

        # Clean up and make manifold if needed
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles()
        bpy.ops.object.mode_set(mode="OBJECT")

        # Deselect GP, select new mesh
        gp_obj.select_set(False)
        mesh_obj.select_set(True)

        self.report({"INFO"}, f"Created solid mesh with thickness {thickness}")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_solid_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
