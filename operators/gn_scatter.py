import math

import bpy
from ..utils.conversion import get_active_grease_pencil
from ..utils.modifier_io import (
    set_input, set_menu, ensure_nodes_modifier, show_modifier_tab,
)
from ..utils.node_groups import get_or_rebuild_group

NODE_GROUP_NAME = "GreaseMesh_Scatter"
GROUP_VERSION = 1
MODIFIER_NAME = "Scatter"
ROT_ATTR = "gm_scatter_rot"

MODE_ALONG = "Along Stroke"
MODE_AREA = "Fill Area"


def _build_interface(ng):
    new = ng.interface.new_socket

    new(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    new(name="Collection", in_out='INPUT', socket_type='NodeSocketCollection')
    new(name="Ground Object", in_out='INPUT', socket_type='NodeSocketObject')
    new(name="Mode", in_out='INPUT', socket_type='NodeSocketMenu')

    def num(name, kind, default, lo, hi, subtype=None):
        s = new(name=name, in_out='INPUT', socket_type=kind)
        s.default_value, s.min_value, s.max_value = default, lo, hi
        if subtype:
            s.subtype = subtype
        return s

    F, I = 'NodeSocketFloat', 'NodeSocketInt'
    num("Spacing", F, 1.0, 0.01, 1000.0, 'DISTANCE')
    num("Density", F, 1.0, 0.0, 1000.0)
    num("Min Distance", F, 0.5, 0.0, 1000.0, 'DISTANCE')
    num("Scale Min", F, 0.8, 0.0, 100.0)
    num("Scale Max", F, 1.2, 0.0, 100.0)
    num("Random Rotation", F, 1.0, 0.0, 1.0, 'FACTOR')
    s = new(name="Follow Stroke", in_out='INPUT', socket_type='NodeSocketBool')
    s.default_value = False
    num("Align to Ground", F, 0.0, 0.0, 1.0, 'FACTOR')
    num("Ground Offset", F, 0.0, -100.0, 100.0, 'DISTANCE')
    s = new(name="Show Strokes", in_out='INPUT', socket_type='NodeSocketBool')
    s.default_value = False
    num("Seed", I, 0, -10000, 10000)

    new(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')


def _build(ng):
    _build_interface(ng)
    nodes = ng.nodes
    L = ng.links.new

    def node(idtype, x, y, **props):
        n = nodes.new(idtype)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def mathn(op, a, b=None, x=0, y=0):
        n = node('ShaderNodeMath', x, y, operation=op)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L(v, n.inputs[i])
        return n.outputs[0]

    gin = node('NodeGroupInput', -2400, 0)
    gout = node('NodeGroupOutput', 3600, 0)
    I = gin.outputs

    # ---- GP -> curves ----
    gp2c = node('GeometryNodeGreasePencilToCurves', -2100, 0)
    gp2c.inputs['Layers as Instances'].default_value = False
    L(I['Geometry'], gp2c.inputs['Grease Pencil'])

    # ---- Along branch ----
    c2p = node('GeometryNodeCurveToPoints', -1800, 300, mode='LENGTH')
    L(gp2c.outputs['Curves'], c2p.inputs['Curve'])
    L(I['Spacing'], c2p.inputs['Length'])
    store_rot = node('GeometryNodeStoreNamedAttribute', -1500, 300, data_type='QUATERNION', domain='POINT')
    store_rot.inputs['Name'].default_value = ROT_ATTR
    L(c2p.outputs['Points'], store_rot.inputs['Geometry'])
    # Curve to Points' own Rotation has Z along the tangent (props would lie
    # on their side), so build an upright yaw instead: local X along the
    # horizontal tangent.
    flat = node('ShaderNodeVectorMath', -1650, 450, operation='MULTIPLY')
    L(c2p.outputs['Tangent'], flat.inputs[0])
    flat.inputs[1].default_value = (1, 1, 0)
    yaw = node('FunctionNodeAlignRotationToVector', -1500, 450, axis='X')
    yaw.inputs['Factor'].default_value = 1.0
    L(flat.outputs['Vector'], yaw.inputs['Vector'])
    L(yaw.outputs['Rotation'], store_rot.inputs['Value'])

    # ---- Area branch ----
    cyc = node('GeometryNodeSetSplineCyclic', -1800, -300)
    cyc.inputs['Cyclic'].default_value = True
    L(gp2c.outputs['Curves'], cyc.inputs['Curve'])
    fill = node('GeometryNodeFillCurve', -1600, -300)
    fill.inputs['Fill Rule'].default_value = 'Even-Odd'
    L(cyc.outputs['Curve'], fill.inputs['Curve'])
    dist = node('GeometryNodeDistributePointsOnFaces', -1400, -300,
                distribute_method='POISSON')
    L(fill.outputs['Mesh'], dist.inputs['Mesh'])
    L(I['Density'], dist.inputs['Density Max'])
    L(I['Min Distance'], dist.inputs['Distance Min'])
    L(I['Seed'], dist.inputs['Seed'])

    # ---- Mode switch ----
    ms = node('GeometryNodeMenuSwitch', -1100, 0, data_type='GEOMETRY')
    ms.enum_items.clear()
    ms.enum_items.new(MODE_ALONG)
    ms.enum_items.new(MODE_AREA)
    L(I['Mode'], ms.inputs['Menu'])
    L(store_rot.outputs['Geometry'], ms.inputs[MODE_ALONG])
    L(dist.outputs['Points'], ms.inputs[MODE_AREA])

    # ---- Snap to ground ----
    gobj = node('GeometryNodeObjectInfo', -900, 300, transform_space='RELATIVE')
    gobj.inputs['As Instance'].default_value = False
    L(I['Ground Object'], gobj.inputs['Object'])

    pos = node('GeometryNodeInputPosition', -900, -150)
    lift = node('ShaderNodeVectorMath', -700, -150, operation='ADD')
    L(pos.outputs['Position'], lift.inputs[0])
    lift.inputs[1].default_value = (0, 0, 100)
    ray = node('GeometryNodeRaycast', -500, 150)
    L(gobj.outputs['Geometry'], ray.inputs['Target Geometry'])
    L(lift.outputs['Vector'], ray.inputs['Source Position'])
    ray.inputs['Ray Direction'].default_value = (0, 0, -1)
    ray.inputs['Ray Length'].default_value = 1000.0

    off = node('ShaderNodeCombineXYZ', -500, -100)
    L(I['Ground Offset'], off.inputs['Z'])
    hitpos = node('ShaderNodeVectorMath', -300, 0, operation='ADD')
    L(ray.outputs['Hit Position'], hitpos.inputs[0])
    L(off.outputs['Vector'], hitpos.inputs[1])
    setpos = node('GeometryNodeSetPosition', -100, 0)
    L(ms.outputs['Output'], setpos.inputs['Geometry'])
    L(ray.outputs['Is Hit'], setpos.inputs['Selection'])
    L(hitpos.outputs['Vector'], setpos.inputs['Position'])

    # ---- Rotation ----
    rot_in = node('GeometryNodeInputNamedAttribute', 100, -300, data_type='QUATERNION')
    rot_in.inputs['Name'].default_value = ROT_ATTR
    follow = node('GeometryNodeSwitch', 300, -300, input_type='ROTATION')
    L(I['Follow Stroke'], follow.inputs['Switch'])
    L(rot_in.outputs['Attribute'], follow.inputs['True'])
    # False stays identity

    nrm = node('GeometryNodeSwitch', 300, -500, input_type='VECTOR')
    L(ray.outputs['Is Hit'], nrm.inputs['Switch'])
    nrm.inputs['False'].default_value = (0, 0, 1)
    L(ray.outputs['Hit Normal'], nrm.inputs['True'])
    align = node('FunctionNodeAlignRotationToVector', 500, -300, axis='Z')
    L(follow.outputs['Output'], align.inputs['Rotation'])
    L(I['Align to Ground'], align.inputs['Factor'])
    L(nrm.outputs['Output'], align.inputs['Vector'])

    seed31 = mathn('ADD', I['Seed'], 31, 100, -700)
    rnd_ang = node('FunctionNodeRandomValue', 300, -700, data_type='FLOAT')
    rnd_ang.inputs['Min'].default_value = 0.0
    rnd_ang.inputs['Max'].default_value = 2 * math.pi
    L(seed31, rnd_ang.inputs['Seed'])
    ang = mathn('MULTIPLY', _out(rnd_ang, 'FLOAT'),
               I['Random Rotation'], 500, -700)
    aa = node('FunctionNodeAxisAngleToRotation', 700, -600)
    aa.inputs['Axis'].default_value = (0, 0, 1)
    L(ang, aa.inputs['Angle'])
    rr = node('FunctionNodeRotateRotation', 900, -400, rotation_space='LOCAL')
    L(align.outputs['Rotation'], rr.inputs['Rotation'])
    L(aa.outputs['Rotation'], rr.inputs['Rotate By'])

    # ---- Scale ----
    seed67 = mathn('ADD', I['Seed'], 67, 100, -900)
    rnd_sc = node('FunctionNodeRandomValue', 300, -900, data_type='FLOAT')
    L(I['Scale Min'], rnd_sc.inputs['Min'])
    L(I['Scale Max'], rnd_sc.inputs['Max'])
    L(seed67, rnd_sc.inputs['Seed'])
    sc = node('ShaderNodeCombineXYZ', 700, -900)
    sv = _out(rnd_sc, 'FLOAT')
    L(sv, sc.inputs['X'])
    L(sv, sc.inputs['Y'])
    L(sv, sc.inputs['Z'])

    # ---- Instances ----
    cinfo = node('GeometryNodeCollectionInfo', 900, 300, transform_space='RELATIVE')
    cinfo.inputs['Separate Children'].default_value = True
    cinfo.inputs['Reset Children'].default_value = True
    L(I['Collection'], cinfo.inputs['Collection'])

    rnd_idx = node('FunctionNodeRandomValue', 900, -900, data_type='INT')
    rnd_idx.inputs['Min'].default_value = 0
    rnd_idx.inputs['Max'].default_value = 100000
    L(I['Seed'], rnd_idx.inputs['Seed'])

    iop = node('GeometryNodeInstanceOnPoints', 1300, 0)
    iop.inputs['Pick Instance'].default_value = True
    L(setpos.outputs['Geometry'], iop.inputs['Points'])
    L(cinfo.outputs['Instances'], iop.inputs['Instance'])
    L(_out(rnd_idx, 'INT'), iop.inputs['Instance Index'])
    L(rr.outputs['Rotation'], iop.inputs['Rotation'])
    L(sc.outputs['Vector'], iop.inputs['Scale'])

    # ---- Output ----
    show = node('GeometryNodeSwitch', 1500, -200, input_type='GEOMETRY')
    L(I['Show Strokes'], show.inputs['Switch'])
    L(I['Geometry'], show.inputs['True'])
    join = node('GeometryNodeJoinGeometry', 1700, 0)
    L(iop.outputs['Instances'], join.inputs['Geometry'])
    L(show.outputs['Output'], join.inputs['Geometry'])
    L(join.outputs['Geometry'], gout.inputs['Geometry'])


def _out(rnd_node, kind):
    """Return the Random Value output socket matching ``kind`` (it has one per type)."""
    want = {'FLOAT': 'VALUE', 'INT': 'INT'}[kind]
    for s in rnd_node.outputs:
        if s.enabled and s.type == want:
            return s
    return rnd_node.outputs[0]


def get_or_create_scatter_node_group():
    return get_or_rebuild_group(NODE_GROUP_NAME, GROUP_VERSION, _build)


def _menu_identifier(ng, name):
    for item in ng.interface.items_tree:
        if item.name == name and item.socket_type == 'NodeSocketMenu':
            return item.identifier
    return None


def _socket_id(ng, name):
    for item in ng.interface.items_tree:
        if item.name == name and getattr(item, "in_out", None) == 'INPUT':
            return item.identifier
    return None


class GPTOOLS_OT_gn_scatter(bpy.types.Operator):
    """Scatter objects from a collection along strokes or inside drawn areas, snapped to a ground object"""

    bl_idname = "gptools.gn_scatter"
    bl_label = "Scatter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        ng = get_or_create_scatter_node_group()
        existed = gp_obj.modifiers.get(MODIFIER_NAME) is not None
        mod = ensure_nodes_modifier(gp_obj, MODIFIER_NAME, ng)

        if not existed:
            mode_id = _menu_identifier(ng, "Mode")
            if mode_id:
                set_menu(mod, mode_id, MODE_ALONG,
                         legacy_value=0, legacy_menu=MODE_ALONG)

            col = context.collection
            if (col is not None and col != context.scene.collection
                    and len(col.objects) > 0
                    and gp_obj.name not in col.objects):
                set_input(mod, _socket_id(ng, "Collection"), col)

            others = [o for o in context.selected_objects
                      if o != gp_obj and o.type == 'MESH']
            if len(others) == 1:
                set_input(mod, _socket_id(ng, "Ground Object"), others[0])
            else:
                self.report({"WARNING"},
                            "Pick a Ground Object on the Scatter modifier")

        context.view_layer.objects.active = gp_obj
        gp_obj.select_set(True)
        show_modifier_tab(context)
        return {"FINISHED"}


classes = [GPTOOLS_OT_gn_scatter]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
