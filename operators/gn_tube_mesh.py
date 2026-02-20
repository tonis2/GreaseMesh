import bpy
from ..utils.conversion import get_active_grease_pencil

NODE_GROUP_NAME = "GreaseMesh_Tube"


def get_or_create_tube_node_group():
    """Get existing or build the Tube Mesh geometry node group."""
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        return ng

    ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

    # Interface sockets
    ng.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')

    res_sock = ng.interface.new_socket(name="Resolution", in_out='INPUT', socket_type='NodeSocketInt')
    res_sock.default_value = 12
    res_sock.min_value = 3
    res_sock.max_value = 64

    rad_sock = ng.interface.new_socket(name="Radius", in_out='INPUT', socket_type='NodeSocketFloat')
    rad_sock.default_value = 0.1
    rad_sock.min_value = 0.001
    rad_sock.max_value = 10.0

    caps_sock = ng.interface.new_socket(name="Fill Caps", in_out='INPUT', socket_type='NodeSocketBool')
    caps_sock.default_value = True

    ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # Nodes
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (-600, 0)

    gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    gp_to_curves.location = (-400, 0)

    circle = ng.nodes.new('GeometryNodeCurvePrimitiveCircle')
    circle.location = (-400, -200)
    circle.mode = 'RADIUS'

    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (-200, 0)

    shade = ng.nodes.new('GeometryNodeSetShadeSmooth')
    shade.location = (0, 0)

    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (200, 0)

    # Links
    ng.links.new(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])
    ng.links.new(gp_to_curves.outputs['Curves'], curve_to_mesh.inputs['Curve'])
    ng.links.new(group_in.outputs['Resolution'], circle.inputs['Resolution'])
    ng.links.new(group_in.outputs['Radius'], circle.inputs['Radius'])
    ng.links.new(circle.outputs['Curve'], curve_to_mesh.inputs['Profile Curve'])
    ng.links.new(group_in.outputs['Fill Caps'], curve_to_mesh.inputs['Fill Caps'])
    ng.links.new(curve_to_mesh.outputs['Mesh'], shade.inputs['Mesh'])
    ng.links.new(shade.outputs['Mesh'], group_out.inputs['Geometry'])

    return ng


class GPTOOLS_OT_gn_tube_mesh(bpy.types.Operator):
    """Add Geometry Nodes modifier to create tube mesh from Grease Pencil strokes"""

    bl_idname = "gptools.gn_tube_mesh"
    bl_label = "Tube Mesh (GN)"
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
        node_group = get_or_create_tube_node_group()

        mod = gp_obj.modifiers.new(name="TubeMesh", type='NODES')
        mod.node_group = node_group
        mod["Socket_1"] = props.tube_resolution
        mod["Socket_2"] = props.tube_radius
        mod["Socket_3"] = True  # Fill Caps

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

        self.report({"INFO"}, "Tube mesh GN modifier added.")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_gn_tube_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
