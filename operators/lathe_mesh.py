import bpy
import math
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil
from .screw_mesh import build_profile_mesh


class GPTOOLS_OT_lathe_mesh(bpy.types.Operator):
    """Create lathe (revolved) mesh from Grease Pencil — draw half the silhouette, get a round object"""

    bl_idname = "gptools.lathe_mesh"
    bl_label = "Create Lathe Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        gp_name = gp_obj.name

        mesh_obj, mesh_data = build_profile_mesh(context, gp_obj)
        if mesh_obj is None:
            self.report({"ERROR"}, "Need at least 2 points in Grease Pencil")
            return {"CANCELLED"}

        # Collect stroke endpoints from GP before it's deleted
        # (the first and last points of each stroke lie on the centerline)
        matrix = gp_obj.matrix_world
        endpoint_positions = []
        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.drawing.strokes:
                    if len(stroke.points) < 2:
                        continue
                    endpoint_positions.append(tuple(matrix @ stroke.points[0].position))
                    endpoint_positions.append(tuple(matrix @ stroke.points[-1].position))

        # Gather vertex positions for axis detection
        vertices = [tuple(v.co) for v in mesh_data.vertices]

        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        zs = [v[2] for v in vertices]
        spans = [
            (max(xs) - min(xs), 0, "X"),
            (max(ys) - min(ys), 1, "Y"),
            (max(zs) - min(zs), 2, "Z"),
        ]
        spans.sort(key=lambda s: s[0])

        # Smallest span = flat/depth axis (drawing plane normal — ignore)
        # Largest span = revolution axis (e.g. Z for a vertical column)
        # Middle span = radial axis (profile width)
        flat_span, flat_axis, flat_name = spans[0]
        radial_span, radial_axis, radial_name = spans[1]
        rev_span, rev_axis, rev_name = spans[2]

        mins = [min(xs), min(ys), min(zs)]
        maxs = [max(xs), max(ys), max(zs)]

        # Find the centerline (inner edge) using stroke endpoints.
        # When drawing a half-silhouette, the start/end points sit on the
        # centerline — pick the side of the radial axis they're closest to.
        avg_endpoint_radial = sum(p[radial_axis] for p in endpoint_positions) / len(endpoint_positions)
        mid_radial = (mins[radial_axis] + maxs[radial_axis]) / 2
        if avg_endpoint_radial < mid_radial:
            inner_edge_pos = mins[radial_axis]
        else:
            inner_edge_pos = maxs[radial_axis]

        new_origin = [0.0, 0.0, 0.0]
        new_origin[radial_axis] = inner_edge_pos
        new_origin[flat_axis] = (mins[flat_axis] + maxs[flat_axis]) / 2
        new_origin[rev_axis] = (mins[rev_axis] + maxs[rev_axis]) / 2

        origin_vec = Vector(new_origin)
        for v in mesh_data.vertices:
            v.co -= origin_vec
        mesh_data.update()

        mesh_obj.location = origin_vec

        # Add Screw modifier on the revolution axis
        axis_map = {0: "X", 1: "Y", 2: "Z"}
        screw = mesh_obj.modifiers.new(name="Screw", type="SCREW")
        screw.steps = 32
        screw.render_steps = 32
        screw.axis = axis_map[rev_axis]
        screw.angle = math.tau
        screw.use_merge_vertices = True
        screw.merge_threshold = 0.0001

        # Decimate modifier
        decimate = mesh_obj.modifiers.new(name="Decimate", type="DECIMATE")
        decimate.ratio = 0.5

        # Select and activate
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)

        bpy.ops.object.shade_smooth()

        # Delete original GP
        if gp_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[gp_name], do_unlink=True)

        # Switch Properties panel to Modifiers tab
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        space.context = 'MODIFIER'
                        break
                break

        self.report({"INFO"}, f"Lathe mesh created (revolved around {rev_name} axis).")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_lathe_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
