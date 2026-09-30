from __future__ import annotations

from copy import deepcopy

import pytest

from spacefleet.cli.action_parser import parse_action_command
from spacefleet.net.commands import Command, Maneuver, validate_command, validate_move
from spacefleet.net.game_state import GameState


def _setup():  # type: ignore[no-untyped-def]
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship = state.get_ship(state.player_ships["player"][0])
    return ship, state.owner_lookup()


def _fire_args(args: object) -> dict[str, object]:
    return {
        "type": "command",
        "ship_id": "player_dauntless",
        "action": "fire",
        "args": args,
    }


def test_single_fire_remains_backward_compatible() -> None:
    ship, owners = _setup()

    result = validate_command(_fire_args({"slot": "3", "bearing": 360}), ship, "player", owners)

    assert result == Command(
        ship_id="player_dauntless",
        action="fire",
        args={"slot": 3, "bearing": 0.0},
    )


def test_multiple_fire_shots_are_normalized_in_input_order() -> None:
    ship, owners = _setup()

    result = validate_command(
        _fire_args(
            {
                "shots": [
                    {"slot": 2, "bearing": 90},
                    {"slot": 1, "bearing": -90},
                ]
            }
        ),
        ship,
        "player",
        owners,
    )

    assert result == Command(
        ship_id="player_dauntless",
        action="fire",
        args={
            "shots": [
                {"slot": 2, "bearing": 90.0},
                {"slot": 1, "bearing": 270.0},
            ]
        },
    )


@pytest.mark.parametrize(
    "args",
    [
        {"shots": []},
        {"shots": "not-a-list"},
        {"shots": [{"slot": 1, "bearing": 270}, "not-an-object"]},
        {"shots": [{"slot": True, "bearing": 270}]},
        {"shots": [{"slot": 1.5, "bearing": 270}]},
        {"shots": [{"slot": 1, "bearing": 270}, {"slot": 1, "bearing": 270}]},
        {"shots": [{"slot": 1, "bearing": float("nan")}]},
        {"shots": [{"slot": 1, "bearing": float("inf")}]},
        {
            "shots": [
                {"slot": 1, "bearing": 270},
                {"slot": 2, "bearing": 90},
                {"slot": 3, "bearing": 0},
                {"slot": 1, "bearing": 270},
            ]
        },
        {"shots": [{"slot": 1, "bearing": 270}], "slot": 1},
        {"shots": [{"slot": 1, "bearing": 270}], "bearing": 270},
    ],
)
def test_invalid_multiple_fire_payload_is_rejected_atomically(args: object) -> None:
    ship, owners = _setup()
    before = deepcopy(ship)

    result = validate_command(_fire_args(args), ship, "player", owners)

    assert isinstance(result, str)
    assert ship == before


@pytest.mark.parametrize(
    "bearing",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(10**10_000, id="overflowing-integer"),
    ],
)
def test_single_fire_rejects_nonfinite_bearing(bearing: object) -> None:
    ship, owners = _setup()
    result = validate_command(_fire_args({"slot": 3, "bearing": bearing}), ship, "player", owners)
    assert isinstance(result, str)


def test_damaged_weapon_without_cooldown_is_reported_unavailable() -> None:
    ship, owners = _setup()
    ship.weapons[2].can_fire = False
    ship.weapons[2].cooldown = 0

    result = validate_command(_fire_args({"slot": 3, "bearing": 0}), ship, "player", owners)

    assert isinstance(result, str)
    assert "unavailable" in result


# ── Maneuver (free) + action ────────────────────────────────


def _msg(action: str, args: object = None, maneuver: object = None) -> dict[str, object]:
    msg: dict[str, object] = {
        "type": "command",
        "ship_id": "player_dauntless",
        "action": action,
        "args": {} if args is None else args,
    }
    if maneuver is not None:
        msg["maneuver"] = maneuver
    return msg


def test_maneuver_and_fire_are_valid_together() -> None:
    ship, owners = _setup()

    result = validate_command(
        _msg("fire", {"slot": 3, "bearing": 0}, {"speed": 8, "turn": -30}),
        ship,
        "player",
        owners,
    )

    assert result == Command(
        ship_id="player_dauntless",
        action="fire",
        args={"slot": 3, "bearing": 0.0},
        maneuver=Maneuver(speed=8.0, turn=-30.0),
    )


def test_maneuver_without_speed_keeps_current_speed() -> None:
    ship, owners = _setup()
    ship.speed = 10.0

    result = validate_command(
        _msg("pass", maneuver={"speed": None, "turn": 20}), ship, "player", owners
    )

    assert isinstance(result, Command)
    assert result.maneuver == Maneuver(speed=None, turn=20.0)


def test_command_without_maneuver_has_none() -> None:
    ship, owners = _setup()

    result = validate_command(_msg("pass"), ship, "player", owners)

    assert result == Command(ship_id="player_dauntless", action="pass", args={})


def test_turn_over_limit_is_rejected_with_the_limit() -> None:
    ship, owners = _setup()
    limit = ship.max_turn_this_turn(8.0)

    result = validate_command(
        _msg("pass", maneuver={"speed": 8, "turn": limit + 15}), ship, "player", owners
    )

    assert isinstance(result, str)
    assert f"limit of {limit:g}° this turn" in result


def test_stationary_ship_pivots_up_to_the_pivot_limit() -> None:
    ship, owners = _setup()
    pivot = ship.max_turn_this_turn(0.0)
    assert pivot > ship.max_turn_this_turn(5.0)

    ok = validate_command(
        _msg("pass", maneuver={"speed": 0, "turn": -pivot}), ship, "player", owners
    )
    moving = validate_command(
        _msg("pass", maneuver={"speed": 5, "turn": -pivot}), ship, "player", owners
    )

    assert isinstance(ok, Command)
    assert ok.maneuver == Maneuver(speed=0.0, turn=-pivot)
    assert isinstance(moving, str)


@pytest.mark.parametrize(
    "maneuver",
    [
        {"speed": -1, "turn": 0},
        {"speed": float("inf"), "turn": 0},
        {"speed": 5, "turn": float("nan")},
        {"speed": "fast", "turn": 0},
        {"speed": 5, "turn": True},
        "ahead",
    ],
)
def test_invalid_maneuver_is_rejected(maneuver: object) -> None:
    ship, owners = _setup()

    result = validate_command(_msg("pass", maneuver=maneuver), ship, "player", owners)

    assert isinstance(result, str)


def test_maneuver_speed_is_clamped_to_speed_max() -> None:
    ship, owners = _setup()

    result = validate_command(
        _msg("pass", maneuver={"speed": ship.speed_max + 50}), ship, "player", owners
    )

    assert isinstance(result, Command)
    assert result.maneuver == Maneuver(speed=ship.speed_max, turn=0.0)


def test_legacy_ahead_becomes_pass_with_speed() -> None:
    ship, owners = _setup()

    explicit = validate_command(_msg("ahead", {"speed": 12}), ship, "player", owners)
    full = validate_command(_msg("ahead", {"speed": None}), ship, "player", owners)

    assert explicit == Command(
        ship_id="player_dauntless", action="pass", args={}, maneuver=Maneuver(speed=12.0)
    )
    assert isinstance(full, Command)
    assert full.maneuver == Maneuver(speed=ship.speed_max)


def test_legacy_stop_becomes_pass_with_zero_speed() -> None:
    ship, owners = _setup()

    result = validate_command(_msg("stop"), ship, "player", owners)

    assert result == Command(
        ship_id="player_dauntless", action="pass", args={}, maneuver=Maneuver(speed=0.0)
    )


def test_legacy_turn_becomes_pass_with_signed_turn() -> None:
    ship, owners = _setup()

    port = validate_command(
        _msg("turn", {"direction": "port", "degrees": 30}), ship, "player", owners
    )
    starboard = validate_command(
        _msg("turn", {"direction": "s", "degrees": 30}), ship, "player", owners
    )
    too_far = validate_command(
        _msg("turn", {"direction": "port", "degrees": 170}), ship, "player", owners
    )

    assert port == Command(
        ship_id="player_dauntless", action="pass", args={}, maneuver=Maneuver(turn=-30.0)
    )
    assert isinstance(starboard, Command)
    assert starboard.maneuver == Maneuver(turn=30.0)
    assert isinstance(too_far, str)
    assert "limit" in too_far


def test_legacy_shortcut_keeps_other_field_of_explicit_maneuver() -> None:
    ship, owners = _setup()

    result = validate_command(
        _msg("ahead", {"speed": 10}, {"speed": 3, "turn": 20}), ship, "player", owners
    )

    assert isinstance(result, Command)
    assert result.action == "pass"
    assert result.maneuver == Maneuver(speed=10.0, turn=20.0)


def test_validate_move_returns_the_maneuver() -> None:
    ship, owners = _setup()

    result = validate_move(_msg("move", maneuver={"speed": 8, "turn": 30}), ship, "player", owners)
    stranger = validate_move(
        {**_msg("move", maneuver={"speed": 8}), "ship_id": "nope"}, ship, "player", owners
    )

    assert result == Maneuver(speed=8.0, turn=30.0)
    assert isinstance(stranger, str)


def test_validate_command_rejects_move_as_costed_action() -> None:
    ship, owners = _setup()

    result = validate_command(_msg("move", maneuver={"speed": 8}), ship, "player", owners)

    assert isinstance(result, str)
    assert "free" in result


# ── Token parser ────────────────────────────────────────────


def test_parser_move_with_speed_and_turn() -> None:
    assert parse_action_command("s1", ["move", "8", "starboard", "30"]) == {
        "type": "command",
        "ship_id": "s1",
        "action": "move",
        "args": {},
        "maneuver": {"speed": 8.0, "turn": 30.0},
    }


def test_parser_move_keep_speed_and_port_turn() -> None:
    parsed = parse_action_command("s1", ["move", "-", "port", "20"])

    assert isinstance(parsed, dict)
    assert parsed["maneuver"] == {"speed": None, "turn": -20.0}


def test_parser_move_speed_only() -> None:
    parsed = parse_action_command("s1", ["move", "0"])

    assert isinstance(parsed, dict)
    assert parsed["maneuver"] == {"speed": 0.0, "turn": 0.0}


@pytest.mark.parametrize(
    "tokens",
    [
        ["move"],
        ["move", "fast"],
        ["move", "8", "up", "30"],
        ["move", "8", "port"],
        ["move", "8", "port", "-5"],
        ["move", "inf"],
    ],
)
def test_parser_move_rejects_bad_input(tokens: list[str]) -> None:
    assert isinstance(parse_action_command("s1", tokens), str)


@pytest.mark.parametrize(
    "tokens",
    [["ahead", "8"], ["ahead"], ["stop"], ["turn", "port", "30"]],
)
def test_parser_legacy_tokens_stay_valid(tokens: list[str]) -> None:
    ship, owners = _setup()
    parsed = parse_action_command(ship.id, tokens)
    assert isinstance(parsed, dict)

    result = validate_command(parsed, ship, "player", owners)

    assert isinstance(result, Command)
    assert result.action == "pass"
    assert result.maneuver is not None
