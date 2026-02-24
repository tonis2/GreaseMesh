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
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
