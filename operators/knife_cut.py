import bpy
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil


def _resample_points(pts, count):
    """Resample a list of Vectors to *count* evenly spaced points along the polyline."""
    if count <= 0 or len(pts) < 2:
        return pts
    if count >= len(pts):
        return pts

    # Compute cumulative arc-length
    dists = [0.0]
    for i in range(1, len(pts)):
        dists.append(dists[-1] + (pts[i] - pts[i - 1]).length)
    total = dists[-1]
    if total < 1e-8:
        return pts[:count]

    step = total / count  # not count-1, since the curve is cyclic
    resampled = []
    seg = 0
    for i in range(count):
        target_d = i * step
        while seg < len(dists) - 2 and dists[seg + 1] < target_d:
            seg += 1
        seg_len = dists[seg + 1] - dists[seg]
        t = (target_d - dists[seg]) / seg_len if seg_len > 1e-8 else 0.0
        resampled.append(pts[seg].lerp(pts[seg + 1], t))
    return resampled


def _gp_to_cutter_curve(gp_obj, resolution=0):
    """Convert a Grease Pencil object to a cyclic curve for knife projection.

    Similar to array_on_curve._gp_to_curve but closes each spline
    so the knife cuts a closed shape.

    If *resolution* > 0, each stroke is resampled to that many points.
    """
    gp_data = gp_obj.data
    matrix = gp_obj.matrix_world

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
                if resolution > 0:
                    pts = _resample_points(pts, resolution)
                all_strokes.append(pts)

    if not all_strokes:
        return None

    origin = all_strokes[0][0].copy()

    curve_data = bpy.data.curves.new(gp_obj.name + "_KnifeCurve", type='CURVE')
    curve_data.dimensions = '3D'

    for pts in all_strokes:
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(pts) - 1)
        for i, world_pos in enumerate(pts):
            local_pos = world_pos - origin
            spline.points[i].co = (local_pos.x, local_pos.y, local_pos.z, 1.0)
        spline.use_cyclic_u = True

    curve_obj = bpy.data.objects.new(gp_obj.name + "_KnifeCurve", curve_data)
    curve_obj.location = origin
    for col in gp_obj.users_collection:
        col.objects.link(curve_obj)

    return curve_obj


def _find_target_mesh(context, gp_obj):
    """Find a selected mesh object that isn't the active GP."""
    for obj in context.selected_objects:
        if obj != gp_obj and obj.type == 'MESH':
            return obj
    return None


class GPTOOLS_OT_knife_cut(bpy.types.Operator):
    """Project a GP shape onto a mesh as new edges (like Knife Project)"""

    bl_idname = "gptools.knife_cut"
    bl_label = "Knife Cut"
    bl_options = {"REGISTER", "UNDO"}

    cut_through: bpy.props.BoolProperty(
        name="Cut Through",
        default=False,
        description="Cut through the entire mesh, not just the visible surface",
    )
    resolution: bpy.props.IntProperty(
        name="Resolution",
        default=0,
        min=0,
        max=512,
        description="Resample strokes to this many points (0 = use original points)",
    )

    @classmethod
    def poll(cls, context):
        gp = get_active_grease_pencil(context)
        if gp is None:
            return False
        return any(
            obj != gp and obj.type == 'MESH' for obj in context.selected_objects
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        target = _find_target_mesh(context, gp_obj)

        if not target:
            self.report({"ERROR"}, "No selected mesh object found as cut target")
            return {"CANCELLED"}

        cutter = _gp_to_cutter_curve(gp_obj, self.resolution)
        if not cutter:
            self.report({"ERROR"}, "No strokes found in Grease Pencil")
            return {"CANCELLED"}

        context.view_layer.update()

        # Set up selection state for knife_project:
        # target must be active + in edit mode, cutter must be selected
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')

        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

        cutter.select_set(True)

        # knife_project requires a VIEW_3D region context
        area_3d = None
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area_3d = area
                break

        if area_3d is None:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(cutter, do_unlink=True)
            self.report({"ERROR"}, "No 3D viewport found")
            return {"CANCELLED"}

        region = None
        for r in area_3d.regions:
            if r.type == 'WINDOW':
                region = r
                break

        try:
            with context.temp_override(area=area_3d, region=region):
                bpy.ops.mesh.knife_project(cut_through=self.cut_through)
        except Exception as e:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(cutter, do_unlink=True)
            self.report({"ERROR"}, f"Knife project failed: {e}")
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode='OBJECT')

        # Cleanup: remove cutter curve and GP object
        bpy.data.objects.remove(cutter, do_unlink=True)
        bpy.data.objects.remove(gp_obj, do_unlink=True)

        # Leave target selected and active
        target.select_set(True)
        context.view_layer.objects.active = target

        self.report({"INFO"}, f"Knife cut applied to '{target.name}' — enter Edit mode to see the cut")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_knife_cut,
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
