"""Smoke tests — verify that key modules import and basic invariants hold."""

from __future__ import annotations


def test_protocol_constants_are_strings() -> None:
    from spacefleet.net.protocol import MSG_AUTH, MSG_AUTH_OK, MSG_GAME_OVER

    assert isinstance(MSG_AUTH, str)
    assert isinstance(MSG_AUTH_OK, str)
    assert isinstance(MSG_GAME_OVER, str)


def test_encode_decode_roundtrip() -> None:
    from spacefleet.net.protocol import decode_message, encode_message

    original = {"type": "auth", "username": "test"}
    raw = encode_message(original)
    assert raw.endswith(b"\n")
    decoded = decode_message(raw)
    assert decoded == original


def test_game_state_create_pve() -> None:
    from spacefleet.net.game_state import GameState

    state = GameState.create_pve(["alice"], ships_per_player=1)
    assert "alice" in state.player_ships
    assert len(state.player_ships["alice"]) == 1
    assert not state.is_game_over()


def test_ws_client_parse_action() -> None:
    from spacefleet.net.ws_client import _parse_action

    result = _parse_action("ship1", "fire", ["1", "270"])
    assert result is not None
    assert result["action"] == "fire"
    assert result["args"]["slot"] == 1
    assert result["args"]["bearing"] == 270.0

    assert _parse_action("ship1", "pass", []) is not None
    assert _parse_action("ship1", "nonsense", []) is None
