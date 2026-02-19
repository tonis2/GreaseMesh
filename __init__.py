bl_info = {
    "name": "Grease Mesh",
    "author": "Tonis",
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
    "grease_mesh.operators.lattice_wrap",
    "grease_mesh.operators.apply_modifiers",
    "grease_mesh.operators.dev_reload",
]


def reload_modules():
    """Reload all addon modules for development"""
    # Unregister everything first
    for module in reversed(registration_modules):
        try:
            module.unregister()
        except Exception:
            pass

    # Reload all modules (try both possible package names)
    for module_name in modules:
        for prefix in [module_name, module_name.replace("grease_mesh.", "GreaseMesh.")]:
            if prefix in sys.modules:
                importlib.reload(sys.modules[prefix])

    # Also reload the package __init__ submodule references
    for mod in registration_modules:
        try:
            importlib.reload(mod)
        except Exception:
            pass

    # Re-register everything
    for module in registration_modules:
        try:
            module.register()
        except Exception:
            pass


# Import modules
from . import properties, panels, modifiers
from .operators import (
    add_gpencil,
    convert_curve,
    convert_mesh,
    convert_line,
    solid_mesh,
    screw_mesh,
    lattice_wrap,
    apply_modifiers,
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
    lattice_wrap,
    apply_modifiers,
    dev_reload,
]


def register():
    for module in registration_modules:
        module.register()


def unregister():
    for module in reversed(registration_modules):
        module.unregister()


# Support for F3 "Reload Scripts"
if __name__ == "__main__":
    reload_modules()
    register()
