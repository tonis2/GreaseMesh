import bpy
import mathutils


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


def stroke_length(stroke):
    """Sum of segment lengths between consecutive stroke points (local space)."""
    pts = [tuple(p.position) for p in stroke.points]
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        dz = pts[i + 1][2] - pts[i][2]
        total += (dx * dx + dy * dy + dz * dz) ** 0.5
    return total


def clean_gp_for_cutter(gp_obj, stub_fraction=0.10, bridge_fraction=0.25):
    """Duplicate gp_obj and prepare it for closed-loop cutter generation.

    Real drawings often have stubs (accidental short strokes) and open shapes
    (e.g. a doorway open at the bottom). This:
      1. Duplicates gp_obj so the user's drawing is preserved.
      2. Drops strokes shorter than stub_fraction * bbox_diag.
      3. If exactly two endpoints remain unbridged (no neighbor within
         bridge_fraction * bbox_diag), adds a synthetic stroke between them
         so the loop closes.

    Returns the duplicate object — caller is responsible for deleting it
    along with its data block.
    """
    new_data = gp_obj.data.copy()
    new_obj = gp_obj.copy()
    new_obj.data = new_data
    new_obj.name = f"_GPCleanup_{gp_obj.name}"
    for col in gp_obj.users_collection:
        col.objects.link(new_obj)

    all_pts = []
    for layer in new_data.layers:
        for frame in layer.frames:
            for s in frame.drawing.strokes:
                for p in s.points:
                    all_pts.append(tuple(p.position))
    if not all_pts:
        return new_obj

    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    zs = [p[2] for p in all_pts]
    diag = (
        (max(xs) - min(xs)) ** 2
        + (max(ys) - min(ys)) ** 2
        + (max(zs) - min(zs)) ** 2
    ) ** 0.5
    if diag < 1e-6:
        return new_obj

    stub_thresh = diag * stub_fraction
    bridge_thresh = diag * bridge_fraction

    for layer in new_data.layers:
        for frame in layer.frames:
            drawing = frame.drawing
            to_remove = [
                i
                for i, s in enumerate(drawing.strokes)
                if len(s.points) < 2 or stroke_length(s) < stub_thresh
            ]
            if to_remove:
                drawing.remove_strokes(indices=to_remove)

    bridge_thresh_sq = bridge_thresh * bridge_thresh
    for layer in new_data.layers:
        for frame in layer.frames:
            drawing = frame.drawing
            endpoints = []  # (stroke_idx, is_start, position)
            for si, s in enumerate(drawing.strokes):
                if len(s.points) >= 2 and not s.cyclic:
                    endpoints.append((si, True, tuple(s.points[0].position)))
                    endpoints.append((si, False, tuple(s.points[-1].position)))

            open_eps = []
            for i, ep in enumerate(endpoints):
                nearest = float("inf")
                for j, other in enumerate(endpoints):
                    if i == j or ep[0] == other[0]:
                        continue
                    d2 = sum((a - b) ** 2 for a, b in zip(ep[2], other[2]))
                    if d2 < nearest:
                        nearest = d2
                if nearest > bridge_thresh_sq:
                    open_eps.append(ep)

            if len(open_eps) == 2:
                a_pos = open_eps[0][2]
                b_pos = open_eps[1][2]
                drawing.add_strokes([2])
                new_stroke = drawing.strokes[-1]
                new_stroke.points[0].position = a_pos
                new_stroke.points[1].position = b_pos
                new_stroke.cyclic = False
                drawing.tag_positions_changed()

    return new_obj


def remove_cleanup_duplicate(cleaned_gp):
    """Remove a duplicate produced by clean_gp_for_cutter, including its data."""
    cleaned_data = cleaned_gp.data
    bpy.data.objects.remove(cleaned_gp, do_unlink=True)
    if cleaned_data.users == 0:
        bpy.data.grease_pencils.remove(cleaned_data)


def walk_strokes_into_loop(strokes_pts):
    """Greedy traversal: order separate stroke point-lists into a single loop
    by chaining nearest endpoints. Returns a flat ordered point list."""
    if not strokes_pts:
        return []
    remaining = list(range(1, len(strokes_pts)))
    ordered = list(strokes_pts[0])
    while remaining:
        last = mathutils.Vector(ordered[-1])
        best_i, best_d, best_rev = None, float("inf"), False
        for i in remaining:
            pts = strokes_pts[i]
            d_start = (mathutils.Vector(pts[0]) - last).length
            d_end = (mathutils.Vector(pts[-1]) - last).length
            if d_start < best_d:
                best_i, best_d, best_rev = i, d_start, False
            if d_end < best_d:
                best_i, best_d, best_rev = i, d_end, True
        if best_i is None:
            break
        next_pts = strokes_pts[best_i]
        if best_rev:
            next_pts = list(reversed(next_pts))
        if (mathutils.Vector(next_pts[0]) - last).length < 1e-3:
            next_pts = next_pts[1:]
        ordered.extend(next_pts)
        remaining.remove(best_i)
    if len(ordered) > 2 and (
        mathutils.Vector(ordered[-1]) - mathutils.Vector(ordered[0])
    ).length < 1e-3:
        ordered = ordered[:-1]
    return ordered
