import bpy
import mathutils
from ..utils.conversion import get_active_grease_pencil
from ..utils.modifier_io import set_input, ensure_nodes_modifier, show_modifier_tab
from ..utils.node_groups import get_or_rebuild_group

NODE_GROUP_NAME = "GreaseMesh_Solid"
MODIFIER_NAME = "SolidMesh"
GROUP_VERSION = 2  # bump whenever the graph or interface below changes


# ---------------------------------------------------------------------------
# Stroke math — the operator computes a local orthonormal basis (U, V, Normal)
# at the PCA-fitted plane through the strokes. Those four vectors (plus the
# centroid) drive the in-graph basis change so Fill Curve can run cleanly on a
# Z=0 plane regardless of how the GP strokes are oriented in 3D.
# ---------------------------------------------------------------------------


def _gather_stroke_points_local(gp_obj):
    pts = []
    for layer in gp_obj.data.layers:
        for frame in layer.frames:
            for s in frame.drawing.strokes:
                for p in s.points:
                    pts.append(p.position.copy())
    return pts


def _pca_plane(pts):
    """PCA on a Vector list → (centroid, smallest-eigenvector unit normal)."""
    n = len(pts)
    cx = sum(p.x for p in pts) / n
    cy = sum(p.y for p in pts) / n
    cz = sum(p.z for p in pts) / n
    centroid = mathutils.Vector((cx, cy, cz))

    cxx = cxy = cxz = cyy = cyz = czz = 0.0
    for p in pts:
        dx, dy, dz = p.x - cx, p.y - cy, p.z - cz
        cxx += dx * dx; cxy += dx * dy; cxz += dx * dz
        cyy += dy * dy; cyz += dy * dz; czz += dz * dz

    try:
        import numpy as np
        cov = np.array([[cxx, cxy, cxz], [cxy, cyy, cyz], [cxz, cyz, czz]])
        _, eigvecs = np.linalg.eigh(cov)
        normal = mathutils.Vector(eigvecs[:, 0]).normalized()
    except Exception:
        normal = mathutils.Vector((0.0, 0.0, 1.0))
    return centroid, normal


def _viewport_camera_position(context):
    """Return the active 3D viewport's camera/eye world position, or None."""
    for area in context.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type != 'VIEW_3D':
                continue
            rv3d = space.region_3d
            if rv3d is None:
                continue
            view_matrix_inv = rv3d.view_matrix.inverted()
            return view_matrix_inv.translation.copy()
    return None


def _sign_correct_outward(centroid_world, normal_world, exclude_obj, context):
    """Flip the normal so it points TOWARD the viewport camera. Falls back to
    raycast (point away from nearby geometry) when no viewport is available."""
    cam_pos = _viewport_camera_position(context)
    if cam_pos is not None:
        to_cam = (cam_pos - centroid_world).normalized()
        if normal_world.dot(to_cam) < 0:
            return -normal_world
        return normal_world

    deps = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene
    eps = 1e-3

    def hit_distance(direction):
        origin = centroid_world + direction * eps
        hit, loc, _, _, hit_obj, _ = scene.ray_cast(deps, origin, direction)
        if not hit or hit_obj == exclude_obj:
            return None
        return (loc - origin).length

    d_pos = hit_distance(normal_world)
    d_neg = hit_distance(-normal_world)
    if d_pos is not None and d_neg is None:
        return -normal_world
    if d_pos is not None and d_neg is not None and d_pos < d_neg:
        return -normal_world
    return normal_world


def _build_basis(normal):
    """Return (U, V) — two unit vectors perpendicular to normal forming a RH frame."""
    n = normal.normalized()
    helper = mathutils.Vector((0.0, 0.0, 1.0))
    if abs(n.dot(helper)) > 0.9:
        helper = mathutils.Vector((1.0, 0.0, 0.0))
    u = (helper - n * helper.dot(n)).normalized()
    v = n.cross(u).normalized()
    return u, v


def compute_plane_basis(context, gp_obj, pts=None):
    """Fit a plane through the GP's stroke points (or ``pts``, local space) and
    return the hidden-socket values {'Center', 'U', 'V', 'Normal'} as tuples in
    GP-local space, with Normal facing the viewport. None if < 3 points."""
    if pts is None:
        pts = _gather_stroke_points_local(gp_obj)
    if len(pts) < 3:
        return None

    centroid_local, normal_local = _pca_plane(pts)

    mw = gp_obj.matrix_world
    centroid_world = mw @ centroid_local
    normal_world = (mw.to_3x3() @ normal_local).normalized()
    oriented = _sign_correct_outward(centroid_world, normal_world, gp_obj, context)
    if (oriented - normal_world).length > 1e-6:
        normal_local = -normal_local
    normal_local.normalize()

    u_local, v_local = _build_basis(normal_local)
    return {
        'Center': tuple(centroid_local),
        'U':      tuple(u_local),
        'V':      tuple(v_local),
        'Normal': tuple(normal_local),
    }


def set_plane_basis_inputs(mod, node_group, socket_values):
    """Write compute_plane_basis() values into the modifier's hidden sockets."""
    for item in node_group.interface.items_tree:
        if getattr(item, 'in_out', None) != 'INPUT':
            continue
        if item.name in socket_values:
            set_input(mod, item.identifier, socket_values[item.name])


# ---------------------------------------------------------------------------
# Geometry Nodes graph — basis-change pipeline.
#
#   strokes (3D)
#     → GP→Curves               (preserves 3D)
#     → Curve→Mesh              (edges in 3D)
#     → Set Position #1         (rotate into U,V,N basis: pos' = (rel·U, rel·V, rel·N))
#     → Merge ×2                (collapse dupes, bridge stroke endpoints)
#     → Mesh→Curve, Set Cyclic, Resample
#     → Fill Curve              (Z is already ~0 in this basis, so flatten is correct)
#     → Set Position #2         (rotate back: world = Center + p.x·U + p.y·V)
#     → Extrude along Normal
#
# Inflate > 0 switches to a second branch that stays in the 2D plane after
# Fill Curve: re-fill with interior grid points (Detail), bulge each vertex by
# its distance d to the outline (sphere profile sqrt(d·(2R − d)), R = max d
# per island), build front (Thickness + bulge), back (−bulge) and a straight
# side band, weld their rims and rotate back with z along Normal. Inflate 0
# never evaluates this branch.
# ---------------------------------------------------------------------------


def _add_dot(ng, name, vec_a, vec_b):
    n = ng.nodes.new('ShaderNodeVectorMath')
    n.operation = 'DOT_PRODUCT'
    n.label = name
    ng.links.new(vec_a, n.inputs[0])
    ng.links.new(vec_b, n.inputs[1])
    return n.outputs['Value']


def _add_scale(ng, vec, scalar):
    n = ng.nodes.new('ShaderNodeVectorMath')
    n.operation = 'SCALE'
    ng.links.new(vec, n.inputs[0])
    if isinstance(scalar, (int, float)):
        n.inputs['Scale'].default_value = scalar
    else:
        ng.links.new(scalar, n.inputs['Scale'])
    return n.outputs['Vector']


def _add_vec_op(ng, op, a, b):
    n = ng.nodes.new('ShaderNodeVectorMath')
    n.operation = op
    ng.links.new(a, n.inputs[0])
    ng.links.new(b, n.inputs[1])
    return n.outputs['Vector']


def _set_inputs(ng, node, values):
    """Link sockets / set constants on node.inputs[0..] (None = leave as is)."""
    for sock, v in zip(node.inputs, values):
        if v is None:
            continue
        if isinstance(v, (bool, int, float, tuple)):
            sock.default_value = v
        else:
            ng.links.new(v, sock)


def _add_math(ng, op, a, b=None, c=None):
    n = ng.nodes.new('ShaderNodeMath')
    n.operation = op
    _set_inputs(ng, n, (a, b, c))
    return n.outputs['Value']


def _add_compare(ng, op, a, b, data_type='FLOAT'):
    n = ng.nodes.new('FunctionNodeCompare')
    n.data_type, n.operation = data_type, op
    _set_inputs(ng, n, (a, b))
    return n.outputs['Result']


def _add_bool(ng, op, a, b=None):
    n = ng.nodes.new('FunctionNodeBooleanMath')
    n.operation = op
    _set_inputs(ng, n, (a, b))
    return n.outputs['Boolean']


def _add_on_domain(ng, domain, value):
    """Evaluate ``value`` (as float) on ``domain``; consumers on another domain
    get the averaged value (e.g. edge flags → 'fraction of edges' per vertex)."""
    n = ng.nodes.new('GeometryNodeFieldOnDomain')
    n.domain, n.data_type = domain, 'FLOAT'
    ng.links.new(value, n.inputs[0])
    return n.outputs[0]


def _add_offset_z(ng, geometry, z):
    """Set Position with offset (0, 0, z) — z is the height in the plane basis."""
    comb = ng.nodes.new('ShaderNodeCombineXYZ')
    ng.links.new(z, comb.inputs['Z'])
    n = ng.nodes.new('GeometryNodeSetPosition')
    ng.links.new(geometry, n.inputs['Geometry'])
    ng.links.new(comb.outputs['Vector'], n.inputs['Offset'])
    return n.outputs['Geometry']


def _add_shade(ng, geometry, smooth):
    n = ng.nodes.new('GeometryNodeSetShadeSmooth')
    ng.links.new(geometry, n.inputs['Mesh'])
    _set_inputs(ng, n, (None, None, smooth))
    return n.outputs['Mesh']


def _build_seam_field(ng, group_in, outline, plane_to_object):
    """Mirror seam fields for points of the plane-basis outline → (seam, snap).

    seam: bool, the point lies on the seam. For each axis a with Seam Mask[a]
    > 0.5 its object-space coordinate is within a small tolerance of the
    outline's minimum on that axis (Mirror mirrors at the bbox min). Axes the
    outline has no extent on (drawn perpendicular to the mirror axis) are
    ignored, otherwise the whole outline would be seam.
    snap: in-plane offset that puts seam points exactly onto the mirror plane,
    so the halves weld (resampling rarely lands a point on the stroke end)."""
    link = ng.links.new
    stat = ng.nodes.new('GeometryNodeAttributeStatistic'); stat.location = (900, -1500)
    stat.data_type, stat.domain = 'FLOAT_VECTOR', 'POINT'
    link(outline, stat.inputs['Geometry'])
    link(plane_to_object, stat.inputs['Attribute'])

    size = ng.nodes.new('ShaderNodeVectorMath'); size.location = (1100, -1700); size.operation = 'LENGTH'
    link(stat.outputs['Range'], size.inputs[0])
    tol = _add_math(ng, 'MULTIPLY', size.outputs['Value'], 0.01)
    min_extent = _add_math(ng, 'MULTIPLY', tol, 4.0)

    sep_mask = ng.nodes.new('ShaderNodeSeparateXYZ'); link(group_in.outputs['Seam Mask'], sep_mask.inputs[0])
    sep_min = ng.nodes.new('ShaderNodeSeparateXYZ'); link(stat.outputs['Min'], sep_min.inputs[0])
    sep_rng = ng.nodes.new('ShaderNodeSeparateXYZ'); link(stat.outputs['Range'], sep_rng.inputs[0])
    sep_pos = ng.nodes.new('ShaderNodeSeparateXYZ'); link(plane_to_object, sep_pos.inputs[0])
    sep_u = ng.nodes.new('ShaderNodeSeparateXYZ'); link(group_in.outputs['U'], sep_u.inputs[0])
    sep_v = ng.nodes.new('ShaderNodeSeparateXYZ'); link(group_in.outputs['V'], sep_v.inputs[0])

    seam = snap = None
    for axis in ('X', 'Y', 'Z'):
        active = _add_bool(ng, 'AND',
                           _add_compare(ng, 'GREATER_THAN', sep_mask.outputs[axis], 0.5),
                           _add_compare(ng, 'GREATER_THAN', sep_rng.outputs[axis], min_extent))
        gap = _add_math(ng, 'SUBTRACT', sep_pos.outputs[axis], sep_min.outputs[axis])
        on_axis = _add_bool(ng, 'AND', active, _add_compare(ng, 'LESS_THAN', _add_math(ng, 'ABSOLUTE', gap), tol))
        seam = on_axis if seam is None else _add_bool(ng, 'OR', seam, on_axis)
        # Move along the axis projected into the plane, w = (U[a], V[a]).
        w = ng.nodes.new('ShaderNodeCombineXYZ')
        link(sep_u.outputs[axis], w.inputs['X'])
        link(sep_v.outputs[axis], w.inputs['Y'])
        w_len2 = _add_math(ng, 'MAXIMUM', _add_dot(ng, "|w|²", w.outputs['Vector'], w.outputs['Vector']), 1e-6)
        step = _add_math(ng, 'MULTIPLY', _add_math(ng, 'DIVIDE', gap, w_len2), _add_math(ng, 'MULTIPLY', on_axis, -1.0))
        offset = _add_scale(ng, w.outputs['Vector'], step)
        snap = offset if snap is None else _add_vec_op(ng, 'ADD', snap, offset)
    return seam, snap


def _build_inflate(ng, group_in, fill_mesh, outline_curve, plane_to_object):
    """Inflated solid, built in the plane basis (z = height along Normal)."""
    link = ng.links.new
    nodes = ng.nodes
    inflate, thickness = group_in.outputs['Inflate'], group_in.outputs['Thickness']

    # Interior resolution: Fill Curve alone only has outline vertices, so
    # re-fill with a hex grid of interior points (one-point curves become
    # Steiner points of the constrained Delaunay fill). Spacing h = mean
    # outline edge · 2^(2 − Detail); above Detail 2 the outline is densified
    # by the same factor so rim triangles stay well shaped.
    detail = group_in.outputs['Detail']
    densify = _add_math(ng, 'POWER', 2.0, _add_math(ng, 'MAXIMUM', _add_math(ng, 'SUBTRACT', detail, 2.0), 0.0))
    fine = nodes.new('GeometryNodeResampleCurve'); fine.location = (700, -1300)
    link(outline_curve, fine.inputs['Curve'])
    link(_add_math(ng, 'MULTIPLY', group_in.outputs['Resolution'], densify), fine.inputs['Count'])
    seam, snap = _build_seam_field(ng, group_in, fine.outputs['Curve'], plane_to_object)
    snapped = nodes.new('GeometryNodeSetPosition'); snapped.location = (900, -1100)
    link(fine.outputs['Curve'], snapped.inputs['Geometry'])
    link(snap, snapped.inputs['Offset'])
    fine_curve = snapped.outputs['Geometry']
    outline = nodes.new('GeometryNodeCurveToMesh'); outline.location = (900, -1300)
    link(fine_curve, outline.inputs['Curve'])

    bbox = nodes.new('GeometryNodeBoundBox'); bbox.location = (900, -1600)
    link(outline.outputs['Mesh'], bbox.inputs['Geometry'])
    size = _add_vec_op(ng, 'SUBTRACT', bbox.outputs['Max'], bbox.outputs['Min'])
    center = _add_scale(ng, _add_vec_op(ng, 'ADD', bbox.outputs['Max'], bbox.outputs['Min']), 0.5)
    sep_size = nodes.new('ShaderNodeSeparateXYZ'); link(size, sep_size.inputs[0])
    curve_len = nodes.new('GeometryNodeCurveLength'); curve_len.location = (700, -1600)
    link(outline_curve, curve_len.inputs['Curve'])
    point_count = nodes.new('GeometryNodeAttributeDomainSize'); point_count.location = (700, -1700)
    point_count.component = 'CURVE'
    link(outline_curve, point_count.inputs['Geometry'])
    edge_len = _add_math(ng, 'DIVIDE', curve_len.outputs['Length'], point_count.outputs['Point Count'])
    size_len = nodes.new('ShaderNodeVectorMath'); size_len.operation = 'LENGTH'; link(size, size_len.inputs[0])
    spacing = _add_math(ng, 'MAXIMUM',
                        _add_math(ng, 'MULTIPLY', edge_len, _add_math(ng, 'POWER', 2.0, _add_math(ng, 'SUBTRACT', 2.0, detail))),
                        _add_math(ng, 'DIVIDE', size_len.outputs['Value'], 600.0))  # cap the grid size
    row_step = _add_math(ng, 'MULTIPLY', spacing, 0.8660254)

    # Odd vertex counts put a grid point on the bbox center (exact R for
    # symmetric shapes); odd rows shift by h/2 for a hexagonal pattern.
    def half_count(extent, step):
        return _add_math(ng, 'CEIL', _add_math(ng, 'DIVIDE', extent, _add_math(ng, 'MULTIPLY', step, 2.0)))
    nx, ny = half_count(sep_size.outputs['X'], spacing), half_count(sep_size.outputs['Y'], row_step)
    grid = nodes.new('GeometryNodeMeshGrid'); grid.location = (1100, -1600)
    link(_add_math(ng, 'MULTIPLY', _add_math(ng, 'MULTIPLY', nx, 2.0), spacing), grid.inputs['Size X'])
    link(_add_math(ng, 'MULTIPLY', _add_math(ng, 'MULTIPLY', ny, 2.0), row_step), grid.inputs['Size Y'])
    link(_add_math(ng, 'MULTIPLY_ADD', nx, 2.0, 1.0), grid.inputs['Vertices X'])
    link(_add_math(ng, 'MULTIPLY_ADD', ny, 2.0, 1.0), grid.inputs['Vertices Y'])
    grid_points = nodes.new('GeometryNodeMeshToPoints'); grid_points.location = (1300, -1600)
    link(grid.outputs['Mesh'], grid_points.inputs['Mesh'])

    position = nodes.new('GeometryNodeInputPosition'); position.location = (1100, -1800)
    sep_grid = nodes.new('ShaderNodeSeparateXYZ'); link(position.outputs['Position'], sep_grid.inputs[0])
    row = _add_math(ng, 'ROUND', _add_math(ng, 'DIVIDE', sep_grid.outputs['Y'], row_step))
    shift = _add_math(ng, 'MULTIPLY', _add_math(ng, 'FLOORED_MODULO', row, 2.0), _add_math(ng, 'MULTIPLY', spacing, 0.5))
    shift_vec = nodes.new('ShaderNodeCombineXYZ'); link(shift, shift_vec.inputs['X'])
    place = nodes.new('GeometryNodeSetPosition'); place.location = (1500, -1600)
    link(grid_points.outputs['Points'], place.inputs['Geometry'])
    link(_add_vec_op(ng, 'ADD', center, shift_vec.outputs['Vector']), place.inputs['Offset'])

    # Keep grid points inside the fill and about h away from the outline.
    in_fill = nodes.new('GeometryNodeProximity'); in_fill.location = (1500, -1800)
    in_fill.target_element = 'FACES'
    link(fill_mesh, in_fill.inputs['Geometry'])
    inside = _add_compare(ng, 'LESS_THAN', in_fill.outputs['Distance'], _add_math(ng, 'MULTIPLY', spacing, 0.001))
    to_outline = nodes.new('GeometryNodeProximity'); to_outline.location = (1500, -2000)
    to_outline.target_element = 'EDGES'
    link(outline.outputs['Mesh'], to_outline.inputs['Geometry'])
    keep = _add_bool(ng, 'AND', inside,
                     _add_compare(ng, 'GREATER_THAN', to_outline.outputs['Distance'], _add_math(ng, 'MULTIPLY', spacing, 0.95)))
    cull = nodes.new('GeometryNodeDeleteGeometry'); cull.location = (1700, -1600)
    link(place.outputs['Geometry'], cull.inputs['Geometry'])
    link(_add_bool(ng, 'NOT', keep), cull.inputs['Selection'])

    # The bulge is steep at the rim (d ~ 0), so sample it with rings parallel
    # to the outline at d_k = k²·h/16 (k = 1..3) instead of the grid.
    rim_points = nodes.new('GeometryNodeCurveToPoints'); rim_points.location = (1100, -2200)
    rim_points.mode = 'EVALUATED'
    link(fine_curve, rim_points.inputs['Curve'])
    no_seam = nodes.new('GeometryNodeDeleteGeometry'); no_seam.location = (1300, -2200)
    link(rim_points.outputs['Points'], no_seam.inputs['Geometry'])
    link(seam, no_seam.inputs['Selection'])
    rings = nodes.new('GeometryNodeDuplicateElements'); rings.location = (1500, -2200)
    rings.domain = 'POINT'
    rings.inputs['Amount'].default_value = 3
    link(no_seam.outputs['Geometry'], rings.inputs['Geometry'])
    ring_k = _add_math(ng, 'ADD', rings.outputs['Duplicate Index'], 1.0)
    ring_d = _add_math(ng, 'MULTIPLY', _add_math(ng, 'MULTIPLY', ring_k, ring_k), _add_math(ng, 'MULTIPLY', spacing, 1.0 / 16.0))

    cross = nodes.new('ShaderNodeVectorMath'); cross.location = (1500, -2400); cross.operation = 'CROSS_PRODUCT'
    link(rim_points.outputs['Tangent'], cross.inputs[0])
    cross.inputs[1].default_value = (0.0, 0.0, 1.0)
    unit = nodes.new('ShaderNodeVectorMath'); unit.location = (1700, -2600); unit.operation = 'NORMALIZE'
    link(cross.outputs['Vector'], unit.inputs[0])
    side = unit.outputs['Vector']                                 # in-plane outline normal
    probe = nodes.new('GeometryNodeProximity'); probe.location = (1700, -2400)  # which side is inside?
    probe.target_element = 'FACES'
    link(fill_mesh, probe.inputs['Geometry'])
    link(_add_vec_op(ng, 'ADD', position.outputs['Position'], _add_scale(ng, side, _add_math(ng, 'MULTIPLY', spacing, 1.0 / 32.0))),
         probe.inputs['Sample Position'])
    side_sign = _add_math(ng, 'SUBTRACT', 1.0, _add_math(ng, 'MULTIPLY', 2.0,
                          _add_compare(ng, 'GREATER_THAN', probe.outputs['Distance'], _add_math(ng, 'MULTIPLY', spacing, 0.001))))
    offset_rings = nodes.new('GeometryNodeSetPosition'); offset_rings.location = (1900, -2200)
    link(rings.outputs['Geometry'], offset_rings.inputs['Geometry'])
    link(_add_scale(ng, side, _add_math(ng, 'MULTIPLY', side_sign, ring_d)), offset_rings.inputs['Offset'])
    # Drop ring points that ended up too close to another part of the outline
    # (narrow necks, concave corners) and weld the ones that bunch up.
    ring_ok = _add_bool(ng, 'AND', inside,
                        _add_compare(ng, 'GREATER_THAN', to_outline.outputs['Distance'], _add_math(ng, 'MULTIPLY', ring_d, 0.8)))
    ring_cull = nodes.new('GeometryNodeDeleteGeometry'); ring_cull.location = (2100, -2200)
    link(offset_rings.outputs['Geometry'], ring_cull.inputs['Geometry'])
    link(_add_bool(ng, 'NOT', ring_ok), ring_cull.inputs['Selection'])
    ring_weld = nodes.new('GeometryNodeMergeByDistance'); ring_weld.location = (2300, -2200)
    link(ring_cull.outputs['Geometry'], ring_weld.inputs['Geometry'])
    link(_add_math(ng, 'MULTIPLY', spacing, 0.1), ring_weld.inputs['Distance'])

    interior = nodes.new('GeometryNodeJoinGeometry'); interior.location = (2300, -1600)
    link(cull.outputs['Geometry'], interior.inputs['Geometry'])
    link(ring_weld.outputs['Geometry'], interior.inputs['Geometry'])
    steiner = nodes.new('GeometryNodePointsToCurves'); steiner.location = (2500, -1600)
    index = nodes.new('GeometryNodeInputIndex'); index.location = (2300, -1800)
    link(interior.outputs['Geometry'], steiner.inputs['Points'])
    link(index.outputs['Index'], steiner.inputs['Curve Group ID'])
    fill_curves = nodes.new('GeometryNodeJoinGeometry'); fill_curves.location = (2700, -1300)
    link(fine_curve, fill_curves.inputs['Geometry'])
    link(steiner.outputs['Curves'], fill_curves.inputs['Geometry'])
    refill = nodes.new('GeometryNodeFillCurve'); refill.location = (2900, -1300)
    link(fill_curves.outputs['Geometry'], refill.inputs['Curve'])
    merge_2d = nodes.new('GeometryNodeMergeByDistance'); merge_2d.location = (3100, -1300)
    merge_2d.inputs['Distance'].default_value = 0.001
    link(refill.outputs['Mesh'], merge_2d.inputs['Geometry'])

    edge_faces = nodes.new('GeometryNodeInputMeshEdgeNeighbors'); edge_faces.location = (2500, -1100)
    is_border_edge = _add_compare(ng, 'EQUAL', edge_faces.outputs['Face Count'], 1, 'INT')
    border_share = _add_on_domain(ng, 'EDGE', is_border_edge)   # per vertex: share of border edges
    is_border = _add_compare(ng, 'GREATER_THAN', border_share, 0.0)

    # Proximity target: the outline edges minus Mirror seam edges (both ends
    # on the seam), so the bulge runs straight across the seam.
    seam_share = _add_on_domain(ng, 'POINT', seam)               # per edge: share of seam ends
    is_seam_edge = _add_compare(ng, 'GREATER_THAN', seam_share, 0.99)

    target = nodes.new('GeometryNodeDeleteGeometry'); target.location = (2500, -1500)
    target.domain = 'EDGE'
    link(outline.outputs['Mesh'], target.inputs['Geometry'])
    link(is_seam_edge, target.inputs['Selection'])

    proximity = nodes.new('GeometryNodeProximity'); proximity.location = (2700, -1300)
    proximity.target_element = 'EDGES'
    link(target.outputs['Geometry'], proximity.inputs['Geometry'])
    dist = proximity.outputs['Distance']

    # bulge = Inflate · sqrt(d·(2R − d)), R = max d over the vertex's island.
    # No vertex sits exactly on the medial axis, so also probe d a little
    # further away from the nearest outline point (where d keeps growing up
    # to the axis); probes are clamped back into the fill.
    away = nodes.new('ShaderNodeVectorMath'); away.location = (2900, -1500); away.operation = 'NORMALIZE'
    link(_add_vec_op(ng, 'SUBTRACT', position.outputs['Position'], proximity.outputs['Position']), away.inputs[0])
    peak = dist
    for step in (0.2, 0.4, 0.6):
        probe_at = _add_vec_op(ng, 'ADD', position.outputs['Position'],
                               _add_scale(ng, away.outputs['Vector'], _add_math(ng, 'MULTIPLY', spacing, step)))
        probe_in = nodes.new('GeometryNodeProximity'); probe_in.target_element = 'FACES'
        link(merge_2d.outputs['Geometry'], probe_in.inputs['Geometry'])
        link(probe_at, probe_in.inputs['Sample Position'])
        probe_d = nodes.new('GeometryNodeProximity'); probe_d.target_element = 'EDGES'
        link(target.outputs['Geometry'], probe_d.inputs['Geometry'])
        link(probe_in.outputs['Position'], probe_d.inputs['Sample Position'])
        peak = _add_math(ng, 'MAXIMUM', peak, probe_d.outputs['Distance'])
    island = nodes.new('GeometryNodeInputMeshIsland'); island.location = (1300, -900)
    radius = nodes.new('GeometryNodeFieldMinAndMax'); radius.location = (1500, -900)
    link(peak, radius.inputs['Value'])
    link(island.outputs['Island Index'], radius.inputs['Group ID'])
    # d has a kink along the medial axis (a crease wherever d < R, e.g. down
    # a mirrored neck), so soften it over the interior grid, fading in from
    # 1.5h to 4.5h so the rim and rings stay exact. 4^Detail / 4 passes keep
    # the width about constant in outline edges; wider flattens domes.
    soften = nodes.new('GeometryNodeBlurAttribute'); soften.location = (2900, -1100)
    soften.data_type = 'FLOAT'
    link(dist, soften.inputs['Value'])
    link(_add_math(ng, 'MULTIPLY', _add_math(ng, 'POWER', 4.0, detail), 0.25), soften.inputs['Iterations'])
    fade = _add_math(ng, 'DIVIDE', _add_math(ng, 'SUBTRACT', dist, _add_math(ng, 'MULTIPLY', spacing, 1.5)),
                     _add_math(ng, 'MULTIPLY', spacing, 3.0))
    fade.node.use_clamp = True
    link(fade, soften.inputs['Weight'])                          # weight 0 = keep exact d
    dist = soften.outputs['Value']
    span = _add_math(ng, 'SUBTRACT', _add_math(ng, 'MULTIPLY', radius.outputs['Max'], 2.0), dist)
    sq = _add_math(ng, 'MAXIMUM', _add_math(ng, 'MULTIPLY', dist, span), 0.0)
    bulge = _add_math(ng, 'MULTIPLY', _add_math(ng, 'SQRT', sq), inflate)
    # Outline vertices stay exactly on the plane (seam vertices keep their bulge).
    pinned = _add_bool(ng, 'AND', is_border, _add_bool(ng, 'NOT', seam))
    bulge = _add_math(ng, 'MULTIPLY', bulge, _add_math(ng, 'SUBTRACT', 1.0, pinned))

    capture = nodes.new('GeometryNodeCaptureAttribute'); capture.location = (1700, -800)
    capture.capture_items.new('FLOAT', "Bulge")
    capture.capture_items.new('BOOLEAN', "Rim")
    link(merge_2d.outputs['Geometry'], capture.inputs['Geometry'])
    link(bulge, capture.inputs['Bulge'])
    link(is_border, capture.inputs['Rim'])
    shape, bulge = capture.outputs['Geometry'], capture.outputs['Bulge']

    # Front = Thickness + bulge, back = −bulge (flat when One-Sided).
    front = _add_offset_z(ng, shape, _add_math(ng, 'ADD', thickness, bulge))
    front = _add_shade(ng, front, True)

    flip = nodes.new('GeometryNodeFlipFaces'); flip.location = (1900, -1000)
    link(shape, flip.inputs['Mesh'])
    two_sided = _add_bool(ng, 'NOT', group_in.outputs['One-Sided'])
    back = _add_offset_z(ng, flip.outputs['Mesh'], _add_math(ng, 'MULTIPLY', bulge, _add_math(ng, 'MULTIPLY', two_sided, -1.0)))
    back = _add_shade(ng, back, two_sided)

    # Straight side band from the outline edges (not the seam), flat shaded so
    # the rim stays crisp; skipped at Thickness 0 where front and back rims meet.
    band = nodes.new('GeometryNodeExtrudeMesh'); band.location = (1900, -1200)
    band.mode = 'EDGES'
    band.inputs['Offset'].default_value = (0.0, 0.0, 1.0)
    link(shape, band.inputs['Mesh'])
    link(_add_bool(ng, 'AND', is_border_edge, _add_bool(ng, 'NOT', is_seam_edge)), band.inputs['Selection'])
    link(thickness, band.inputs['Offset Scale'])
    band_only = nodes.new('GeometryNodeDeleteGeometry'); band_only.location = (2100, -1200)
    band_only.domain = 'FACE'
    link(band.outputs['Mesh'], band_only.inputs['Geometry'])
    link(_add_bool(ng, 'NOT', band.outputs['Side']), band_only.inputs['Selection'])
    has_band = nodes.new('GeometryNodeSwitch'); has_band.location = (2300, -1200)
    has_band.input_type = 'GEOMETRY'
    link(_add_compare(ng, 'GREATER_THAN', thickness, 0.0), has_band.inputs['Switch'])
    band_flip = nodes.new('GeometryNodeFlipFaces'); band_flip.location = (2100, -1400)  # extruded flaps face inward
    link(band_only.outputs['Geometry'], band_flip.inputs['Mesh'])
    link(_add_shade(ng, band_flip.outputs['Mesh'], False), has_band.inputs['True'])

    join = nodes.new('GeometryNodeJoinGeometry'); join.location = (2500, -900)
    for part in (front, back, has_band.outputs['Output']):
        link(part, join.inputs['Geometry'])

    # Rim vertices of the parts coincide exactly in the plane basis.
    weld = nodes.new('GeometryNodeMergeByDistance'); weld.location = (2700, -900)
    weld.inputs['Distance'].default_value = 1e-5
    link(join.outputs['Geometry'], weld.inputs['Geometry'])
    link(capture.outputs['Rim'], weld.inputs['Selection'])

    # Back to object space: Center + x·U + y·V + z·N
    sep = nodes.new('ShaderNodeSeparateXYZ'); sep.location = (2700, -700)
    link(position.outputs['Position'], sep.inputs[0])
    world = _add_vec_op(ng, 'ADD', plane_to_object, _add_scale(ng, group_in.outputs['Normal'], sep.outputs['Z']))
    set_back = nodes.new('GeometryNodeSetPosition'); set_back.location = (2900, -900)
    link(weld.outputs['Geometry'], set_back.inputs['Geometry'])
    link(world, set_back.inputs['Position'])
    return set_back.outputs['Geometry']


def _build(ng):
    iface = ng.interface
    iface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')

    res = iface.new_socket(name="Resolution", in_out='INPUT', socket_type='NodeSocketInt')
    res.default_value, res.min_value, res.max_value = 64, 8, 512

    thick = iface.new_socket(name="Thickness", in_out='INPUT', socket_type='NodeSocketFloat')
    thick.default_value, thick.min_value, thick.max_value = 0.4, 0.0, 20.0

    infl = iface.new_socket(name="Inflate", in_out='INPUT', socket_type='NodeSocketFloat')
    infl.default_value, infl.min_value, infl.max_value = 0.0, 0.0, 5.0

    detail = iface.new_socket(name="Detail", in_out='INPUT', socket_type='NodeSocketInt')
    detail.default_value, detail.min_value, detail.max_value = 2, 0, 5

    iface.new_socket(name="One-Sided", in_out='INPUT', socket_type='NodeSocketBool').default_value = False

    for hidden_name, default in (
        ("Center", (0.0, 0.0, 0.0)),
        ("U", (1.0, 0.0, 0.0)),
        ("V", (0.0, 1.0, 0.0)),
        ("Normal", (0.0, 0.0, 1.0)),
        ("Seam Mask", (0.0, 0.0, 0.0)),
    ):
        s = iface.new_socket(name=hidden_name, in_out='INPUT', socket_type='NodeSocketVector')
        s.default_value = default
        s.hide_in_modifier = True

    iface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    link = ng.links.new
    nodes = ng.nodes

    group_in = nodes.new('NodeGroupInput'); group_in.location = (-2200, 0)

    gp_to_curves = nodes.new('GeometryNodeGreasePencilToCurves'); gp_to_curves.location = (-2000, 0)
    gp_to_curves.inputs['Layers as Instances'].default_value = False
    link(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])

    curve_to_mesh = nodes.new('GeometryNodeCurveToMesh'); curve_to_mesh.location = (-1800, 0)
    link(gp_to_curves.outputs['Curves'], curve_to_mesh.inputs['Curve'])

    # Forward basis change on mesh: pos' = (rel·U, rel·V, rel·N) where rel = pos − Center
    pos1 = nodes.new('GeometryNodeInputPosition'); pos1.location = (-1700, 300)
    rel1 = nodes.new('ShaderNodeVectorMath'); rel1.location = (-1500, 300); rel1.operation = 'SUBTRACT'
    link(pos1.outputs['Position'], rel1.inputs[0])
    link(group_in.outputs['Center'], rel1.inputs[1])

    dot_u = _add_dot(ng, "rel·U", rel1.outputs['Vector'], group_in.outputs['U'])
    dot_v = _add_dot(ng, "rel·V", rel1.outputs['Vector'], group_in.outputs['V'])
    dot_n = _add_dot(ng, "rel·N", rel1.outputs['Vector'], group_in.outputs['Normal'])

    combine_uvn = nodes.new('ShaderNodeCombineXYZ'); combine_uvn.location = (-900, 300)
    link(dot_u, combine_uvn.inputs['X'])
    link(dot_v, combine_uvn.inputs['Y'])
    link(dot_n, combine_uvn.inputs['Z'])

    set_pos_fwd = nodes.new('GeometryNodeSetPosition'); set_pos_fwd.location = (-700, 0)
    link(curve_to_mesh.outputs['Mesh'], set_pos_fwd.inputs['Geometry'])
    link(combine_uvn.outputs['Vector'], set_pos_fwd.inputs['Position'])

    # Adaptive merge distances driven by bbox diagonal of the rotated mesh.
    bbox = nodes.new('GeometryNodeBoundBox'); bbox.location = (-500, -300)
    link(set_pos_fwd.outputs['Geometry'], bbox.inputs['Geometry'])
    bbox_sub = nodes.new('ShaderNodeVectorMath'); bbox_sub.location = (-300, -300); bbox_sub.operation = 'SUBTRACT'
    link(bbox.outputs['Max'], bbox_sub.inputs[0])
    link(bbox.outputs['Min'], bbox_sub.inputs[1])
    bbox_len = nodes.new('ShaderNodeVectorMath'); bbox_len.location = (-100, -300); bbox_len.operation = 'LENGTH'
    link(bbox_sub.outputs['Vector'], bbox_len.inputs[0])
    scale_small = nodes.new('ShaderNodeMath'); scale_small.location = (100, -250); scale_small.operation = 'MULTIPLY'
    scale_small.inputs[1].default_value = 0.025
    link(bbox_len.outputs['Value'], scale_small.inputs[0])
    scale_large = nodes.new('ShaderNodeMath'); scale_large.location = (100, -350); scale_large.operation = 'MULTIPLY'
    scale_large.inputs[1].default_value = 0.25
    link(bbox_len.outputs['Value'], scale_large.inputs[0])

    merge_dupes = nodes.new('GeometryNodeMergeByDistance'); merge_dupes.location = (-500, 0)
    link(set_pos_fwd.outputs['Geometry'], merge_dupes.inputs['Geometry'])
    link(scale_small.outputs['Value'], merge_dupes.inputs['Distance'])

    # Bridge open stroke endpoints (large merge limited to verts with 1 neighbor)
    vert_neighbors = nodes.new('GeometryNodeInputMeshVertexNeighbors'); vert_neighbors.location = (-300, -150)
    is_endpoint = nodes.new('FunctionNodeCompare'); is_endpoint.location = (-100, -150)
    is_endpoint.data_type = 'INT'; is_endpoint.operation = 'EQUAL'
    is_endpoint.inputs['B'].default_value = 1
    link(vert_neighbors.outputs['Vertex Count'], is_endpoint.inputs['A'])

    merge_join = nodes.new('GeometryNodeMergeByDistance'); merge_join.location = (-300, 0)
    link(merge_dupes.outputs['Geometry'], merge_join.inputs['Geometry'])
    link(scale_large.outputs['Value'], merge_join.inputs['Distance'])
    link(is_endpoint.outputs['Result'], merge_join.inputs['Selection'])

    mesh_to_curve = nodes.new('GeometryNodeMeshToCurve'); mesh_to_curve.location = (-100, 0)
    link(merge_join.outputs['Geometry'], mesh_to_curve.inputs['Mesh'])

    set_cyclic = nodes.new('GeometryNodeSetSplineCyclic'); set_cyclic.location = (100, 0)
    set_cyclic.inputs['Cyclic'].default_value = True
    link(mesh_to_curve.outputs['Curve'], set_cyclic.inputs['Curve'])

    resample = nodes.new('GeometryNodeResampleCurve'); resample.location = (300, 0)
    link(set_cyclic.outputs['Curve'], resample.inputs['Curve'])
    link(group_in.outputs['Resolution'], resample.inputs['Count'])

    fill = nodes.new('GeometryNodeFillCurve'); fill.location = (500, 0)
    link(resample.outputs['Curve'], fill.inputs['Curve'])

    # Reverse basis change on filled mesh: world = Center + p.x·U + p.y·V (Z=0 from Fill)
    pos2 = nodes.new('GeometryNodeInputPosition'); pos2.location = (600, 300)
    sep_pos = nodes.new('ShaderNodeSeparateXYZ'); sep_pos.location = (800, 300)
    link(pos2.outputs['Position'], sep_pos.inputs[0])

    u_scaled = _add_scale(ng, group_in.outputs['U'], sep_pos.outputs['X'])
    v_scaled = _add_scale(ng, group_in.outputs['V'], sep_pos.outputs['Y'])
    uv_sum = _add_vec_op(ng, 'ADD', u_scaled, v_scaled)
    world_back = _add_vec_op(ng, 'ADD', uv_sum, group_in.outputs['Center'])

    set_pos_back = nodes.new('GeometryNodeSetPosition'); set_pos_back.location = (1700, 0)
    link(fill.outputs['Mesh'], set_pos_back.inputs['Geometry'])
    link(world_back, set_pos_back.inputs['Position'])

    merge_pre_extrude = nodes.new('GeometryNodeMergeByDistance'); merge_pre_extrude.location = (1900, 0)
    merge_pre_extrude.inputs['Distance'].default_value = 0.001
    link(set_pos_back.outputs['Geometry'], merge_pre_extrude.inputs['Geometry'])

    extrude = nodes.new('GeometryNodeExtrudeMesh'); extrude.location = (2100, 0)
    extrude.inputs['Individual'].default_value = False
    link(merge_pre_extrude.outputs['Geometry'], extrude.inputs['Mesh'])
    link(group_in.outputs['Normal'], extrude.inputs['Offset'])
    link(group_in.outputs['Thickness'], extrude.inputs['Offset Scale'])

    flip = nodes.new('GeometryNodeFlipFaces'); flip.location = (2100, -200)
    link(merge_pre_extrude.outputs['Geometry'], flip.inputs['Mesh'])

    join = nodes.new('GeometryNodeJoinGeometry'); join.location = (2300, 0)
    link(extrude.outputs['Mesh'], join.inputs['Geometry'])
    link(flip.outputs['Mesh'], join.inputs['Geometry'])

    merge_final = nodes.new('GeometryNodeMergeByDistance'); merge_final.location = (2500, 0)
    merge_final.inputs['Distance'].default_value = 0.001
    link(join.outputs['Geometry'], merge_final.inputs['Geometry'])

    inflated = _build_inflate(ng, group_in, fill.outputs['Mesh'], resample.outputs['Curve'], world_back)
    use_inflate = nodes.new('GeometryNodeSwitch'); use_inflate.location = (3100, 0)
    use_inflate.input_type = 'GEOMETRY'
    link(_add_compare(ng, 'GREATER_THAN', group_in.outputs['Inflate'], 0.0), use_inflate.inputs['Switch'])
    link(merge_final.outputs['Geometry'], use_inflate.inputs['False'])
    link(inflated, use_inflate.inputs['True'])

    group_out = nodes.new('NodeGroupOutput'); group_out.location = (3300, 0)
    link(use_inflate.outputs['Output'], group_out.inputs['Geometry'])


def get_or_create_solid_node_group():
    return get_or_rebuild_group(NODE_GROUP_NAME, GROUP_VERSION, _build)


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class GPTOOLS_OT_gn_solid_mesh(bpy.types.Operator):
    """Add a Geometry Nodes modifier on the Grease Pencil that renders its
    strokes as a solid extruded shape. Live-linked to the GP — editing strokes
    updates the result. Depth and resolution are editable on the modifier."""

    bl_idname = "gptools.gn_solid_mesh"
    bl_label = "Solid Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        basis = compute_plane_basis(context, gp_obj)
        if basis is None:
            self.report({"ERROR"}, "Need at least 3 stroke points")
            return {"CANCELLED"}

        node_group = get_or_create_solid_node_group()
        mod = ensure_nodes_modifier(gp_obj, MODIFIER_NAME, node_group)
        set_plane_basis_inputs(mod, node_group, basis)

        gp_obj.update_tag()

        for o in context.view_layer.objects:
            if o.select_get():
                o.select_set(False)
        gp_obj.select_set(True)
        context.view_layer.objects.active = gp_obj

        show_modifier_tab(context)

        self.report(
            {"INFO"},
            "Solid mesh modifier added. Edit strokes to reshape; adjust Thickness for depth.",
        )
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
