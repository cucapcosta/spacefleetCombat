"""Braille-dot raster canvas rendered to Rich text rows.

Each terminal cell is a braille character holding a 2x4 dot grid.  Angles
use compass degrees like ship headings: 0 is up (north), clockwise.
"""

from __future__ import annotations

import math

from rich.text import Text

# Bit for dot (x % 2, y % 4) inside a cell, standard braille numbering.
_DOT_BITS = (
    (0x01, 0x02, 0x04, 0x40),  # left column, top -> bottom
    (0x08, 0x10, 0x20, 0x80),  # right column
)
_BRAILLE_BASE = 0x2800


class BrailleCanvas:
    def __init__(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        self._bits = [[0] * cols for _ in range(rows)]
        self._styles: list[list[str | None]] = [[None] * cols for _ in range(rows)]
        self._text: dict[tuple[int, int], tuple[str, str | None]] = {}

    def set_dot(self, x: float, y: float, style: str | None = None) -> None:
        xi, yi = math.floor(x + 0.5), math.floor(y + 0.5)
        if not (0 <= xi < self.cols * 2 and 0 <= yi < self.rows * 4):
            return
        col, row = xi // 2, yi // 4
        self._bits[row][col] |= _DOT_BITS[xi % 2][yi % 4]
        if style is not None:
            self._styles[row][col] = style

    def line(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        style: str | None = None,
        dashed: bool = False,
    ) -> None:
        """Bresenham line; ``dashed`` draws 2 dots on, 2 off."""
        xa, ya = math.floor(x0 + 0.5), math.floor(y0 + 0.5)
        xb, yb = math.floor(x1 + 0.5), math.floor(y1 + 0.5)
        dx, dy = abs(xb - xa), -abs(yb - ya)
        sx = 1 if xa < xb else -1
        sy = 1 if ya < yb else -1
        err = dx + dy
        step = 0
        while True:
            if not dashed or step % 4 < 2:
                self.set_dot(xa, ya, style)
            if xa == xb and ya == yb:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                xa += sx
            if e2 <= dx:
                err += dx
                ya += sy
            step += 1

    def arc(
        self,
        cx: float,
        cy: float,
        r: float,
        start_deg: float,
        end_deg: float,
        style: str | None = None,
    ) -> None:
        """Arc swept clockwise from ``start_deg`` to ``end_deg`` (compass)."""
        span = (end_deg - start_deg) % 360.0
        if span == 0.0 and end_deg != start_deg:
            span = 360.0
        steps = max(1, math.ceil(math.radians(span) * r * 2))
        for i in range(steps + 1):
            theta = math.radians(start_deg + span * i / steps)
            self.set_dot(cx + r * math.sin(theta), cy - r * math.cos(theta), style)

    def circle(self, cx: float, cy: float, r: float, style: str | None = None) -> None:
        self.arc(cx, cy, r, 0.0, 360.0, style)

    def sector(
        self,
        cx: float,
        cy: float,
        r: float,
        start_deg: float,
        end_deg: float,
        style: str | None = None,
    ) -> None:
        """Arc plus the two bounding radii (a firing-arc wedge)."""
        self.arc(cx, cy, r, start_deg, end_deg, style)
        for deg in (start_deg, end_deg):
            theta = math.radians(deg)
            self.line(cx, cy, cx + r * math.sin(theta), cy - r * math.cos(theta), style)

    def put_text(self, col: int, row: int, text: str, style: str | None = None) -> None:
        """Overlay characters on whole cells; they hide any dots underneath."""
        if not 0 <= row < self.rows:
            return
        for i, ch in enumerate(text):
            c = col + i
            if 0 <= c < self.cols:
                self._text[(c, row)] = (ch, style)

    def render(self) -> list[Text]:
        lines: list[Text] = []
        for row in range(self.rows):
            line = Text()
            for col in range(self.cols):
                overlay = self._text.get((col, row))
                if overlay is not None:
                    ch, style = overlay
                elif bits := self._bits[row][col]:
                    ch, style = chr(_BRAILLE_BASE + bits), self._styles[row][col]
                else:
                    ch, style = " ", None
                line.append(ch, style)
            lines.append(line)
        return lines
