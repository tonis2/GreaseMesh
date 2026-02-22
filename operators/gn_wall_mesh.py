import bpy
from ..utils.conversion import get_active_grease_pencil

NODE_GROUP_NAME = "GreaseMesh_Wall"


def get_or_create_wall_node_group():
    """Get existing or build the Wall Mesh geometry node group.

    Pipeline:
      GP (floor plan strokes) → Curves → Resample → Set Cyclic
        → Rectangle profile (Thickness × Height), offset up by Height/2
        → Curve to Mesh (sweep profile along floor plan, fill caps)
        → Shade Smooth → Output
    """
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        return ng

    ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

    # Interface sockets
    ng.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')

    res_sock = ng.interface.new_socket(
        name="Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    res_sock.default_value = 64
    res_sock.min_value = 8
    res_sock.max_value = 512

    height_sock = ng.interface.new_socket(
        name="Height", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    height_sock.default_value = 3.0
    height_sock.min_value = 0.1
    height_sock.max_value = 100.0

    thick_sock = ng.interface.new_socket(
        name="Thickness", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    thick_sock.default_value = 0.3
    thick_sock.min_value = 0.01
    thick_sock.max_value = 10.0

    ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # --- Nodes ---
    x = -1200
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (x, 0)

    # GP to Curves
    x += 200
    gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    gp_to_curves.location = (x, 0)
    gp_to_curves.inputs['Layers as Instances'].default_value = False

    # Resample to uniform point count
    x += 200
    resample = ng.nodes.new('GeometryNodeResampleCurve')
    resample.location = (x, 0)

    # Close the curve (floor plan loop)
    x += 200
    set_cyclic = ng.nodes.new('GeometryNodeSetSplineCyclic')
    set_cyclic.location = (x, 0)
    set_cyclic.inputs['Cyclic'].default_value = True

    # Rectangle profile: Width = Thickness, Height = Height
    x += 200
    quad = ng.nodes.new('GeometryNodeCurvePrimitiveQuadrilateral')
    quad.location = (x, -300)
    quad.mode = 'RECTANGLE'

    # Compute Height / 2 for vertical offset
    half_height = ng.nodes.new('ShaderNodeMath')
    half_height.location = (x, -500)
    half_height.operation = 'MULTIPLY'
    half_height.inputs[1].default_value = 0.5

    # Build offset vector (0, 0, Height/2) — Z is up in Blender
    x += 200
    combine = ng.nodes.new('ShaderNodeCombineXYZ')
    combine.location = (x, -500)

    # Offset the rectangle profile up so bottom edge sits at ground
    set_pos = ng.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (x, -300)

    # Sweep: Curve to Mesh with profile and filled caps
    x += 200
    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (x, 0)
    curve_to_mesh.inputs['Fill Caps'].default_value = True

    # Smooth shading
    x += 200
    shade = ng.nodes.new('GeometryNodeSetShadeSmooth')
    shade.location = (x, 0)

    x += 200
    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x, 0)

    # --- Links ---
    link = ng.links.new

    # GP → Curves → Resample → Cyclic
    link(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])
    link(gp_to_curves.outputs['Curves'], resample.inputs['Curve'])
    link(group_in.outputs['Resolution'], resample.inputs['Count'])
    link(resample.outputs['Curve'], set_cyclic.inputs['Curve'])

    # Rectangle profile: Width = Thickness, Height = Height
    link(group_in.outputs['Thickness'], quad.inputs['Width'])
    link(group_in.outputs['Height'], quad.inputs['Height'])

    # Offset profile: Height/2 → CombineXYZ(Z) → SetPosition offset
    link(group_in.outputs['Height'], half_height.inputs[0])
    link(half_height.outputs['Value'], combine.inputs['Z'])
    link(quad.outputs['Curve'], set_pos.inputs['Geometry'])
    link(combine.outputs['Vector'], set_pos.inputs['Offset'])

    # Sweep profile along floor plan curves
    link(set_cyclic.outputs['Curve'], curve_to_mesh.inputs['Curve'])
    link(set_pos.outputs['Geometry'], curve_to_mesh.inputs['Profile Curve'])

    # Shade smooth → Output
    link(curve_to_mesh.outputs['Mesh'], shade.inputs['Mesh'])
    link(shade.outputs['Mesh'], group_out.inputs['Geometry'])

    return ng


class GPTOOLS_OT_gn_wall_mesh(bpy.types.Operator):
    """Add Geometry Nodes modifier to create walls from Grease Pencil floor plan strokes"""

    bl_idname = "gptools.gn_wall_mesh"
    bl_label = "Wall Mesh (GN)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        node_group = get_or_create_wall_node_group()

        mod = gp_obj.modifiers.new(name="WallMesh", type='NODES')
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

        self.report({"INFO"}, "Wall mesh GN modifier added.")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_gn_wall_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
