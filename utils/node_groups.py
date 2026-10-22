"""Versioned Geometry Nodes group cache.

Node groups are built in Python and stored in the .blend by name. Returning a
cached group as-is means old files keep old graphs forever; always rebuilding
resets every modifier's values (socket identifiers change) and breaks links in
groups that nest it. Instead each builder declares a version and the group is
rebuilt in place only when the stored version differs.
"""

import bpy

VERSION_KEY = "gm_version"


def get_or_rebuild_group(name, version, build_fn):
    """Return node group ``name``, (re)building it with ``build_fn(ng)`` when it
    is missing or its stored version differs from ``version``.

    ``build_fn`` receives an empty GeometryNodeTree (no nodes, no interface)
    and must populate both interface and nodes.
    """
    ng = bpy.data.node_groups.get(name)
    if ng is not None and ng.get(VERSION_KEY) == version:
        return ng

    if ng is None:
        ng = bpy.data.node_groups.new(name=name, type='GeometryNodeTree')
    else:
        ng.nodes.clear()
        for item in list(ng.interface.items_tree):
            ng.interface.remove(item)

    build_fn(ng)
    ng[VERSION_KEY] = version
    return ng
