"""Centralised morale change triggers.

Combat resolvers and boarding code call into this module so the
constants live in one place and can be tweaked for balance.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


MORALE_PER_HULL_DAMAGE = -3
MORALE_PER_CRIT = -5
MORALE_PER_BOARDING_CREW_HIT = -10


def apply_hull_damage_morale(ship: Ship, *, hull_damage: int) -> int:
    """Drop morale proportional to hull damage taken.  Returns delta."""
    if hull_damage <= 0:
        return 0
    return ship.apply_morale_change(MORALE_PER_HULL_DAMAGE * hull_damage)


def apply_critical_hit_morale(ship: Ship) -> int:
    """Flat morale loss for any critical hit landed."""
    return ship.apply_morale_change(MORALE_PER_CRIT)


def apply_boarding_crew_morale(ship: Ship, *, crew_damage_count: int) -> int:
    """Morale loss for each successful boarding crew-damage roll."""
    if crew_damage_count <= 0:
        return 0
    return ship.apply_morale_change(
        MORALE_PER_BOARDING_CREW_HIT * crew_damage_count,
    )
