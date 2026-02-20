import bpy
from ..utils.conversion import get_active_grease_pencil

NODE_GROUP_NAME = "GreaseMesh_Path"

PROFILE_LAYER_NAME = "Profile"
PATH_LAYER_NAME = "Path"


def _layer_has_strokes(layer):
    """Check if a GP layer has any drawn strokes."""
    return any(len(f.drawing.strokes) > 0 for f in layer.frames)


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


def _add_center_offset(ng, link, curve_out, x, y):
    """Center geometry at origin using bbox. Returns Set Position output."""
    bbox = ng.nodes.new('GeometryNodeBoundBox')
    bbox.location = (x, y - 200)

    vec_add = ng.nodes.new('ShaderNodeVectorMath')
    vec_add.location = (x + 200, y - 200)
    vec_add.operation = 'ADD'

    vec_half = ng.nodes.new('ShaderNodeVectorMath')
    vec_half.location = (x + 400, y - 200)
    vec_half.operation = 'SCALE'
    vec_half.inputs['Scale'].default_value = 0.5

    vec_neg = ng.nodes.new('ShaderNodeVectorMath')
    vec_neg.location = (x + 600, y - 200)
    vec_neg.operation = 'SCALE'
    vec_neg.inputs['Scale'].default_value = -1.0

    pos = ng.nodes.new('GeometryNodeInputPosition')
    pos.location = (x + 400, y + 100)

    add_offset = ng.nodes.new('ShaderNodeVectorMath')
    add_offset.location = (x + 800, y + 100)
    add_offset.operation = 'ADD'

    set_pos = ng.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (x + 1000, y)

    link(curve_out, bbox.inputs['Geometry'])
    link(bbox.outputs['Min'], vec_add.inputs[0])
    link(bbox.outputs['Max'], vec_add.inputs[1])
    link(vec_add.outputs['Vector'], vec_half.inputs[0])
    link(vec_half.outputs['Vector'], vec_neg.inputs[0])
    link(pos.outputs['Position'], add_offset.inputs[0])
    link(vec_neg.outputs['Vector'], add_offset.inputs[1])
    link(curve_out, set_pos.inputs['Geometry'])
    link(add_offset.outputs['Vector'], set_pos.inputs['Position'])

    return set_pos.outputs['Geometry']


def get_or_create_path_node_group():
    """Get existing or build the Path Mesh geometry node group.

    Pipeline:
      Profile: GP → Named Layer Selection → GP to Curves → Resample → Cyclic → Center
      Path:    GP → Named Layer Selection → GP to Curves → Resample
      Curve to Mesh(path, centered_profile, Fill Caps) → Shade Smooth → Output
    """
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        return ng

    ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')
    _build_interface(ng)

    link = ng.links.new

    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (-1000, 0)

    # Profile branch (cyclic, centered)
    profile_out = _add_gp_branch(
        ng, link, group_in, PROFILE_LAYER_NAME, 'Profile Resolution',
        cyclic=True, x=-800, y=200,
    )
    centered_profile = _add_center_offset(ng, link, profile_out, x=0, y=200)

    # Path branch (open curve)
    path_out = _add_gp_branch(
        ng, link, group_in, PATH_LAYER_NAME, 'Path Resolution',
        cyclic=False, x=-800, y=-200,
    )

    # Sweep profile along path
    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (1200, 0)

    shade = ng.nodes.new('GeometryNodeSetShadeSmooth')
    shade.location = (1400, 0)

    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (1600, 0)

    link(path_out, curve_to_mesh.inputs['Curve'])
    link(centered_profile, curve_to_mesh.inputs['Profile Curve'])
    link(group_in.outputs['Fill Caps'], curve_to_mesh.inputs['Fill Caps'])
    link(curve_to_mesh.outputs['Mesh'], shade.inputs['Mesh'])
    link(shade.outputs['Mesh'], group_out.inputs['Geometry'])

    return ng


def _show_properties_tab(context, tab):
    """Switch Properties editor to a specific tab."""
    try:
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        space.context = tab
                        return
    except TypeError:
        pass


class GPTOOLS_OT_gn_path_mesh(bpy.types.Operator):
    """Add Geometry Nodes modifier to sweep a profile along a path from Grease Pencil layers"""

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
        profile = gp_data.layers.get(PROFILE_LAYER_NAME)
        path = gp_data.layers.get(PATH_LAYER_NAME)
        has_profile = profile and _layer_has_strokes(profile)
        has_path = path and _layer_has_strokes(path)

        if not has_profile and not has_path:
            self.report({"WARNING"}, "Draw a line first, then click Path Mesh again.")
            return {"CANCELLED"}

        if not has_profile:
            _show_properties_tab(context, 'DATA')
            gp_data.layers.active = profile
            self.report(
                {"WARNING"},
                "Now draw the cross-section on the 'Profile' layer, then click Path Mesh again.",
            )
            return {"CANCELLED"}

        if not has_path:
            _show_properties_tab(context, 'DATA')
            gp_data.layers.active = path
            self.report({"WARNING"}, "No strokes on 'Path' layer. Draw your sweep line there.")
            return {"CANCELLED"}

        mod = gp_obj.modifiers.new(name="PathMesh", type='NODES')
        mod.node_group = get_or_create_path_node_group()

        context.view_layer.objects.active = gp_obj
        gp_obj.select_set(True)

        _show_properties_tab(context, 'MODIFIER')

        self.report({"INFO"}, "Path mesh GN modifier added.")
        return {"FINISHED"}


classes = [GPTOOLS_OT_gn_path_mesh]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
