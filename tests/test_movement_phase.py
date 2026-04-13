"""Tests for the movement phase resolver."""

from __future__ import annotations

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.phases.movement_phase import MoveOrder, resolve_movement_phase


def _ship(name: str, *, x: float = 0.0, y: float = 0.0) -> Ship:
    return Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(x, y),
        heading=0.0,
    )


def test_no_orders_drifts_ships():
    ship = _ship("a")
    ship.speed = 10.0
    log = resolve_movement_phase([ship], orders={})
    assert ship.position.y > 0  # drifted forward
    assert any(e.kind == "drift" for e in log)


def test_accelerate_then_drift():
    ship = _ship("a")
    ship.combustion = 50
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(target_speed=10.0)},
    )
    assert ship.speed == 10.0
    assert ship.combustion == 40
    assert any(e.kind == "speed" for e in log)
    assert any(e.kind == "drift" for e in log)


def test_turn_order_pivots():
    ship = _ship("a")
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(turn_degrees=30.0)},
    )
    assert any(e.kind == "turn" for e in log)
