"""Compatibility helpers for setting Geometry Nodes modifier inputs.

Blender 5.x removed the id-property subscript API (``mod[identifier] = value``)
in favour of a structured interface at ``mod.properties.inputs``. These helpers
prefer the new API and transparently fall back to the legacy subscript so the
addon keeps working on Blender 4.x.
"""


def _inputs(mod):
    """Return the Blender 5.x modifier input interface, or None on older Blender."""
    return getattr(getattr(mod, "properties", None), "inputs", None)


def set_input(mod, identifier, value):
    """Set a value/object Geometry Nodes modifier input by socket identifier."""
    inputs = _inputs(mod)
    if inputs is not None:
        getattr(inputs, identifier).value = value          # Blender 5.x
    else:
        mod[identifier] = value                              # Blender <= 4.x


def set_menu(mod, identifier, enum_value, legacy_value=None, legacy_menu=None):
    """Set a menu/enum modifier input.

    Blender 5.x expects the enum identifier string (``enum_value``). Older
    Blender stored an integer index (``legacy_value``) and, for some sockets, a
    companion ``<id>_menu`` display string (``legacy_menu``).
    """
    inputs = _inputs(mod)
    if inputs is not None:
        getattr(inputs, identifier).value = enum_value      # Blender 5.x
    else:
        if legacy_value is not None:
            mod[identifier] = legacy_value
        if legacy_menu is not None:
            mod[identifier + "_menu"] = legacy_menu
