import bpy
from ..utils.conversion import get_active_grease_pencil

NODE_GROUP_NAME = "GreaseMesh_Solid"


def get_or_create_solid_node_group():
    """Build the Solid Mesh geometry node group.

    Pipeline:
      GP → Curves → Curve to Mesh (edges)
        → Merge by Distance (small, collapse duplicates)
        → Merge by Distance (large, endpoints only, bridge gaps)
        → Mesh to Curve → Set Cyclic → Resample
        → Fill Curve (triangulated) → Merge
        → Extrude (region) → bottom cap → Join → Merge
    """
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        ng.nodes.clear()
    else:
        ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

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
    x = -1600
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (x, 0)

    x += 200
    gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    gp_to_curves.location = (x, 0)
    gp_to_curves.inputs['Layers as Instances'].default_value = False

    # Convert all curve splines to edge mesh (no profile = edges only)
    x += 200
    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (x, 0)

    # --- Adaptive merge distances from bounding box diagonal ---
    bbox = ng.nodes.new('GeometryNodeBoundBox')
    bbox.location = (x + 200, -300)

    bbox_sub = ng.nodes.new('ShaderNodeVectorMath')
    bbox_sub.location = (x + 400, -300)
    bbox_sub.operation = 'SUBTRACT'

    bbox_len = ng.nodes.new('ShaderNodeVectorMath')
    bbox_len.location = (x + 600, -300)
    bbox_len.operation = 'LENGTH'

    # 10% for collapsing overlapping/duplicate strokes
    bbox_scale_small = ng.nodes.new('ShaderNodeMath')
    bbox_scale_small.location = (x + 800, -250)
    bbox_scale_small.operation = 'MULTIPLY'
    bbox_scale_small.inputs[1].default_value = 0.025

    # 25% for bridging gaps between stroke endpoints
    bbox_scale_large = ng.nodes.new('ShaderNodeMath')
    bbox_scale_large.location = (x + 800, -350)
    bbox_scale_large.operation = 'MULTIPLY'
    bbox_scale_large.inputs[1].default_value = 0.25

    # Pass 1: collapse duplicates (all vertices, small distance)
    x += 200
    merge_dupes = ng.nodes.new('GeometryNodeMergeByDistance')
    merge_dupes.location = (x, 0)

    # Pass 2: bridge gaps (endpoints only, large distance)
    x += 200
    vert_neighbors = ng.nodes.new('GeometryNodeInputMeshVertexNeighbors')
    vert_neighbors.location = (x, -150)

    is_endpoint = ng.nodes.new('FunctionNodeCompare')
    is_endpoint.location = (x + 200, -150)
    is_endpoint.data_type = 'INT'
    is_endpoint.operation = 'EQUAL'
    is_endpoint.inputs[3].default_value = 1

    merge_join = ng.nodes.new('GeometryNodeMergeByDistance')
    merge_join.location = (x, 0)

    # Convert welded edge mesh back to curve
    x += 200
    mesh_to_curve = ng.nodes.new('GeometryNodeMeshToCurve')
    mesh_to_curve.location = (x, 0)

    x += 200
    set_cyclic = ng.nodes.new('GeometryNodeSetSplineCyclic')
    set_cyclic.location = (x, 0)
    set_cyclic.inputs['Cyclic'].default_value = True

    x += 200
    resample = ng.nodes.new('GeometryNodeResampleCurve')
    resample.location = (x, 0)

    x += 200
    fill_curve = ng.nodes.new('GeometryNodeFillCurve')
    fill_curve.location = (x, 0)

    x += 200
    merge = ng.nodes.new('GeometryNodeMergeByDistance')
    merge.location = (x, 0)
    merge.inputs['Distance'].default_value = 0.001

    x += 200
    extrude = ng.nodes.new('GeometryNodeExtrudeMesh')
    extrude.location = (x, 0)
    extrude.inputs['Individual'].default_value = False

    flip = ng.nodes.new('GeometryNodeFlipFaces')
    flip.location = (x, -200)

    x += 200
    join = ng.nodes.new('GeometryNodeJoinGeometry')
    join.location = (x, 0)

    merge_final = ng.nodes.new('GeometryNodeMergeByDistance')
    merge_final.location = (x + 200, 0)
    merge_final.inputs['Distance'].default_value = 0.001

    x += 400
    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x, 0)

    # --- Links ---
    link = ng.links.new

    link(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])
    link(gp_to_curves.outputs['Curves'], curve_to_mesh.inputs['Curve'])

    # Adaptive merge distances
    link(curve_to_mesh.outputs['Mesh'], bbox.inputs['Geometry'])
    link(bbox.outputs['Max'], bbox_sub.inputs[0])
    link(bbox.outputs['Min'], bbox_sub.inputs[1])
    link(bbox_sub.outputs['Vector'], bbox_len.inputs[0])
    link(bbox_len.outputs['Value'], bbox_scale_small.inputs[0])
    link(bbox_len.outputs['Value'], bbox_scale_large.inputs[0])

    # Pass 1: collapse duplicates
    link(curve_to_mesh.outputs['Mesh'], merge_dupes.inputs['Geometry'])
    link(bbox_scale_small.outputs['Value'], merge_dupes.inputs['Distance'])

    # Pass 2: bridge gaps (endpoints only)
    link(merge_dupes.outputs['Geometry'], merge_join.inputs['Geometry'])
    link(bbox_scale_large.outputs['Value'], merge_join.inputs['Distance'])
    link(vert_neighbors.outputs['Vertex Count'], is_endpoint.inputs[2])
    link(is_endpoint.outputs['Result'], merge_join.inputs['Selection'])

    # Edge mesh → Curve → Cyclic → Resample → Fill
    link(merge_join.outputs['Geometry'], mesh_to_curve.inputs['Mesh'])
    link(mesh_to_curve.outputs['Curve'], set_cyclic.inputs['Curve'])
    link(set_cyclic.outputs['Curve'], resample.inputs['Curve'])
    link(group_in.outputs['Resolution'], resample.inputs['Count'])
    link(resample.outputs['Curve'], fill_curve.inputs['Curve'])

    # Fill → Merge → Extrude + Bottom cap → Join → Merge → Output
    link(fill_curve.outputs['Mesh'], merge.inputs['Geometry'])
    link(merge.outputs['Geometry'], extrude.inputs['Mesh'])
    link(group_in.outputs['Thickness'], extrude.inputs['Offset Scale'])

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
