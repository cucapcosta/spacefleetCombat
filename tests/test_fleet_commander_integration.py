"""Fleet holds commander + flagship + ship ids, resolves against state."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def _make_ship(sid: str) -> Ship:
    return Ship.from_profile(
        sid,
        sid,
        HULK_HULL,
        make_hulk_weapons(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_fleet_holds_commander_and_flagship() -> None:
    cmdr = Commander(id="c1", name="Admiral", faction=Faction.IMPERIAL_NAVY)
    fleet = Fleet(
        id="player1",
        commander=cmdr,
        flagship_ship_id="ship_a",
        ship_ids=["ship_a", "ship_b"],
    )
    assert fleet.id == "player1"
    assert fleet.commander is cmdr
    assert fleet.flagship_ship_id == "ship_a"


def test_ships_in_resolves_against_state() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    b = _make_ship("ship_b")
    state.add_ship(a)
    state.add_ship(b)
    fleet = Fleet(id="f", ship_ids=["ship_a", "ship_b", "missing"])
    resolved = fleet.ships_in(state)
    assert len(resolved) == 2
    assert a in resolved
    assert b in resolved


def test_alive_ships_in_filters_destroyed() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    b = _make_ship("ship_b")
    b.is_destroyed = True
    state.add_ship(a)
    state.add_ship(b)
    fleet = Fleet(id="f", ship_ids=["ship_a", "ship_b"])
    assert fleet.alive_ships_in(state) == [a]


def test_flagship_in_returns_none_when_down() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    a.is_destroyed = True
    state.add_ship(a)
    fleet = Fleet(id="f", flagship_ship_id="ship_a", ship_ids=["ship_a"])
    assert fleet.flagship_in(state) is None


def test_flagship_in_returns_ship_when_alive() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    state.add_ship(a)
    fleet = Fleet(id="f", flagship_ship_id="ship_a", ship_ids=["ship_a"])
    assert fleet.flagship_in(state) is a


def test_fleet_backward_compat_with_ships_list() -> None:
    a = _make_ship("ship_a")
    fleet = Fleet(commander_name="Old Admiral", ships=[a])
    # Legacy path still works
    assert fleet.commander_name == "Old Admiral"
    assert fleet.ships == [a]
    assert fleet.total_hull_points() == a.hull_current
