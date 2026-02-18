import bpy


def create_gp_controller_node_group():
    """Create Geometry Nodes controller that just passes geometry through
    but exposes Thickness and Roundness inputs for driving real modifiers"""

    group_name = "GP_Mesh_Controller"
    if group_name in bpy.data.node_groups:
        return bpy.data.node_groups[group_name]

    # Create new node group
    node_group = bpy.data.node_groups.new(name=group_name, type="GeometryNodeTree")

    # Create group inputs
    node_group.interface.new_socket(
        name="Geometry", socket_type="NodeSocketGeometry", in_out="INPUT"
    )
    node_group.interface.new_socket(
        name="Thickness", socket_type="NodeSocketFloat", in_out="INPUT"
    )
    node_group.interface.new_socket(
        name="Roundness", socket_type="NodeSocketFloat", in_out="INPUT"
    )

    # Set default values and limits
    thickness_socket = node_group.interface.items_tree["Thickness"]
    thickness_socket.default_value = 0.1
    thickness_socket.min_value = 0.0
    thickness_socket.max_value = 2.0

    roundness_socket = node_group.interface.items_tree["Roundness"]
    roundness_socket.default_value = 0.3
    roundness_socket.min_value = 0.0
    roundness_socket.max_value = 1.0

    # Create group outputs
    node_group.interface.new_socket(
        name="Geometry", socket_type="NodeSocketGeometry", in_out="OUTPUT"
    )

    # Clear default nodes
    for node in node_group.nodes:
        node_group.nodes.remove(node)

    # Create simple passthrough nodes
    input_node = node_group.nodes.new("NodeGroupInput")
    input_node.location = (-200, 0)

    output_node = node_group.nodes.new("NodeGroupOutput")
    output_node.location = (200, 0)

    # Just pass geometry through
    links = node_group.links
    links.new(input_node.outputs["Geometry"], output_node.inputs["Geometry"])

    return node_group


def setup_modifier_driver(obj, modifier, data_path, gn_socket_name, node_group):
    """Set up a driver to link Geometry Nodes input to modifier value"""

    # Find the socket index for the GN input
    # Socket_0 = Geometry, Socket_1 = Thickness, Socket_2 = Roundness
    socket_index_map = {"Thickness": 1, "Roundness": 2}

    socket_index = socket_index_map.get(gn_socket_name)
    if socket_index is None:
        return False

    # Create driver
    try:
        driver = modifier.driver_add(data_path).driver
        driver.type = "SUM"

        # Add variable
        var = driver.variables.new()
        var.name = gn_socket_name.lower()
        var.type = "SINGLE_PROP"

        # Set up the variable to read from the Geometry Nodes modifier
        var.targets[0].id = obj
        var.targets[0].data_path = f'modifiers["GP Mesh"]["Socket_{socket_index}"]'

        # Set driver expression
        driver.expression = var.name

        return True
    except Exception as e:
        print(f"Warning: Could not create driver for {modifier.name}.{data_path}: {e}")
        return False


def add_gp_mesh_controller(obj, thickness=0.1, roundness=0.3):
    """Add working modifiers + GN controller with drivers"""

    # Step 1: Create the node group controller
    node_group = create_gp_controller_node_group()

    # Step 2: Add working modifiers (these do the actual work)
    # Solidify modifier
    solidify = obj.modifiers.new(name="_GPT_Solidify", type="SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_rim = True
    solidify.use_rim_only = False
    solidify.show_expanded = False

    # Bevel modifier
    bevel_width = roundness * 0.5
    bevel_segments = max(1, int(roundness * 12))

    bevel = obj.modifiers.new(name="_GPT_Bevel", type="BEVEL")
    bevel.width = bevel_width
    bevel.segments = bevel_segments
    bevel.limit_method = "ANGLE"
    bevel.angle_limit = 0.5236
    bevel.use_clamp_overlap = True
    bevel.show_expanded = False

    # Step 3: Add Geometry Nodes modifier (this is what user sees)
    # Place it at the TOP of the stack so it's visible first
    gn_mod = obj.modifiers.new(name="GP Mesh", type="NODES")
    gn_mod.node_group = node_group

    # Move GN modifier to top of stack
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_move_to_index(modifier="GP Mesh", index=0)

    # Step 4: Set initial values on GN modifier
    gn_mod["Socket_1"] = thickness
    gn_mod["Socket_2"] = roundness

    # Step 5: Set up drivers to link GN inputs to real modifiers
    # Thickness drives Solidify
    setup_modifier_driver(obj, solidify, "thickness", "Thickness", node_group)

    # Roundness drives Bevel width and segments
    # For width: roundness * 0.5
    setup_modifier_driver(obj, bevel, "width", "Roundness", node_group)

    # For segments, we need a more complex driver that does int(roundness * 12)
    # We'll handle this by updating in the depsgraph handler

    return gn_mod


def update_bevel_segments_from_driver(obj):
    """Update bevel segments based on GN roundness value"""
    gn_mod = obj.modifiers.get("GP Mesh")
    bevel = obj.modifiers.get("_GPT_Bevel")

    if gn_mod and bevel:
        roundness = gn_mod.get("Socket_2", 0.3)
        new_segments = max(1, int(roundness * 12))
        if bevel.segments != new_segments:
            bevel.segments = new_segments


def register():
    pass


def unregister():
    pass
