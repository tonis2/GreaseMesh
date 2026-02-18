import bpy
import bmesh
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil
from ..modifiers import add_grease_pencil_solidify_modifier


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

        gp_name = gp_obj.name

        # Create mesh preserving Grease Pencil's 3D orientation
        mesh_data = bpy.data.meshes.new(name="GP_Solid_Mesh")
        mesh_obj = bpy.data.objects.new(name="GP_Solid_Mesh", object_data=mesh_data)
        context.collection.objects.link(mesh_obj)

        # Build flat mesh with face
        bm = bmesh.new()

        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.drawing.strokes:
                    if len(stroke.points) < 3:
                        continue

                    points = [pt.position for pt in stroke.points]

                    # Create vertices preserving Grease Pencil's 3D orientation
                    verts = []
                    for pt in points:
                        v = bm.verts.new((pt.x, pt.y, pt.z))
                        verts.append(v)

                    # Create closed edge loop
                    for i in range(len(verts)):
                        v1 = verts[i]
                        v2 = verts[(i + 1) % len(verts)]
                        try:
                            bm.edges.new((v1, v2))
                        except:
                            pass

                    # Create face
                    if len(verts) >= 3:
                        try:
                            bm.faces.new(verts)
                        except:
                            pass

        # Update mesh
        bm.normal_update()
        bm.to_mesh(mesh_data)
        bm.free()
        mesh_data.update()

        # Verify
        if len(mesh_data.polygons) == 0:
            self.report({"ERROR"}, "Failed to create faces")
            return {"CANCELLED"}

        # Add the Solidify and Bevel modifiers (stays live - not applied)
        # User can adjust thickness and roundness in the Modifiers panel
        add_grease_pencil_solidify_modifier(
            mesh_obj, thickness=0.1, bevel_width=0.02, bevel_segments=2
        )

        # Delete original GP
        if gp_name in bpy.data.objects:
            gp_to_delete = bpy.data.objects[gp_name]
            bpy.data.objects.remove(gp_to_delete, do_unlink=True)

        # Select mesh and make active
        mesh_obj.select_set(True)
        context.view_layer.objects.active = mesh_obj

        # Enter Edit Mode
        bpy.ops.object.mode_set(mode="EDIT")

        # Select all vertices
        bpy.ops.mesh.select_all(action="SELECT")

        # Run Merge by Distance - opens popup in bottom-left
        bpy.ops.mesh.remove_doubles()

        # Stay in Edit Mode so user can see the popup and adjust
        self.report({"INFO"}, "Adjust Merge Distance in bottom-left, then press Tab")
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
