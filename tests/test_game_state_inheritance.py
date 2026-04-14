"""net.GameState inherits from core.CoreGameState."""

from __future__ import annotations

from spacefleet.core.game_state import CoreGameState
from spacefleet.net.game_state import GameState


def test_game_state_is_core_game_state() -> None:
    assert issubclass(GameState, CoreGameState)


def test_create_pve_state_has_core_methods() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1)
    assert hasattr(state, "alive_ships")
    assert hasattr(state, "enemy_ships_of")
    assert hasattr(state, "friendly_ships_of")
    assert hasattr(state, "is_game_over")
    assert callable(state.alive_ships)
    assert "alice" in state.player_ships
    assert state.next_projectile_id() == "salvo_1"
