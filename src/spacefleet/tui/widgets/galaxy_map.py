"""Braille galaxy map showing the campaign route and the fleet's position."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget

from spacefleet.campaign.models import CampaignStatus
from spacefleet.core.types import Faction
from spacefleet.tui.model.galaxy import MARKERS, node_states
from spacefleet.tui.model.raster import BrailleCanvas

if TYPE_CHECKING:
    from textual.app import RenderResult

    from spacefleet.tui.model.galaxy import Galaxy

MIN_WIDTH = 20
MIN_HEIGHT = 5

_NEXT_STYLE = {
    Faction.IMPERIAL_NAVY: "bold bright_cyan",
    Faction.CHAOS_FLEET: "bold bright_red",
}
_STATE_STYLE = {
    "cleared": "green",
    "current": "bold bright_white",
    "next": "bold yellow",
    "unknown": "dim",
    "final": "magenta",
    "defeated": "bold red",
}
_LABEL_STYLE = {
    "cleared": "green",
    "current": "bold bright_white",
    "unknown": "dim",
    "final": "magenta",
    "defeated": "red",
}
_BANNERS = {
    CampaignStatus.COMPLETED: ("COMPLETED", "bold green"),
    CampaignStatus.DEFEATED: ("DEFEATED", "bold red"),
}
_STAR_STYLE = "dim"
_CLEARED_LEG_STYLE = "green"
_FUTURE_LEG_STYLE = "dim"


class GalaxyMap(Widget):
    """Route of the campaign across a seeded sector of space."""

    DEFAULT_CSS = """
    GalaxyMap {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._galaxy: Galaxy | None = None
        self._encounter = 1
        self._status = CampaignStatus.ACTIVE
        self._enemy: Faction | None = None

    def set_state(
        self,
        galaxy: Galaxy,
        encounter: int,
        status: CampaignStatus,
        enemy_faction: Faction | None,
    ) -> None:
        self._galaxy = galaxy
        self._encounter = encounter
        self._status = status
        self._enemy = enemy_faction
        self.refresh()

    def render(self) -> RenderResult:
        return Text("\n").join(self.render_text_lines(self.size.width, self.size.height))

    def render_text_lines(self, width: int, height: int) -> list[Text]:
        galaxy = self._galaxy
        height = max(1, height)
        if width <= 0:
            return [Text() for _ in range(height)]
        if galaxy is None:
            return [Text(" " * width) for _ in range(height)]
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            heading = Text(f"✦ {galaxy.sector_name}"[:width], style="bold")
            return [heading] + [Text() for _ in range(height - 1)]

        canvas = BrailleCanvas(width, height)
        states = node_states(self._encounter, self._status, len(galaxy.nodes))
        cells = [
            (round(node.x * (width - 1)), round(node.y * (height - 1))) for node in galaxy.nodes
        ]

        # Route legs, as braille lines from cell centre to cell centre.
        route_cells: set[tuple[int, int]] = set()
        for i in range(len(cells) - 1):
            (c0, r0), (c1, r1) = cells[i], cells[i + 1]
            x0, y0, x1, y1 = c0 * 2 + 1, r0 * 4 + 2, c1 * 2 + 1, r1 * 4 + 2
            cleared = states[i + 1] in ("cleared", "current")
            canvas.line(
                x0,
                y0,
                x1,
                y1,
                _CLEARED_LEG_STYLE if cleared else _FUTURE_LEG_STYLE,
                dashed=not cleared,
            )
            steps = max(abs(x1 - x0), abs(y1 - y0), 1)
            for s in range(steps + 1):
                t = s / steps
                route_cells.add((int((x0 + (x1 - x0) * t) // 2), int((y0 + (y1 - y0) * t) // 4)))

        # Background stars, kept off the route so they do not hide it.
        for sx, sy in galaxy.stars:
            cell = (round(sx * (width - 1)), round(sy * (height - 1)))
            if cell not in route_cells:
                canvas.put_text(cell[0], cell[1], "·", _STAR_STYLE)

        # Labels first, then markers on top so a long label never hides one.
        marker_cells = set(cells)
        for (col, row), node, state in zip(cells, galaxy.nodes, states, strict=True):
            label = self._label(node.name, state)
            if not label:
                continue
            # One blank cell between marker and name keeps the route legible.
            label = f" {label} "
            start = col + 1
            if start + len(label) > width:
                start = max(0, col - len(label))
            # Stop short of another node's marker on the same row.
            text = ""
            for i, ch in enumerate(label):
                if (start + i, row) in marker_cells or start + i >= width:
                    break
                text += ch
            canvas.put_text(start, row, text, self._label_style(state))
        for (col, row), state in zip(cells, states, strict=True):
            canvas.put_text(col, row, MARKERS[state], self._marker_style(state))

        title = f"✦ {galaxy.sector_name}"
        canvas.put_text(1, 0, " " + title + " ", "bold")
        banner = _BANNERS.get(self._status)
        if banner is not None:
            text, style = banner
            canvas.put_text(max(0, width - len(text) - 3), 0, f" {text} ", style)
        return canvas.render()

    @staticmethod
    def _label(name: str, state: str) -> str:
        if state == "current":
            return "YOU"
        if state == "unknown":
            return ""
        return name

    def _marker_style(self, state: str) -> str:
        if state == "next" and self._enemy is not None:
            return _NEXT_STYLE[self._enemy]
        return _STATE_STYLE[state]

    def _label_style(self, state: str) -> str:
        if state == "next":
            return self._marker_style(state)
        return _LABEL_STYLE[state]
