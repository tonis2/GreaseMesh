import bpy


def add_grease_pencil_solidify_modifier(
    obj, thickness=0.1, bevel_width=0.02, bevel_segments=2
):
    """Add the Grease Pencil Solidify modifier with Bevel for roundness (stays live)"""

    # Add Solidify modifier - stays LIVE (not applied)
    solidify = obj.modifiers.new(name="Grease Pencil Solidify", type="SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_rim = True
    solidify.use_rim_only = False

    # Add Bevel modifier for roundness - placed AFTER Solidify
    bevel = obj.modifiers.new(name="Roundness", type="BEVEL")
    bevel.width = bevel_width
    bevel.segments = bevel_segments
    bevel.limit_method = "ANGLE"
    bevel.angle_limit = 0.5236  # 30 degrees
    bevel.use_clamp_overlap = True

    return solidify, bevel


def register():
    pass


def unregister():
    pass
