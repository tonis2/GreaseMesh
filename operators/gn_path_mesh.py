import math

import bpy
from ..utils.conversion import get_active_grease_pencil
from ..utils.modifier_io import set_menu, ensure_nodes_modifier, show_modifier_tab
from ..utils.node_groups import get_or_rebuild_group

NODE_GROUP_NAME = "GreaseMesh_Path"
GROUP_VERSION = 2  # bump whenever the graph or interface changes

PROFILE_LAYER_NAME = "Profile"
PATH_LAYER_NAME = "Path"


def _layer_has_strokes(layer):
    """Check if a GP layer has any drawn strokes."""
    return layer is not None and any(len(f.drawing.strokes) > 0 for f in layer.frames)


def ensure_gp_layers(gp_obj):
    """Ensure the GP object has 'Profile' and 'Path' layers with drawable frames.

    If neither layer exists yet but there's an existing layer with strokes,
    rename it to 'Path' so the user's first drawing is used as the sweep path.
    """
    gp_data = gp_obj.data
    scene_frame = bpy.context.scene.frame_current

    has_profile = gp_data.layers.get(PROFILE_LAYER_NAME)
    has_path = gp_data.layers.get(PATH_LAYER_NAME)

    # If no Profile/Path layers yet, adopt the first layer with strokes as Path
    if not has_profile and not has_path:
        for layer in gp_data.layers:
            if _layer_has_strokes(layer):
                layer.name = PATH_LAYER_NAME
                break

    # Create any missing layers with a drawable frame
    for name in [PROFILE_LAYER_NAME, PATH_LAYER_NAME]:
        layer = gp_data.layers.get(name)
        if layer is None:
            layer = gp_data.layers.new(name)
        if len(layer.frames) == 0:
            layer.frames.new(scene_frame)


def _build_interface(ng):
    """Create the modifier panel sockets."""
    ng.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry',
    )

    s = ng.interface.new_socket(
        name="Profile Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    s.default_value, s.min_value, s.max_value = 32, 3, 256

    s = ng.interface.new_socket(
        name="Path Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    s.default_value, s.min_value, s.max_value = 64, 3, 512

    s = ng.interface.new_socket(
        name="Fill Caps", in_out='INPUT', socket_type='NodeSocketBool',
    )
    s.default_value = True

    s = ng.interface.new_socket(
        name="Corner Radius", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 0.1, 0.0, 10.0

    s = ng.interface.new_socket(
        name="Corner Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    s.default_value, s.min_value, s.max_value = 4, 1, 32

    s = ng.interface.new_socket(
        name="Merge Distance", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 0.01, 0.0, 10.0
    s.subtype = 'DISTANCE'

    ng.interface.new_socket(
        name="Normal Mode", in_out='INPUT', socket_type='NodeSocketMenu',
    )

    s = ng.interface.new_socket(
        name="Noise Strength", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 0.0, 0.0, 1.0

    s = ng.interface.new_socket(
        name="Noise Scale", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 3.0, 0.1, 50.0

    s = ng.interface.new_socket(
        name="Noise Detail", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 4.0, 0.0, 15.0

    s = ng.interface.new_socket(
        name="Noise Seed", in_out='INPUT', socket_type='NodeSocketInt',
    )
    s.default_value, s.min_value, s.max_value = 0, 0, 10000

    ng.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry',
    )


def _add_gp_branch(ng, link, group_in, layer_name, res_socket_name, cyclic, x, y):
    """Build a GP → Curves → Resample (→ Set Cyclic) branch. Returns curve output."""
    sel = ng.nodes.new('GeometryNodeInputNamedLayerSelection')
    sel.location = (x, y)
    sel.inputs['Name'].default_value = layer_name

    gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    gp_to_curves.location = (x + 200, y)
    gp_to_curves.inputs['Layers as Instances'].default_value = False

    resample = ng.nodes.new('GeometryNodeResampleCurve')
    resample.location = (x + 400, y)

    link(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])
    link(sel.outputs['Selection'], gp_to_curves.inputs['Selection'])
    link(gp_to_curves.outputs['Curves'], resample.inputs['Curve'])
    link(group_in.outputs[res_socket_name], resample.inputs['Count'])

    out = resample.outputs['Curve']

    if cyclic:
        set_cyclic = ng.nodes.new('GeometryNodeSetSplineCyclic')
        set_cyclic.location = (x + 600, y)
        set_cyclic.inputs['Cyclic'].default_value = True
        link(out, set_cyclic.inputs['Curve'])
        out = set_cyclic.outputs['Curve']

    return out


def _node(ng, idname, loc, **props):
    """Create a node at ``loc`` and set the given RNA properties on it."""
    node = ng.nodes.new(idname)
    node.location = loc
    for key, value in props.items():
        setattr(node, key, value)
    return node


def _feed(link, socket, value):
    """Link ``value`` into ``socket`` if it is a socket, else set it as default."""
    if value is None:
        return
    if isinstance(value, bpy.types.NodeSocket):
        link(value, socket)
    else:
        socket.default_value = value


def _math(ng, link, op, a, b=None, loc=(0, 0), clamp=False):
    node = _node(ng, 'ShaderNodeMath', loc, operation=op, use_clamp=clamp)
    _feed(link, node.inputs[0], a)
    _feed(link, node.inputs[1], b)
    return node.outputs['Value']


def _imath(ng, link, op, a, b=None, c=None, loc=(0, 0)):
    node = _node(ng, 'FunctionNodeIntegerMath', loc, operation=op)
    _feed(link, node.inputs[0], a)
    _feed(link, node.inputs[1], b)
    _feed(link, node.inputs[2], c)
    return node.outputs['Value']


def _vmath(ng, link, op, a, b=None, loc=(0, 0), scale=None):
    node = _node(ng, 'ShaderNodeVectorMath', loc, operation=op)
    _feed(link, node.inputs[0], a)
    _feed(link, node.inputs[1], b)
    _feed(link, node.inputs[3], scale)  # 'Scale'
    out = 'Value' if op in {'DOT_PRODUCT', 'LENGTH', 'DISTANCE'} else 'Vector'
    return node.outputs[out]


def _compare(ng, link, op, a, b, loc=(0, 0)):
    node = _node(ng, 'FunctionNodeCompare', loc, data_type='FLOAT', operation=op)
    _feed(link, node.inputs['A'], a)
    _feed(link, node.inputs['B'], b)
    return node.outputs['Result']


def _switch(ng, link, input_type, cond, if_false, if_true, loc=(0, 0)):
    node = _node(ng, 'GeometryNodeSwitch', loc, input_type=input_type)
    _feed(link, node.inputs['Switch'], cond)
    _feed(link, node.inputs['False'], if_false)
    _feed(link, node.inputs['True'], if_true)
    return node.outputs['Output']


def _sample_index(ng, link, geometry, value, index, data_type, loc=(0, 0)):
    """Sample ``value`` on the point domain of ``geometry`` at ``index``."""
    node = _node(ng, 'GeometryNodeSampleIndex', loc, data_type=data_type, domain='POINT')
    link(geometry, node.inputs['Geometry'])
    link(value, node.inputs['Value'])
    _feed(link, node.inputs['Index'], index)
    return node.outputs['Value']


def _separate(ng, link, vec, loc=(0, 0)):
    node = _node(ng, 'ShaderNodeSeparateXYZ', loc)
    link(vec, node.inputs['Vector'])
    return node.outputs


def _add_axis_remap(ng, link, extent, vec, x, y):
    """Drop the thinnest axis of ``extent`` from ``vec``, remapping the other
    two to (X, Y, 0).  Works per element when ``extent`` is a field, so every
    profile can be drawn from its own view angle (top, front, side):

      X thinnest → (Y, Z)    Y thinnest → (X, Z)    Z thinnest → (X, Y)
    """
    ext = _separate(ng, link, extent, (x, y - 250))

    # x_thin = (ext_x <= ext_y) AND (ext_x <= ext_z)
    x_thin = _node(ng, 'FunctionNodeBooleanMath', (x + 400, y - 200), operation='AND')
    link(_compare(ng, link, 'LESS_EQUAL', ext['X'], ext['Y'], (x + 200, y - 150)), x_thin.inputs[0])
    link(_compare(ng, link, 'LESS_EQUAL', ext['X'], ext['Z'], (x + 200, y - 300)), x_thin.inputs[1])

    # y_thin = (ext_y < ext_x) AND (ext_y <= ext_z)
    y_thin = _node(ng, 'FunctionNodeBooleanMath', (x + 400, y - 500), operation='AND')
    link(_compare(ng, link, 'LESS_THAN', ext['Y'], ext['X'], (x + 200, y - 450)), y_thin.inputs[0])
    link(_compare(ng, link, 'LESS_EQUAL', ext['Y'], ext['Z'], (x + 200, y - 600)), y_thin.inputs[1])

    comp = _separate(ng, link, vec, (x, y + 100))
    remaps = {}
    for i, (axis, (a, b)) in enumerate((('X', ('Y', 'Z')), ('Y', ('X', 'Z')), ('Z', ('X', 'Y')))):
        node = _node(ng, 'ShaderNodeCombineXYZ', (x + 400, y + 200 - 150 * i))
        link(comp[a], node.inputs['X'])
        link(comp[b], node.inputs['Y'])
        remaps[axis] = node.outputs['Vector']

    yz = _switch(ng, link, 'VECTOR', y_thin.outputs['Boolean'], remaps['Z'], remaps['Y'],
                 (x + 600, y - 50))
    return _switch(ng, link, 'VECTOR', x_thin.outputs['Boolean'], yz, remaps['X'],
                   (x + 800, y + 100))


def _add_profile_alignment(ng, link, group_in, profiles, x, y):
    """Centre, flatten and normalise every profile stroke on its own.

    Each profile (one curve, exactly N = Profile Resolution points) is centred
    on its own bbox centre and flattened by its own thinnest bbox axis.  Then
    its point order is normalised so profiles blend without twisting:
      * winding: shoelace signed area of the flattened 2D shape; traversal is
        reversed when negative, so every profile is counter-clockwise (that is
        what makes Curve to Mesh produce outward facing normals);
      * start: the point with the smallest atan2(y, x) in [0, 2π) becomes 0.

    Returns (geometry, aligned, center): ``aligned`` is the flattened 2D point
    at aligned position ``Index in Curve`` and ``center`` the profile's bbox
    centre in object space, both captured on the point domain.
    """
    res = group_in.outputs['Profile Resolution']

    curve_of_pt = _node(ng, 'GeometryNodeCurveOfPoint', (x, y + 200))
    curve_id = curve_of_pt.outputs['Curve Index']
    idx_in_curve = curve_of_pt.outputs['Index in Curve']
    pos = _node(ng, 'GeometryNodeInputPosition', (x, y)).outputs['Position']

    # --- per-profile bbox → centre / extent ---
    bounds = _node(ng, 'GeometryNodeFieldMinAndMax', (x + 200, y - 200),
                   data_type='FLOAT_VECTOR', domain='POINT')
    link(pos, bounds.inputs['Value'])
    link(curve_id, bounds.inputs['Group ID'])
    center = _vmath(ng, link, 'SCALE',
                    _vmath(ng, link, 'ADD', bounds.outputs['Min'], bounds.outputs['Max'],
                           (x + 400, y - 150)),
                    loc=(x + 600, y - 150), scale=0.5)
    extent = _vmath(ng, link, 'SUBTRACT', bounds.outputs['Max'], bounds.outputs['Min'],
                    (x + 400, y - 300))
    local = _vmath(ng, link, 'SUBTRACT', pos, center, (x + 800, y))
    flat = _add_axis_remap(ng, link, extent, local, x=x + 1000, y=y)

    # --- winding: shoelace sum of cross(p_i, p_i+1).z per profile ---
    wx = x + 2000
    nxt = _node(ng, 'GeometryNodeOffsetPointInCurve', (wx, y + 400))
    nxt.inputs['Offset'].default_value = 1
    flat_next = _node(ng, 'GeometryNodeFieldAtIndex', (wx + 200, y + 400),
                      data_type='FLOAT_VECTOR', domain='POINT')
    link(flat, flat_next.inputs['Value'])
    link(nxt.outputs['Point Index'], flat_next.inputs['Index'])
    edge_cross = _vmath(ng, link, 'CROSS_PRODUCT', flat, flat_next.outputs['Value'],
                        (wx + 400, y + 400))
    area = _node(ng, 'GeometryNodeAccumulateField', (wx + 800, y + 400),
                 data_type='FLOAT', domain='POINT')
    link(_separate(ng, link, edge_cross, (wx + 600, y + 400))['Z'], area.inputs['Value'])
    link(curve_id, area.inputs['Group ID'])
    direction = _switch(
        ng, link, 'INT',
        _compare(ng, link, 'GREATER_EQUAL', area.outputs['Total'], 0.0, (wx + 1000, y + 400)),
        -1, 1, (wx + 1200, y + 400),
    )

    # --- start point: smallest angle around the centre, in [0, 2π) ---
    flat_c = _separate(ng, link, flat, (wx, y + 100))
    angle = _math(ng, link, 'FLOORED_MODULO',
                  _math(ng, link, 'ARCTAN2', flat_c['Y'], flat_c['X'], (wx + 200, y + 100)),
                  2.0 * math.pi, (wx + 400, y + 100))
    angle_min = _node(ng, 'GeometryNodeFieldMinAndMax', (wx + 600, y + 100),
                      data_type='FLOAT', domain='POINT')
    link(angle, angle_min.inputs['Value'])
    link(curve_id, angle_min.inputs['Group ID'])
    candidate = _switch(
        ng, link, 'INT',
        _compare(ng, link, 'LESS_EQUAL', angle, angle_min.outputs['Min'], (wx + 800, y + 100)),
        1 << 30, idx_in_curve, (wx + 1000, y + 100),
    )
    start = _node(ng, 'GeometryNodeFieldMinAndMax', (wx + 1200, y + 100),
                  data_type='INT', domain='POINT')
    link(candidate, start.inputs['Value'])
    link(curve_id, start.inputs['Group ID'])

    # --- aligned point j of profile k = flat[k*N + (start + dir*j) mod N] ---
    src = _imath(ng, link, 'FLOORED_MODULO',
                 _imath(ng, link, 'MULTIPLY_ADD', direction, idx_in_curve,
                        start.outputs['Min'], (wx + 1400, y + 250)),
                 res, loc=(wx + 1600, y + 250))
    src = _imath(ng, link, 'MULTIPLY_ADD', curve_id, res, src, (wx + 1800, y + 250))
    aligned = _node(ng, 'GeometryNodeFieldAtIndex', (wx + 2000, y + 250),
                    data_type='FLOAT_VECTOR', domain='POINT')
    link(flat, aligned.inputs['Value'])
    link(src, aligned.inputs['Index'])

    capture = _node(ng, 'GeometryNodeCaptureAttribute', (wx + 2200, y), domain='POINT')
    capture.capture_items.new('VECTOR', 'Aligned')
    capture.capture_items.new('VECTOR', 'Center')
    link(profiles, capture.inputs['Geometry'])
    link(aligned.outputs['Value'], capture.inputs['Aligned'])
    link(center, capture.inputs['Center'])
    return capture.outputs['Geometry'], capture.outputs['Aligned'], capture.outputs['Center']


def _add_path_branch(ng, link, group_in, x, y):
    """GP 'Path' layer → Curves → edges → Merge → Curve → Fillet → Resample →
    Set Curve Normal.  Returns the path curve output."""
    path_sel = _node(ng, 'GeometryNodeInputNamedLayerSelection', (x, y))
    path_sel.inputs['Name'].default_value = PATH_LAYER_NAME

    path_gp = _node(ng, 'GeometryNodeGreasePencilToCurves', (x + 200, y))
    path_gp.inputs['Layers as Instances'].default_value = False

    # Convert curves → edges → merge nearby points → back to curve
    # This straightens segments and collapses GP noise into clean corners
    curves_to_edges = _node(ng, 'GeometryNodeCurveToMesh', (x + 400, y))
    merge = _node(ng, 'GeometryNodeMergeByDistance', (x + 600, y))
    edges_to_curve = _node(ng, 'GeometryNodeMeshToCurve', (x + 800, y))

    # Fillet must come before Resample so it rounds actual corners, not every point
    fillet = _node(ng, 'GeometryNodeFilletCurve', (x + 1000, y))
    fillet.inputs['Mode'].default_value = 'Poly'

    path_resample = _node(ng, 'GeometryNodeResampleCurve', (x + 1200, y))

    # Set curve normal mode (user-switchable from modifier panel)
    set_normal = _node(ng, 'GeometryNodeSetCurveNormal', (x + 1400, y))

    link(group_in.outputs['Geometry'], path_gp.inputs['Grease Pencil'])
    link(path_sel.outputs['Selection'], path_gp.inputs['Selection'])
    link(path_gp.outputs['Curves'], curves_to_edges.inputs['Curve'])
    link(curves_to_edges.outputs['Mesh'], merge.inputs['Geometry'])
    link(group_in.outputs['Merge Distance'], merge.inputs['Distance'])
    link(merge.outputs['Geometry'], edges_to_curve.inputs['Mesh'])
    link(edges_to_curve.outputs['Curve'], fillet.inputs['Curve'])
    link(group_in.outputs['Corner Radius'], fillet.inputs['Radius'])
    link(group_in.outputs['Corner Resolution'], fillet.inputs['Count'])
    link(fillet.outputs['Curve'], path_resample.inputs['Curve'])
    link(group_in.outputs['Path Resolution'], path_resample.inputs['Count'])
    link(path_resample.outputs['Curve'], set_normal.inputs['Curve'])
    link(group_in.outputs['Normal Mode'], set_normal.inputs['Mode'])
    return set_normal.outputs['Curve']


def _add_profile_keys(ng, link, group_in, profiles, center, path, x, y):
    """One point per profile at (t, 0, 0), sorted by t, where t is the spline
    parameter factor of the path point nearest to the profile's bbox centre.

    Returns (keys geometry, captured profile index field, profile count).
    """
    res = group_in.outputs['Profile Resolution']

    count = _node(ng, 'GeometryNodeAttributeDomainSize', (x, y), component='CURVE')
    link(profiles, count.inputs['Geometry'])
    num_profiles = count.outputs['Spline Count']

    # Profile k's points are k*N .. k*N + N-1, so its centre is at index k*N
    index = _node(ng, 'GeometryNodeInputIndex', (x, y - 200)).outputs['Index']
    first = _imath(ng, link, 'MULTIPLY', index, res, loc=(x + 200, y - 200))
    centers = _node(ng, 'GeometryNodePoints', (x + 600, y))
    link(num_profiles, centers.inputs['Count'])
    link(_sample_index(ng, link, profiles, center, first, 'FLOAT_VECTOR', (x + 400, y - 200)),
         centers.inputs['Position'])

    profile_id = _node(ng, 'GeometryNodeCaptureAttribute', (x + 800, y), domain='POINT')
    profile_id.capture_items.new('INT', 'Profile')
    link(centers.outputs['Points'], profile_id.inputs['Geometry'])
    link(index, profile_id.inputs['Profile'])

    # Nearest path point (3D) → its spline parameter factor
    path_points = _node(ng, 'GeometryNodeCurveToPoints', (x + 400, y - 450), mode='EVALUATED')
    link(path, path_points.inputs['Curve'])
    nearest = _node(ng, 'GeometryNodeSampleNearest', (x + 600, y - 450), domain='POINT')
    link(path_points.outputs['Points'], nearest.inputs['Geometry'])
    factor = _node(ng, 'GeometryNodeSplineParameter', (x + 600, y - 600)).outputs['Factor']
    t = _sample_index(ng, link, path, factor, nearest.outputs['Index'], 'FLOAT',
                      (x + 800, y - 450))
    key_pos = _node(ng, 'ShaderNodeCombineXYZ', (x + 1000, y - 300))
    link(t, key_pos.inputs['X'])

    set_key = _node(ng, 'GeometryNodeSetPosition', (x + 1200, y))
    link(profile_id.outputs['Geometry'], set_key.inputs['Geometry'])
    link(key_pos.outputs['Vector'], set_key.inputs['Position'])

    sort = _node(ng, 'GeometryNodeSortElements', (x + 1600, y), domain='POINT')
    link(set_key.outputs['Geometry'], sort.inputs['Geometry'])
    key_x = _separate(ng, link, _node(ng, 'GeometryNodeInputPosition', (x + 1200, y - 200))
                      .outputs['Position'], (x + 1400, y - 200))['X']
    link(key_x, sort.inputs['Sort Weight'])

    return sort.outputs['Geometry'], profile_id.outputs['Profile'], num_profiles


def _add_loft(ng, link, group_in, path, profiles, aligned, keys, profile_id,
              num_profiles, x, y):
    """Sweep along the path, blending between the sorted profiles.

    Topology comes from Curve to Mesh(path, N-point circle): vertex v belongs
    to path point i = v div N and aligned profile point j = v mod N.  Each
    vertex is placed like Curve to Mesh places a profile point (px, py):
    P + px·Normal + py·cross(Tangent, Normal), with (px, py) linearly blended
    between the two profiles around the vertex's path factor (held constant
    before the first / after the last profile).
    """
    res = group_in.outputs['Profile Resolution']

    template = _node(ng, 'GeometryNodeCurvePrimitiveCircle', (x, y + 200), mode='POINTS')
    link(res, template.inputs['Resolution'])
    sweep = _node(ng, 'GeometryNodeCurveToMesh', (x + 200, y + 200))
    link(path, sweep.inputs['Curve'])
    link(template.outputs['Curve'], sweep.inputs['Profile Curve'])
    link(group_in.outputs['Fill Caps'], sweep.inputs['Fill Caps'])

    # --- vertex → (path point i, profile point j) ---
    index = _node(ng, 'GeometryNodeInputIndex', (x, y - 100)).outputs['Index']
    ring = _imath(ng, link, 'DIVIDE_FLOOR', index, res, loc=(x + 200, y - 100))
    j = _imath(ng, link, 'FLOORED_MODULO', index, res, loc=(x + 200, y - 250))

    # --- path frame at point i ---
    sx = x + 400
    path_pos = _sample_index(ng, link, path,
                             _node(ng, 'GeometryNodeInputPosition', (sx, y)).outputs['Position'],
                             ring, 'FLOAT_VECTOR', (sx + 200, y))
    normal = _sample_index(ng, link, path,
                           _node(ng, 'GeometryNodeInputNormal', (sx, y - 200)).outputs['Normal'],
                           ring, 'FLOAT_VECTOR', (sx + 200, y - 200))
    tangent = _sample_index(ng, link, path,
                            _node(ng, 'GeometryNodeInputTangent', (sx, y - 400)).outputs['Tangent'],
                            ring, 'FLOAT_VECTOR', (sx + 200, y - 400))
    f = _sample_index(ng, link, path,
                      _node(ng, 'GeometryNodeSplineParameter', (sx, y - 600)).outputs['Factor'],
                      ring, 'FLOAT', (sx + 200, y - 600))

    # --- neighbouring profiles lo/hi around f ---
    kx = x + 800
    key_t = _separate(ng, link, _node(ng, 'GeometryNodeInputPosition', (kx, y - 1000))
                      .outputs['Position'], (kx + 200, y - 1000))['X']
    f_vec = _node(ng, 'ShaderNodeCombineXYZ', (kx, y - 800))
    link(f, f_vec.inputs['X'])
    nearest = _node(ng, 'GeometryNodeSampleNearest', (kx + 200, y - 800), domain='POINT')
    link(keys, nearest.inputs['Geometry'])
    link(f_vec.outputs['Vector'], nearest.inputs['Sample Position'])
    near = nearest.outputs['Index']
    t_near = _sample_index(ng, link, keys, key_t, near, 'FLOAT', (kx + 400, y - 900))
    after = _compare(ng, link, 'GREATER_EQUAL', f, t_near, (kx + 600, y - 800))

    last = _imath(ng, link, 'SUBTRACT', num_profiles, 1, loc=(kx + 400, y - 1150))
    prev_k = _imath(ng, link, 'MAXIMUM',
                    _imath(ng, link, 'SUBTRACT', near, 1, loc=(kx + 400, y - 1300)), 0,
                    loc=(kx + 600, y - 1300))
    next_k = _imath(ng, link, 'MINIMUM',
                    _imath(ng, link, 'ADD', near, 1, loc=(kx + 600, y - 1150)), last,
                    loc=(kx + 800, y - 1150))
    lo = _switch(ng, link, 'INT', after, prev_k, near, (kx + 1000, y - 800))
    hi = _switch(ng, link, 'INT', after, near, next_k, (kx + 1000, y - 1000))

    bx = kx + 1200
    t_lo = _sample_index(ng, link, keys, key_t, lo, 'FLOAT', (bx, y - 700))
    t_hi = _sample_index(ng, link, keys, key_t, hi, 'FLOAT', (bx, y - 900))
    k_lo = _sample_index(ng, link, keys, profile_id, lo, 'INT', (bx, y - 1100))
    k_hi = _sample_index(ng, link, keys, profile_id, hi, 'INT', (bx, y - 1300))

    # w = clamp((f - t_lo) / (t_hi - t_lo)); Math Divide returns 0 for t_lo == t_hi
    weight = _math(ng, link, 'DIVIDE',
                   _math(ng, link, 'SUBTRACT', f, t_lo, (bx + 200, y - 600)),
                   _math(ng, link, 'SUBTRACT', t_hi, t_lo, (bx + 200, y - 800)),
                   (bx + 400, y - 700), clamp=True)

    # --- blended 2D profile point ---
    a_lo = _sample_index(ng, link, profiles, aligned,
                         _imath(ng, link, 'MULTIPLY_ADD', k_lo, res, j, (bx + 200, y - 1100)),
                         'FLOAT_VECTOR', (bx + 400, y - 1000))
    a_hi = _sample_index(ng, link, profiles, aligned,
                         _imath(ng, link, 'MULTIPLY_ADD', k_hi, res, j, (bx + 200, y - 1300)),
                         'FLOAT_VECTOR', (bx + 400, y - 1200))
    blend = _vmath(ng, link, 'ADD', a_lo,
                   _vmath(ng, link, 'SCALE',
                          _vmath(ng, link, 'SUBTRACT', a_hi, a_lo, (bx + 600, y - 1100)),
                          loc=(bx + 800, y - 1000), scale=weight),
                   (bx + 1000, y - 900))
    p2 = _separate(ng, link, blend, (bx + 1200, y - 900))

    # --- P + px·N + py·cross(T, N) ---
    binormal = _vmath(ng, link, 'CROSS_PRODUCT', tangent, normal, (bx + 1200, y - 300))
    offset = _vmath(ng, link, 'ADD',
                    _vmath(ng, link, 'SCALE', normal, loc=(bx + 1400, y - 200), scale=p2['X']),
                    _vmath(ng, link, 'SCALE', binormal, loc=(bx + 1400, y - 400), scale=p2['Y']),
                    (bx + 1600, y - 300))
    position = _vmath(ng, link, 'ADD', path_pos, offset, (bx + 1800, y - 200))

    set_pos = _node(ng, 'GeometryNodeSetPosition', (bx + 2000, y + 200))
    link(sweep.outputs['Mesh'], set_pos.inputs['Geometry'])
    link(position, set_pos.inputs['Position'])
    return set_pos.outputs['Geometry']


def _build(ng):
    """Build the Path Mesh geometry node group.

    Pipeline:
      Profile: GP → 'Profile' layer → GP to Curves → Resample (N) → Cyclic
               → per profile: centre, flatten, normalise winding + start point
      Path:    GP → 'Path' layer → GP to Curves → Merge → Fillet → Resample
               → Set Curve Normal
      Keys:    one point per profile at its path factor, sorted along the path
      Loft:    Curve to Mesh(path, N-point circle) for topology, then Set
               Position blending the two profiles around each ring
               (no profiles → plain Curve to Mesh of the path, as before)
      → Shade flat → Noise → Output
    """
    _build_interface(ng)

    link = ng.links.new

    group_in = _node(ng, 'NodeGroupInput', (-1400, 0))

    # Profile branch (cyclic), every stroke centred/flattened/aligned on its own
    profile_out = _add_gp_branch(
        ng, link, group_in, PROFILE_LAYER_NAME, 'Profile Resolution',
        cyclic=True, x=-1200, y=1200,
    )
    profiles, aligned, center = _add_profile_alignment(
        ng, link, group_in, profile_out, x=-400, y=1200,
    )

    path_out = _add_path_branch(ng, link, group_in, x=-1200, y=-400)

    keys, profile_id, num_profiles = _add_profile_keys(
        ng, link, group_in, profiles, center, path_out, x=600, y=-400,
    )

    loft = _add_loft(
        ng, link, group_in, path_out, profiles, aligned, keys, profile_id, num_profiles,
        x=2600, y=0,
    )

    # Without any profile stroke fall back to Curve to Mesh of the bare path
    no_profile = _node(ng, 'GeometryNodeCurveToMesh', (5400, -600))
    link(path_out, no_profile.inputs['Curve'])
    link(profiles, no_profile.inputs['Profile Curve'])
    link(group_in.outputs['Fill Caps'], no_profile.inputs['Fill Caps'])
    result = _switch(
        ng, link, 'GEOMETRY',
        _compare(ng, link, 'GREATER_THAN', num_profiles, 0, (5400, -400)),
        no_profile.outputs['Mesh'], loft, (5600, 0),
    )

    # Force flat shading (Curve to Mesh outputs smooth by default)
    ox = 5800
    shade_flat = _node(ng, 'GeometryNodeSetShadeSmooth', (ox, 0))
    shade_flat.inputs['Shade Smooth'].default_value = False

    # Noise displacement nodes
    noise_pos = _node(ng, 'GeometryNodeInputPosition', (ox + 200, -200))

    seed_mul = _node(ng, 'ShaderNodeMath', (ox + 200, -400), operation='MULTIPLY')
    seed_mul.inputs[1].default_value = 137.3

    seed_combine = _node(ng, 'ShaderNodeCombineXYZ', (ox + 400, -400))
    seed_add = _node(ng, 'ShaderNodeVectorMath', (ox + 400, -200), operation='ADD')
    noise_tex = _node(ng, 'ShaderNodeTexNoise', (ox + 600, -200), noise_dimensions='3D')

    noise_center = _node(ng, 'ShaderNodeVectorMath', (ox + 800, -200), operation='SUBTRACT')
    noise_center.inputs[1].default_value = (0.5, 0.5, 0.5)

    noise_scale = _node(ng, 'ShaderNodeVectorMath', (ox + 1000, -200), operation='SCALE')
    noise_set_pos = _node(ng, 'GeometryNodeSetPosition', (ox + 1200, 0))
    group_out = _node(ng, 'NodeGroupOutput', (ox + 1400, 0))

    link(result, shade_flat.inputs['Mesh'])

    # Noise pipeline links
    link(group_in.outputs['Noise Seed'], seed_mul.inputs[0])
    link(seed_mul.outputs['Value'], seed_combine.inputs['X'])
    link(seed_mul.outputs['Value'], seed_combine.inputs['Y'])
    link(seed_mul.outputs['Value'], seed_combine.inputs['Z'])
    link(noise_pos.outputs['Position'], seed_add.inputs[0])
    link(seed_combine.outputs['Vector'], seed_add.inputs[1])
    link(seed_add.outputs['Vector'], noise_tex.inputs['Vector'])
    link(group_in.outputs['Noise Scale'], noise_tex.inputs['Scale'])
    link(group_in.outputs['Noise Detail'], noise_tex.inputs['Detail'])
    link(noise_tex.outputs['Color'], noise_center.inputs[0])
    link(noise_center.outputs['Vector'], noise_scale.inputs[0])
    link(group_in.outputs['Noise Strength'], noise_scale.inputs['Scale'])

    # shade_flat → noise_set_pos → group_out
    link(shade_flat.outputs['Mesh'], noise_set_pos.inputs['Geometry'])
    link(noise_scale.outputs['Vector'], noise_set_pos.inputs['Offset'])
    link(noise_set_pos.outputs['Geometry'], group_out.inputs['Geometry'])


def get_or_create_path_node_group():
    return get_or_rebuild_group(NODE_GROUP_NAME, GROUP_VERSION, _build)



STAGE_PROP = "gm_path_stage"  # 'PATH' / 'PROFILE' while the guided drawing steps are open


def get_stage(gp_obj):
    return gp_obj.get(STAGE_PROP) if gp_obj is not None else None


def _start_stage(context, gp_obj, stage):
    """Make the stage's layer active and switch to Draw mode so the user can draw it."""
    gp_obj[STAGE_PROP] = stage
    layer_name = PATH_LAYER_NAME if stage == 'PATH' else PROFILE_LAYER_NAME
    gp_obj.data.layers.active = gp_obj.data.layers.get(layer_name)
    context.view_layer.objects.active = gp_obj
    gp_obj.select_set(True)
    if context.mode != 'PAINT_GREASE_PENCIL':
        bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')


def _end_stage(gp_obj):
    if STAGE_PROP in gp_obj:
        del gp_obj[STAGE_PROP]


def _add_path_modifier(context, gp_obj):
    is_new = gp_obj.modifiers.get("PathMesh") is None
    mod = ensure_nodes_modifier(gp_obj, "PathMesh", get_or_create_path_node_group())

    # Set Normal Mode default to Minimum Twist (only on first creation,
    # so re-runs don't reset the user's choice)
    if is_new:
        for item in mod.node_group.interface.items_tree:
            if item.name == 'Normal Mode' and item.socket_type == 'NodeSocketMenu':
                set_menu(mod, item.identifier, 'Minimum Twist',
                         legacy_value=0, legacy_menu='Minimum Twist')
                break

    context.view_layer.objects.active = gp_obj
    gp_obj.select_set(True)
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    show_modifier_tab(context)


class GPTOOLS_OT_gn_path_mesh(bpy.types.Operator):
    """Sweep a profile along a drawn path. Walks you through the path and
    profile steps in the panel when they're missing"""

    bl_idname = "gptools.gn_path_mesh"
    bl_label = "Path Mesh (GN)"
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

        gp_data = gp_obj.data
        has_profile = _layer_has_strokes(gp_data.layers.get(PROFILE_LAYER_NAME))
        has_path = _layer_has_strokes(gp_data.layers.get(PATH_LAYER_NAME))

        if not has_path:
            _start_stage(context, gp_obj, 'PATH')
            self.report({"INFO"}, "Draw the path, then click Next in the GMesh panel.")
            return {"FINISHED"}

        if not has_profile:
            _start_stage(context, gp_obj, 'PROFILE')
            self.report({"INFO"}, "Draw the profile shape, then click Done in the GMesh panel.")
            return {"FINISHED"}

        _end_stage(gp_obj)
        _add_path_modifier(context, gp_obj)
        self.report({"INFO"}, "Path mesh GN modifier added.")
        return {"FINISHED"}


class GPTOOLS_OT_gn_path_next(bpy.types.Operator):
    """Finish the current Path Mesh drawing step"""

    bl_idname = "gptools.gn_path_next"
    bl_label = "Next"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_stage(get_active_grease_pencil(context)) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        stage = get_stage(gp_obj)
        layer_name = PATH_LAYER_NAME if stage == 'PATH' else PROFILE_LAYER_NAME
        layer = gp_obj.data.layers.get(layer_name)
        if layer is None or not _layer_has_strokes(layer):
            what = "path" if stage == 'PATH' else "profile shape"
            self.report({"WARNING"}, f"Draw the {what} first.")
            return {"CANCELLED"}

        if stage == 'PATH':
            ensure_gp_layers(gp_obj)
            if not _layer_has_strokes(gp_obj.data.layers.get(PROFILE_LAYER_NAME)):
                _start_stage(context, gp_obj, 'PROFILE')
                return {"FINISHED"}

        _end_stage(gp_obj)
        _add_path_modifier(context, gp_obj)
        self.report({"INFO"}, "Path mesh GN modifier added.")
        return {"FINISHED"}


class GPTOOLS_OT_gn_path_cancel(bpy.types.Operator):
    """Stop the Path Mesh drawing steps. Strokes drawn so far are kept"""

    bl_idname = "gptools.gn_path_cancel"
    bl_label = "Cancel"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_stage(get_active_grease_pencil(context)) is not None

    def execute(self, context):
        _end_stage(get_active_grease_pencil(context))
        return {"FINISHED"}


classes = [GPTOOLS_OT_gn_path_mesh, GPTOOLS_OT_gn_path_next, GPTOOLS_OT_gn_path_cancel]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
