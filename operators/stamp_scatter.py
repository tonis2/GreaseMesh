import bpy
import math
from mathutils import Vector
from ..utils.conversion import get_active_grease_pencil

SCATTER_NODE_GROUP = "GreaseMesh_StampScatter"


def _compute_x_mark_centers(gp_obj, merge_distance, layer_name=None):
    """Compute AABB centers of X marks from GP strokes.

    1. Get the centroid of each stroke (world space)
    2. Group nearby centroids within merge_distance (X = 2 close strokes)
    3. For each group, compute AABB of ALL points across its strokes
    4. Return the AABB center of each group

    If layer_name is given, only process strokes on that layer.
    """
    gp_matrix = gp_obj.matrix_world

    # Collect per-stroke data: centroid + all world-space points
    strokes_data = []
    for layer in gp_obj.data.layers:
        if layer_name is not None and layer.name != layer_name:
            continue
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


def get_or_create_scatter_node_group():
    """Reusable GN sub-group that instances an object at input points.

    Pipeline:
      Points → ObjectInfo → InstanceOnPoints (random pick)
        → RotateInstances (random Z OR surface-aligned) → ScaleInstances → Output

    The Mesh input accepts a single mesh object or a collection-instance empty.
    Pick Instance is enabled so collection-instance empties randomly pick children.

    Cached by name — shared across all scatter operations.
    """
    ng = bpy.data.node_groups.get(SCATTER_NODE_GROUP)
    if ng is not None:
        return ng

    ng = bpy.data.node_groups.new(name=SCATTER_NODE_GROUP, type='GeometryNodeTree')

    # --- Interface ---
    ng.interface.new_socket(
        name="Points", in_out='INPUT', socket_type='NodeSocketGeometry',
    )
    ng.interface.new_socket(
        name="Mesh", in_out='INPUT', socket_type='NodeSocketObject',
    )
    ng.interface.new_socket(
        name="Target Object", in_out='INPUT', socket_type='NodeSocketObject',
    )
    align_sock = ng.interface.new_socket(
        name="Align to Surface", in_out='INPUT', socket_type='NodeSocketBool',
    )
    align_sock.default_value = False

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
        name="Instances", in_out='OUTPUT', socket_type='NodeSocketGeometry',
    )

    # --- Nodes ---
    x = -800
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (x, 0)

    # Object Info (for mesh or collection-instance empty)
    x += 200
    mesh_info = ng.nodes.new('GeometryNodeObjectInfo')
    mesh_info.location = (x, -300)
    mesh_info.transform_space = 'ORIGINAL'

    # Index for per-point randomization
    index_node = ng.nodes.new('GeometryNodeInputIndex')
    index_node.location = (x, -150)

    # --- Surface alignment branch ---
    # ObjectInfo for target surface
    obj_info = ng.nodes.new('GeometryNodeObjectInfo')
    obj_info.location = (x, -600)
    obj_info.transform_space = 'RELATIVE'

    # Input Normal (to sample from target mesh)
    input_normal = ng.nodes.new('GeometryNodeInputNormal')
    input_normal.location = (x + 200, -700)

    # Input Position (sample position = scatter point positions)
    input_pos = ng.nodes.new('GeometryNodeInputPosition')
    input_pos.location = (x + 200, -500)

    # Sample Nearest Surface — get normal from target at each scatter point
    sample_surface = ng.nodes.new('GeometryNodeSampleNearestSurface')
    sample_surface.location = (x + 400, -600)
    sample_surface.data_type = 'FLOAT_VECTOR'

    # Align Rotation to Vector — Y axis faces wall normal, Z stays up
    align_rot = ng.nodes.new('FunctionNodeAlignRotationToVector')
    align_rot.location = (x + 600, -600)
    align_rot.axis = 'Y'
    align_rot.pivot_axis = 'Z'

    # Instance on Points
    x += 400
    inst_on_pts = ng.nodes.new('GeometryNodeInstanceOnPoints')
    inst_on_pts.location = (x, 0)
    inst_on_pts.inputs['Pick Instance'].default_value = False

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

    # Rotate Instances (random Z)
    x += 200
    rotate = ng.nodes.new('GeometryNodeRotateInstances')
    rotate.location = (x, -200)

    # Switch: skip random rotation when aligning to surface
    rot_switch = ng.nodes.new('GeometryNodeSwitch')
    rot_switch.location = (x, 0)
    rot_switch.input_type = 'GEOMETRY'

    # Combine scale vector (S, S, S)
    combine_scale = ng.nodes.new('ShaderNodeCombineXYZ')
    combine_scale.location = (x + 200, -200)

    # Scale Instances
    x += 400
    scale_inst = ng.nodes.new('GeometryNodeScaleInstances')
    scale_inst.location = (x, 0)

    x += 200
    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x, 0)

    # --- Links ---
    link = ng.links.new

    # Mesh object
    link(group_in.outputs['Mesh'], mesh_info.inputs['Object'])

    # Surface alignment: ObjectInfo → SampleNearestSurface → AlignRotationToVector
    link(group_in.outputs['Target Object'], obj_info.inputs['Object'])
    link(obj_info.outputs['Geometry'], sample_surface.inputs['Mesh'])
    link(input_normal.outputs['Normal'], sample_surface.inputs['Value'])
    link(input_pos.outputs['Position'], sample_surface.inputs['Sample Position'])
    link(sample_surface.outputs['Value'], align_rot.inputs['Vector'])

    # Feed surface rotation into InstanceOnPoints
    link(align_rot.outputs['Rotation'], inst_on_pts.inputs['Rotation'])

    # Instance on Points
    link(group_in.outputs['Points'], inst_on_pts.inputs['Points'])
    link(mesh_info.outputs['Geometry'], inst_on_pts.inputs['Instance'])

    # Random rotation
    link(group_in.outputs['Seed'], seed_offset.inputs[0])
    link(seed_offset.outputs['Value'], rand_rot.inputs['Seed'])
    link(index_node.outputs['Index'], rand_rot.inputs['ID'])
    link(rand_rot.outputs[1], combine_rot.inputs['Z'])

    # Rotate (random Z — only used when NOT aligning)
    link(inst_on_pts.outputs['Instances'], rotate.inputs['Instances'])
    link(combine_rot.outputs['Vector'], rotate.inputs['Rotation'])

    # Switch: Align to Surface → skip random rotation (True), use random (False)
    link(group_in.outputs['Align to Surface'], rot_switch.inputs['Switch'])
    link(rotate.outputs['Instances'], rot_switch.inputs['False'])
    link(inst_on_pts.outputs['Instances'], rot_switch.inputs['True'])

    # Scale
    link(group_in.outputs['Scale'], combine_scale.inputs['X'])
    link(group_in.outputs['Scale'], combine_scale.inputs['Y'])
    link(group_in.outputs['Scale'], combine_scale.inputs['Z'])
    link(rot_switch.outputs['Output'], scale_inst.inputs['Instances'])
    link(combine_scale.outputs['Vector'], scale_inst.inputs['Scale'])

    # Output
    link(scale_inst.outputs['Instances'], group_out.inputs['Instances'])

    return ng



class GPTOOLS_OT_stamp_scatter(bpy.types.Operator):
    """Scatter mesh objects at GP X-mark locations.

    Computes AABB centers per layer, creates one scatter object per layer,
    and adds a GreaseMesh_StampScatter GN modifier with a Mesh Object picker.
    """

    bl_idname = "gptools.stamp_scatter"
    bl_label = "Stamp Scatter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        gp = get_active_grease_pencil(context)
        if gp is None:
            return False
        return any(
            len(f.drawing.strokes) > 0
            for layer in gp.data.layers
            for f in layer.frames
        )

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)

        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        # Collect layers that have strokes, compute centers per layer
        layers_data = []
        for layer in gp_obj.data.layers:
            centers = _compute_x_mark_centers(gp_obj, 2.0, layer_name=layer.name)
            if centers:
                layers_data.append((layer.name, centers))

        if not layers_data:
            self.report({"ERROR"}, "No marks found in Grease Pencil strokes")
            return {"CANCELLED"}

        # Ensure the reusable sub-group exists
        scatter_ng = get_or_create_scatter_node_group()

        # Create one scatter object per layer with the sub-group directly
        scatter_objs = []
        for layer_name, centers in layers_data:
            verts = [c[:] for c in centers]
            mesh = bpy.data.meshes.new(f"{layer_name}_Scatter_{gp_obj.name}")
            mesh.from_pydata(verts, [], [])
            mesh.update()

            scatter_obj = bpy.data.objects.new(mesh.name, mesh)
            for col in gp_obj.users_collection:
                col.objects.link(scatter_obj)
            layer_ng = scatter_ng.copy()
            layer_ng.name = f"{layer_name}_Scatter"
            mod = scatter_obj.modifiers.new(name="Scatter", type='NODES')
            mod.node_group = layer_ng
            scatter_objs.append(scatter_obj)

        # Select the last scatter object
        last = scatter_objs[-1]
        context.view_layer.objects.active = last
        for obj in scatter_objs:
            obj.select_set(True)
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

        total = sum(len(centers) for _, centers in layers_data)
        layer_info = ", ".join(
            f"{name} ({len(centers)})" for name, centers in layers_data
        )
        self.report(
            {"INFO"},
            f"Scattered {total} instance(s) across {len(layers_data)} layer(s): {layer_info}",
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
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
