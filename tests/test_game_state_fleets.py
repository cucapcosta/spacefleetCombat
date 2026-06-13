"""CoreGameState holds fleets and looks up the fleet of a ship."""

from __future__ import annotations

from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def _ship(sid: str) -> Ship:
    return Ship.from_profile(
        sid,
        sid,
        HULK_HULL,
        make_hulk_weapons(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_fleets_default_empty() -> None:
    state = CoreGameState()
    assert state.fleets == {}


def test_fleet_of_ship() -> None:
    state = CoreGameState()
    a = _ship("a")
    b = _ship("b")
    state.add_ship(a)
    state.add_ship(b)
    fleet = Fleet(id="f1", ship_ids=["a", "b"])
    state.fleets["f1"] = fleet
    assert state.fleet_of(a) is fleet
    assert state.fleet_of(b) is fleet


def test_fleet_of_unlisted_ship_is_none() -> None:
    state = CoreGameState()
    a = _ship("a")
    state.add_ship(a)
    assert state.fleet_of(a) is None
