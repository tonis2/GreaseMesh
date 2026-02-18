bl_info = {
    "name": "Grease Mesh",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > N-Panel > GPTools",
    "description": "Easy toolbox for creating meshes from Grease Pencil",
    "category": "Mesh",
    "support": "COMMUNITY",
}

import bpy
import importlib
import sys

# List of modules to reload during development
modules = [
    "grease_mesh.properties",
    "grease_mesh.panels",
    "grease_mesh.modifiers",
    "grease_mesh.utils.conversion",
    "grease_mesh.operators.add_gpencil",
    "grease_mesh.operators.convert_curve",
    "grease_mesh.operators.convert_mesh",
    "grease_mesh.operators.convert_line",
    "grease_mesh.operators.solid_mesh",
    "grease_mesh.operators.screw_mesh",
    "grease_mesh.operators.dev_reload",
]


def reload_modules():
    """Reload all addon modules for development"""
    for module_name in modules:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])


# Import modules
from . import properties, panels, modifiers
from .operators import (
    add_gpencil,
    convert_curve,
    convert_mesh,
    convert_line,
    solid_mesh,
    screw_mesh,
    dev_reload,
)

registration_modules = [
    properties,
    panels,
    modifiers,
    add_gpencil,
    convert_curve,
    convert_mesh,
    convert_line,
    solid_mesh,
    screw_mesh,
    dev_reload,
]


@bpy.app.handlers.persistent
def gp_mesh_driver_update_handler(scene, depsgraph):
    """Update bevel segments from Geometry Nodes roundness value"""
    from .modifiers import update_bevel_segments_from_driver

    for obj in scene.objects:
        if obj.modifiers.get("GP Mesh") and obj.modifiers.get("_GPT_Bevel"):
            update_bevel_segments_from_driver(obj)


def register():
    for module in registration_modules:
        module.register()

    # Register driver update handler
    bpy.app.handlers.depsgraph_update_post.append(gp_mesh_driver_update_handler)


def unregister():
    # Unregister driver update handler
    if gp_mesh_driver_update_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(gp_mesh_driver_update_handler)

    for module in reversed(registration_modules):
        module.unregister()


# Support for F3 "Reload Scripts"
if __name__ == "__main__":
    reload_modules()
    register()
