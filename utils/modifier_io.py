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


def get_input(mod, identifier):
    """Read a Geometry Nodes modifier input by socket identifier (None if unset)."""
    inputs = _inputs(mod)
    if inputs is not None:
        sock = getattr(inputs, identifier, None)               # Blender 5.x
        return None if sock is None else sock.value
    return mod.get(identifier)                                 # Blender <= 4.x


def ensure_nodes_modifier(obj, name, node_group):
    """Return obj's Geometry Nodes modifier called ``name`` (creating it if
    missing) with ``node_group`` assigned. Re-running an operator then updates
    the existing modifier instead of stacking a new one."""
    mod = obj.modifiers.get(name)
    if mod is None or mod.type != 'NODES':
        mod = obj.modifiers.new(name=name, type='NODES')
    if mod.node_group != node_group:
        mod.node_group = node_group
    return mod


def show_properties_tab(context, tab='MODIFIER'):
    """Switch the first Properties editor to ``tab`` (no-op without one)."""
    try:
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        space.context = tab
                        break
                break
    except TypeError:
        pass


def show_modifier_tab(context):
    """Switch the Properties editor to the Modifiers tab."""
    show_properties_tab(context, 'MODIFIER')
