import bpy
import math
from ..utils.conversion import get_active_grease_pencil


class GPTOOLS_OT_screw_mesh(bpy.types.Operator):
    """Create screw (lathe) mesh from Grease Pencil profile"""

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
        axis = props.screw_axis
        segments = props.screw_segments

        # Create mesh from GP strokes
        mesh_data = bpy.data.meshes.new(name="GP_Screw_Mesh")
        mesh_obj = bpy.data.objects.new(name="GP_Screw_Mesh", object_data=mesh_data)
        context.collection.objects.link(mesh_obj)

        # Collect all stroke points
        profile_points = []
        gp_data = gp_obj.data
        for layer in gp_data.layers:
            for frame in layer.frames:
                for stroke in frame.strokes:
                    for pt in stroke.points:
                        profile_points.append(pt.co.copy())

        if len(profile_points) < 2:
            self.report({"ERROR"}, "Need at least 2 points in Grease Pencil")
            return {"CANCELLED"}

        # Generate screw mesh
        vertices = []
        faces = []

        # Create rotation matrix based on axis
        angle_step = 2 * math.pi / segments

        for i in range(segments + 1):
            angle = i * angle_step
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)

            for pt in profile_points:
                if axis == "X":
                    # Rotate around X axis
                    x = pt.x
                    y = pt.y * cos_a - pt.z * sin_a
                    z = pt.y * sin_a + pt.z * cos_a
                elif axis == "Y":
                    # Rotate around Y axis
                    x = pt.x * cos_a + pt.z * sin_a
                    y = pt.y
                    z = -pt.x * sin_a + pt.z * cos_a
                else:  # Z axis
                    # Rotate around Z axis
                    x = pt.x * cos_a - pt.y * sin_a
                    y = pt.x * sin_a + pt.y * cos_a
                    z = pt.z

                vertices.append((x, y, z))

        # Create faces
        profile_len = len(profile_points)
        for i in range(segments):
            for j in range(profile_len - 1):
                v0 = i * profile_len + j
                v1 = i * profile_len + j + 1
                v2 = (i + 1) * profile_len + j + 1
                v3 = (i + 1) * profile_len + j

                faces.append((v0, v1, v2, v3))

        # Create mesh
        mesh_data.from_pydata(vertices, [], faces)
        mesh_data.update()

        # Add smooth shading
        for poly in mesh_data.polygons:
            poly.use_smooth = True

        # Set active
        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)
        gp_obj.select_set(False)

        self.report(
            {"INFO"}, f"Created screw mesh with {segments} segments around {axis} axis"
        )
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_screw_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
