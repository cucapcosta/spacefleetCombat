"""Battery gunnery table + helper lookups.

This module owns the gunnery table and target-aspect calculation.
The full ``resolve_battery_attack`` resolver still lives in
``combat.resolution`` for now; this is the canonical home for the
table itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.spatial.geometry import bearing_from_to, relative_bearing

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


GUNNERY_COLUMNS = ["far_closing", "closing", "abeam", "running", "far_running"]


GUNNERY_TABLE: dict[int, list[int]] = {
    1: [0, 0, 1, 1, 1],
    2: [0, 1, 1, 1, 2],
    3: [0, 1, 1, 2, 2],
    4: [1, 1, 2, 2, 3],
    5: [1, 1, 2, 3, 3],
    6: [1, 2, 2, 3, 4],
    7: [1, 2, 3, 3, 4],
    8: [1, 2, 3, 4, 5],
    9: [2, 2, 3, 4, 5],
    10: [2, 3, 4, 4, 6],
    11: [2, 3, 4, 5, 6],
    12: [2, 3, 4, 5, 7],
    13: [3, 3, 5, 6, 7],
    14: [3, 4, 5, 6, 8],
    15: [3, 4, 5, 7, 8],
    16: [3, 4, 6, 7, 9],
}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def column_index(*, aspect_shift: int, stance_shift: int) -> int:
    """Final column index in [0, 4] given the aspect + stance shifts."""
    return _clamp(2 + aspect_shift + stance_shift, 0, 4)


def lookup_hits(*, strength: int, column: int) -> int:
    """Look up hit count, clamping strength to the table range."""
    s = _clamp(strength, 1, max(GUNNERY_TABLE.keys()))
    c = _clamp(column, 0, 4)
    return GUNNERY_TABLE[s][c]


def target_aspect(attacker: Ship, target: Ship) -> tuple[str, int]:
    """Return ``(aspect_name, shift)`` for the face the target presents.

    Shift values:
        ``-1`` closing (target shows prow), ``0`` abeam, ``+1`` running.
    """
    abs_bearing = bearing_from_to(target.position, attacker.position)
    rel = relative_bearing(target.heading, abs_bearing)
    abs_rel = abs(rel)
    if abs_rel <= 45:
        return "closing", -1
    if abs_rel <= 135:
        return "abeam", 0
    return "running", 1
