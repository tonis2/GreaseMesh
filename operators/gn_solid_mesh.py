import bpy
import mathutils
from ..utils.conversion import get_active_grease_pencil
from ..utils.modifier_io import set_input

NODE_GROUP_NAME = "GreaseMesh_Solid"
MODIFIER_NAME = "SolidMesh"


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
    ng.links.new(scalar, n.inputs['Scale'])
    return n.outputs['Vector']


def _add_vec_op(ng, op, a, b):
    n = ng.nodes.new('ShaderNodeVectorMath')
    n.operation = op
    ng.links.new(a, n.inputs[0])
    ng.links.new(b, n.inputs[1])
    return n.outputs['Vector']


def get_or_create_solid_node_group():
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

    group_out = nodes.new('NodeGroupOutput'); group_out.location = (2700, 0)
    link(merge_final.outputs['Geometry'], group_out.inputs['Geometry'])

    return ng


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

        pts = _gather_stroke_points_local(gp_obj)
        if len(pts) < 3:
            self.report({"ERROR"}, "Need at least 3 stroke points")
            return {"CANCELLED"}

        centroid_local, normal_local = _pca_plane(pts)

        mw = gp_obj.matrix_world
        centroid_world = mw @ centroid_local
        normal_world = (mw.to_3x3() @ normal_local).normalized()
        oriented = _sign_correct_outward(centroid_world, normal_world, gp_obj, context)
        if (oriented - normal_world).length > 1e-6:
            normal_local = -normal_local
        normal_local.normalize()

        u_local, v_local = _build_basis(normal_local)

        node_group = get_or_create_solid_node_group()

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
