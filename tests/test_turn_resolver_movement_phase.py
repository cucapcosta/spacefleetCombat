"""turn_resolver delegates the movement section to resolve_movement_phase."""

from __future__ import annotations

import inspect

from spacefleet.net import turn_resolver
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState


def test_turn_resolver_imports_resolve_movement_phase() -> None:
    src = inspect.getsource(turn_resolver)
    assert "from spacefleet.phases.movement_phase import" in src
    assert "resolve_movement_phase" in src


def test_ahead_within_max_does_not_spend_combustion() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["alice"][0]
    ship = state.get_ship(ship_id)
    ship.combustion = 50
    ship.speed = 0.0

    cmd = Command(ship_id=ship_id, action="ahead", args={"speed": 10.0})
    turn_resolver.resolve_turn(state, {ship_id: cmd})

    assert ship.speed == 10.0
    # within max → no spend; end-of-turn regen adds +15 → 65
    assert ship.combustion == 65


def test_over_burn_ahead_spends_combustion() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["alice"][0]
    ship = state.get_ship(ship_id)
    ship.combustion = 10
    cap = ship.effective_speed_max
    ship.speed = 0.0

    cmd = Command(ship_id=ship_id, action="ahead", args={"speed": cap + 3})
    turn_resolver.resolve_turn(state, {ship_id: cmd})

    assert ship.speed == cap + 3
    # 10 − 3 spent = 7, then +15 regen = 22
    assert ship.combustion == 22
