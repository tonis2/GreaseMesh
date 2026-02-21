import bpy
import random
from mathutils import Vector


def calculate_x_mark_centers(gp_obj):
    """Calculate bounding box centers for each X mark from GP strokes.

    Converts local GP coordinates to world space.
    """
    centers = []

    # Get GP object's world matrix for coordinate transformation
    gp_matrix = gp_obj.matrix_world

    for layer in gp_obj.data.layers:
        for frame in layer.frames:
            strokes = frame.drawing.strokes

            # Process strokes in pairs (each X is 2 strokes)
            for i in range(0, len(strokes), 2):
                if i + 1 < len(strokes):
                    stroke1 = strokes[i]
                    stroke2 = strokes[i + 1]

                    # Get all points from both strokes and transform to world space
                    all_points = []
                    for pt in stroke1.points:
                        # Transform from local to world space
                        world_pos = gp_matrix @ Vector(pt.position)
                        all_points.append(world_pos)
                    for pt in stroke2.points:
                        # Transform from local to world space
                        world_pos = gp_matrix @ Vector(pt.position)
                        all_points.append(world_pos)

                    if all_points:
                        # Calculate bounding box center in world space
                        min_x = min(p.x for p in all_points)
                        max_x = max(p.x for p in all_points)
                        min_y = min(p.y for p in all_points)
                        max_y = max(p.y for p in all_points)
                        min_z = min(p.z for p in all_points)
                        max_z = max(p.z for p in all_points)

                        center = Vector(
                            (
                                (min_x + max_x) / 2,
                                (min_y + max_y) / 2,
                                (min_z + max_z) / 2,
                            )
                        )

                        centers.append(center)

    return centers


class GPTOOLS_OT_stamp_scatter(bpy.types.Operator):
    """Scatter assets from a collection based on Grease Pencil X marks.

    Creates instances at X mark centers. Instances remain separate from the ground
    mesh and preserve their materials.
    """

    bl_idname = "gptools.stamp_scatter"
    bl_label = "Stamp Scatter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # Need both a mesh and a Grease Pencil in selection
        has_mesh = False
        has_gp = False

        for obj in context.selected_objects:
            if obj.type == "MESH":
                has_mesh = True
            elif obj.type == "GREASEPENCIL":
                has_gp = True

        if not has_mesh or not has_gp:
            return False

        # Also need an asset collection selected
        if not context.scene.gptools.stamp_collection:
            return False

        return True

    def execute(self, context):
        props = context.scene.gptools

        # Find mesh and GP from selected objects
        mesh_obj = None
        gp_obj = None

        for obj in context.selected_objects:
            if obj.type == "MESH" and not mesh_obj:
                mesh_obj = obj
            elif obj.type == "GREASEPENCIL" and not gp_obj:
                gp_obj = obj

        if not mesh_obj:
            self.report({"ERROR"}, "No mesh object found in selection")
            return {"CANCELLED"}

        if not gp_obj:
            self.report({"ERROR"}, "No Grease Pencil found in selection")
            return {"CANCELLED"}

        # Get collection
        coll = props.stamp_collection
        if not coll:
            self.report({"ERROR"}, "Please select an asset collection")
            return {"CANCELLED"}

        # Get mesh objects from collection
        coll_objects = [obj for obj in coll.objects if obj.type == "MESH"]
        if not coll_objects:
            self.report({"ERROR"}, "No mesh objects found in collection")
            return {"CANCELLED"}

        # Calculate X mark centers
        x_centers = calculate_x_mark_centers(gp_obj)

        if not x_centers:
            self.report({"ERROR"}, "No X marks found in Grease Pencil")
            return {"CANCELLED"}

        # Create instances at X mark centers
        instances = []

        for i, center in enumerate(x_centers):
            # Pick random object from collection
            source_obj = random.choice(coll_objects)

            # Create instance (copy of object)
            new_obj = source_obj.copy()
            new_obj.data = source_obj.data.copy()

            # Position at X mark center
            new_obj.location = center

            # Apply scale
            new_obj.scale = (props.stamp_scale, props.stamp_scale, props.stamp_scale)

            # Random rotation around Z
            random_rot = random.uniform(-3.14159, 3.14159)
            new_obj.rotation_euler = (0, 0, random_rot)

            # Parent to target mesh (keeps them organized but separate)
            new_obj.parent = mesh_obj
            new_obj.parent_type = "OBJECT"

            # Link to scene
            context.scene.collection.objects.link(new_obj)
            instances.append(new_obj)

        # Report success
        self.report(
            {"INFO"},
            f"Stamp scatter complete! Created {len(instances)} instances from '{coll.name}' at X mark centers.",
        )

        return {"FINISHED"}


class GPTOOLS_OT_stamp_scatter_selected(bpy.types.Operator):
    """Quick scatter using the selected collection"""

    bl_idname = "gptools.stamp_scatter_selected"
    bl_label = "Scatter Selected Collection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        has_collection = False
        if context.selected_ids:
            for item in context.selected_ids:
                if isinstance(item, bpy.types.Collection):
                    has_collection = True
                    break

        has_mesh = False
        has_gp = False
        for obj in context.selected_objects:
            if obj.type == "MESH":
                has_mesh = True
            elif obj.type == "GREASEPENCIL":
                has_gp = True

        return has_mesh and has_gp and has_collection

    def execute(self, context):
        # Find mesh and GP
        mesh_obj = None
        gp_obj = None

        for obj in context.selected_objects:
            if obj.type == "MESH" and not mesh_obj:
                mesh_obj = obj
            elif obj.type == "GREASEPENCIL" and not gp_obj:
                gp_obj = obj

        # Get collection
        coll = None
        for item in context.selected_ids:
            if isinstance(item, bpy.types.Collection):
                coll = item
                break

        if not mesh_obj or not gp_obj or not coll:
            self.report({"ERROR"}, "Need mesh, GP, and collection selected")
            return {"CANCELLED"}

        # Get mesh objects
        coll_objects = [obj for obj in coll.objects if obj.type == "MESH"]
        if not coll_objects:
            self.report({"ERROR"}, "No mesh objects in collection")
            return {"CANCELLED"}

        # Calculate centers
        x_centers = calculate_x_mark_centers(gp_obj)

        if not x_centers:
            self.report({"ERROR"}, "No X marks found")
            return {"CANCELLED"}

        # Create instances
        instances = []
        for center in x_centers:
            source_obj = random.choice(coll_objects)
            new_obj = source_obj.copy()
            new_obj.data = source_obj.data.copy()
            new_obj.location = center
            new_obj.parent = mesh_obj
            new_obj.parent_type = "OBJECT"
            context.scene.collection.objects.link(new_obj)
            instances.append(new_obj)

        self.report(
            {"INFO"}, f"Stamp scatter complete! {len(instances)} instances created."
        )
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_stamp_scatter,
    GPTOOLS_OT_stamp_scatter_selected,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
