import bpy


def add_grease_pencil_solidify_modifier(obj):
    """Add the Grease Pencil Solidify modifier (single modifier, stays live)"""

    # Add only Solidify modifier - stays LIVE (not applied)
    # Merge by Distance is done manually in Edit Mode after creation
    solidify = obj.modifiers.new(name="Grease Pencil Solidify", type="SOLIDIFY")
    solidify.thickness = 0.1
    solidify.offset = 0.0
    solidify.use_rim = True
    solidify.use_rim_only = False

    return solidify


def register():
    pass


def unregister():
    pass
