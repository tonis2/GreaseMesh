import bpy


def add_grease_pencil_solidify_modifier(obj):
    """Add the Grease Pencil Solidify modifier stack to an object"""
    
    # Add Solidify modifier (main thickness)
    solidify = obj.modifiers.new(name="Grease Pencil Solidify", type='SOLIDIFY')
    solidify.thickness = 0.1
    solidify.offset = 0.0
    solidify.use_rim = True
    solidify.use_rim_only = False
    
    # Add Weld modifier (Merge by Distance functionality)
    weld = obj.modifiers.new(name="GP Merge", type='WELD')
    weld.merge_threshold = 0.0001
    
    return solidify


def register():
    pass


def unregister():
    pass
