import bpy


def add_solid_mesh_modifiers(obj, thickness=0.1, roundness=0.3):
    """Add Decimate, Solidify, Bevel, and Subdivision modifiers to a mesh object"""

    # Solidify modifier
    solidify = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_rim = True
    solidify.use_rim_only = False

    # Bevel modifier
    bevel = obj.modifiers.new(name="Bevel", type="BEVEL")
    bevel.width = roundness * 0.5
    bevel.segments = max(1, int(roundness * 12))
    bevel.limit_method = "ANGLE"
    bevel.angle_limit = 0.5236  # ~30 degrees
    bevel.use_clamp_overlap = True

    # Subdivision Surface modifier
    subdiv = obj.modifiers.new(name="Subdivision", type="SUBSURF")
    subdiv.levels = max(1, int(roundness * 3))
    subdiv.render_levels = subdiv.levels
    subdiv.subdivision_type = "CATMULL_CLARK"
    subdiv.show_only_control_edges = True


def register():
    pass


def unregister():
    pass
