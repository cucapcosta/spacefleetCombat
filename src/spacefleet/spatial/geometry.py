"""Vector math, angle operations, and weapon-arc checking."""

from __future__ import annotations

import math

from spacefleet.core.types import Arc, Vector2D, normalize_angle


def distance(a: Vector2D, b: Vector2D) -> float:
    """Euclidean distance between two points."""
    return a.distance_to(b)


def bearing_from_to(origin: Vector2D, target: Vector2D) -> float:
    """Absolute bearing from *origin* to *target* (0° = north, clockwise)."""
    dx = target.x - origin.x
    dy = target.y - origin.y
    angle = math.degrees(math.atan2(dx, dy))
    return normalize_angle(angle)


def relative_bearing(ship_heading: float, absolute_bearing: float) -> float:
    """Signed relative bearing from ship heading to a target bearing.

    Returns a value in (-180, 180].
    Positive = starboard (right), negative = port (left).
    """
    diff = normalize_angle(absolute_bearing - ship_heading)
    if diff > 180:
        diff -= 360
    return diff


def is_in_arc(ship_heading: float, bearing_to_target: float, arc: Arc) -> bool:
    """Return *True* if *bearing_to_target* (absolute) falls inside *arc*."""
    rel = relative_bearing(ship_heading, bearing_to_target)

    if arc == Arc.PROW:
        return -45 <= rel <= 45
    if arc == Arc.PORT:
        return -135 <= rel < -45
    if arc == Arc.STARBOARD:
        return 45 < rel <= 135
    if arc == Arc.AFT:
        return abs(rel) > 135
    if arc == Arc.DORSAL:
        return -135 <= rel <= 135
    return False


def angle_diff(a: float, b: float) -> float:
    """Smallest signed difference *b - a*, in (-180, 180]."""
    diff = normalize_angle(b - a)
    if diff > 180:
        diff -= 360
    return diff


def arc_name(arc: Arc) -> str:
    """Human-readable name for an arc."""
    return {
        Arc.PROW: "Prow (front)",
        Arc.PORT: "Port (left)",
        Arc.STARBOARD: "Starboard (right)",
        Arc.AFT: "Aft (rear)",
        Arc.DORSAL: "Dorsal (top)",
    }.get(arc, arc.value)


def arc_range_str(arc: Arc) -> str:
    """Describe the angular range of an arc relative to heading."""
    return {
        Arc.PROW: "345°–015° from heading",
        Arc.PORT: "225°–315° from heading",
        Arc.STARBOARD: "045°–135° from heading",
        Arc.AFT: "135°–225° from heading",
        Arc.DORSAL: "225°–135° (everything except aft)",
    }.get(arc, "?")


# ─────────────────────────────────────────────────────────────────
# Line-segment collision (for projectiles)
# ─────────────────────────────────────────────────────────────────


def point_to_segment_distance(
    point: Vector2D,
    seg_start: Vector2D,
    seg_end: Vector2D,
) -> tuple[float, Vector2D]:
    """Minimum distance from *point* to line segment ``[seg_start, seg_end]``.

    Returns ``(distance, closest_point_on_segment)``.

    Uses projection-clamped-to-segment: project *point* onto the
    infinite line, clamp the parameter *t* to [0, 1], then compute
    the closest point.
    """
    dx = seg_end.x - seg_start.x
    dy = seg_end.y - seg_start.y
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq < 1e-12:
        # Degenerate segment (start == end)
        return (distance(point, seg_start), seg_start)

    # Parameter t ∈ [0, 1] along the segment
    t = ((point.x - seg_start.x) * dx + (point.y - seg_start.y) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))

    closest = Vector2D(seg_start.x + t * dx, seg_start.y + t * dy)
    dist = distance(point, closest)
    return (dist, closest)
