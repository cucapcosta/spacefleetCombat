"""Combustion economy for over-burn movement.

Combustion is afterburner fuel — it is **only** spent when a ship
accelerates above its ``effective_speed_max``.  Normal speed changes
inside ``[0, effective_speed_max]`` and any deceleration are free.

``Ship.set_speed`` is the single public API; this module only exposes
the pure helpers it needs.
"""

from __future__ import annotations

import math


def combustion_cost(
    *,
    current_speed: float,
    target_speed: float,
    max_speed: float,
) -> int:
    """Combustion cost of moving from *current_speed* to *target_speed*.

    Only the portion **above** *max_speed* costs combustion.  The cost is
    ``ceil(target_over − current_over)`` where ``*_over`` is
    ``max(0, speed − max_speed)``.  Returns 0 for any change that stays
    within the normal range or that decreases the over-burn portion.
    """
    current_over = max(0.0, current_speed - max_speed)
    target_over = max(0.0, target_speed - max_speed)
    additional = target_over - current_over
    if additional <= 0:
        return 0
    return math.ceil(additional)
