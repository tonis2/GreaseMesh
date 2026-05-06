import bpy
from ..utils.conversion import get_active_grease_pencil
from .gn_solid_mesh import (
    _pca_plane,
    _viewport_camera_position,
    _sign_correct_outward,
    _build_basis,
    _add_dot,
    _add_scale,
    _add_vec_op,
)

NODE_GROUP_NAME = "GreaseMesh_Blocks"
MODIFIER_NAME = "BlocksMesh"
PATH_LAYER_NAME = "Path"
PAINT_LAYER_NAME = "Paint"


def _layer_has_strokes(layer):
    return any(len(f.drawing.strokes) > 0 for f in layer.frames)


def _gather_layer_points_local(gp_obj, layer_name):
    layer = gp_obj.data.layers.get(layer_name)
    if layer is None:
        return []
    pts = []
    for frame in layer.frames:
        for s in frame.drawing.strokes:
            for p in s.points:
                pts.append(p.position.copy())
    return pts


def ensure_gp_layers(gp_obj):
    """Ensure 'Path' and 'Paint' layers exist with drawable frames.

    If neither exists yet but a layer with strokes does, rename the first such
    layer to 'Path' so the user's first drawing seeds the basis.
    """
    gp_data = gp_obj.data
    scene_frame = bpy.context.scene.frame_current

    has_path = gp_data.layers.get(PATH_LAYER_NAME)
    has_paint = gp_data.layers.get(PAINT_LAYER_NAME)

    if not has_path and not has_paint:
        for layer in gp_data.layers:
            if _layer_has_strokes(layer):
                layer.name = PATH_LAYER_NAME
                break

    for name in (PATH_LAYER_NAME, PAINT_LAYER_NAME):
        layer = gp_data.layers.get(name)
        if layer is None:
            layer = gp_data.layers.new(name)
        if len(layer.frames) == 0:
            layer.frames.new(scene_frame)


def _show_properties_tab(context, tab):
    try:
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        space.context = tab
                        return
    except TypeError:
        pass


# ---------------------------------------------------------------------------
# Geometry Nodes graph — basis-change pipeline applied per-Paint-stroke.
#
#   GP (Paint layer only)
#     → Fillet Curve         (per-spline corner rounding on raw 3D points)
#     → Curve→Mesh           (polyline edges in 3D)
#     → Set Position #1      (forward basis: pos' = (rel·U, rel·V, rel·N))
#     → Merge ×2             (collapse dupes; bridge open endpoints per stroke)
#     → Mesh→Curve, Set Cyclic, Resample
#     → Fill Curve           (one face per closed stroke, on Z≈0 in basis)
#     → Set Position #2      (reverse basis: world = Center + p.x·U + p.y·V)
#     → Extrude along Normal (Offset=Normal, Scale=Thickness; per-face independent)
#     + Flip Faces (back caps)
#     → Join, Merge, Noise displacement → Output
# ---------------------------------------------------------------------------


def get_or_create_blocks_node_group():
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        ng.nodes.clear()
        for item in list(ng.interface.items_tree):
            ng.interface.remove(item)
    else:
        ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

    iface = ng.interface
    iface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')

    res = iface.new_socket(name="Resolution", in_out='INPUT', socket_type='NodeSocketInt')
    res.default_value, res.min_value, res.max_value = 64, 8, 512

    thick = iface.new_socket(name="Thickness", in_out='INPUT', socket_type='NodeSocketFloat')
    thick.default_value, thick.min_value, thick.max_value = 0.4, 0.0, 20.0

    cr = iface.new_socket(name="Corner Radius", in_out='INPUT', socket_type='NodeSocketFloat')
    cr.default_value, cr.min_value, cr.max_value = 0.0, 0.0, 10.0

    cres = iface.new_socket(name="Corner Resolution", in_out='INPUT', socket_type='NodeSocketInt')
    cres.default_value, cres.min_value, cres.max_value = 4, 1, 32

    ns = iface.new_socket(name="Noise Strength", in_out='INPUT', socket_type='NodeSocketFloat')
    ns.default_value, ns.min_value, ns.max_value = 0.0, 0.0, 1.0

    nsc = iface.new_socket(name="Noise Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    nsc.default_value, nsc.min_value, nsc.max_value = 3.0, 0.1, 50.0

    nd = iface.new_socket(name="Noise Detail", in_out='INPUT', socket_type='NodeSocketFloat')
    nd.default_value, nd.min_value, nd.max_value = 4.0, 0.0, 15.0

    nseed = iface.new_socket(name="Noise Seed", in_out='INPUT', socket_type='NodeSocketInt')
    nseed.default_value, nseed.min_value, nseed.max_value = 0, 0, 10000

    for hidden_name, default in (
        ("Center", (0.0, 0.0, 0.0)),
        ("U", (1.0, 0.0, 0.0)),
        ("V", (0.0, 1.0, 0.0)),
        ("Normal", (0.0, 0.0, 1.0)),
    ):
        s = iface.new_socket(name=hidden_name, in_out='INPUT', socket_type='NodeSocketVector')
        s.default_value = default
        s.hide_in_modifier = True

    iface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    link = ng.links.new
    nodes = ng.nodes

    group_in = nodes.new('NodeGroupInput'); group_in.location = (-2400, 0)

    # Filter input GP to the Paint layer only — Path layer is operator-side basis source.
    paint_sel = nodes.new('GeometryNodeInputNamedLayerSelection'); paint_sel.location = (-2300, -150)
    paint_sel.inputs['Name'].default_value = PAINT_LAYER_NAME

    gp_to_curves = nodes.new('GeometryNodeGreasePencilToCurves'); gp_to_curves.location = (-2100, 0)
    gp_to_curves.inputs['Layers as Instances'].default_value = False
    link(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])
    link(paint_sel.outputs['Selection'], gp_to_curves.inputs['Selection'])

    # Per-spline fillet (corner rounding) on raw 3D points before resample.
    fillet = nodes.new('GeometryNodeFilletCurve'); fillet.location = (-1900, 0)
    fillet.inputs['Mode'].default_value = 'Poly'
    link(gp_to_curves.outputs['Curves'], fillet.inputs['Curve'])
    link(group_in.outputs['Corner Radius'], fillet.inputs['Radius'])
    link(group_in.outputs['Corner Resolution'], fillet.inputs['Count'])

    curve_to_mesh = nodes.new('GeometryNodeCurveToMesh'); curve_to_mesh.location = (-1700, 0)
    link(fillet.outputs['Curve'], curve_to_mesh.inputs['Curve'])

    # Forward basis change on mesh: pos' = (rel·U, rel·V, rel·N) where rel = pos − Center
    pos1 = nodes.new('GeometryNodeInputPosition'); pos1.location = (-1600, 300)
    rel1 = nodes.new('ShaderNodeVectorMath'); rel1.location = (-1400, 300); rel1.operation = 'SUBTRACT'
    link(pos1.outputs['Position'], rel1.inputs[0])
    link(group_in.outputs['Center'], rel1.inputs[1])

    dot_u = _add_dot(ng, "rel·U", rel1.outputs['Vector'], group_in.outputs['U'])
    dot_v = _add_dot(ng, "rel·V", rel1.outputs['Vector'], group_in.outputs['V'])
    dot_n = _add_dot(ng, "rel·N", rel1.outputs['Vector'], group_in.outputs['Normal'])

    combine_uvn = nodes.new('ShaderNodeCombineXYZ'); combine_uvn.location = (-800, 300)
    link(dot_u, combine_uvn.inputs['X'])
    link(dot_v, combine_uvn.inputs['Y'])
    link(dot_n, combine_uvn.inputs['Z'])

    set_pos_fwd = nodes.new('GeometryNodeSetPosition'); set_pos_fwd.location = (-600, 0)
    link(curve_to_mesh.outputs['Mesh'], set_pos_fwd.inputs['Geometry'])
    link(combine_uvn.outputs['Vector'], set_pos_fwd.inputs['Position'])

    # NOTE: deliberately NO bbox-driven merge here. Solid uses one because its
    # input is a single stroke, but Blocks has N spatially-close paint strokes —
    # a bbox-relative merge would weld neighbors together and erase any block
    # whose perimeter sits within ~2.5% of the overall bbox diagonal of another.
    # Cyclic input strokes already close themselves through Curve→Mesh, and
    # Set Cyclic(True) below handles open input.

    mesh_to_curve = nodes.new('GeometryNodeMeshToCurve'); mesh_to_curve.location = (0, 0)
    link(set_pos_fwd.outputs['Geometry'], mesh_to_curve.inputs['Mesh'])

    set_cyclic = nodes.new('GeometryNodeSetSplineCyclic'); set_cyclic.location = (200, 0)
    set_cyclic.inputs['Cyclic'].default_value = True
    link(mesh_to_curve.outputs['Curve'], set_cyclic.inputs['Curve'])

    resample = nodes.new('GeometryNodeResampleCurve'); resample.location = (400, 0)
    link(set_cyclic.outputs['Curve'], resample.inputs['Curve'])
    link(group_in.outputs['Resolution'], resample.inputs['Count'])

    fill = nodes.new('GeometryNodeFillCurve'); fill.location = (600, 0)
    link(resample.outputs['Curve'], fill.inputs['Curve'])

    # Reverse basis change on filled mesh: world = Center + p.x·U + p.y·V (Z=0 from Fill)
    pos2 = nodes.new('GeometryNodeInputPosition'); pos2.location = (700, 300)
    sep_pos = nodes.new('ShaderNodeSeparateXYZ'); sep_pos.location = (900, 300)
    link(pos2.outputs['Position'], sep_pos.inputs[0])

    u_scaled = _add_scale(ng, group_in.outputs['U'], sep_pos.outputs['X'])
    v_scaled = _add_scale(ng, group_in.outputs['V'], sep_pos.outputs['Y'])
    uv_sum = _add_vec_op(ng, 'ADD', u_scaled, v_scaled)
    world_back = _add_vec_op(ng, 'ADD', uv_sum, group_in.outputs['Center'])

    set_pos_back = nodes.new('GeometryNodeSetPosition'); set_pos_back.location = (1800, 0)
    link(fill.outputs['Mesh'], set_pos_back.inputs['Geometry'])
    link(world_back, set_pos_back.inputs['Position'])

    merge_pre_extrude = nodes.new('GeometryNodeMergeByDistance'); merge_pre_extrude.location = (2000, 0)
    merge_pre_extrude.inputs['Distance'].default_value = 0.001
    link(set_pos_back.outputs['Geometry'], merge_pre_extrude.inputs['Geometry'])

    extrude = nodes.new('GeometryNodeExtrudeMesh'); extrude.location = (2200, 0)
    extrude.inputs['Individual'].default_value = False
    link(merge_pre_extrude.outputs['Geometry'], extrude.inputs['Mesh'])
    link(group_in.outputs['Normal'], extrude.inputs['Offset'])
    link(group_in.outputs['Thickness'], extrude.inputs['Offset Scale'])

    flip = nodes.new('GeometryNodeFlipFaces'); flip.location = (2200, -200)
    link(merge_pre_extrude.outputs['Geometry'], flip.inputs['Mesh'])

    join = nodes.new('GeometryNodeJoinGeometry'); join.location = (2400, 0)
    link(extrude.outputs['Mesh'], join.inputs['Geometry'])
    link(flip.outputs['Mesh'], join.inputs['Geometry'])

    merge_post_extrude = nodes.new('GeometryNodeMergeByDistance'); merge_post_extrude.location = (2600, 0)
    merge_post_extrude.inputs['Distance'].default_value = 0.001
    link(join.outputs['Geometry'], merge_post_extrude.inputs['Geometry'])

    # Noise displacement (post-extrude), same shape as Path operator
    noise_pos = nodes.new('GeometryNodeInputPosition'); noise_pos.location = (2600, -300)

    seed_mul = nodes.new('ShaderNodeMath'); seed_mul.location = (2600, -500); seed_mul.operation = 'MULTIPLY'
    seed_mul.inputs[1].default_value = 137.3
    link(group_in.outputs['Noise Seed'], seed_mul.inputs[0])

    seed_combine = nodes.new('ShaderNodeCombineXYZ'); seed_combine.location = (2800, -500)
    link(seed_mul.outputs['Value'], seed_combine.inputs['X'])
    link(seed_mul.outputs['Value'], seed_combine.inputs['Y'])
    link(seed_mul.outputs['Value'], seed_combine.inputs['Z'])

    seed_add = nodes.new('ShaderNodeVectorMath'); seed_add.location = (2800, -300); seed_add.operation = 'ADD'
    link(noise_pos.outputs['Position'], seed_add.inputs[0])
    link(seed_combine.outputs['Vector'], seed_add.inputs[1])

    noise_tex = nodes.new('ShaderNodeTexNoise'); noise_tex.location = (3000, -300)
    noise_tex.noise_dimensions = '3D'
    link(seed_add.outputs['Vector'], noise_tex.inputs['Vector'])
    link(group_in.outputs['Noise Scale'], noise_tex.inputs['Scale'])
    link(group_in.outputs['Noise Detail'], noise_tex.inputs['Detail'])

    noise_center = nodes.new('ShaderNodeVectorMath'); noise_center.location = (3200, -300); noise_center.operation = 'SUBTRACT'
    noise_center.inputs[1].default_value = (0.5, 0.5, 0.5)
    link(noise_tex.outputs['Color'], noise_center.inputs[0])

    noise_scale = nodes.new('ShaderNodeVectorMath'); noise_scale.location = (3400, -300); noise_scale.operation = 'SCALE'
    link(noise_center.outputs['Vector'], noise_scale.inputs[0])
    link(group_in.outputs['Noise Strength'], noise_scale.inputs['Scale'])

    noise_set_pos = nodes.new('GeometryNodeSetPosition'); noise_set_pos.location = (3600, 0)
    link(merge_post_extrude.outputs['Geometry'], noise_set_pos.inputs['Geometry'])
    link(noise_scale.outputs['Vector'], noise_set_pos.inputs['Offset'])

    group_out = nodes.new('NodeGroupOutput'); group_out.location = (3800, 0)
    link(noise_set_pos.outputs['Geometry'], group_out.inputs['Geometry'])

    return ng


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class GPTOOLS_OT_gn_blocks_mesh(bpy.types.Operator):
    """Add a Geometry Nodes modifier on the Grease Pencil that turns each
    closed stroke on the 'Paint' layer into its own extruded solid, oriented
    on the plane fitted through the 'Path' layer's strokes."""

    bl_idname = "gptools.gn_blocks_mesh"
    bl_label = "Blocks Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        ensure_gp_layers(gp_obj)

        path_pts = _gather_layer_points_local(gp_obj, PATH_LAYER_NAME)
        if len(path_pts) < 3:
            path_layer = gp_obj.data.layers.get(PATH_LAYER_NAME)
            if path_layer is not None:
                gp_obj.data.layers.active = path_layer
            _show_properties_tab(context, 'DATA')
            self.report(
                {"WARNING"},
                "Draw on the 'Path' layer first, then click Blocks again.",
            )
            return {"CANCELLED"}

        centroid_local, normal_local = _pca_plane(path_pts)

        mw = gp_obj.matrix_world
        centroid_world = mw @ centroid_local
        normal_world = (mw.to_3x3() @ normal_local).normalized()
        oriented = _sign_correct_outward(centroid_world, normal_world, gp_obj, context)
        if (oriented - normal_world).length > 1e-6:
            normal_local = -normal_local
        normal_local.normalize()

        u_local, v_local = _build_basis(normal_local)

        node_group = get_or_create_blocks_node_group()

        mod = gp_obj.modifiers.get(MODIFIER_NAME)
        if mod is None or mod.type != 'NODES':
            mod = gp_obj.modifiers.new(name=MODIFIER_NAME, type='NODES')
        mod.node_group = node_group

        socket_values = {
            'Center': (centroid_local.x, centroid_local.y, centroid_local.z),
            'U':      (u_local.x, u_local.y, u_local.z),
            'V':      (v_local.x, v_local.y, v_local.z),
            'Normal': (normal_local.x, normal_local.y, normal_local.z),
        }
        for item in node_group.interface.items_tree:
            if getattr(item, 'in_out', None) != 'INPUT':
                continue
            if item.name in socket_values:
                mod[item.identifier] = socket_values[item.name]

        gp_obj.update_tag()

        for o in context.view_layer.objects:
            if o.select_get():
                o.select_set(False)
        gp_obj.select_set(True)
        context.view_layer.objects.active = gp_obj

        _show_properties_tab(context, 'MODIFIER')

        paint_layer = gp_obj.data.layers.get(PAINT_LAYER_NAME)
        if paint_layer is not None and not _layer_has_strokes(paint_layer):
            self.report(
                {"INFO"},
                "Blocks modifier added. Activate the 'Paint' layer and draw closed strokes — each becomes its own block.",
            )
        else:
            self.report(
                {"INFO"},
                "Blocks modifier added/updated. Each closed stroke on the 'Paint' layer is now its own block.",
            )
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_gn_blocks_mesh,
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
