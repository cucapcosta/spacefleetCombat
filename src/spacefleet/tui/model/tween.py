"""Interpolation helpers for playback animation."""

from __future__ import annotations

from spacefleet.core.types import Vector2D


def ease_in_out(t: float) -> float:
    """Smoothstep easing; ``t`` is clamped to [0, 1]."""
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_vec(a: Vector2D, b: Vector2D, t: float) -> Vector2D:
    return Vector2D(lerp(a.x, b.x, t), lerp(a.y, b.y, t))


def lerp_angle(a: float, b: float, t: float) -> float:
    """Interpolate headings along the shortest arc, result in [0, 360)."""
    delta = (b - a + 180.0) % 360.0 - 180.0
    return (a + delta * t) % 360.0
