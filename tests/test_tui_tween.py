"""Tests for the TUI tween helpers."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Vector2D
from spacefleet.tui.model.tween import ease_in_out, lerp, lerp_angle, lerp_vec


def test_ease_endpoints_and_midpoint() -> None:
    assert ease_in_out(0.0) == 0.0
    assert ease_in_out(1.0) == 1.0
    assert ease_in_out(0.5) == pytest.approx(0.5)


def test_ease_clamps_out_of_range() -> None:
    assert ease_in_out(-1.0) == 0.0
    assert ease_in_out(2.0) == 1.0


def test_ease_is_monotonic() -> None:
    values = [ease_in_out(i / 20) for i in range(21)]
    assert values == sorted(values)


def test_lerp() -> None:
    assert lerp(10.0, 20.0, 0.25) == pytest.approx(12.5)


def test_lerp_vec() -> None:
    p = lerp_vec(Vector2D(0.0, 0.0), Vector2D(10.0, -4.0), 0.5)
    assert (p.x, p.y) == pytest.approx((5.0, -2.0))


def test_lerp_angle_wraps_through_north() -> None:
    assert lerp_angle(350.0, 10.0, 0.5) == pytest.approx(0.0)
    assert lerp_angle(10.0, 350.0, 0.25) == pytest.approx(5.0)


def test_lerp_angle_result_normalized() -> None:
    assert 0.0 <= lerp_angle(350.0, 10.0, 0.75) < 360.0
    assert lerp_angle(350.0, 10.0, 0.75) == pytest.approx(5.0)
    assert lerp_angle(90.0, 180.0, 0.5) == pytest.approx(135.0)
