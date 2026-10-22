import bpy
from ..utils.conversion import get_active_grease_pencil

EDIT_PROP = "gm_edit_layer"      # layer being edited through Edit Drawing
OVERLAY_PROP = "gm_stroke_overlay"  # marks the in-front copy that shows the strokes


def is_greasemesh_gp(gp_obj):
    """True if the GP has a GreaseMesh Geometry Nodes modifier (its strokes are
    hidden behind the generated mesh)."""
    if gp_obj is None:
        return False
    return any(
        m.type == 'NODES' and m.node_group is not None
        and m.node_group.name.startswith("GreaseMesh_")
        for m in gp_obj.modifiers
    )


def get_edit_layer(gp_obj):
    return gp_obj.get(EDIT_PROP) if gp_obj is not None else None


def _overlays(gp_obj):
    return [c for c in gp_obj.children if c.get(OVERLAY_PROP)]


def _add_overlay(gp_obj):
    """The modifier output replaces the strokes, so drawing would be blind.
    A modifier-free object sharing the GP data shows the strokes in front of
    the mesh while it keeps updating live."""
    if _overlays(gp_obj):
        return
    overlay = bpy.data.objects.new(f"{gp_obj.name}_Strokes", gp_obj.data)
    overlay[OVERLAY_PROP] = True
    for coll in gp_obj.users_collection:
        coll.objects.link(overlay)
    overlay.parent = gp_obj
    overlay.show_in_front = True
    overlay.hide_select = True
    overlay.hide_render = True


def end_edit(gp_obj):
    """Remove the stroke overlay and the edit marker (no-op when not editing)."""
    for overlay in _overlays(gp_obj):
        bpy.data.objects.remove(overlay, do_unlink=True)
    if EDIT_PROP in gp_obj:
        del gp_obj[EDIT_PROP]


class GPTOOLS_OT_edit_drawing(bpy.types.Operator):
    """Draw on this layer again. The strokes are shown in front of the mesh,
    which keeps updating as you draw"""

    bl_idname = "gptools.edit_drawing"
    bl_label = "Edit Drawing"
    bl_options = {"REGISTER", "UNDO"}

    layer: bpy.props.StringProperty(name="Layer")

    @classmethod
    def poll(cls, context):
        return is_greasemesh_gp(get_active_grease_pencil(context))

    def execute(self, context):
        gp_obj = get_active_grease_pencil(context)
        layer = gp_obj.data.layers.get(self.layer)
        if layer is None:
            self.report({"ERROR"}, f"Layer '{self.layer}' not found")
            return {"CANCELLED"}

        layer.hide = False
        layer.lock = False
        if len(layer.frames) == 0:
            layer.frames.new(context.scene.frame_current)
        gp_obj.data.layers.active = layer
        gp_obj[EDIT_PROP] = layer.name
        _add_overlay(gp_obj)

        context.view_layer.objects.active = gp_obj
        gp_obj.select_set(True)
        if context.mode != 'PAINT_GREASE_PENCIL':
            bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')
        return {"FINISHED"}


class GPTOOLS_OT_edit_drawing_done(bpy.types.Operator):
    """Stop editing the drawing and go back to Object mode"""

    bl_idname = "gptools.edit_drawing_done"
    bl_label = "Done"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_edit_layer(get_active_grease_pencil(context)) is not None

    def execute(self, context):
        end_edit(get_active_grease_pencil(context))
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        return {"FINISHED"}


classes = [GPTOOLS_OT_edit_drawing, GPTOOLS_OT_edit_drawing_done]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
