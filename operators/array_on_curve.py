import bpy
from mathutils import Vector


def _gp_to_curve(gp_obj):
    """Convert a Grease Pencil object to a Curve object.

    bpy.ops.object.convert(target='CURVE') silently fails on GP v3
    in Blender 5.0, so we build the curve manually from stroke data.

    Spline points are stored in local space relative to the first point.
    The curve object's origin is placed at that first point in world space.
    """
    gp_data = gp_obj.data
    matrix = gp_obj.matrix_world

    # Collect all world-space points per stroke
    all_strokes = []
    for layer in gp_data.layers:
        for frame in layer.frames:
            for stroke in frame.drawing.strokes:
                n = len(stroke.points)
                if n < 2:
                    continue
                pts = []
                for i in range(n):
                    pts.append(Vector(matrix @ stroke.points[i].position))
                all_strokes.append(pts)

    if not all_strokes:
        return None

    # Use the first point of the first stroke as curve origin
    origin = all_strokes[0][0].copy()

    curve_data = bpy.data.curves.new(gp_obj.name + "_Curve", type='CURVE')
    curve_data.dimensions = '3D'

    for pts in all_strokes:
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(pts) - 1)
        for i, world_pos in enumerate(pts):
            local_pos = world_pos - origin
            spline.points[i].co = (local_pos.x, local_pos.y, local_pos.z, 1.0)

    curve_obj = bpy.data.objects.new(gp_obj.name + "_Curve", curve_data)
    curve_obj.location = origin
    for col in gp_obj.users_collection:
        col.objects.link(curve_obj)

    return curve_obj


class GPTOOLS_OT_array_on_curve(bpy.types.Operator):
    """Convert GP to curve, add built-in Array modifier to mesh"""

    bl_idname = "gptools.array_on_curve"
    bl_label = "Array on Curve"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        selected = context.selected_objects
        has_gp = any(o.type == 'GREASEPENCIL' for o in selected)
        has_mesh = any(o.type == 'MESH' for o in selected)
        return has_gp and has_mesh

    def execute(self, context):
        gp_obj = None
        mesh_obj = None
        for obj in context.selected_objects:
            if obj.type == 'GREASEPENCIL' and gp_obj is None:
                gp_obj = obj
            elif obj.type == 'MESH' and mesh_obj is None:
                mesh_obj = obj

        if not gp_obj or not mesh_obj:
            self.report({"ERROR"}, "Select a Grease Pencil and a mesh object")
            return {"CANCELLED"}

        # Convert GP to curve manually
        curve_obj = _gp_to_curve(gp_obj)
        if not curve_obj:
            self.report({"ERROR"}, "No strokes found in Grease Pencil")
            return {"CANCELLED"}

        context.view_layer.update()

        # Hide original GP
        gp_obj.hide_set(True)

        # Select mesh so modifier_add_node_group targets it
        for obj in context.selected_objects:
            obj.select_set(False)
        mesh_obj.select_set(True)
        context.view_layer.objects.active = mesh_obj

        # Add Blender 5.0 built-in Array GN modifier
        bpy.ops.object.modifier_add_node_group(
            asset_library_type='ESSENTIALS',
            asset_library_identifier="",
            relative_asset_identifier="nodes/geometry_nodes_essentials.blend/NodeTree/Array",
        )

        mod = mesh_obj.modifiers.get("Array")
        if not mod:
            self.report({"ERROR"}, "Failed to add Array modifier")
            return {"CANCELLED"}

        # Configure: Shape = Curve, Count Method = Distance, Curve Object = converted GP
        mod["Socket_2"] = 2       # Shape: Curve
        mod["Socket_33"] = 1      # Count Method: Distance
        mod["Socket_27"] = curve_obj  # Curve Object

        # Switch Properties panel to Modifier tab
        try:
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    for space in area.spaces:
                        if space.type == 'PROPERTIES':
                            space.context = 'MODIFIER'
                            break
                    break
        except TypeError:
            pass

        self.report({"INFO"}, f"Array on Curve added to '{mesh_obj.name}'")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_array_on_curve,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
