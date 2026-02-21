import bpy
import math
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil

NODE_GROUP_NAME = "GreaseMesh_StampScatter"


def _compute_x_mark_centers(gp_obj, merge_distance):
    """Compute AABB centers of X marks from GP strokes.

    1. Get the centroid of each stroke (world space)
    2. Group nearby centroids within merge_distance (X = 2 close strokes)
    3. For each group, compute AABB of ALL points across its strokes
    4. Return the AABB center of each group
    """
    gp_matrix = gp_obj.matrix_world

    # Collect per-stroke data: centroid + all world-space points
    strokes_data = []
    for layer in gp_obj.data.layers:
        for frame in layer.frames:
            for stroke in frame.drawing.strokes:
                if len(stroke.points) == 0:
                    continue
                world_pts = [gp_matrix @ Vector(pt.position) for pt in stroke.points]
                centroid = Vector((0, 0, 0))
                for p in world_pts:
                    centroid += p
                centroid /= len(world_pts)
                strokes_data.append((centroid, world_pts))

    if not strokes_data:
        return []

    # Group strokes by centroid proximity
    used = [False] * len(strokes_data)
    groups = []
    for i in range(len(strokes_data)):
        if used[i]:
            continue
        group = [i]
        used[i] = True
        for j in range(i + 1, len(strokes_data)):
            if used[j]:
                continue
            if (strokes_data[i][0] - strokes_data[j][0]).length <= merge_distance:
                group.append(j)
                used[j] = True
        groups.append(group)

    # For each group, compute AABB center from all points
    centers = []
    for group in groups:
        all_pts = []
        for idx in group:
            all_pts.extend(strokes_data[idx][1])

        min_v = Vector((min(p.x for p in all_pts),
                         min(p.y for p in all_pts),
                         min(p.z for p in all_pts)))
        max_v = Vector((max(p.x for p in all_pts),
                         max(p.y for p in all_pts),
                         max(p.z for p in all_pts)))
        centers.append((min_v + max_v) / 2)

    return centers


def get_or_create_instance_node_group():
    """GN group that instances a collection at each vertex of the input mesh.

    Pipeline:
      Mesh vertices → InstanceOnPoints (random pick from collection)
        → RotateInstances (random Z) → ScaleInstances → Output
    """
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        return ng

    ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

    # Interface sockets
    ng.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry',
    )

    ng.interface.new_socket(
        name="Collection", in_out='INPUT', socket_type='NodeSocketCollection',
    )

    scale_sock = ng.interface.new_socket(
        name="Scale", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    scale_sock.default_value = 1.0
    scale_sock.min_value = 0.01
    scale_sock.max_value = 10.0

    seed_sock = ng.interface.new_socket(
        name="Seed", in_out='INPUT', socket_type='NodeSocketInt',
    )
    seed_sock.default_value = 0
    seed_sock.min_value = 0
    seed_sock.max_value = 10000

    ng.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry',
    )

    # --- Nodes ---
    x = -600
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (x, 0)

    # Collection Info
    x += 200
    coll_info = ng.nodes.new('GeometryNodeCollectionInfo')
    coll_info.location = (x, -300)
    coll_info.transform_space = 'RELATIVE'
    coll_info.inputs['Separate Children'].default_value = True
    coll_info.inputs['Reset Children'].default_value = True

    # Index for per-point randomization
    index_node = ng.nodes.new('GeometryNodeInputIndex')
    index_node.location = (x, -150)

    # Random integer for picking which collection object
    rand_pick = ng.nodes.new('FunctionNodeRandomValue')
    rand_pick.location = (x + 100, -200)
    rand_pick.data_type = 'INT'
    rand_pick.inputs[4].default_value = 0      # Min (INT)
    rand_pick.inputs[5].default_value = 99999  # Max (INT, wraps via modulo)

    # Instance on Points
    x += 200
    inst_on_pts = ng.nodes.new('GeometryNodeInstanceOnPoints')
    inst_on_pts.location = (x, 0)
    inst_on_pts.inputs['Pick Instance'].default_value = True

    # Seed + 1 for different random stream for rotation
    seed_offset = ng.nodes.new('ShaderNodeMath')
    seed_offset.location = (x, -400)
    seed_offset.operation = 'ADD'
    seed_offset.inputs[1].default_value = 1

    # Random float for Z rotation
    rand_rot = ng.nodes.new('FunctionNodeRandomValue')
    rand_rot.location = (x + 100, -300)
    rand_rot.data_type = 'FLOAT'
    rand_rot.inputs[2].default_value = -math.pi
    rand_rot.inputs[3].default_value = math.pi

    # Combine rotation vector (0, 0, random_z)
    x += 200
    combine_rot = ng.nodes.new('ShaderNodeCombineXYZ')
    combine_rot.location = (x, -300)

    # Rotate Instances
    x += 200
    rotate = ng.nodes.new('GeometryNodeRotateInstances')
    rotate.location = (x, 0)

    # Combine scale vector (S, S, S)
    combine_scale = ng.nodes.new('ShaderNodeCombineXYZ')
    combine_scale.location = (x, -200)

    # Scale Instances
    x += 200
    scale_inst = ng.nodes.new('GeometryNodeScaleInstances')
    scale_inst.location = (x, 0)

    x += 200
    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x, 0)

    # --- Links ---
    link = ng.links.new

    # Collection
    link(group_in.outputs['Collection'], coll_info.inputs['Collection'])

    # Random pick
    link(index_node.outputs['Index'], rand_pick.inputs['ID'])
    link(group_in.outputs['Seed'], rand_pick.inputs['Seed'])

    # Instance on Points (input geometry vertices = scatter points)
    link(group_in.outputs['Geometry'], inst_on_pts.inputs['Points'])
    link(coll_info.outputs['Instances'], inst_on_pts.inputs['Instance'])
    link(rand_pick.outputs[2], inst_on_pts.inputs['Instance Index'])

    # Random rotation
    link(group_in.outputs['Seed'], seed_offset.inputs[0])
    link(seed_offset.outputs['Value'], rand_rot.inputs['Seed'])
    link(index_node.outputs['Index'], rand_rot.inputs['ID'])
    link(rand_rot.outputs[1], combine_rot.inputs['Z'])

    # Rotate
    link(inst_on_pts.outputs['Instances'], rotate.inputs['Instances'])
    link(combine_rot.outputs['Vector'], rotate.inputs['Rotation'])

    # Scale
    link(group_in.outputs['Scale'], combine_scale.inputs['X'])
    link(group_in.outputs['Scale'], combine_scale.inputs['Y'])
    link(group_in.outputs['Scale'], combine_scale.inputs['Z'])
    link(rotate.outputs['Instances'], scale_inst.inputs['Instances'])
    link(combine_scale.outputs['Vector'], scale_inst.inputs['Scale'])

    # Output
    link(scale_inst.outputs['Instances'], group_out.inputs['Geometry'])

    return ng


class GPTOOLS_OT_stamp_scatter(bpy.types.Operator):
    """Scatter collection assets at GP X-mark locations on a surface.

    Computes AABB center of each X mark, creates a scatter mesh,
    and adds a non-destructive GN instancing modifier.
    """

    bl_idname = "gptools.stamp_scatter"
    bl_label = "Stamp Scatter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        gp = get_active_grease_pencil(context)
        if gp is None:
            return False
        if not context.scene.gptools.stamp_collection:
            return False
        return True

    def execute(self, context):
        props = context.scene.gptools
        gp_obj = get_active_grease_pencil(context)

        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        coll = props.stamp_collection
        if not coll:
            self.report({"ERROR"}, "Please select an asset collection")
            return {"CANCELLED"}

        # Compute X mark centers using AABB (merge distance = 2.0)
        centers = _compute_x_mark_centers(gp_obj, 2.0)
        if not centers:
            self.report({"ERROR"}, "No marks found in Grease Pencil strokes")
            return {"CANCELLED"}

        # Create a scatter mesh with one vertex per X mark center
        mesh = bpy.data.meshes.new("StampScatter")
        mesh.from_pydata([c[:] for c in centers], [], [])
        mesh.update()

        scatter_obj = bpy.data.objects.new("StampScatter", mesh)
        for col in gp_obj.users_collection:
            col.objects.link(scatter_obj)

        # Add the instancing GN modifier
        node_group = get_or_create_instance_node_group()
        mod = scatter_obj.modifiers.new(name="StampScatter", type='NODES')
        mod.node_group = node_group

        items = mod.node_group.interface.items_tree
        mod[items['Collection'].identifier] = coll

        # Select the scatter object
        context.view_layer.objects.active = scatter_obj
        scatter_obj.select_set(True)
        gp_obj.select_set(False)

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

        self.report(
            {"INFO"},
            f"Scattered {len(centers)} instance(s) — edit settings in Modifiers panel",
        )
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_stamp_scatter,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
