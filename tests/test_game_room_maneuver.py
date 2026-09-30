from __future__ import annotations

import asyncio
from typing import Any

from spacefleet.net.commands import Command, Maneuver
from spacefleet.net.game_room import GameRoom, PlayerConnection
from spacefleet.net.game_state import GameState
from spacefleet.net.protocol import (
    MSG_COMMAND,
    MSG_COMMAND_ACK,
    MSG_COMMAND_REJECT,
    MSG_PROMPT,
    MSG_QUERY_RESULT,
    decode_message,
    encode_message,
)


class _Writer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def write(self, data: bytes) -> None:
        msg = decode_message(data)
        assert msg is not None
        self.sent.append(msg)

    async def drain(self) -> None:
        return None


def _run(messages: list[dict[str, Any]]) -> tuple[Command | None, list[dict[str, Any]]]:
    async def scenario() -> tuple[Command | None, list[dict[str, Any]]]:
        state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
        room = GameRoom("room", state)
        reader = asyncio.StreamReader()
        for msg in messages:
            reader.feed_data(encode_message(msg))
        reader.feed_eof()
        writer = _Writer()
        conn = PlayerConnection("player", reader, writer)  # type: ignore[arg-type]
        ship = state.get_ship(state.player_ships["player"][0])
        cmd = await room._wait_for_command("player", conn, ship, state.owner_lookup())
        return cmd, writer.sent

    return asyncio.run(scenario())


def _command(action: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": MSG_COMMAND,
        "ship_id": "player_dauntless",
        "action": action,
        "args": {},
        **extra,
    }


def test_move_then_fire_yields_one_command_with_both() -> None:
    fire = _command("fire", args={"slot": 3, "bearing": 0})

    cmd, sent = _run([_command("move", maneuver={"speed": 8, "turn": 30}), fire])

    assert cmd == Command(
        ship_id="player_dauntless",
        action="fire",
        args={"slot": 3, "bearing": 0.0},
        maneuver=Maneuver(speed=8.0, turn=30.0),
    )
    types = [m["type"] for m in sent]
    assert types == [MSG_QUERY_RESULT, MSG_PROMPT, MSG_COMMAND_ACK]
    assert "starboard 30" in sent[0]["text"]


def test_later_move_replaces_pending_maneuver() -> None:
    cmd, _ = _run(
        [
            _command("move", maneuver={"speed": 8, "turn": 30}),
            _command("move", maneuver={"speed": None, "turn": -10}),
            _command("pass"),
        ]
    )

    assert cmd is not None
    assert cmd.maneuver == Maneuver(speed=None, turn=-10.0)


def test_explicit_maneuver_on_costed_command_wins() -> None:
    cmd, _ = _run(
        [
            _command("move", maneuver={"speed": 8, "turn": 30}),
            _command("pass", maneuver={"speed": 2, "turn": 0}),
        ]
    )

    assert cmd is not None
    assert cmd.maneuver == Maneuver(speed=2.0, turn=0.0)


def test_invalid_move_is_rejected_and_not_stored() -> None:
    cmd, sent = _run(
        [
            _command("move", maneuver={"speed": 8, "turn": 170}),
            _command("pass"),
        ]
    )

    assert sent[0]["type"] == MSG_COMMAND_REJECT
    assert "limit" in sent[0]["reason"]
    assert cmd is not None
    assert cmd.maneuver is None


def test_legacy_ahead_keeps_pending_turn() -> None:
    cmd, _ = _run(
        [
            _command("move", maneuver={"speed": None, "turn": 20}),
            _command("ahead", args={"speed": 10}),
        ]
    )

    assert cmd == Command(
        ship_id="player_dauntless",
        action="pass",
        args={},
        maneuver=Maneuver(speed=10.0, turn=20.0),
    )


def test_ws_client_move_matches_shared_parser() -> None:
    from spacefleet.cli.action_parser import parse_action_command
    from spacefleet.net.ws_client import _parse_action

    for tokens in (["8", "starboard", "30"], ["-", "port", "20"], ["0"]):
        assert _parse_action("s1", "move", tokens) == parse_action_command("s1", ["move", *tokens])
    assert _parse_action("s1", "move", ["8", "up", "30"]) is None
    assert _parse_action("s1", "move", []) is None


def test_server_help_and_prompt_describe_move_then_action() -> None:
    from spacefleet.net.server_renderer import ServerRenderer

    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship = state.get_ship(state.player_ships["player"][0])
    renderer = ServerRenderer()

    help_text = renderer.render_query("player", ship, "help", state)
    prompt = renderer.render_prompt(ship, 1, 1, state, "player")

    assert "move" in help_text and "port|starboard" in help_text
    assert "strike" in help_text and "pass" in help_text
    assert f"{ship.max_turn_this_turn(ship.speed):g}" in prompt
    assert "move" in prompt and "fire/strike/pass" in prompt
