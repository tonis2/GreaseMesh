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

_needs_reload = "bpy" in locals()

import bpy

from . import panels
from .operators import (
    add_gpencil,
    gn_solid_mesh,
    gn_mirror_mesh,
    gn_path_mesh,
    gn_wall_mesh,
    screw_mesh,
    lattice_wrap,
    bool_cut,
    array_on_curve,
    apply_modifiers,
    stamp_scatter,
    knife_cut,
)

if _needs_reload:
    import importlib
    panels = importlib.reload(panels)
    add_gpencil = importlib.reload(add_gpencil)
    gn_solid_mesh = importlib.reload(gn_solid_mesh)
    gn_mirror_mesh = importlib.reload(gn_mirror_mesh)
    gn_path_mesh = importlib.reload(gn_path_mesh)
    gn_wall_mesh = importlib.reload(gn_wall_mesh)
    screw_mesh = importlib.reload(screw_mesh)
    lattice_wrap = importlib.reload(lattice_wrap)
    bool_cut = importlib.reload(bool_cut)
    array_on_curve = importlib.reload(array_on_curve)
    apply_modifiers = importlib.reload(apply_modifiers)
    stamp_scatter = importlib.reload(stamp_scatter)
    knife_cut = importlib.reload(knife_cut)

registration_modules = [
    panels,
    add_gpencil,
    gn_solid_mesh,
    gn_mirror_mesh,
    gn_path_mesh,
    gn_wall_mesh,
    screw_mesh,
    lattice_wrap,
    bool_cut,
    array_on_curve,
    apply_modifiers,
    stamp_scatter,
    knife_cut,
]


def register():
    for module in registration_modules:
        module.register()


def unregister():
    for module in reversed(registration_modules):
        module.unregister()
