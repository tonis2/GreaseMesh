import bpy
from ..utils.conversion import get_active_grease_pencil
from ..utils.modifier_io import set_input
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
PAINT_LAYER_NAME = "Paint"


def _layer_has_strokes(layer):
    return any(len(f.drawing.strokes) > 0 for f in layer.frames)


def _gather_path_points_local(gp_obj):
    """Path strokes are anything NOT on the Paint layer — typically the GP's
    default 'Layer'. Collected for the PCA basis fit."""
    pts = []
    for layer in gp_obj.data.layers:
        if layer.name == PAINT_LAYER_NAME:
            continue
        for frame in layer.frames:
            for s in frame.drawing.strokes:
                for p in s.points:
                    pts.append(p.position.copy())
    return pts


def ensure_gp_layers(gp_obj):
    """Ensure a 'Paint' layer exists with a drawable frame. The default GP
    layer (typically 'Layer') is used for path strokes — we never rename it,
    so the user keeps their familiar default layer for drawing the spine."""
    gp_data = gp_obj.data
    scene_frame = bpy.context.scene.frame_current

    paint = gp_data.layers.get(PAINT_LAYER_NAME)
    if paint is None:
        paint = gp_data.layers.new(PAINT_LAYER_NAME)
    if len(paint.frames) == 0:
        paint.frames.new(scene_frame)


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

    tj = iface.new_socket(name="Thickness Jitter", in_out='INPUT', socket_type='NodeSocketFloat')
    tj.default_value, tj.min_value, tj.max_value = 0.0, 0.0, 1.0
    tj.subtype = 'FACTOR'

    sj = iface.new_socket(name="Scale Jitter", in_out='INPUT', socket_type='NodeSocketFloat')
    sj.default_value, sj.min_value, sj.max_value = 0.0, 0.0, 1.0
    sj.subtype = 'FACTOR'

    rj = iface.new_socket(name="Rotation Jitter", in_out='INPUT', socket_type='NodeSocketFloat')
    rj.default_value, rj.min_value, rj.max_value = 0.0, 0.0, 1.5707963
    rj.subtype = 'ANGLE'

    jseed = iface.new_socket(name="Jitter Seed", in_out='INPUT', socket_type='NodeSocketInt')
    jseed.default_value, jseed.min_value, jseed.max_value = 0, 0, 10000

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

    # ── Per-block jitter ────────────────────────────────────────────────────
    # Each Paint stroke fills as a disjoint mesh island. Mesh Island Index is
    # a stable per-block ID across all evaluation domains (vertex/face/edge),
    # which is what we need to drive Random Value consistently and to compute
    # a per-block centroid via AccumulateField grouped by island.
    #
    # CaptureAttribute(domain=FACE) was tried first but in this Blender build
    # its value field is evaluated per-vertex regardless of the domain knob,
    # so per-face Index/Position came back as per-vertex values.
    captured_geom = fill.outputs['Mesh']

    isl = nodes.new('GeometryNodeInputMeshIsland'); isl.location = (700, -360)
    block_id_field = isl.outputs['Island Index']

    # Per-island centroid via AccumulateField: total Position summed per island,
    # divided by per-island vertex count (also via AccumulateField summing 1).
    pos_for_cen = nodes.new('GeometryNodeInputPosition'); pos_for_cen.location = (700, -200)
    acc_pos = nodes.new('GeometryNodeAccumulateField'); acc_pos.location = (900, -200)
    acc_pos.data_type = 'FLOAT_VECTOR'
    acc_pos.domain = 'POINT'
    link(pos_for_cen.outputs['Position'], acc_pos.inputs['Value'])
    link(isl.outputs['Island Index'], acc_pos.inputs['Group ID'])

    one_const = nodes.new('ShaderNodeValue'); one_const.location = (700, -100)
    one_const.outputs['Value'].default_value = 1.0
    acc_count = nodes.new('GeometryNodeAccumulateField'); acc_count.location = (900, -100)
    acc_count.data_type = 'FLOAT'
    acc_count.domain = 'POINT'
    link(one_const.outputs['Value'], acc_count.inputs['Value'])
    link(isl.outputs['Island Index'], acc_count.inputs['Group ID'])

    inv_count = nodes.new('ShaderNodeMath'); inv_count.location = (1100, -100)
    inv_count.operation = 'DIVIDE'
    inv_count.inputs[0].default_value = 1.0
    link(acc_count.outputs['Total'], inv_count.inputs[1])

    centroid_scale = nodes.new('ShaderNodeVectorMath'); centroid_scale.location = (1300, -150)
    centroid_scale.operation = 'SCALE'
    link(acc_pos.outputs['Total'], centroid_scale.inputs[0])
    link(inv_count.outputs['Value'], centroid_scale.inputs['Scale'])
    centroid_field = centroid_scale.outputs['Vector']

    def _seeded_rand(label, seed_offset, x_off):
        # Three independent per-block randoms by adding offsets to Jitter Seed
        seed_node = nodes.new('ShaderNodeMath'); seed_node.location = (1100 + x_off, 800)
        seed_node.operation = 'ADD'
        seed_node.inputs[1].default_value = float(seed_offset)
        link(group_in.outputs['Jitter Seed'], seed_node.inputs[0])

        r = nodes.new('FunctionNodeRandomValue'); r.location = (1300 + x_off, 800)
        r.data_type = 'FLOAT'
        r.inputs['Min'].default_value = -1.0
        r.inputs['Max'].default_value = 1.0
        link(block_id_field, r.inputs['ID'])
        link(seed_node.outputs['Value'], r.inputs['Seed'])
        r.label = label
        return r.outputs['Value']

    rand_thick = _seeded_rand('thick', 0,    0)
    rand_scale = _seeded_rand('scale', 31, 250)
    rand_rot   = _seeded_rand('rot',   67, 500)

    # rot_angle  = rand_rot * Rotation Jitter   (radians)
    rot_mul = nodes.new('ShaderNodeMath'); rot_mul.location = (1900, 800); rot_mul.operation = 'MULTIPLY'
    link(rand_rot, rot_mul.inputs[0])
    link(group_in.outputs['Rotation Jitter'], rot_mul.inputs[1])

    # scale_factor = 1 + rand_scale * Scale Jitter
    sj_mul = nodes.new('ShaderNodeMath'); sj_mul.location = (1500, 1000); sj_mul.operation = 'MULTIPLY'
    link(rand_scale, sj_mul.inputs[0])
    link(group_in.outputs['Scale Jitter'], sj_mul.inputs[1])
    sj_add = nodes.new('ShaderNodeMath'); sj_add.location = (1700, 1000); sj_add.operation = 'ADD'
    sj_add.inputs[1].default_value = 1.0
    link(sj_mul.outputs['Value'], sj_add.inputs[0])

    # thick_factor = 1 + rand_thick * Thickness Jitter
    tj_mul = nodes.new('ShaderNodeMath'); tj_mul.location = (1500, 1200); tj_mul.operation = 'MULTIPLY'
    link(rand_thick, tj_mul.inputs[0])
    link(group_in.outputs['Thickness Jitter'], tj_mul.inputs[1])
    tj_add = nodes.new('ShaderNodeMath'); tj_add.location = (1700, 1200); tj_add.operation = 'ADD'
    tj_add.inputs[1].default_value = 1.0
    link(tj_mul.outputs['Value'], tj_add.inputs[0])

    # Per-vertex transform in basis frame: rotate around face centroid (Z-axis,
    # which is the basis Normal), then scale around the same point.
    pos_for_jitter = nodes.new('GeometryNodeInputPosition'); pos_for_jitter.location = (1900, 600)
    vrot = nodes.new('ShaderNodeVectorRotate'); vrot.location = (2100, 600)
    vrot.rotation_type = 'Z_AXIS'
    link(pos_for_jitter.outputs['Position'], vrot.inputs['Vector'])
    link(centroid_field, vrot.inputs['Center'])
    link(rot_mul.outputs['Value'], vrot.inputs['Angle'])

    rel_after_rot = nodes.new('ShaderNodeVectorMath'); rel_after_rot.location = (2300, 600)
    rel_after_rot.operation = 'SUBTRACT'
    link(vrot.outputs['Vector'], rel_after_rot.inputs[0])
    link(centroid_field, rel_after_rot.inputs[1])

    scaled_rel = _add_scale(ng, rel_after_rot.outputs['Vector'], sj_add.outputs['Value'])
    jittered_pos = _add_vec_op(ng, 'ADD', scaled_rel, centroid_field)

    set_pos_jitter = nodes.new('GeometryNodeSetPosition'); set_pos_jitter.location = (2700, 0)
    link(captured_geom, set_pos_jitter.inputs['Geometry'])
    link(jittered_pos, set_pos_jitter.inputs['Position'])

    # Reverse basis change on (jittered) filled mesh: world = Center + p.x·U + p.y·V
    pos2 = nodes.new('GeometryNodeInputPosition'); pos2.location = (2800, 300)
    sep_pos = nodes.new('ShaderNodeSeparateXYZ'); sep_pos.location = (3000, 300)
    link(pos2.outputs['Position'], sep_pos.inputs[0])

    u_scaled = _add_scale(ng, group_in.outputs['U'], sep_pos.outputs['X'])
    v_scaled = _add_scale(ng, group_in.outputs['V'], sep_pos.outputs['Y'])
    uv_sum = _add_vec_op(ng, 'ADD', u_scaled, v_scaled)
    world_back = _add_vec_op(ng, 'ADD', uv_sum, group_in.outputs['Center'])

    set_pos_back = nodes.new('GeometryNodeSetPosition'); set_pos_back.location = (3500, 0)
    link(set_pos_jitter.outputs['Geometry'], set_pos_back.inputs['Geometry'])
    link(world_back, set_pos_back.inputs['Position'])

    merge_pre_extrude = nodes.new('GeometryNodeMergeByDistance'); merge_pre_extrude.location = (3700, 0)
    merge_pre_extrude.inputs['Distance'].default_value = 0.001
    link(set_pos_back.outputs['Geometry'], merge_pre_extrude.inputs['Geometry'])

    # Per-face thickness for Extrude — same thick_factor field re-evaluated on
    # FACE domain (named-attribute lookup on FACE returns one value per face).
    extrude_scale_field = nodes.new('ShaderNodeMath'); extrude_scale_field.location = (3700, -200)
    extrude_scale_field.operation = 'MULTIPLY'
    link(group_in.outputs['Thickness'], extrude_scale_field.inputs[0])
    link(tj_add.outputs['Value'], extrude_scale_field.inputs[1])

    extrude = nodes.new('GeometryNodeExtrudeMesh'); extrude.location = (3900, 0)
    extrude.inputs['Individual'].default_value = False
    link(merge_pre_extrude.outputs['Geometry'], extrude.inputs['Mesh'])
    link(group_in.outputs['Normal'], extrude.inputs['Offset'])
    link(extrude_scale_field.outputs['Value'], extrude.inputs['Offset Scale'])

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
    on the plane fitted through strokes on the default (non-Paint) layer."""

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

        path_pts = _gather_path_points_local(gp_obj)
        if len(path_pts) < 3:
            # Activate the first non-Paint layer so the user can draw on it
            for layer in gp_obj.data.layers:
                if layer.name != PAINT_LAYER_NAME:
                    gp_obj.data.layers.active = layer
                    break
            _show_properties_tab(context, 'DATA')
            self.report(
                {"WARNING"},
                "Draw a line on any non-'Paint' layer first, then click Blocks again.",
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
                set_input(mod, item.identifier, socket_values[item.name])

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
