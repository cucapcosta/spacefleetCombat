"""Movement helpers: combustion spending + speed transitions.

The geometry primitives (``apply_drift``, ``apply_turn``) stay on
``Ship``.  This module owns the *combustion economy* — accelerating
costs combustion points; decelerating is free.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


class CombustionError(RuntimeError):
    """Raised when a ship cannot pay the combustion cost of a manoeuvre."""


def combustion_cost(current_speed: float, target_speed: float) -> int:
    """Combustion points required to change *current_speed* to *target_speed*.

    Acceleration: ``ceil(target − current)``.  Deceleration: free.
    """
    delta = target_speed - current_speed
    if delta <= 0:
        return 0
    return int(delta + 0.999999)  # ceil for non-integer speeds


def accelerate(ship: Ship, *, target_speed: float) -> None:
    """Spend combustion to raise *ship*'s speed.

    Clamps to ``effective_speed_max``.  Raises :class:`CombustionError`
    if the ship lacks the combustion to reach the (clamped) target.
    """
    target = min(target_speed, ship.effective_speed_max)
    cost = combustion_cost(ship.speed, target)
    if cost > ship.combustion:
        raise CombustionError(
            f"{ship.name}: needs {cost} combustion, has {ship.combustion}",
        )
    ship.combustion -= cost
    ship.speed = target


def decelerate(ship: Ship, *, target_speed: float) -> None:
    """Reduce *ship*'s speed for free.  Clamps to ``[0, current]``."""
    target = max(0.0, min(target_speed, ship.speed))
    ship.speed = target
