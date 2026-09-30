"""Tests for the movement phase resolver."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.phases.movement_phase import (
    MoveOrder,
    apply_move_orders,
    drift_ship,
    resolve_movement_phase,
)


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


def test_accelerate_within_max_is_free():
    ship = _ship("a")
    ship.combustion = 50
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(target_speed=10.0)},
    )
    assert ship.speed == 10.0
    assert ship.combustion == 50
    assert any(e.kind == "speed" for e in log)
    assert any(e.kind == "drift" for e in log)


def test_over_burn_spends_combustion():
    ship = _ship("a")
    ship.combustion = 10
    cap = ship.effective_speed_max
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(target_speed=cap + 3)},
    )
    assert ship.speed == cap + 3
    assert ship.combustion == 7
    assert any(e.kind == "speed" for e in log)


def test_turn_order_pivots():
    ship = _ship("a")
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(turn_degrees=30.0)},
    )
    assert any(e.kind == "turn" for e in log)


# ── Full turn, no carry-over (spec 2026-09-30 "Resolução do turno") ──


def test_full_turn_distance_equals_speed() -> None:
    # New rule: a turn is two movement halves, so a ship covers its whole speed.
    ship = _ship("a")
    ship.speed = 10.0
    resolve_movement_phase([ship], orders={})
    assert ship.position.y == pytest.approx(10.0)


def test_total_turn_equals_ordered_and_nothing_pending() -> None:
    ship = _ship("a")
    ship.speed = 10.0
    resolve_movement_phase([ship], orders={"a": MoveOrder(turn_degrees=40.0)})
    assert ship.heading == pytest.approx(40.0)
    assert ship.pending_turn == 0.0


def test_turn_beyond_limit_is_clamped_and_never_carries_over() -> None:
    # New rule: only this turn's turn executes; the excess is dropped, not kept.
    ship = _ship("a")
    ship.speed = 10.0
    limit = ship.max_turn_this_turn(10.0)
    resolve_movement_phase([ship], orders={"a": MoveOrder(turn_degrees=-(limit + 50.0))})
    assert ship.heading == pytest.approx(360.0 - limit)
    assert ship.pending_turn == 0.0


def test_stationary_pivot_uses_multiplier_limit() -> None:
    ship = _ship("a")
    limit = ship.max_turn_this_turn(0.0)
    assert limit == pytest.approx(ship.effective_turn_rate * Ship.PIVOT_RATE_MULTIPLIER)
    resolve_movement_phase([ship], orders={"a": MoveOrder(turn_degrees=limit + 30.0)})
    assert ship.heading == pytest.approx(limit)
    assert ship.position == Vector2D(0.0, 0.0)
    assert ship.pending_turn == 0.0


def test_leftover_pending_turn_from_old_saves_is_dropped() -> None:
    ship = _ship("a")
    ship.speed = 10.0
    ship.pending_turn = 50.0
    resolve_movement_phase([ship], orders={})
    assert ship.heading == 0.0
    assert ship.pending_turn == 0.0


def test_each_half_executes_half_the_turn() -> None:
    ship = _ship("a")
    ship.speed = 0.0
    apply_move_orders([ship], {"a": MoveOrder(turn_degrees=40.0)})
    drift_ship(ship, 0.5)
    assert ship.heading == pytest.approx(20.0)
    drift_ship(ship, 0.5, remaining=0.5)
    assert ship.heading == pytest.approx(40.0)
    assert ship.pending_turn == 0.0
