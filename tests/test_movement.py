"""Tests for spatial.movement (combustion gauge)."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.spatial.movement import (
    CombustionError,
    accelerate,
    combustion_cost,
    decelerate,
)


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_cost_is_speed_delta():
    assert combustion_cost(0.0, 10.0) == 10
    assert combustion_cost(10.0, 25.0) == 15
    assert combustion_cost(20.0, 5.0) == 0  # decel free


def test_accelerate_spends_combustion():
    ship = _ship()
    ship.combustion = 50
    accelerate(ship, target_speed=10.0)
    assert ship.speed == 10.0
    assert ship.combustion == 40


def test_accelerate_clamps_to_max_speed():
    ship = _ship()
    ship.combustion = 999
    accelerate(ship, target_speed=999.0)
    assert ship.speed == ship.effective_speed_max


def test_accelerate_insufficient_combustion_raises():
    ship = _ship()
    ship.combustion = 5
    with pytest.raises(CombustionError):
        accelerate(ship, target_speed=20.0)


def test_decelerate_is_free():
    ship = _ship()
    ship.combustion = 10
    ship.speed = 20.0
    decelerate(ship, target_speed=5.0)
    assert ship.speed == 5.0
    assert ship.combustion == 10  # untouched
