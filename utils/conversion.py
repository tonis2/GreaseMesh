import bpy


def get_active_grease_pencil(context):
    """Get the active Grease Pencil object, or None if not found"""
    obj = context.active_object
    if obj and obj.type == "GREASEPENCIL":
        return obj
    return None


def gpencil_to_points(gp_obj):
    """Extract all points from a Grease Pencil object"""
    points = []
    gp_data = gp_obj.data

    for layer in gp_data.layers:
        for frame in layer.frames:
            for stroke in frame.drawing.strokes:
                stroke_points = []
                for pt in stroke.points:
                    stroke_points.append(pt.position.copy())
                points.append(stroke_points)

    return points


def get_stroke_count(gp_obj):
    """Count total number of strokes in Grease Pencil"""
    count = 0
    gp_data = gp_obj.data

    for layer in gp_data.layers:
        for frame in layer.frames:
            count += len(frame.drawing.strokes)

    return count
