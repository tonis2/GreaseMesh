import bpy


class GPToolsProperties(bpy.types.PropertyGroup):
    # Screw Mesh settings
    screw_segments: bpy.props.IntProperty(
        name="Segments",
        description="Number of segments for screw mesh",
        default=32,
        min=3,
        max=256,
    )

    # Lattice Wrap settings
    lattice_resolution: bpy.props.IntProperty(
        name="Resolution",
        description="Lattice control point resolution per axis",
        default=10,
        min=2,
        max=32,
    )

    # Stamp Scatter settings
    stamp_collection: bpy.props.PointerProperty(
        name="Asset Collection",
        description="Collection of assets to scatter on GP marks",
        type=bpy.types.Collection,
    )
    stamp_scale: bpy.props.FloatProperty(
        name="Scale",
        description="Scale of scattered assets",
        default=1.0,
        min=0.01,
        max=10.0,
    )
    stamp_spacing: bpy.props.FloatProperty(
        name="Point Spacing",
        description="Distance between points along GP strokes",
        default=0.5,
        min=0.01,
        max=10.0,
    )
    stamp_seed: bpy.props.IntProperty(
        name="Random Seed",
        description="Seed for random asset selection",
        default=0,
        min=0,
        max=10000,
    )


classes = [
    GPToolsProperties,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gptools = bpy.props.PointerProperty(type=GPToolsProperties)


def unregister():
    del bpy.types.Scene.gptools
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
