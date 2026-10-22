import bpy
from ..utils.conversion import get_active_grease_pencil
from ..utils.modifier_io import (
    ensure_nodes_modifier, set_input, set_menu, show_modifier_tab,
)
from ..utils.node_groups import get_or_rebuild_group
from .gn_solid_mesh import compute_plane_basis, set_plane_basis_inputs

NODE_GROUP_NAME = "GreaseMesh_Stroke"
GROUP_VERSION = 2  # bump whenever the graph or interface below changes

MODIFIER_NAME = "StrokeMesh"
SURFACE_SOCKET_NAME = "Surface Object"
STASH_ATTR = "gm_stroke_mat"


def _build(ng):
    """Build the Stroke Mesh node group into the empty tree ``ng``.

    Pipeline:
      GP → Curves (keeps radius, vertex_color, material_index)
        → Set Position (Project onto Surface: snap points to the Surface Object,
          nearest point or along the drawing direction)
        → Set Curve Normal (Free; surface normal if Surface Object, else plane Normal)
        → Set Position (lift along that normal by Surface Offset)
        → Curve to Mesh with a flat line profile (Ribbon) or a circle (Tube)
          (Scale = curve radius * Width Scale)
        → Menu Switch(Mode) → Shade Smooth → Output
    """
    iface = ng.interface
    link = ng.links.new

    # ---- interface -------------------------------------------------------
    iface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    iface.new_socket(name="Mode", in_out='INPUT', socket_type='NodeSocketMenu')

    s = iface.new_socket(name="Width Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    s.default_value, s.min_value = 1.0, 0.0

    s = iface.new_socket(name="Profile Resolution", in_out='INPUT', socket_type='NodeSocketInt')
    s.default_value, s.min_value, s.max_value = 6, 3, 64

    iface.new_socket(name=SURFACE_SOCKET_NAME, in_out='INPUT', socket_type='NodeSocketObject')

    s = iface.new_socket(name="Project onto Surface", in_out='INPUT', socket_type='NodeSocketBool')
    s.default_value = True

    iface.new_socket(name="Projection", in_out='INPUT', socket_type='NodeSocketMenu')

    s = iface.new_socket(name="Surface Offset", in_out='INPUT', socket_type='NodeSocketFloat')
    s.default_value, s.min_value = 0.002, 0.0
    s.subtype = 'DISTANCE'

    for name, default in (
        ("Center", (0.0, 0.0, 0.0)),
        ("U", (1.0, 0.0, 0.0)),
        ("V", (0.0, 1.0, 0.0)),
        ("Normal", (0.0, 0.0, 1.0)),
    ):
        s = iface.new_socket(name=name, in_out='INPUT', socket_type='NodeSocketVector')
        s.default_value = default
        s.hide_in_modifier = True

    iface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # ---- nodes -----------------------------------------------------------
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (-1400, 0)

    gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    gp_to_curves.location = (-1200, 200)
    gp_to_curves.inputs['Layers as Instances'].default_value = False
    link(group_in.outputs['Geometry'], gp_to_curves.inputs['Grease Pencil'])

    # Surface normal lookup
    obj_info = ng.nodes.new('GeometryNodeObjectInfo')
    obj_info.location = (-1200, -200)
    obj_info.transform_space = 'RELATIVE'
    link(group_in.outputs[SURFACE_SOCKET_NAME], obj_info.inputs['Object'])

    position = ng.nodes.new('GeometryNodeInputPosition')
    position.location = (-1200, -400)

    surf_normal = ng.nodes.new('GeometryNodeInputNormal')
    surf_normal.location = (-1200, -550)

    sample = ng.nodes.new('GeometryNodeSampleNearestSurface')
    sample.location = (-1000, -300)
    sample.data_type = 'FLOAT_VECTOR'
    link(obj_info.outputs['Geometry'], sample.inputs['Mesh'])
    link(surf_normal.outputs['Normal'], sample.inputs['Value'])
    link(position.outputs['Position'], sample.inputs['Sample Position'])

    normal_switch = ng.nodes.new('GeometryNodeSwitch')
    normal_switch.location = (-800, -300)
    normal_switch.input_type = 'VECTOR'
    link(sample.outputs['Is Valid'], normal_switch.inputs['Switch'])
    link(group_in.outputs['Normal'], normal_switch.inputs['False'])
    link(sample.outputs['Value'], normal_switch.inputs['True'])

    # Curve to Mesh does not carry the per-stroke material_index to faces, but it
    # does carry point attributes to vertices. Stash it on the points first and
    # restore it per face after the mesh is built.
    mat_in = ng.nodes.new('GeometryNodeInputNamedAttribute')
    mat_in.location = (-1000, 400)
    mat_in.data_type = 'INT'
    mat_in.inputs['Name'].default_value = "material_index"

    mat_stash = ng.nodes.new('GeometryNodeStoreNamedAttribute')
    mat_stash.location = (-1000, 200)
    mat_stash.data_type = 'INT'
    mat_stash.domain = 'POINT'
    mat_stash.inputs['Name'].default_value = STASH_ATTR
    link(gp_to_curves.outputs['Curves'], mat_stash.inputs['Geometry'])
    link(mat_in.outputs['Attribute'], mat_stash.inputs['Value'])

    # Project onto Surface. Nearest: closest point on the surface. Drawing
    # Direction: ray along -Normal (the drawing plane faces the viewport), so a
    # drawing made in front of the surface lands on it like a projector; misses
    # fall back to nearest.
    near_pos = ng.nodes.new('GeometryNodeSampleNearestSurface')
    near_pos.location = (-1000, 700)
    near_pos.data_type = 'FLOAT_VECTOR'
    link(obj_info.outputs['Geometry'], near_pos.inputs['Mesh'])
    link(position.outputs['Position'], near_pos.inputs['Value'])
    link(position.outputs['Position'], near_pos.inputs['Sample Position'])

    ray_start_offset = ng.nodes.new('ShaderNodeVectorMath')
    ray_start_offset.location = (-1200, 900)
    ray_start_offset.operation = 'SCALE'
    ray_start_offset.inputs['Scale'].default_value = 100.0
    link(group_in.outputs['Normal'], ray_start_offset.inputs[0])

    ray_start = ng.nodes.new('ShaderNodeVectorMath')
    ray_start.location = (-1000, 900)
    ray_start.operation = 'ADD'
    link(position.outputs['Position'], ray_start.inputs[0])
    link(ray_start_offset.outputs['Vector'], ray_start.inputs[1])

    ray_dir = ng.nodes.new('ShaderNodeVectorMath')
    ray_dir.location = (-1000, 1050)
    ray_dir.operation = 'SCALE'
    ray_dir.inputs['Scale'].default_value = -1.0
    link(group_in.outputs['Normal'], ray_dir.inputs[0])

    raycast = ng.nodes.new('GeometryNodeRaycast')
    raycast.location = (-800, 1000)
    raycast.inputs['Ray Length'].default_value = 1000.0
    link(obj_info.outputs['Geometry'], raycast.inputs['Target Geometry'])
    link(ray_start.outputs['Vector'], raycast.inputs['Source Position'])
    link(ray_dir.outputs['Vector'], raycast.inputs['Ray Direction'])

    ray_or_near = ng.nodes.new('GeometryNodeSwitch')
    ray_or_near.location = (-600, 900)
    ray_or_near.input_type = 'VECTOR'
    link(raycast.outputs['Is Hit'], ray_or_near.inputs['Switch'])
    link(near_pos.outputs['Value'], ray_or_near.inputs['False'])
    link(raycast.outputs['Hit Position'], ray_or_near.inputs['True'])

    projection = ng.nodes.new('GeometryNodeMenuSwitch')
    projection.location = (-400, 800)
    projection.data_type = 'VECTOR'
    projection.enum_items.clear()
    projection.enum_items.new("Nearest")
    projection.enum_items.new("Drawing Direction")
    link(group_in.outputs['Projection'], projection.inputs['Menu'])
    link(near_pos.outputs['Value'], projection.inputs['Nearest'])
    link(ray_or_near.outputs['Output'], projection.inputs['Drawing Direction'])

    # Only project when enabled and a Surface Object is set
    do_project = ng.nodes.new('FunctionNodeBooleanMath')
    do_project.location = (-400, 600)
    do_project.operation = 'AND'
    link(group_in.outputs['Project onto Surface'], do_project.inputs[0])
    link(near_pos.outputs['Is Valid'], do_project.inputs[1])

    project = ng.nodes.new('GeometryNodeSetPosition')
    project.location = (-200, 600)
    link(mat_stash.outputs['Geometry'], project.inputs['Geometry'])
    link(do_project.outputs['Boolean'], project.inputs['Selection'])
    link(projection.outputs['Output'], project.inputs['Position'])

    set_normal = ng.nodes.new('GeometryNodeSetCurveNormal')
    set_normal.location = (-800, 200)
    set_normal.inputs['Mode'].default_value = 'Free'
    link(project.outputs['Geometry'], set_normal.inputs['Curve'])
    link(normal_switch.outputs['Output'], set_normal.inputs['Normal'])

    # Lift off the surface along the normal
    offset_vec = ng.nodes.new('ShaderNodeVectorMath')
    offset_vec.location = (-600, -300)
    offset_vec.operation = 'SCALE'
    link(normal_switch.outputs['Output'], offset_vec.inputs[0])
    link(group_in.outputs['Surface Offset'], offset_vec.inputs['Scale'])

    lift = ng.nodes.new('GeometryNodeSetPosition')
    lift.location = (-600, 200)
    link(set_normal.outputs['Curve'], lift.inputs['Geometry'])
    link(offset_vec.outputs['Vector'], lift.inputs['Offset'])

    # Curve to Mesh does not apply the curve radius itself (verified in 5.2),
    # so Scale = radius * Width Scale.
    radius = ng.nodes.new('GeometryNodeInputRadius')
    radius.location = (-600, -500)
    scale = ng.nodes.new('ShaderNodeMath')
    scale.location = (-400, -500)
    scale.operation = 'MULTIPLY'
    link(radius.outputs['Radius'], scale.inputs[0])
    link(group_in.outputs['Width Scale'], scale.inputs[1])

    # Ribbon: profile along Y. Curve to Mesh maps profile X to the curve
    # normal, so X would stand edge-on to the drawing plane.
    ribbon_profile = ng.nodes.new('GeometryNodeCurvePrimitiveLine')
    ribbon_profile.location = (-600, 0)
    ribbon_profile.inputs['Start'].default_value = (0.0, -1.0, 0.0)
    ribbon_profile.inputs['End'].default_value = (0.0, 1.0, 0.0)

    ribbon = ng.nodes.new('GeometryNodeCurveToMesh')
    ribbon.location = (-300, 200)
    link(lift.outputs['Geometry'], ribbon.inputs['Curve'])
    link(ribbon_profile.outputs['Curve'], ribbon.inputs['Profile Curve'])
    link(scale.outputs['Value'], ribbon.inputs['Scale'])

    # Tube
    tube_profile = ng.nodes.new('GeometryNodeCurvePrimitiveCircle')
    tube_profile.location = (-600, -150)
    tube_profile.inputs['Radius'].default_value = 1.0
    link(group_in.outputs['Profile Resolution'], tube_profile.inputs['Resolution'])

    tube = ng.nodes.new('GeometryNodeCurveToMesh')
    tube.location = (-300, -100)
    tube.inputs['Fill Caps'].default_value = True
    link(lift.outputs['Geometry'], tube.inputs['Curve'])
    link(tube_profile.outputs['Curve'], tube.inputs['Profile Curve'])
    link(scale.outputs['Value'], tube.inputs['Scale'])

    # Mode switch
    menu = ng.nodes.new('GeometryNodeMenuSwitch')
    menu.location = (0, 100)
    menu.data_type = 'GEOMETRY'
    menu.enum_items.clear()
    menu.enum_items.new("Ribbon")
    menu.enum_items.new("Tube")
    link(group_in.outputs['Mode'], menu.inputs['Menu'])
    link(ribbon.outputs['Mesh'], menu.inputs['Ribbon'])
    link(tube.outputs['Mesh'], menu.inputs['Tube'])

    stash_in = ng.nodes.new('GeometryNodeInputNamedAttribute')
    stash_in.location = (0, -100)
    stash_in.data_type = 'INT'
    stash_in.inputs['Name'].default_value = STASH_ATTR

    mat_face = ng.nodes.new('GeometryNodeStoreNamedAttribute')
    mat_face.location = (200, 100)
    mat_face.data_type = 'INT'
    mat_face.domain = 'FACE'
    mat_face.inputs['Name'].default_value = "material_index"
    link(menu.outputs['Output'], mat_face.inputs['Geometry'])
    link(stash_in.outputs['Attribute'], mat_face.inputs['Value'])

    unstash = ng.nodes.new('GeometryNodeRemoveAttribute')
    unstash.location = (400, 100)
    unstash.inputs['Name'].default_value = STASH_ATTR
    link(mat_face.outputs['Geometry'], unstash.inputs['Geometry'])

    smooth = ng.nodes.new('GeometryNodeSetShadeSmooth')
    smooth.location = (600, 100)
    link(unstash.outputs['Geometry'], smooth.inputs['Mesh'])

    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (800, 100)
    link(smooth.outputs['Mesh'], group_out.inputs['Geometry'])


def get_or_create_stroke_node_group():
    return get_or_rebuild_group(NODE_GROUP_NAME, GROUP_VERSION, _build)


def _socket_identifier(ng, name):
    for item in ng.interface.items_tree:
        if getattr(item, 'in_out', None) == 'INPUT' and item.name == name:
            return item.identifier
    return None


class GPTOOLS_OT_gn_stroke_mesh(bpy.types.Operator):
    """Turn the drawing into a flat ribbon/tube mesh that keeps stroke widths and colours"""

    bl_idname = "gptools.gn_stroke_mesh"
    bl_label = "Stroke Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        values = compute_plane_basis(context, gp_obj)
        if values is None:
            self.report({"ERROR"}, "Draw some strokes first (need at least 3 points).")
            return {"CANCELLED"}

        ng = get_or_create_stroke_node_group()
        is_new = gp_obj.modifiers.get(MODIFIER_NAME) is None
        mod = ensure_nodes_modifier(gp_obj, MODIFIER_NAME, ng)
        set_plane_basis_inputs(mod, ng, values)

        # Menu defaults only on first creation so re-runs keep the user's choices
        if is_new:
            for name, value in (("Mode", 'Ribbon'), ("Projection", 'Nearest')):
                ident = _socket_identifier(ng, name)
                if ident:
                    set_menu(mod, ident, value, legacy_value=0, legacy_menu=value)

        others = [o for o in context.selected_objects if o != gp_obj and o.type == 'MESH']
        if len(others) == 1:
            surf_id = _socket_identifier(ng, SURFACE_SOCKET_NAME)
            if surf_id:
                set_input(mod, surf_id, others[0])

        context.view_layer.objects.active = gp_obj
        gp_obj.select_set(True)
        show_modifier_tab(context)

        self.report({"INFO"}, "Stroke mesh added. Apply, then Bind to Surface to rig it.")
        return {"FINISHED"}


classes = [GPTOOLS_OT_gn_stroke_mesh]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
