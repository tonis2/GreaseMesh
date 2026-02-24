import bpy
import math
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil


def detect_revolution_axis(mesh_data, gp_obj):
    """Auto-detect the revolution axis from vertex spans.
    Largest span = revolution axis, middle = radial, smallest = flat/depth.
    Also moves the origin to the inner edge (centerline) on the radial axis."""
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

    flat_span, flat_axis, flat_name = spans[0]
    radial_span, radial_axis, radial_name = spans[1]
    rev_span, rev_axis, rev_name = spans[2]

    # Find the inner edge using stroke endpoints (centerline detection)
    matrix = gp_obj.matrix_world
    endpoint_positions = []
    for layer in gp_obj.data.layers:
        for frame in layer.frames:
            for stroke in frame.drawing.strokes:
                if len(stroke.points) < 2:
                    continue
                endpoint_positions.append(tuple(matrix @ stroke.points[0].position))
                endpoint_positions.append(tuple(matrix @ stroke.points[-1].position))

    mins = [min(xs), min(ys), min(zs)]
    maxs = [max(xs), max(ys), max(zs)]

    if endpoint_positions:
        avg_endpoint_radial = sum(p[radial_axis] for p in endpoint_positions) / len(endpoint_positions)
        mid_radial = (mins[radial_axis] + maxs[radial_axis]) / 2
        if avg_endpoint_radial < mid_radial:
            inner_edge_pos = mins[radial_axis]
        else:
            inner_edge_pos = maxs[radial_axis]
    else:
        if abs(mins[radial_axis]) < abs(maxs[radial_axis]):
            inner_edge_pos = mins[radial_axis]
        else:
            inner_edge_pos = maxs[radial_axis]

    # Move origin to inner edge on radial axis, centered on other axes
    new_origin = [0.0, 0.0, 0.0]
    new_origin[radial_axis] = inner_edge_pos
    new_origin[flat_axis] = (mins[flat_axis] + maxs[flat_axis]) / 2
    new_origin[rev_axis] = (mins[rev_axis] + maxs[rev_axis]) / 2

    origin_vec = Vector(new_origin)
    for v in mesh_data.vertices:
        v.co -= origin_vec
    mesh_data.update()

    return rev_name, origin_vec


def build_profile_mesh(context, gp_obj):
    """Build edge-only profile mesh from GP strokes. Returns (mesh_obj, mesh_data) or (None, None)."""
    mesh_data = bpy.data.meshes.new(name="GP_Screw_Mesh")
    mesh_obj = bpy.data.objects.new(name="GP_Screw_Mesh", object_data=mesh_data)
    context.collection.objects.link(mesh_obj)

    vertices = []
    edges = []
    matrix = gp_obj.matrix_world

    gp_data = gp_obj.data
    for layer in gp_data.layers:
        for frame in layer.frames:
            for stroke in frame.drawing.strokes:
                if len(stroke.points) < 2:
                    continue
                offset = len(vertices)
                for pt in stroke.points:
                    world_pos = matrix @ pt.position
                    vertices.append(tuple(world_pos))
                n = len(stroke.points)
                for i in range(n - 1):
                    edges.append((offset + i, offset + i + 1))

    if len(vertices) < 2:
        bpy.data.objects.remove(mesh_obj, do_unlink=True)
        bpy.data.meshes.remove(mesh_data)
        return None, None

    mesh_data.from_pydata(vertices, edges, [])
    mesh_data.update()
    return mesh_obj, mesh_data


class GPTOOLS_OT_screw_mesh(bpy.types.Operator):
    """Create screw (lathe) mesh from Grease Pencil profile using Screw modifier"""

    bl_idname = "gptools.screw_mesh"
    bl_label = "Create Screw Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        props = context.scene.gptools
        gp_name = gp_obj.name

        mesh_obj, mesh_data = build_profile_mesh(context, gp_obj)
        if mesh_obj is None:
            self.report({"ERROR"}, "Need at least 2 points in Grease Pencil")
            return {"CANCELLED"}

        # Auto-detect revolution axis and move origin to centerline
        detected_axis, origin_vec = detect_revolution_axis(mesh_data, gp_obj)
        mesh_obj.location = origin_vec

        # Add native Blender Screw modifier
        screw = mesh_obj.modifiers.new(name="Screw", type="SCREW")
        screw.steps = props.screw_segments
        screw.render_steps = props.screw_segments
        screw.axis = detected_axis
        screw.angle = math.tau
        screw.use_merge_vertices = True
        screw.merge_threshold = 0.0001

        # Decimate modifier
        decimate = mesh_obj.modifiers.new(name="Decimate", type="DECIMATE")
        decimate.ratio = 0.5

        # Select and activate
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)


        # Delete original GP
        if gp_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[gp_name], do_unlink=True)

        # Switch Properties panel to Modifiers tab
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

        self.report({"INFO"}, f"Screw mesh created (axis: {detected_axis}).")
        return {"FINISHED"}


class GPTOOLS_OT_square_screw_mesh(bpy.types.Operator):
    """Create square screw (lathe) mesh from Grease Pencil profile"""

    bl_idname = "gptools.square_screw_mesh"
    bl_label = "Create Square Screw Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        props = context.scene.gptools
        gp_name = gp_obj.name

        mesh_obj, mesh_data = build_profile_mesh(context, gp_obj)
        if mesh_obj is None:
            self.report({"ERROR"}, "Need at least 2 points in Grease Pencil")
            return {"CANCELLED"}

        # Auto-detect revolution axis and move origin to centerline
        detected_axis, origin_vec = detect_revolution_axis(mesh_data, gp_obj)
        mesh_obj.location = origin_vec

        # Rotate 45° on Z and scale up to compensate for square shape
        mesh_obj.rotation_euler[2] = math.radians(45)
        mesh_obj.scale[0] = 1.4
        mesh_obj.scale[1] = 1.4

        # Add Screw modifier with 4 steps for square cross-section
        screw = mesh_obj.modifiers.new(name="Screw", type="SCREW")
        screw.steps = 4
        screw.render_steps = 4
        screw.axis = detected_axis
        screw.angle = math.tau
        screw.use_merge_vertices = True
        screw.merge_threshold = 0.0001

        # Decimate modifier
        decimate = mesh_obj.modifiers.new(name="Decimate", type="DECIMATE")
        decimate.ratio = 0.5

        # Select and activate
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)


        # Delete original GP
        if gp_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[gp_name], do_unlink=True)

        # Switch Properties panel to Modifiers tab
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

        self.report({"INFO"}, "Square screw mesh created.")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_screw_mesh,
    GPTOOLS_OT_square_screw_mesh,
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
