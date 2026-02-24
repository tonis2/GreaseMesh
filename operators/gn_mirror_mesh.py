import bpy
from ..utils.conversion import get_active_grease_pencil
from .gn_solid_mesh import get_or_create_solid_node_group

NODE_GROUP_NAME = "GreaseMesh_Mirror"

AXIS_NAMES = ["Mirror X", "Mirror Y", "Mirror Z"]
AXIS_SCALES = [(-1, 1, 1), (1, -1, 1), (1, 1, -1)]


def _build_interface(ng):
    """Create the modifier panel sockets."""
    ng.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry',
    )

    s = ng.interface.new_socket(
        name="Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    s.default_value, s.min_value, s.max_value = 64, 8, 512

    s = ng.interface.new_socket(
        name="Thickness", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 0.4, 0.0, 20.0

    for name, default in [("Mirror X", True), ("Mirror Y", False), ("Mirror Z", False)]:
        s = ng.interface.new_socket(
            name=name, in_out='INPUT', socket_type='NodeSocketBool',
        )
        s.default_value = default

    s = ng.interface.new_socket(
        name="Merge Distance", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 0.001, 0.0, 1.0

    ng.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry',
    )


def _add_origin_shift(ng, link, group_in, solid_out, x):
    """Move geometry so bbox min sits at origin (mirror seam edge).
    Returns (shifted_geometry_output, bbox_min_output) so position can be restored later."""
    bbox = ng.nodes.new('GeometryNodeBoundBox')
    bbox.location = (x, -200)

    negate = ng.nodes.new('ShaderNodeVectorMath')
    negate.location = (x + 200, -200)
    negate.operation = 'SCALE'
    negate.inputs['Scale'].default_value = -1.0

    pos = ng.nodes.new('GeometryNodeInputPosition')
    pos.location = (x + 200, 200)

    add = ng.nodes.new('ShaderNodeVectorMath')
    add.location = (x + 400, 200)
    add.operation = 'ADD'

    set_pos = ng.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (x + 600, 0)

    link(solid_out, bbox.inputs['Geometry'])
    link(bbox.outputs['Min'], negate.inputs[0])
    link(pos.outputs['Position'], add.inputs[0])
    link(negate.outputs['Vector'], add.inputs[1])
    link(solid_out, set_pos.inputs['Geometry'])
    link(add.outputs['Vector'], set_pos.inputs['Position'])

    return set_pos.outputs['Geometry'], bbox.outputs['Min']


def _add_position_restore(ng, link, geometry_out, bbox_min_out, x):
    """Move geometry back to its original position after mirroring."""
    pos = ng.nodes.new('GeometryNodeInputPosition')
    pos.location = (x, 200)

    add = ng.nodes.new('ShaderNodeVectorMath')
    add.location = (x + 200, 200)
    add.operation = 'ADD'

    set_pos = ng.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (x + 400, 0)

    link(pos.outputs['Position'], add.inputs[0])
    link(bbox_min_out, add.inputs[1])
    link(geometry_out, set_pos.inputs['Geometry'])
    link(add.outputs['Vector'], set_pos.inputs['Position'])

    return set_pos.outputs['Geometry']


def _add_mirror_stage(ng, link, group_in, prev_output, axis_name, scale, x):
    """Add one mirror axis: Transform → FlipFaces → Join → Merge → Switch."""
    transform = ng.nodes.new('GeometryNodeTransform')
    transform.location = (x, -200)
    transform.inputs['Scale'].default_value = scale

    flip = ng.nodes.new('GeometryNodeFlipFaces')
    flip.location = (x + 200, -200)

    join = ng.nodes.new('GeometryNodeJoinGeometry')
    join.location = (x + 400, 0)

    merge = ng.nodes.new('GeometryNodeMergeByDistance')
    merge.location = (x + 600, 0)

    switch = ng.nodes.new('GeometryNodeSwitch')
    switch.location = (x + 800, 0)
    switch.input_type = 'GEOMETRY'

    link(prev_output, transform.inputs['Geometry'])
    link(transform.outputs['Geometry'], flip.inputs['Mesh'])
    link(prev_output, join.inputs['Geometry'])
    link(flip.outputs['Mesh'], join.inputs['Geometry'])
    link(join.outputs['Geometry'], merge.inputs['Geometry'])
    link(group_in.outputs['Merge Distance'], merge.inputs['Distance'])
    link(group_in.outputs[axis_name], switch.inputs['Switch'])
    link(prev_output, switch.inputs['False'])
    link(merge.outputs['Geometry'], switch.inputs['True'])

    return switch.outputs['Output']


def get_or_create_mirror_node_group():
    """Get existing or build the Mirror Mesh geometry node group.

    Pipeline:
      [GreaseMesh_Solid subgroup] → shift bbox min to origin
        → per-axis mirror stage (X, Y, Z) with toggle switches
        → Set Shade Smooth → Group Output
    """
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        return ng

    solid_ng = get_or_create_solid_node_group()
    ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')
    _build_interface(ng)

    link = ng.links.new

    # --- Nodes ---
    x = -800
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (x, 0)

    x += 200
    solid_group = ng.nodes.new('GeometryNodeGroup')
    solid_group.location = (x, 0)
    solid_group.node_tree = solid_ng

    link(group_in.outputs['Geometry'], solid_group.inputs['Geometry'])
    link(group_in.outputs['Resolution'], solid_group.inputs['Resolution'])
    link(group_in.outputs['Thickness'], solid_group.inputs['Thickness'])

    # Shift so bbox min is at origin (mirror seam)
    x += 200
    prev, bbox_min = _add_origin_shift(ng, link, group_in, solid_group.outputs['Geometry'], x)
    x += 800

    # Mirror stages
    for axis_name, scale in zip(AXIS_NAMES, AXIS_SCALES):
        x += 200
        prev = _add_mirror_stage(ng, link, group_in, prev, axis_name, scale, x)
        x += 800

    # Restore original position
    x += 200
    prev = _add_position_restore(ng, link, prev, bbox_min, x)
    x += 600

    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x + 200, 0)

    link(prev, group_out.inputs['Geometry'])

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

        mod = gp_obj.modifiers.new(name="MirrorMesh", type='NODES')
        mod.node_group = get_or_create_mirror_node_group()

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


classes = [GPTOOLS_OT_gn_mirror_mesh]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
