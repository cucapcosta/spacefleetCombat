"""Ship.set_speed — over-burn combustion model."""

from __future__ import annotations

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


def test_within_max_is_free() -> None:
    ship = _ship()
    ship.combustion = 50
    cap = ship.effective_speed_max
    ship.set_speed(cap)
    assert ship.speed == cap
    assert ship.combustion == 50


def test_exactly_at_max_is_free() -> None:
    ship = _ship()
    ship.combustion = 50
    ship.set_speed(ship.effective_speed_max)
    assert ship.combustion == 50


def test_over_burn_spends_combustion() -> None:
    ship = _ship()
    ship.combustion = 10
    cap = ship.effective_speed_max
    ship.set_speed(cap + 5)
    assert ship.speed == cap + 5
    assert ship.combustion == 5


def test_over_burn_clamps_to_available_combustion() -> None:
    ship = _ship()
    ship.combustion = 3
    cap = ship.effective_speed_max
    ship.set_speed(cap + 10)
    assert ship.speed == cap + 3
    assert ship.combustion == 0


def test_decelerate_from_over_burn_is_free() -> None:
    ship = _ship()
    ship.combustion = 0
    cap = ship.effective_speed_max
    ship.speed = cap + 5
    ship.set_speed(cap)
    assert ship.speed == cap
    assert ship.combustion == 0


def test_decelerate_within_normal_range_is_free() -> None:
    ship = _ship()
    ship.combustion = 10
    ship.speed = 15.0
    ship.set_speed(5.0)
    assert ship.speed == 5.0
    assert ship.combustion == 10


def test_raising_further_while_already_over_burn_costs_delta_only() -> None:
    ship = _ship()
    ship.combustion = 10
    cap = ship.effective_speed_max
    ship.speed = cap + 2
    ship.set_speed(cap + 5)
    assert ship.speed == cap + 5
    assert ship.combustion == 7


def test_negative_target_clamps_to_zero() -> None:
    ship = _ship()
    ship.speed = 10.0
    ship.set_speed(-5.0)
    assert ship.speed == 0.0
