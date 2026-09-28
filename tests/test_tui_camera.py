"""Tests for the TUI tactical-map camera."""

from __future__ import annotations

import math

import pytest

from spacefleet.core.types import Vector2D
from spacefleet.tui.model.camera import Camera


def _cam() -> Camera:
    return Camera(center=Vector2D(0.0, 0.0), gu_per_dot=0.5, cols=40, rows=20)


def test_center_maps_to_middle_of_dot_grid() -> None:
    assert _cam().world_to_dot(Vector2D(0.0, 0.0)) == pytest.approx((40.0, 40.0))


def test_north_is_up_on_screen() -> None:
    cam = _cam()
    _, dy_center = cam.world_to_dot(Vector2D(0.0, 0.0))
    _, dy_north = cam.world_to_dot(Vector2D(0.0, 10.0))
    assert dy_north < dy_center


def test_world_dot_roundtrip() -> None:
    cam = Camera(center=Vector2D(12.0, -7.0), gu_per_dot=1.3, cols=33, rows=17)
    p = Vector2D(21.5, 4.25)
    back = cam.dot_to_world(*cam.world_to_dot(p))
    assert (back.x, back.y) == pytest.approx((p.x, p.y))


def test_world_to_cell() -> None:
    cam = _cam()
    assert cam.world_to_cell(Vector2D(0.0, 0.0)) == (20, 10)
    # 1 GU east = 2 dots = 1 cell; 2 GU north = 4 dots = 1 cell up.
    assert cam.world_to_cell(Vector2D(1.0, 2.0)) == (21, 9)


def test_zoom_preserves_anchor_dot_position() -> None:
    cam = _cam()
    anchor = Vector2D(7.0, 3.0)
    before = cam.world_to_dot(anchor)
    cam.zoom(2.0, anchor)
    assert cam.gu_per_dot == pytest.approx(0.25)
    assert cam.world_to_dot(anchor) == pytest.approx(before)


def test_zoom_without_anchor_keeps_center() -> None:
    cam = _cam()
    cam.zoom(0.5)
    assert (cam.center.x, cam.center.y) == (0.0, 0.0)
    assert cam.gu_per_dot == pytest.approx(1.0)


def test_pan_moves_center_by_cells() -> None:
    cam = _cam()
    cam.pan(1, 1)  # one cell right, one cell down
    assert (cam.center.x, cam.center.y) == pytest.approx((1.0, -2.0))


def test_fit_includes_all_points() -> None:
    cam = _cam()
    points = [Vector2D(-100.0, 5.0), Vector2D(40.0, 80.0), Vector2D(3.0, -60.0)]
    cam.fit(points)
    for p in points:
        dx, dy = cam.world_to_dot(p)
        assert 0 <= dx < cam.cols * 2
        assert 0 <= dy < cam.rows * 4


def test_fit_single_and_empty_use_sane_scale() -> None:
    cam = _cam()
    cam.fit([Vector2D(50.0, 50.0)])
    assert (cam.center.x, cam.center.y) == (50.0, 50.0)
    assert cam.gu_per_dot > 0
    cam.fit([])
    assert cam.gu_per_dot > 0


def _is_round(value: float) -> bool:
    mantissa = value / 10 ** math.floor(math.log10(value))
    return any(math.isclose(mantissa, m) for m in (1.0, 2.0, 5.0))


def test_scale_bar_returns_round_value() -> None:
    cam = Camera(center=Vector2D(0.0, 0.0), gu_per_dot=0.37, cols=80, rows=20)
    length, gu = cam.scale_bar(10)
    assert 0 < length <= 10
    assert _is_round(gu)
    # The bar length must actually represent `gu` world units (2 dots per cell).
    assert length == round(gu / (cam.gu_per_dot * 2))


def test_scale_bar_picks_largest_round_value_that_fits() -> None:
    cam = Camera(center=Vector2D(0.0, 0.0), gu_per_dot=0.5, cols=80, rows=20)
    # 10 cells = 20 dots = 10 GU.
    assert cam.scale_bar(10) == (10, 10.0)
    assert cam.scale_bar(9) == (5, 5.0)
