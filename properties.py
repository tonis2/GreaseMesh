import bpy


class GPToolsProperties(bpy.types.PropertyGroup):
    # Solid Mesh settings
    solid_thickness: bpy.props.FloatProperty(
        name="Thickness",
        description="Thickness for solid mesh extrusion",
        default=1.0,
        min=0.001,
        max=10.0,
        step=0.1,
        precision=3,
        unit="LENGTH",
    )

    solid_round: bpy.props.BoolProperty(
        name="Round",
        description="Add Bevel and Subdivision modifiers for rounded edges",
        default=False,
    )

    solid_roundness: bpy.props.FloatProperty(
        name="Roundness",
        description="Roundness of edges for solid mesh",
        default=0.3,
        min=0.0,
        max=1.0,
        step=0.01,
        precision=3,
    )
    
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
