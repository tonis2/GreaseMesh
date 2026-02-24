import bpy
from ..utils.conversion import get_active_grease_pencil

NODE_GROUP_NAME = "GreaseMesh_Solid"


def get_or_create_solid_node_group():
    """Get existing or build the Solid Mesh geometry node group.

    Pipeline:
      GP → Curves → Resample → Set Cyclic → Curve to Mesh (edge loop)
        → count verts → Mesh Circle (ngon, same vert count)
        → sample positions from edge loop → set on circle
        → Merge by Distance → Extrude → Shade Smooth

    Creates a filled ngon disc with the same vertex count as the curve,
    then remaps vertex positions to match the curve shape. This fills
    any shape (convex or concave) correctly. Inspired by ClayPencil.
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

    thick_sock = ng.interface.new_socket(
        name="Thickness", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    thick_sock.default_value = 0.4
    thick_sock.min_value = 0.0
    thick_sock.max_value = 20.0

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

    # Close the curve
    x += 200
    set_cyclic = ng.nodes.new('GeometryNodeSetSplineCyclic')
    set_cyclic.location = (x, 0)
    set_cyclic.inputs['Cyclic'].default_value = True

    # Convert curve to edge loop (no profile = edges only)
    x += 200
    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (x, 0)

    # Count vertices in the edge loop
    x += 200
    domain_size = ng.nodes.new('GeometryNodeAttributeDomainSize')
    domain_size.location = (x, -200)

    # Sample positions from edge loop by index
    position = ng.nodes.new('GeometryNodeInputPosition')
    position.location = (x, -400)

    index = ng.nodes.new('GeometryNodeInputIndex')
    index.location = (x + 100, -300)

    x += 200
    sample_idx = ng.nodes.new('GeometryNodeSampleIndex')
    sample_idx.location = (x, -300)
    sample_idx.data_type = 'FLOAT_VECTOR'

    # Create filled disc with same vertex count
    circle = ng.nodes.new('GeometryNodeMeshCircle')
    circle.location = (x, 0)
    circle.fill_type = 'NGON'

    # Map disc vertex positions to curve positions
    x += 200
    set_pos = ng.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (x, 0)

    # Clean up coincident verts
    x += 200
    merge = ng.nodes.new('GeometryNodeMergeByDistance')
    merge.location = (x, 0)
    merge.inputs['Distance'].default_value = 0.001

    # Extrude for thickness (creates top + sides, bottom is open)
    x += 200
    extrude = ng.nodes.new('GeometryNodeExtrudeMesh')
    extrude.location = (x, 0)
    extrude.inputs['Individual'].default_value = True

    # Bottom cap: flip a copy of the original flat face
    flip = ng.nodes.new('GeometryNodeFlipFaces')
    flip.location = (x, -200)

    # Join extruded shape + flipped bottom cap
    x += 200
    join = ng.nodes.new('GeometryNodeJoinGeometry')
    join.location = (x, 0)

    # Merge coincident verts to weld bottom cap to extrude sides
    merge_final = ng.nodes.new('GeometryNodeMergeByDistance')
    merge_final.location = (x + 200, 0)
    merge_final.inputs['Distance'].default_value = 0.001

    x += 400
    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x, 0)

    # --- Links ---
    link = ng.links.new

    # GP → Curves → Resample → Cyclic → Edge loop
    link(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])
    link(gp_to_curves.outputs['Curves'], resample.inputs['Curve'])
    link(group_in.outputs['Resolution'], resample.inputs['Count'])
    link(resample.outputs['Curve'], set_cyclic.inputs['Curve'])
    link(set_cyclic.outputs['Curve'], curve_to_mesh.inputs['Curve'])

    # Count verts → Mesh Circle with same count
    link(curve_to_mesh.outputs['Mesh'], domain_size.inputs['Geometry'])
    link(domain_size.outputs['Point Count'], circle.inputs['Vertices'])

    # Sample positions from edge loop
    link(curve_to_mesh.outputs['Mesh'], sample_idx.inputs['Geometry'])
    link(position.outputs['Position'], sample_idx.inputs['Value'])
    link(index.outputs['Index'], sample_idx.inputs['Index'])

    # Remap circle verts to curve positions
    link(circle.outputs['Mesh'], set_pos.inputs['Geometry'])
    link(sample_idx.outputs['Value'], set_pos.inputs['Position'])

    # Clean up → Extrude + Bottom cap → Join → Merge → Shade Smooth → Output
    link(set_pos.outputs['Geometry'], merge.inputs['Geometry'])
    link(merge.outputs['Geometry'], extrude.inputs['Mesh'])
    link(group_in.outputs['Thickness'], extrude.inputs['Offset Scale'])

    # Bottom cap: flip a copy of the filled face, join with extruded shape
    link(merge.outputs['Geometry'], flip.inputs['Mesh'])
    link(extrude.outputs['Mesh'], join.inputs['Geometry'])
    link(flip.outputs['Mesh'], join.inputs['Geometry'])
    link(join.outputs['Geometry'], merge_final.inputs['Geometry'])
    link(merge_final.outputs['Geometry'], group_out.inputs['Geometry'])

    return ng


class GPTOOLS_OT_gn_solid_mesh(bpy.types.Operator):
    """Add Geometry Nodes modifier to create solid mesh from Grease Pencil strokes"""

    bl_idname = "gptools.gn_solid_mesh"
    bl_label = "Solid Mesh (GN)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        node_group = get_or_create_solid_node_group()

        mod = gp_obj.modifiers.new(name="SolidMesh", type='NODES')
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

        self.report({"INFO"}, "Solid mesh GN modifier added.")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_gn_solid_mesh,
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
