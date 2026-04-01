import bpy
from ..utils.conversion import get_active_grease_pencil

BOOL_CUTTER_NODE_GROUP = "GreaseMesh_BoolCutter"


def get_or_create_bool_cutter_node_group():
    """Build a node group like Solid, but centered so it straddles the surface.

    Same edge-merge pipeline as Solid, then offsets by -Normal * Thickness/2
    so the cutter penetrates inward.
    """
    ng = bpy.data.node_groups.get(BOOL_CUTTER_NODE_GROUP)
    if ng is not None:
        ng.nodes.clear()
    else:
        ng = bpy.data.node_groups.new(name=BOOL_CUTTER_NODE_GROUP, type='GeometryNodeTree')

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
        thick_sock.default_value = 2.0
        thick_sock.min_value = 0.01
        thick_sock.max_value = 100.0

        ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # --- Nodes ---
    x = -1600
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (x, 0)

    x += 200
    gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    gp_to_curves.location = (x, 0)
    gp_to_curves.inputs['Layers as Instances'].default_value = False

    x += 200
    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (x, 0)

    # --- Adaptive merge distances ---
    bbox = ng.nodes.new('GeometryNodeBoundBox')
    bbox.location = (x + 200, -300)

    bbox_sub = ng.nodes.new('ShaderNodeVectorMath')
    bbox_sub.location = (x + 400, -300)
    bbox_sub.operation = 'SUBTRACT'

    bbox_len = ng.nodes.new('ShaderNodeVectorMath')
    bbox_len.location = (x + 600, -300)
    bbox_len.operation = 'LENGTH'

    bbox_scale_small = ng.nodes.new('ShaderNodeMath')
    bbox_scale_small.location = (x + 800, -250)
    bbox_scale_small.operation = 'MULTIPLY'
    bbox_scale_small.inputs[1].default_value = 0.025

    bbox_scale_large = ng.nodes.new('ShaderNodeMath')
    bbox_scale_large.location = (x + 800, -350)
    bbox_scale_large.operation = 'MULTIPLY'
    bbox_scale_large.inputs[1].default_value = 0.25

    x += 200
    merge_dupes = ng.nodes.new('GeometryNodeMergeByDistance')
    merge_dupes.location = (x, 0)

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

    # --- Center the flat face so extrusion straddles the surface ---
    x += 200
    normal_node = ng.nodes.new('GeometryNodeInputNormal')
    normal_node.location = (x, -200)

    negate_half = ng.nodes.new('ShaderNodeMath')
    negate_half.location = (x, -350)
    negate_half.operation = 'MULTIPLY'
    negate_half.inputs[1].default_value = -0.5

    x += 200
    scale_normal = ng.nodes.new('ShaderNodeVectorMath')
    scale_normal.location = (x, -200)
    scale_normal.operation = 'SCALE'

    x += 200
    offset_pos = ng.nodes.new('GeometryNodeSetPosition')
    offset_pos.location = (x, 0)

    x += 200
    extrude = ng.nodes.new('GeometryNodeExtrudeMesh')
    extrude.location = (x, 0)
    extrude.inputs['Individual'].default_value = False

    flip = ng.nodes.new('GeometryNodeFlipFaces')
    flip.location = (x - 200, -200)

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

    link(merge_join.outputs['Geometry'], mesh_to_curve.inputs['Mesh'])
    link(mesh_to_curve.outputs['Curve'], set_cyclic.inputs['Curve'])
    link(set_cyclic.outputs['Curve'], resample.inputs['Curve'])
    link(group_in.outputs['Resolution'], resample.inputs['Count'])
    link(resample.outputs['Curve'], fill_curve.inputs['Curve'])

    link(fill_curve.outputs['Mesh'], merge.inputs['Geometry'])

    # Offset: Normal * (-Thickness / 2)
    link(group_in.outputs['Thickness'], negate_half.inputs[0])
    link(normal_node.outputs['Normal'], scale_normal.inputs[0])
    link(negate_half.outputs['Value'], scale_normal.inputs['Scale'])

    link(merge.outputs['Geometry'], offset_pos.inputs['Geometry'])
    link(scale_normal.outputs['Vector'], offset_pos.inputs['Offset'])

    link(offset_pos.outputs['Geometry'], flip.inputs['Mesh'])
    link(offset_pos.outputs['Geometry'], extrude.inputs['Mesh'])
    link(group_in.outputs['Thickness'], extrude.inputs['Offset Scale'])

    link(extrude.outputs['Mesh'], join.inputs['Geometry'])
    link(flip.outputs['Mesh'], join.inputs['Geometry'])
    link(join.outputs['Geometry'], merge_final.inputs['Geometry'])
    link(merge_final.outputs['Geometry'], group_out.inputs['Geometry'])

    return ng


def _find_target_mesh(context, gp_obj):
    """Find a selected mesh object that isn't the active GP."""
    for obj in context.selected_objects:
        if obj != gp_obj and obj.type == 'MESH':
            return obj
    return None


def _extract_cutter_mesh(context, gp_obj, thickness, resolution):
    """Create a cutter mesh from GP using the BoolCutter node group via depsgraph."""
    node_group = get_or_create_bool_cutter_node_group()
    mod = gp_obj.modifiers.new(name="_BoolCutter", type='NODES')
    mod.node_group = node_group
    mod[mod.node_group.interface.items_tree['Thickness'].identifier] = thickness
    mod[mod.node_group.interface.items_tree['Resolution'].identifier] = resolution

    # Force depsgraph to pick up the new modifier
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()

    # Extract mesh data from depsgraph instances
    verts = []
    faces = []
    for inst in depsgraph.object_instances:
        if inst.object.original == gp_obj and inst.is_instance:
            mesh_data = inst.object.to_mesh()
            if mesh_data and len(mesh_data.vertices) > 0:
                verts = [v.co[:] for v in mesh_data.vertices]
                faces = [list(p.vertices) for p in mesh_data.polygons]
            inst.object.to_mesh_clear()
            break

    # Remove the temporary modifier
    gp_obj.modifiers.remove(mod)

    if not verts:
        return None

    # Build cutter mesh object
    cutter_mesh = bpy.data.meshes.new("_BoolCutter")
    cutter_mesh.from_pydata(verts, [], faces)
    cutter_mesh.update()

    cutter_obj = bpy.data.objects.new("_BoolCutter", cutter_mesh)
    for col in gp_obj.users_collection:
        col.objects.link(cutter_obj)
    cutter_obj.matrix_world = gp_obj.matrix_world.copy()

    return cutter_obj


class GPTOOLS_OT_bool_cut(bpy.types.Operator):
    """Boolean-cut a shape drawn with Grease Pencil from a target mesh"""

    bl_idname = "gptools.bool_cut"
    bl_label = "Bool Cut"
    bl_options = {"REGISTER", "UNDO"}

    cut_depth: bpy.props.FloatProperty(
        name="Cut Depth",
        default=10.0,
        min=0.01,
        max=1000.0,
        description="Thickness of the cutter volume — must exceed target mesh thickness",
    )
    resolution: bpy.props.IntProperty(
        name="Resolution",
        default=64,
        min=8,
        max=512,
        description="Number of points to resample the cut shape",
    )

    @classmethod
    def poll(cls, context):
        gp = get_active_grease_pencil(context)
        if gp is None:
            return False
        return any(
            obj != gp and obj.type == 'MESH' for obj in context.selected_objects
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        target = _find_target_mesh(context, gp_obj)

        if not target:
            self.report({"ERROR"}, "No selected mesh object found as cut target")
            return {"CANCELLED"}

        # Create cutter mesh from GP strokes (already centered on surface)
        cutter = _extract_cutter_mesh(context, gp_obj, self.cut_depth, self.resolution)
        if not cutter:
            self.report({"ERROR"}, "Could not create cutter mesh from GP strokes")
            return {"CANCELLED"}

        # Ensure cutter is visible to the boolean modifier
        context.view_layer.update()

        # Add boolean modifier to target mesh
        bool_mod = target.modifiers.new(name="BoolCut", type='BOOLEAN')
        bool_mod.operation = 'DIFFERENCE'
        bool_mod.solver = 'EXACT'
        bool_mod.object = cutter

        # Hide cutter from viewport (boolean still uses it)
        cutter.hide_set(True)

        # Apply the boolean modifier via depsgraph (avoids nested undo steps
        # that break Ctrl+Z when using bpy.ops.object.modifier_apply).
        context.view_layer.objects.active = target
        try:
            depsgraph = context.evaluated_depsgraph_get()
            eval_target = target.evaluated_get(depsgraph)
            new_mesh = bpy.data.meshes.new_from_object(eval_target)
            if new_mesh is None or len(new_mesh.vertices) == 0:
                raise RuntimeError("Boolean produced no geometry")
            old_mesh = target.data
            new_mesh.name = old_mesh.name
            target.data = new_mesh
            # Don't remove old_mesh — bypasses undo system.
            target.modifiers.remove(bool_mod)
        except Exception as e:
            self.report({"ERROR"}, f"Boolean failed: {e}")
            bpy.data.objects.remove(cutter, do_unlink=True)
            return {"CANCELLED"}

        # Verify the boolean didn't destroy the target
        if len(target.data.polygons) == 0:
            self.report({"ERROR"}, "Boolean produced empty geometry — try adjusting Cut Depth")
            bpy.data.objects.remove(cutter, do_unlink=True)
            return {"CANCELLED"}

        # Cleanup: delete GP object and cutter
        bpy.data.objects.remove(gp_obj, do_unlink=True)
        bpy.data.objects.remove(cutter, do_unlink=True)

        # Leave target selected and active
        target.select_set(True)
        context.view_layer.objects.active = target

        self.report({"INFO"}, f"Bool cut applied to '{target.name}'")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_bool_cut,
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
