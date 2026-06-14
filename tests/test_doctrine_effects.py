"""Doctrine effects — build-time stat mods, handlers, validation."""

from __future__ import annotations

from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.ship import Ship


def test_morale_floor_clamps_losses() -> None:
    s = Ship.from_profile("s", "S", HULK_HULL, make_hulk_weapons(), morale_floor=20)
    s.apply_morale_change(-1000)
    assert s.morale == 20


def test_default_floor_is_zero() -> None:
    s = Ship.from_profile("s", "S", HULK_HULL, make_hulk_weapons())
    assert s.morale_floor == 0
    assert s.doctrine_id is None
    s.apply_morale_change(-1000)
    assert s.morale == 0
