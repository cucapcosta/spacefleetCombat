"""Tests for Fleet container."""
from __future__ import annotations

from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def _ship(name: str) -> Ship:
    return Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_add_and_iterate():
    f = Fleet(commander_name="Lord Solar")
    f.add(_ship("a"))
    f.add(_ship("b"))
    assert len(f) == 2
    assert [s.name for s in f] == ["a", "b"]


def test_alive_filters_destroyed():
    f = Fleet()
    a = _ship("a")
    b = _ship("b")
    b.is_destroyed = True
    f.add(a)
    f.add(b)
    assert f.alive() == [a]


def test_total_hull_points():
    f = Fleet()
    s = _ship("a")
    s.hull_current = 5
    f.add(s)
    assert f.total_hull_points() == 5


def test_faction_homogeneous():
    f = Fleet()
    f.add(_ship("a"))
    assert f.faction == Faction.IMPERIAL_NAVY
