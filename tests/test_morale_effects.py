"""Tests for combat.morale_effects."""
from __future__ import annotations

from spacefleet.combat.morale_effects import (
    MORALE_PER_BOARDING_CREW_HIT,
    MORALE_PER_CRIT,
    MORALE_PER_HULL_DAMAGE,
    apply_boarding_crew_morale,
    apply_critical_hit_morale,
    apply_hull_damage_morale,
)
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="t",
        name="T",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_hull_damage_morale():
    ship = _ship()
    apply_hull_damage_morale(ship, hull_damage=2)
    assert ship.morale == 100 + MORALE_PER_HULL_DAMAGE * 2


def test_critical_hit_morale():
    ship = _ship()
    apply_critical_hit_morale(ship)
    assert ship.morale == 100 + MORALE_PER_CRIT


def test_boarding_crew_morale():
    ship = _ship()
    apply_boarding_crew_morale(ship, crew_damage_count=3)
    assert ship.morale == 100 + MORALE_PER_BOARDING_CREW_HIT * 3
