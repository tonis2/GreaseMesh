import bpy
import math
from ..utils.conversion import get_active_grease_pencil


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

        # Add native Blender Screw modifier
        screw = mesh_obj.modifiers.new(name="Screw", type="SCREW")
        screw.steps = props.screw_segments
        screw.render_steps = props.screw_segments
        screw.axis = props.screw_axis
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

        self.report({"INFO"}, "Screw mesh created.")
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

        # Rotate 45° on Z and scale up to compensate for square shape
        mesh_obj.rotation_euler[2] = math.radians(45)
        mesh_obj.scale[0] = 1.4
        mesh_obj.scale[1] = 1.4

        # Add Screw modifier with 4 steps for square cross-section
        screw = mesh_obj.modifiers.new(name="Screw", type="SCREW")
        screw.steps = 4
        screw.render_steps = 4
        screw.axis = props.screw_axis
        screw.angle = math.tau
        screw.use_merge_vertices = True
        screw.merge_threshold = 0.0001

        # Decimate modifier
        decimate = mesh_obj.modifiers.new(name="Decimate", type="DECIMATE")
        decimate.ratio = 0.5

        # Select and activate
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)

        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))

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
        bpy.utils.unregister_class(cls)
