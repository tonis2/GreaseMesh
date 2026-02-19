import bpy
from ..utils.conversion import get_active_grease_pencil
from ..modifiers import add_solid_mesh_modifiers


class GPTOOLS_OT_solid_mesh(bpy.types.Operator):
    """Create solid mesh from Grease Pencil strokes with Solidify modifier"""

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

        props = context.scene.gptools
        gp_name = gp_obj.name

        # Build edge-only mesh from GP strokes (closed loops)
        mesh_data = bpy.data.meshes.new(name="GP_Solid_Mesh")
        mesh_obj = bpy.data.objects.new(name="GP_Solid_Mesh", object_data=mesh_data)
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

        # Fill faces using Blender's fill algorithm
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.dissolve_limited(angle_limit=0.000001)
        bpy.ops.mesh.edge_face_add()
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")

        if len(mesh_data.polygons) == 0:
            self.report({"ERROR"}, "Failed to create faces")
            bpy.data.objects.remove(mesh_obj, do_unlink=True)
            bpy.data.meshes.remove(mesh_data)
            return {"CANCELLED"}

        # Add modifier stack (Solidify + Bevel + Subdiv)
        add_solid_mesh_modifiers(
            mesh_obj,
            thickness=props.solid_thickness,
            roundness=props.solid_roundness,
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

        self.report({"INFO"}, "Solid mesh created. Adjust modifiers in Properties panel.")
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
