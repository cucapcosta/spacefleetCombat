"""Tests for core.game_state."""

from __future__ import annotations

from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship(name: str, faction: Faction) -> Ship:
    s = Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )
    s.faction = faction
    return s


def test_add_ship_and_lookup():
    state = CoreGameState()
    a = _ship("a", Faction.IMPERIAL_NAVY)
    state.add_ship(a)
    assert state.get_ship("a") is a
    assert state.alive_ships() == [a]


def test_enemy_lookup():
    state = CoreGameState()
    a = _ship("a", Faction.IMPERIAL_NAVY)
    b = _ship("b", Faction.CHAOS_FLEET)
    state.add_ship(a)
    state.add_ship(b)
    assert state.enemies_of(a) == [b]
    assert state.friendlies_of(a) == []


def test_advance_turn_increments():
    state = CoreGameState()
    assert state.turn == 0
    state.advance_turn()
    assert state.turn == 1


def test_game_over_when_one_faction_left():
    state = CoreGameState()
    a = _ship("a", Faction.IMPERIAL_NAVY)
    b = _ship("b", Faction.CHAOS_FLEET)
    state.add_ship(a)
    state.add_ship(b)
    assert not state.is_game_over()
    b.is_destroyed = True
    assert state.is_game_over()
