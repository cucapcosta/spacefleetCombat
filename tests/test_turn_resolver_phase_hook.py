from __future__ import annotations

from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import resolve_turn

# New rule: two movement halves, observed through "mid_move" between them.
PHASES = ["start", "after_fire", "mid_move", "after_move", "end"]


def _state_and_commands() -> tuple[GameState, dict[str, Command]]:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]
    return state, {ship_id: Command(ship_id=ship_id, action="ahead", args={"speed": 20.0})}


def test_hook_called_once_per_phase_in_order_with_same_state() -> None:
    state, commands = _state_and_commands()
    calls: list[tuple[str, GameState]] = []

    resolve_turn(state, commands, on_phase=lambda name, s: calls.append((name, s)))

    assert [name for name, _ in calls] == PHASES
    assert all(s is state for _, s in calls)


def test_hook_does_not_change_resolution() -> None:
    plain_state, plain_cmds = _state_and_commands()
    hooked_state, hooked_cmds = _state_and_commands()

    plain_log = resolve_turn(plain_state, plain_cmds)
    hooked_log = resolve_turn(hooked_state, hooked_cmds, on_phase=lambda _n, _s: None)

    assert [type(e) for e in plain_log.events] == [type(e) for e in hooked_log.events]
    assert {
        sid: (s.position.x, s.position.y, s.hull_current) for sid, s in plain_state.ships.items()
    } == {
        sid: (s.position.x, s.position.y, s.hull_current) for sid, s in hooked_state.ships.items()
    }


def test_after_fire_sees_pre_move_positions_and_after_move_sees_post_move() -> None:
    state, commands = _state_and_commands()
    ship_id = next(iter(commands))
    positions: dict[str, tuple[float, float]] = {}

    def record(name: str, s: GameState) -> None:
        pos = s.get_ship(ship_id).position
        positions[name] = (pos.x, pos.y)

    resolve_turn(state, commands, on_phase=record)

    assert positions["start"] == positions["after_fire"]
    assert positions["after_fire"] != positions["after_move"]
    assert positions["after_move"] == positions["end"]
