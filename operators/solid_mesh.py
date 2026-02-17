import bpy
import bmesh
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil
from ..modifiers import add_grease_pencil_solidify_modifier


class GPTOOLS_OT_solid_mesh(bpy.types.Operator):
    """Create solid mesh from Grease Pencil strokes with Grease Pencil Solidify modifier"""

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

        # Create flat mesh from GP strokes
        mesh_data = bpy.data.meshes.new(name="GP_Solid_Mesh")
        mesh_obj = bpy.data.objects.new(name="GP_Solid_Mesh", object_data=mesh_data)
        context.collection.objects.link(mesh_obj)

        # Build flat mesh with filled face from strokes
        bm = bmesh.new()
        
        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.drawing.strokes:
                    if len(stroke.points) < 3:
                        continue
                    
                    points = [pt.position for pt in stroke.points]
                    
                    # Create vertices for the stroke (flat, at z=0)
                    verts = []
                    for pt in points:
                        v = bm.verts.new((pt.x, pt.y, 0))
                        verts.append(v)
                    
                    # Create edges to form a closed loop
                    edges = []
                    for i in range(len(verts)):
                        v1 = verts[i]
                        v2 = verts[(i + 1) % len(verts)]  # Wrap around to close
                        try:
                            e = bm.edges.new((v1, v2))
                            edges.append(e)
                        except:
                            pass
                    
                    # Fill the face (CRITICAL!)
                    if len(verts) >= 3:
                        try:
                            face = bm.faces.new(verts)
                            # Ensure face is valid
                            face.normal_update()
                        except Exception as e:
                            print(f"Could not create face: {e}")
                            # Try simpler triangulation
                            try:
                                # Create fan triangulation from first vertex
                                for i in range(1, len(verts) - 1):
                                    bm.faces.new((verts[0], verts[i], verts[i + 1]))
                            except:
                                pass

        # Ensure the mesh has faces
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        print(f"Created mesh with {len(bm.verts)} verts, {len(bm.edges)} edges, {len(bm.faces)} faces")
        
        # Update mesh
        bm.normal_update()
        bm.to_mesh(mesh_data)
        bm.free()
        
        mesh_data.update()
        
        # Verify we have faces
        if len(mesh_data.polygons) == 0:
            self.report({"ERROR"}, "Failed to create faces - need closed loop")
            return {"CANCELLED"}

        # Add the Grease Pencil Solidify modifier
        add_grease_pencil_solidify_modifier(mesh_obj)

        # Delete the original Grease Pencil
        if gp_name in bpy.data.objects:
            gp_to_delete = bpy.data.objects[gp_name]
            bpy.data.objects.remove(gp_to_delete, do_unlink=True)

        # Select the new mesh
        mesh_obj.select_set(True)
        context.view_layer.objects.active = mesh_obj

        self.report({"INFO"}, f"Created solid mesh with {len(mesh_data.polygons)} face(s) - adjust settings in Modifiers panel")
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
