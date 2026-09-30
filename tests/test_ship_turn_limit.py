from __future__ import annotations

import pytest

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_moving_ship_turns_up_to_its_turn_rate_per_turn() -> None:
    ship = _ship()
    assert ship.max_turn_this_turn(speed_after=5.0) == pytest.approx(ship.effective_turn_rate)


def test_stationary_ship_pivots_faster() -> None:
    ship = _ship()
    expected = ship.effective_turn_rate * Ship.PIVOT_RATE_MULTIPLIER
    assert ship.max_turn_this_turn(speed_after=0.0) == pytest.approx(expected)


def test_damaged_thrusters_cannot_turn() -> None:
    ship = _ship()
    ship.crit_thrusters_damaged = True
    assert ship.max_turn_this_turn(speed_after=5.0) == 0.0
