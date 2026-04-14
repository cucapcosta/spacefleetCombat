"""turn_resolver publishes each TurnEvent on CoreGameState.events."""

from __future__ import annotations

from spacefleet.core.events import EventBus
from spacefleet.net import turn_resolver
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import DriftEvent, SpeedChangeEvent


def test_state_has_event_bus() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    assert isinstance(state.events, EventBus)


def test_subscriber_receives_speed_change() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    received: list[SpeedChangeEvent] = []
    state.events.subscribe(SpeedChangeEvent, received.append)

    ship_id = state.player_ships["alice"][0]
    state.get_ship(ship_id).combustion = 50
    cmd = Command(ship_id=ship_id, action="ahead", args={"speed": 5.0})
    turn_resolver.resolve_turn(state, {ship_id: cmd})

    assert len(received) >= 1
    assert any(ev.new_speed == 5.0 for ev in received)


def test_subscriber_receives_drift() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    received: list[DriftEvent] = []
    state.events.subscribe(DriftEvent, received.append)

    ship_id = state.player_ships["alice"][0]
    cmd = Command(ship_id=ship_id, action="pass", args={})
    turn_resolver.resolve_turn(state, {ship_id: cmd})

    assert len(received) >= 1
