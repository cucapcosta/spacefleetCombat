"""Ship.subsystems is the source of truth; legacy attrs forward to it."""

from __future__ import annotations

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.models.subsystems import Subsystems


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_ship_has_subsystems_field() -> None:
    ship = _ship()
    assert isinstance(ship.subsystems, Subsystems)
    assert ship.subsystems.all_operational()


def test_legacy_attrs_read_from_subsystems() -> None:
    ship = _ship()
    ship.subsystems.engines = False
    assert ship.subsystem_engines is False
    assert ship.subsystem_generator is True


def test_legacy_attrs_write_through_to_subsystems() -> None:
    ship = _ship()
    ship.subsystem_weapons = False
    assert ship.subsystems.weapons is False
    assert not ship.subsystems.all_operational()


def test_independent_ship_instances_do_not_share_subsystems() -> None:
    a = _ship()
    b = _ship()
    a.subsystem_deck = False
    assert b.subsystem_deck is True
