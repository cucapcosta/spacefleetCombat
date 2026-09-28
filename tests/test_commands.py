from __future__ import annotations

from copy import deepcopy

import pytest

from spacefleet.net.commands import Command, validate_command
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
