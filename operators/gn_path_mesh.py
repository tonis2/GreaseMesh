import bpy
from ..utils.conversion import get_active_grease_pencil

NODE_GROUP_NAME = "GreaseMesh_Path"

PROFILE_LAYER_NAME = "Profile"
PATH_LAYER_NAME = "Path"


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
            has_strokes = any(len(f.drawing.strokes) > 0 for f in layer.frames)
            if has_strokes:
                layer.name = PATH_LAYER_NAME
                break

    # Create any missing layers with a drawable frame
    for name in [PROFILE_LAYER_NAME, PATH_LAYER_NAME]:
        layer = gp_data.layers.get(name)
        if layer is None:
            layer = gp_data.layers.new(name)
        if len(layer.frames) == 0:
            layer.frames.new(scene_frame)


def get_or_create_path_node_group():
    """Get existing or build the Path Mesh geometry node group.

    Pipeline:
      GP → Named Layer Selection("Profile") → GP to Curves → Resample → Set Cyclic → profile
      GP → Named Layer Selection("Path")    → GP to Curves → Resample              → path
      Curve to Mesh(path, profile, Fill Caps) → Shade Smooth → Output
    """
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None:
        return ng

    ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

    # Interface sockets
    ng.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')

    profile_res_sock = ng.interface.new_socket(
        name="Profile Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    profile_res_sock.default_value = 32
    profile_res_sock.min_value = 3
    profile_res_sock.max_value = 256

    path_res_sock = ng.interface.new_socket(
        name="Path Resolution", in_out='INPUT', socket_type='NodeSocketInt',
    )
    path_res_sock.default_value = 64
    path_res_sock.min_value = 3
    path_res_sock.max_value = 512

    caps_sock = ng.interface.new_socket(
        name="Fill Caps", in_out='INPUT', socket_type='NodeSocketBool',
    )
    caps_sock.default_value = True

    ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # --- Nodes ---
    group_in = ng.nodes.new('NodeGroupInput')
    group_in.location = (-1000, 0)

    # === Profile branch (top) ===
    x_p = -800
    profile_sel = ng.nodes.new('GeometryNodeInputNamedLayerSelection')
    profile_sel.location = (x_p, 200)
    profile_sel.inputs['Name'].default_value = PROFILE_LAYER_NAME

    x_p += 200
    profile_gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    profile_gp_to_curves.location = (x_p, 200)
    profile_gp_to_curves.inputs['Layers as Instances'].default_value = False

    x_p += 200
    profile_resample = ng.nodes.new('GeometryNodeResampleCurve')
    profile_resample.location = (x_p, 200)

    x_p += 200
    profile_cyclic = ng.nodes.new('GeometryNodeSetSplineCyclic')
    profile_cyclic.location = (x_p, 200)
    profile_cyclic.inputs['Cyclic'].default_value = True

    # Center the profile: compute bounding box center, subtract from positions
    x_p += 200
    profile_bbox = ng.nodes.new('GeometryNodeBoundBox')
    profile_bbox.location = (x_p, 0)

    # center = (Min + Max) / 2
    x_p += 200
    vec_add = ng.nodes.new('ShaderNodeVectorMath')
    vec_add.location = (x_p, -50)
    vec_add.operation = 'ADD'

    vec_scale = ng.nodes.new('ShaderNodeVectorMath')
    vec_scale.location = (x_p + 200, -50)
    vec_scale.operation = 'SCALE'
    vec_scale.inputs['Scale'].default_value = 0.5

    # offset = -center
    vec_negate = ng.nodes.new('ShaderNodeVectorMath')
    vec_negate.location = (x_p + 400, -50)
    vec_negate.operation = 'SCALE'
    vec_negate.inputs['Scale'].default_value = -1.0

    # Apply offset to profile positions
    profile_pos = ng.nodes.new('GeometryNodeInputPosition')
    profile_pos.location = (x_p + 200, 300)

    vec_add_offset = ng.nodes.new('ShaderNodeVectorMath')
    vec_add_offset.location = (x_p + 600, 300)
    vec_add_offset.operation = 'ADD'

    profile_set_pos = ng.nodes.new('GeometryNodeSetPosition')
    profile_set_pos.location = (x_p + 800, 200)

    # === Path branch (bottom) ===
    path_sel = ng.nodes.new('GeometryNodeInputNamedLayerSelection')
    path_sel.location = (-800, -200)
    path_sel.inputs['Name'].default_value = PATH_LAYER_NAME

    path_gp_to_curves = ng.nodes.new('GeometryNodeGreasePencilToCurves')
    path_gp_to_curves.location = (-600, -200)
    path_gp_to_curves.inputs['Layers as Instances'].default_value = False

    path_resample = ng.nodes.new('GeometryNodeResampleCurve')
    path_resample.location = (-400, -200)

    # === Sweep ===
    curve_to_mesh = ng.nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.location = (x_p + 1000, 0)

    shade = ng.nodes.new('GeometryNodeSetShadeSmooth')
    shade.location = (x_p + 1200, 0)

    group_out = ng.nodes.new('NodeGroupOutput')
    group_out.location = (x_p + 1400, 0)

    # --- Links ---
    link = ng.links.new

    # Profile branch: GP → Curves → Resample → Cyclic
    link(group_in.outputs['Geometry'], profile_gp_to_curves.inputs['Grease Pencil'])
    link(profile_sel.outputs['Selection'], profile_gp_to_curves.inputs['Selection'])
    link(profile_gp_to_curves.outputs['Curves'], profile_resample.inputs['Curve'])
    link(group_in.outputs['Profile Resolution'], profile_resample.inputs['Count'])
    link(profile_resample.outputs['Curve'], profile_cyclic.inputs['Curve'])

    # Center profile: bbox → center → negate → offset positions
    link(profile_cyclic.outputs['Curve'], profile_bbox.inputs['Geometry'])
    link(profile_bbox.outputs['Min'], vec_add.inputs[0])
    link(profile_bbox.outputs['Max'], vec_add.inputs[1])
    link(vec_add.outputs['Vector'], vec_scale.inputs[0])
    link(vec_scale.outputs['Vector'], vec_negate.inputs[0])
    link(profile_pos.outputs['Position'], vec_add_offset.inputs[0])
    link(vec_negate.outputs['Vector'], vec_add_offset.inputs[1])
    link(profile_cyclic.outputs['Curve'], profile_set_pos.inputs['Geometry'])
    link(vec_add_offset.outputs['Vector'], profile_set_pos.inputs['Position'])

    # Path branch
    link(group_in.outputs['Geometry'], path_gp_to_curves.inputs['Grease Pencil'])
    link(path_sel.outputs['Selection'], path_gp_to_curves.inputs['Selection'])
    link(path_gp_to_curves.outputs['Curves'], path_resample.inputs['Curve'])
    link(group_in.outputs['Path Resolution'], path_resample.inputs['Count'])

    # Sweep centered profile along path
    link(path_resample.outputs['Curve'], curve_to_mesh.inputs['Curve'])
    link(profile_set_pos.outputs['Geometry'], curve_to_mesh.inputs['Profile Curve'])
    link(group_in.outputs['Fill Caps'], curve_to_mesh.inputs['Fill Caps'])
    link(curve_to_mesh.outputs['Mesh'], shade.inputs['Mesh'])
    link(shade.outputs['Mesh'], group_out.inputs['Geometry'])

    return ng


class GPTOOLS_OT_gn_path_mesh(bpy.types.Operator):
    """Add Geometry Nodes modifier to sweep a profile along a path from Grease Pencil layers"""

    bl_idname = "gptools.gn_path_mesh"
    bl_label = "Path Mesh (GN)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_grease_pencil(context) is not None

    @staticmethod
    def _show_layers_panel(context):
        """Switch Properties editor to Object Data tab to show GP layers."""
        try:
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    for space in area.spaces:
                        if space.type == 'PROPERTIES':
                            space.context = 'DATA'
                            return
        except TypeError:
            pass

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        if not gp_obj:
            self.report({"ERROR"}, "No active Grease Pencil found")
            return {"CANCELLED"}

        # Ensure Profile and Path layers exist
        ensure_gp_layers(gp_obj)

        # Check if either layer has drawings
        gp_data = gp_obj.data
        has_profile = False
        has_path = False
        for layer in gp_data.layers:
            if layer.name == PROFILE_LAYER_NAME:
                has_profile = any(len(f.drawing.strokes) > 0 for f in layer.frames)
            elif layer.name == PATH_LAYER_NAME:
                has_path = any(len(f.drawing.strokes) > 0 for f in layer.frames)

        if not has_profile and not has_path:
            self.report(
                {"WARNING"},
                "Draw a line first, then click Path Mesh again.",
            )
            return {"CANCELLED"}

        if not has_profile:
            # Show layers panel so user can see Profile/Path layers
            self._show_layers_panel(context)
            # Set Profile as active layer so user can draw on it
            gp_data.layers.active = gp_data.layers.get(PROFILE_LAYER_NAME)
            self.report({"WARNING"}, "Now draw the cross-section on the 'Profile' layer, then click Path Mesh again.")
            return {"CANCELLED"}

        if not has_path:
            self._show_layers_panel(context)
            gp_data.layers.active = gp_data.layers.get(PATH_LAYER_NAME)
            self.report({"WARNING"}, "No strokes on 'Path' layer. Draw your sweep line there.")
            return {"CANCELLED"}

        node_group = get_or_create_path_node_group()

        mod = gp_obj.modifiers.new(name="PathMesh", type='NODES')
        mod.node_group = node_group

        context.view_layer.objects.active = gp_obj
        gp_obj.select_set(True)

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

        self.report({"INFO"}, "Path mesh GN modifier added.")
        return {"FINISHED"}


classes = [
    GPTOOLS_OT_gn_path_mesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
