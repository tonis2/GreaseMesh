import bpy
from ..utils.conversion import get_active_grease_pencil, gpencil_to_points


class GPTOOLS_OT_convert_curve(bpy.types.Operator):
    """Convert Grease Pencil strokes to a Bezier Curve"""

    bl_idname = "gptools.convert_curve"
    bl_label = "GP to Curve"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        # Create curve
        curve_data = bpy.data.curves.new(name="GP_Curve", type="CURVE")
        curve_data.dimensions = "3D"
        curve_obj = bpy.data.objects.new(name="GP_Curve", object_data=curve_data)
        context.collection.objects.link(curve_obj)

        # Convert strokes to Bezier splines
        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.drawing.strokes:
                    spline = curve_data.splines.new("BEZIER")
                    spline.bezier_points.add(len(stroke.points) - 1)

                    for i, pt in enumerate(stroke.points):
                        bp = spline.bezier_points[i]
                        bp.co = pt.position
                        bp.handle_left = pt.position
                        bp.handle_right = pt.position

        # Set active
        context.view_layer.objects.active = curve_obj
        curve_obj.select_set(True)
        gp_obj.select_set(False)

        self.report(
            {"INFO"}, f"Converted to Curve with {len(curve_data.splines)} splines"
        )
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_convert_curve,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
