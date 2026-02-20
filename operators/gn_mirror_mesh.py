import bpy
from ..utils.conversion import get_active_grease_pencil
from .gn_solid_mesh import get_or_create_solid_node_group

NODE_GROUP_NAME = "GreaseMesh_Mirror"


def get_or_create_mirror_node_group():
    """Get existing or build the Mirror Mesh geometry node group.

    Pipeline:
      [GreaseMesh_Solid subgroup] → solid_geo
        → per-axis mirror stage (X, Y, Z):
            geo ──┬── join
                  └── Transform(scale=-1 on axis) → FlipFaces → join
            join → MergeByDistance → Switch(bypass if axis off)
        → Set Shade Smooth → Group Output
    """
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        return ng

    # Ensure the solid subgroup exists
    solid_ng = get_or_create_solid_node_group()

    ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

    # Interface sockets
    ng.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')

    res_sock = ng.interface.new_socket(
        name="Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    res_sock.default_value = 64
    res_sock.min_value = 8
    res_sock.max_value = 512

    thick_sock = ng.interface.new_socket(
        name="Thickness", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    thick_sock.default_value = 0.4
    thick_sock.min_value = 0.0
    thick_sock.max_value = 20.0

    mirror_x_sock = ng.interface.new_socket(
        name="Mirror X", in_out='INPUT', socket_type='NodeSocketBool',
    )
    mirror_x_sock.default_value = True

    mirror_y_sock = ng.interface.new_socket(
        name="Mirror Y", in_out='INPUT', socket_type='NodeSocketBool',
    )
    mirror_y_sock.default_value = False

    mirror_z_sock = ng.interface.new_socket(
        name="Mirror Z", in_out='INPUT', socket_type='NodeSocketBool',
    )
    mirror_z_sock.default_value = False

    merge_dist_sock = ng.interface.new_socket(
        name="Merge Distance", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    merge_dist_sock.default_value = 0.001
    merge_dist_sock.min_value = 0.0
    merge_dist_sock.max_value = 1.0

    ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # --- Nodes ---
    x = -800
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (x, 0)

    # Solid subgroup
    x += 200
    solid_group = ng.nodes.new('GeometryNodeGroup')
    solid_group.location = (x, 0)
    solid_group.node_tree = solid_ng

    # Link inputs to solid subgroup
    ng.links.new(group_in.outputs['Geometry'], solid_group.inputs['Geometry'])
    ng.links.new(group_in.outputs['Resolution'], solid_group.inputs['Resolution'])
    ng.links.new(group_in.outputs['Thickness'], solid_group.inputs['Thickness'])

    # Move geometry so bbox Min is at origin — the flat edge where
    # the user expects the mirror seam sits at (0,0,0), and the shape
    # extends into the positive quadrant.  Mirror (scale -1) then
    # creates the other half in the negative quadrant, joining at 0.
    x += 200
    bbox = ng.nodes.new('GeometryNodeBoundBox')
    bbox.location = (x, -200)

    vec_negate = ng.nodes.new('ShaderNodeVectorMath')
    vec_negate.location = (x + 200, -200)
    vec_negate.operation = 'SCALE'
    vec_negate.inputs['Scale'].default_value = -1.0

    origin_pos = ng.nodes.new('GeometryNodeInputPosition')
    origin_pos.location = (x + 200, 200)

    origin_add = ng.nodes.new('ShaderNodeVectorMath')
    origin_add.location = (x + 400, 200)
    origin_add.operation = 'ADD'

    set_pos = ng.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (x + 600, 0)

    # offset = -bbox_min  →  shifts min corner to origin
    ng.links.new(solid_group.outputs['Geometry'], bbox.inputs['Geometry'])
    ng.links.new(bbox.outputs['Min'], vec_negate.inputs[0])
    ng.links.new(origin_pos.outputs['Position'], origin_add.inputs[0])
    ng.links.new(vec_negate.outputs['Vector'], origin_add.inputs[1])
    ng.links.new(solid_group.outputs['Geometry'], set_pos.inputs['Geometry'])
    ng.links.new(origin_add.outputs['Vector'], set_pos.inputs['Position'])

    x += 1000

    # Build mirror stages for each axis
    prev_output = set_pos.outputs['Geometry']
    axis_names = ['Mirror X', 'Mirror Y', 'Mirror Z']
    axis_scales = [(-1, 1, 1), (1, -1, 1), (1, 1, -1)]

    for i, (axis_name, scale) in enumerate(zip(axis_names, axis_scales)):
        x += 250
        y_offset = 0

        # Transform: scale -1 on this axis
        transform = ng.nodes.new('GeometryNodeTransform')
        transform.location = (x, y_offset - 200)
        transform.inputs['Scale'].default_value = scale

        # Flip faces on the mirrored copy
        flip = ng.nodes.new('GeometryNodeFlipFaces')
        flip.location = (x + 200, y_offset - 200)

        # Join original + mirrored
        x += 400
        join = ng.nodes.new('GeometryNodeJoinGeometry')
        join.location = (x, y_offset)

        # Merge by distance
        merge = ng.nodes.new('GeometryNodeMergeByDistance')
        merge.location = (x + 200, y_offset)

        # Switch: bypass if axis is off (False = pass through original, True = mirrored result)
        switch = ng.nodes.new('GeometryNodeSwitch')
        switch.location = (x + 400, y_offset)
        switch.input_type = 'GEOMETRY'

        # Links for this axis stage
        ng.links.new(prev_output, transform.inputs['Geometry'])
        ng.links.new(transform.outputs['Geometry'], flip.inputs['Mesh'])
        ng.links.new(prev_output, join.inputs['Geometry'])
        ng.links.new(flip.outputs['Mesh'], join.inputs['Geometry'])
        ng.links.new(join.outputs['Geometry'], merge.inputs['Geometry'])
        ng.links.new(group_in.outputs['Merge Distance'], merge.inputs['Distance'])

        # Switch: off → original geo, on → mirrored+merged geo
        ng.links.new(group_in.outputs[axis_name], switch.inputs['Switch'])
        ng.links.new(prev_output, switch.inputs['False'])
        ng.links.new(merge.outputs['Geometry'], switch.inputs['True'])

        prev_output = switch.outputs['Output']
        x += 400

    # Shade smooth
    shade = ng.nodes.new('GeometryNodeSetShadeSmooth')
    shade.location = (x + 200, 0)

    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x + 400, 0)

    ng.links.new(prev_output, shade.inputs['Mesh'])
    ng.links.new(shade.outputs['Mesh'], group_out.inputs['Geometry'])

    return ng


class GPTOOLS_OT_gn_mirror_mesh(bpy.types.Operator):
    """Add Geometry Nodes modifier to create mirrored solid mesh from Grease Pencil strokes"""

    bl_idname = "gptools.gn_mirror_mesh"
    bl_label = "Mirror Mesh (GN)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        node_group = get_or_create_mirror_node_group()

        mod = gp_obj.modifiers.new(name="MirrorMesh", type='NODES')
        mod.node_group = node_group

        context.view_layer.objects.active = gp_obj
        gp_obj.select_set(True)

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

        self.report({"INFO"}, "Mirror mesh GN modifier added.")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_gn_mirror_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
