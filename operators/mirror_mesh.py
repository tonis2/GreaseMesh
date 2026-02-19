import bpy
import math
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil
from ..modifiers import add_solid_mesh_modifiers


class GPTOOLS_OT_mirror_mesh(bpy.types.Operator):
    """Create mirrored solid mesh from Grease Pencil strokes — draw half, get the full shape"""

    bl_idname = "gptools.mirror_mesh"
    bl_label = "Create Mirror Mesh"
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

        # Build edge-only mesh from GP strokes (closed loops)
        mesh_data = bpy.data.meshes.new(name="GP_Mirror_Mesh")
        mesh_obj = bpy.data.objects.new(name="GP_Mirror_Mesh", object_data=mesh_data)
        context.collection.objects.link(mesh_obj)

        vertices = []
        edges = []
        matrix = gp_obj.matrix_world

        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.drawing.strokes:
                    if len(stroke.points) < 3:
                        continue
                    offset = len(vertices)
                    for pt in stroke.points:
                        world_pos = matrix @ pt.position
                        vertices.append(tuple(world_pos))
                    n = len(stroke.points)
                    for i in range(n):
                        edges.append((offset + i, offset + (i + 1) % n))

        if not vertices:
            self.report({"ERROR"}, "No stroke points found")
            bpy.data.objects.remove(mesh_obj, do_unlink=True)
            bpy.data.meshes.remove(mesh_data)
            return {"CANCELLED"}

        mesh_data.from_pydata(vertices, edges, [])
        mesh_data.update()

        # Determine the drawing plane and mirror axis
        # Find the axis with the smallest span (the flat/drawing plane normal)
        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        zs = [v[2] for v in vertices]
        spans = [
            (max(xs) - min(xs), 0, "X"),
            (max(ys) - min(ys), 1, "Y"),
            (max(zs) - min(zs), 2, "Z"),
        ]
        spans.sort(key=lambda s: s[0])

        # The flat axis (smallest span) is the depth/thickness direction
        # The mirror axis is the narrower of the two remaining axes
        flat_span, flat_axis, flat_name = spans[0]
        narrow_span, narrow_axis, narrow_name = spans[1]
        tall_span, tall_axis, tall_name = spans[2]

        # Move origin to the center of the mirror edge
        # (center of the narrow axis, at the min or max — whichever is closer to 0)
        mins = [min(xs), min(ys), min(zs)]
        maxs = [max(xs), max(ys), max(zs)]

        # The mirror edge is on the narrow axis — pick the side FURTHER from world center
        # (the outer edge of the half-profile, so geometry stays on the inner side)
        if abs(mins[narrow_axis]) > abs(maxs[narrow_axis]):
            mirror_edge_pos = mins[narrow_axis]
        else:
            mirror_edge_pos = maxs[narrow_axis]

        # Build the new origin position
        new_origin = [0.0, 0.0, 0.0]
        new_origin[narrow_axis] = mirror_edge_pos
        new_origin[flat_axis] = (mins[flat_axis] + maxs[flat_axis]) / 2
        new_origin[tall_axis] = (mins[tall_axis] + maxs[tall_axis]) / 2

        # Move vertices relative to new origin
        origin_vec = Vector(new_origin)
        for v in mesh_data.vertices:
            v.co -= origin_vec
        mesh_data.update()

        # Set object location to the origin position
        mesh_obj.location = origin_vec

        # Simplify and fill mesh
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.dissolve_limited(angle_limit=math.radians(45))
        bpy.ops.mesh.edge_face_add()
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")

        if len(mesh_data.polygons) == 0:
            self.report({"ERROR"}, "Failed to create faces")
            bpy.data.objects.remove(mesh_obj, do_unlink=True)
            bpy.data.meshes.remove(mesh_data)
            return {"CANCELLED"}

        # Add Mirror modifier on the narrow axis
        mirror = mesh_obj.modifiers.new(name="Mirror", type="MIRROR")
        mirror.use_axis[0] = (narrow_axis == 0)
        mirror.use_axis[1] = (narrow_axis == 1)
        mirror.use_axis[2] = (narrow_axis == 2)
        mirror.use_clip = True
        mirror.merge_threshold = 0.001

        # Add Solidify (and optionally Bevel + Subdiv if Round is enabled)
        add_solid_mesh_modifiers(
            mesh_obj,
            thickness=props.solid_thickness,
            roundness=props.solid_roundness,
            round_edges=props.solid_round,
        )

        # Delete original GP
        if gp_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[gp_name], do_unlink=True)

        # Select result
        mesh_obj.select_set(True)
        context.view_layer.objects.active = mesh_obj

        # Switch Properties panel to Modifiers tab
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        space.context = 'MODIFIER'
                        break
                break

        self.report({"INFO"}, f"Mirror mesh created (mirrored on {narrow_name} axis).")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_mirror_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
