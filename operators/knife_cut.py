import bpy
from mathutils import Vector
from ..utils.conversion import (
    get_active_grease_pencil,
    clean_gp_for_cutter,
    remove_cleanup_duplicate,
    walk_strokes_into_loop,
)


def _resample_loop(pts, count):
    """Resample a closed polyline (list of Vectors) to *count* evenly spaced points."""
    if count <= 0 or len(pts) < 2:
        return pts
    if count >= len(pts):
        return pts

    dists = [0.0]
    for i in range(1, len(pts)):
        dists.append(dists[-1] + (pts[i] - pts[i - 1]).length)
    total = dists[-1]
    if total < 1e-8:
        return pts[:count]

    step = total / count  # cyclic — divide by count, not count-1
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
    """Convert a Grease Pencil object to a single cyclic curve for knife projection.

    Strokes are first cleaned (stubs dropped, open endpoints bridged) on a
    throwaway duplicate so the user's drawing isn't mutated. Remaining strokes
    are walked into one ordered loop, which becomes a single cyclic POLY spline.
    This makes multi-stroke shapes (e.g. a doorway drawn as arch + sides + floor)
    project as one connected outline rather than several independent loops.
    """
    cleaned_gp = clean_gp_for_cutter(gp_obj)
    try:
        strokes_pts = []
        mw = cleaned_gp.matrix_world
        for layer in cleaned_gp.data.layers:
            for frame in layer.frames:
                for stroke in frame.drawing.strokes:
                    if len(stroke.points) < 2:
                        continue
                    strokes_pts.append([Vector(mw @ p.position) for p in stroke.points])
                break  # first frame only
            break  # first layer only

        loop = walk_strokes_into_loop([list(s) for s in strokes_pts])
    finally:
        remove_cleanup_duplicate(cleaned_gp)

    if len(loop) < 3:
        return None

    loop = [Vector(p) for p in loop]
    if resolution > 0:
        loop = _resample_loop(loop, resolution)

    origin = loop[0].copy()

    curve_data = bpy.data.curves.new(gp_obj.name + "_KnifeCurve", type='CURVE')
    curve_data.dimensions = '3D'

    spline = curve_data.splines.new('POLY')
    spline.points.add(len(loop) - 1)
    for i, world_pos in enumerate(loop):
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
        description="Resample the combined loop to this many points (0 = use original points)",
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
            self.report({"ERROR"}, "No usable strokes found in Grease Pencil")
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
