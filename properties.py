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

    # Tube Mesh settings
    tube_resolution: bpy.props.IntProperty(
        name="Resolution",
        description="Number of vertices around the tube cross-section",
        default=12,
        min=3,
        max=64,
    )

    tube_radius: bpy.props.FloatProperty(
        name="Radius",
        description="Radius of the tube cross-section",
        default=0.1,
        min=0.001,
        max=10.0,
        step=0.01,
        precision=3,
        unit="LENGTH",
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
