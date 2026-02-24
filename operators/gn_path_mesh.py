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

    s = ng.interface.new_socket(
        name="Corner Radius", in_out='INPUT', socket_type='NodeSocketFloat',
    )
    s.default_value, s.min_value, s.max_value = 0.1, 0.0, 10.0

    s = ng.interface.new_socket(
        name="Corner Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    s.default_value, s.min_value, s.max_value = 4, 1, 32

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


def _add_flatten_profile(ng, link, geometry_out, x, y):
    """Flatten profile to XY plane by detecting the thinnest bbox axis.

    Finds which axis (X, Y, or Z) has the smallest extent and discards it,
    remapping the other two axes to X and Y.  This lets users draw the
    profile from any view angle (top, front, side) and get a correct result.
    """
    # --- bbox extent per axis ---
    bbox = ng.nodes.new('GeometryNodeBoundBox')
    bbox.location = (x, y - 250)

    extent = ng.nodes.new('ShaderNodeVectorMath')
    extent.location = (x + 200, y - 250)
    extent.operation = 'SUBTRACT'

    sep_ext = ng.nodes.new('ShaderNodeSeparateXYZ')
    sep_ext.location = (x + 400, y - 250)

    link(geometry_out, bbox.inputs['Geometry'])
    link(bbox.outputs['Max'], extent.inputs[0])
    link(bbox.outputs['Min'], extent.inputs[1])
    link(extent.outputs['Vector'], sep_ext.inputs['Vector'])

    # --- detect thinnest axis ---
    # x_thin = (ext_x <= ext_y) AND (ext_x <= ext_z)
    cmp_xy = ng.nodes.new('FunctionNodeCompare')
    cmp_xy.location = (x + 600, y - 150)
    cmp_xy.data_type = 'FLOAT'
    cmp_xy.operation = 'LESS_EQUAL'

    cmp_xz = ng.nodes.new('FunctionNodeCompare')
    cmp_xz.location = (x + 600, y - 300)
    cmp_xz.data_type = 'FLOAT'
    cmp_xz.operation = 'LESS_EQUAL'

    x_thin = ng.nodes.new('FunctionNodeBooleanMath')
    x_thin.location = (x + 800, y - 200)
    x_thin.operation = 'AND'

    link(sep_ext.outputs['X'], cmp_xy.inputs['A'])
    link(sep_ext.outputs['Y'], cmp_xy.inputs['B'])
    link(sep_ext.outputs['X'], cmp_xz.inputs['A'])
    link(sep_ext.outputs['Z'], cmp_xz.inputs['B'])
    link(cmp_xy.outputs['Result'], x_thin.inputs[0])
    link(cmp_xz.outputs['Result'], x_thin.inputs[1])

    # y_thin = (ext_y < ext_x) AND (ext_y <= ext_z)
    cmp_yx = ng.nodes.new('FunctionNodeCompare')
    cmp_yx.location = (x + 600, y - 450)
    cmp_yx.data_type = 'FLOAT'
    cmp_yx.operation = 'LESS_THAN'

    cmp_yz = ng.nodes.new('FunctionNodeCompare')
    cmp_yz.location = (x + 600, y - 600)
    cmp_yz.data_type = 'FLOAT'
    cmp_yz.operation = 'LESS_EQUAL'

    y_thin = ng.nodes.new('FunctionNodeBooleanMath')
    y_thin.location = (x + 800, y - 500)
    y_thin.operation = 'AND'

    link(sep_ext.outputs['Y'], cmp_yx.inputs['A'])
    link(sep_ext.outputs['X'], cmp_yx.inputs['B'])
    link(sep_ext.outputs['Y'], cmp_yz.inputs['A'])
    link(sep_ext.outputs['Z'], cmp_yz.inputs['B'])
    link(cmp_yx.outputs['Result'], y_thin.inputs[0])
    link(cmp_yz.outputs['Result'], y_thin.inputs[1])

    # --- position components ---
    pos = ng.nodes.new('GeometryNodeInputPosition')
    pos.location = (x, y + 100)

    sep_pos = ng.nodes.new('ShaderNodeSeparateXYZ')
    sep_pos.location = (x + 200, y + 100)

    link(pos.outputs['Position'], sep_pos.inputs['Vector'])

    # --- build remapped positions ---
    # X thinnest → (Y, Z, 0)
    pos_x = ng.nodes.new('ShaderNodeCombineXYZ')
    pos_x.location = (x + 800, y + 200)
    link(sep_pos.outputs['Y'], pos_x.inputs['X'])
    link(sep_pos.outputs['Z'], pos_x.inputs['Y'])

    # Y thinnest → (X, Z, 0)
    pos_y = ng.nodes.new('ShaderNodeCombineXYZ')
    pos_y.location = (x + 800, y + 50)
    link(sep_pos.outputs['X'], pos_y.inputs['X'])
    link(sep_pos.outputs['Z'], pos_y.inputs['Y'])

    # Z thinnest → (X, Y, 0)
    pos_z = ng.nodes.new('ShaderNodeCombineXYZ')
    pos_z.location = (x + 800, y - 100)
    link(sep_pos.outputs['X'], pos_z.inputs['X'])
    link(sep_pos.outputs['Y'], pos_z.inputs['Y'])

    # --- switches to pick the right remap ---
    # inner switch: y_thin ? pos_y : pos_z
    sw_yz = ng.nodes.new('GeometryNodeSwitch')
    sw_yz.location = (x + 1000, y - 50)
    sw_yz.input_type = 'VECTOR'
    link(y_thin.outputs['Boolean'], sw_yz.inputs['Switch'])
    link(pos_z.outputs['Vector'], sw_yz.inputs['False'])
    link(pos_y.outputs['Vector'], sw_yz.inputs['True'])

    # outer switch: x_thin ? pos_x : sw_yz
    sw_final = ng.nodes.new('GeometryNodeSwitch')
    sw_final.location = (x + 1200, y + 100)
    sw_final.input_type = 'VECTOR'
    link(x_thin.outputs['Boolean'], sw_final.inputs['Switch'])
    link(sw_yz.outputs['Output'], sw_final.inputs['False'])
    link(pos_x.outputs['Vector'], sw_final.inputs['True'])

    # --- apply ---
    set_pos = ng.nodes.new('GeometryNodeSetPosition')
    set_pos.location = (x + 1400, y)
    link(geometry_out, set_pos.inputs['Geometry'])
    link(sw_final.outputs['Output'], set_pos.inputs['Position'])

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
    flattened_profile = _add_flatten_profile(ng, link, centered_profile, x=1100, y=200)

    # Path branch: GP → Curves → Fillet → Resample
    # (Fillet must come before Resample so it rounds actual corners, not every point)
    path_x = -800
    path_y = -200

    path_sel = ng.nodes.new('GeometryNodeInputNamedLayerSelection')
    path_sel.location = (path_x, path_y)
    path_sel.inputs['Name'].default_value = PATH_LAYER_NAME

    path_gp = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    path_gp.location = (path_x + 200, path_y)
    path_gp.inputs['Layers as Instances'].default_value = False

    fillet = ng.nodes.new('GeometryNodeFilletCurve')
    fillet.location = (path_x + 400, path_y)
    fillet.inputs['Mode'].default_value = 'Poly'

    path_resample = ng.nodes.new('GeometryNodeResampleCurve')
    path_resample.location = (path_x + 600, path_y)

    link(group_in.outputs['Geometry'], path_gp.inputs['Grease Pencil'])
    link(path_sel.outputs['Selection'], path_gp.inputs['Selection'])
    link(path_gp.outputs['Curves'], fillet.inputs['Curve'])
    link(group_in.outputs['Corner Radius'], fillet.inputs['Radius'])
    link(group_in.outputs['Corner Resolution'], fillet.inputs['Count'])
    link(fillet.outputs['Curve'], path_resample.inputs['Curve'])
    link(group_in.outputs['Path Resolution'], path_resample.inputs['Count'])
    path_out = path_resample.outputs['Curve']

    # Sweep profile along path
    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (1800, 0)

    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (2000, 0)

    link(path_out, curve_to_mesh.inputs['Curve'])
    link(flattened_profile, curve_to_mesh.inputs['Profile Curve'])
    link(group_in.outputs['Fill Caps'], curve_to_mesh.inputs['Fill Caps'])
    link(curve_to_mesh.outputs['Mesh'], group_out.inputs['Geometry'])

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
                "Draw the profile shape, then click Path Mesh again.",
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
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
