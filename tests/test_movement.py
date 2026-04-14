"""Tests for spatial.movement (combustion cost helper)."""

from __future__ import annotations

from spacefleet.spatial.movement import combustion_cost


def test_cost_zero_within_max() -> None:
    assert combustion_cost(current_speed=0.0, target_speed=10.0, max_speed=20.0) == 0
    assert combustion_cost(current_speed=0.0, target_speed=20.0, max_speed=20.0) == 0


def test_cost_only_over_portion() -> None:
    assert combustion_cost(current_speed=0.0, target_speed=25.0, max_speed=20.0) == 5


def test_cost_already_over_burn_delta_only() -> None:
    assert combustion_cost(current_speed=22.0, target_speed=25.0, max_speed=20.0) == 3


def test_cost_decelerating_over_burn_is_free() -> None:
    assert combustion_cost(current_speed=25.0, target_speed=20.0, max_speed=20.0) == 0
    assert combustion_cost(current_speed=25.0, target_speed=22.0, max_speed=20.0) == 0


def test_cost_decelerating_within_normal_range_is_free() -> None:
    assert combustion_cost(current_speed=15.0, target_speed=5.0, max_speed=20.0) == 0


def test_cost_rounds_up_fractional_over() -> None:
    assert combustion_cost(current_speed=0.0, target_speed=20.5, max_speed=20.0) == 1
