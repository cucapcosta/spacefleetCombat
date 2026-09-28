"""World <-> braille-dot mapping for the tactical map.

The dot grid is ``cols * 2`` wide and ``rows * 4`` tall (one braille cell
holds 2x4 dots).  Dots are assumed square.  The map is north-up: world +Y
is up on screen, so dot ``dy`` grows as world ``y`` shrinks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.core.types import Vector2D

if TYPE_CHECKING:
    from collections.abc import Iterable

# Smallest world span (GU) ``fit`` will frame, so one ship is not a blur.
MIN_FIT_SPAN = 20.0


@dataclass
class Camera:
    center: Vector2D
    gu_per_dot: float
    cols: int
    rows: int

    @property
    def dot_width(self) -> int:
        return self.cols * 2

    @property
    def dot_height(self) -> int:
        return self.rows * 4

    def world_to_dot(self, p: Vector2D) -> tuple[float, float]:
        dx = self.dot_width / 2 + (p.x - self.center.x) / self.gu_per_dot
        dy = self.dot_height / 2 - (p.y - self.center.y) / self.gu_per_dot
        return dx, dy

    def dot_to_world(self, dx: float, dy: float) -> Vector2D:
        x = self.center.x + (dx - self.dot_width / 2) * self.gu_per_dot
        y = self.center.y - (dy - self.dot_height / 2) * self.gu_per_dot
        return Vector2D(x, y)

    def world_to_cell(self, p: Vector2D) -> tuple[int, int]:
        dx, dy = self.world_to_dot(p)
        return math.floor(dx) // 2, math.floor(dy) // 4

    def zoom(self, factor: float, anchor: Vector2D | None = None) -> None:
        """Zoom in by ``factor`` (>1 magnifies), keeping ``anchor`` fixed on screen."""
        new_gu = self.gu_per_dot / factor
        if anchor is not None:
            keep = new_gu / self.gu_per_dot
            self.center = anchor - (anchor - self.center) * keep
        self.gu_per_dot = new_gu

    def pan(self, dx_cells: float, dy_cells: float) -> None:
        """Move the view; positive values pan right / down."""
        self.center = Vector2D(
            self.center.x + dx_cells * 2 * self.gu_per_dot,
            self.center.y - dy_cells * 4 * self.gu_per_dot,
        )

    def fit(self, points: Iterable[Vector2D], margin: float = 0.1) -> None:
        """Center and scale so every point is visible; no-op for no points."""
        pts = list(points)
        if not pts:
            return
        min_x = min(p.x for p in pts)
        max_x = max(p.x for p in pts)
        min_y = min(p.y for p in pts)
        max_y = max(p.y for p in pts)
        self.center = Vector2D((min_x + max_x) / 2, (min_y + max_y) / 2)
        pad = 1.0 + 2.0 * margin
        self.gu_per_dot = max(
            (max_x - min_x) * pad / self.dot_width,
            (max_y - min_y) * pad / self.dot_height,
            MIN_FIT_SPAN / min(self.dot_width, self.dot_height),
        )

    def scale_bar(self, max_cells: int) -> tuple[int, float]:
        """Largest round GU value (1, 2, 5 x 10^n) whose bar fits ``max_cells``."""
        gu_per_cell = self.gu_per_dot * 2
        limit = max_cells * gu_per_cell
        exponent = math.floor(math.log10(limit))
        gu = 10.0**exponent
        for mantissa in (5.0, 2.0, 1.0):
            candidate = mantissa * 10.0**exponent
            if candidate <= limit * (1 + 1e-9):
                gu = candidate
                break
        return round(gu / gu_per_cell), gu
