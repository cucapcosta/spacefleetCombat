"""Player fleet status: order marker plus hull / shields / morale bars."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from rich.text import Text
from textual.message import Message
from textual.widget import Widget

from spacefleet.tui.model.timeline import Bars

if TYPE_CHECKING:
    from rich.console import RenderableType
    from textual import events

    from spacefleet.tui.model.snapshot import BattleSnapshot, ShipView

BAR_WIDTH = 10
ROW_HEIGHT = 4  # name line + three bars
_PARTIALS = " ▏▎▍▌▋▊▉"


class ShipSelected(Message):
    def __init__(self, ship_id: str) -> None:
        super().__init__()
        self.ship_id = ship_id


def bar(value: float, maximum: int, width: int = BAR_WIDTH) -> Text:
    """A block bar of *value*/*maximum* in eighths, coloured by ratio."""
    ratio = 0.0 if maximum <= 0 else min(max(value / maximum, 0.0), 1.0)
    eighths = round(ratio * width * 8)
    full, partial = divmod(eighths, 8)
    filled = "█" * full + (_PARTIALS[partial] if partial else "")
    colour = "green" if ratio > 0.6 else "yellow" if ratio > 0.3 else "red"
    text = Text(filled, style=colour)
    text.append("░" * (width - len(filled)), style="grey35")
    return text


def _count(value: float) -> str:
    return str(math.floor(value + 0.5))


class StatusPanel(Widget):
    DEFAULT_CSS = """
    StatusPanel { height: auto; }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - Textual's keyword
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._ships: list[ShipView] = []
        self._ordered: set[str] = set()
        self._bars: dict[str, Bars] = {}
        self._selected: str | None = None

    def set_snapshot(self, snapshot: BattleSnapshot, ordered_ids: set[str]) -> None:
        self._ships = [ship for ship in snapshot.ships if ship.is_player]
        self._ordered = set(ordered_ids)
        self._bars = {ship.id: _snapshot_bars(ship) for ship in self._ships}
        self.refresh(layout=True)

    def set_ordered(self, ordered_ids: set[str]) -> None:
        self._ordered = set(ordered_ids)
        self.refresh()

    def set_bars(self, bars: dict[str, Bars]) -> None:
        """Override bar values (fractional during playback animation)."""
        self._bars.update(bars)
        self.refresh()

    def set_selected(self, ship_id: str | None) -> None:
        self._selected = ship_id
        self.refresh()

    def select_row(self, index: int) -> None:
        if 0 <= index < len(self._ships):
            self.post_message(ShipSelected(self._ships[index].id))

    def plain_text(self) -> str:
        return self._text().plain

    def on_click(self, event: events.Click) -> None:
        self.select_row(event.y // ROW_HEIGHT)

    def render(self) -> RenderableType:
        return self._text()

    def get_content_height(self, container: object, viewport: object, width: int) -> int:
        return max(1, len(self._ships) * ROW_HEIGHT)

    def _text(self) -> Text:
        text = Text()
        for ship in self._ships:
            pointer = "▸" if ship.id == self._selected else " "
            marker = "✓" if ship.id in self._ordered else "·"
            text.append(f"{pointer} {ship.name} ", style="bold" if pointer != " " else "")
            if not ship.alive:
                text.append("✕ destroyed\n\n\n\n", style="dim")
                continue
            text.append(f"[order {marker}]\n", style="green" if marker == "✓" else "dim")
            values = self._bars.get(ship.id)
            if values is None:
                text.append("\n\n\n")
                continue
            for label, value, maximum in (
                ("Hull  ", values.hull, values.hull_max),
                ("Shield", values.shields, values.shields_max),
                ("Morale", values.morale, values.morale_max),
            ):
                text.append(f"  {label} ")
                text.append_text(bar(value, maximum))
                text.append(f" {_count(value)}/{maximum}\n")
        text.rstrip()
        return text


def _snapshot_bars(ship: ShipView) -> Bars:
    return Bars(
        hull=float(ship.hull or 0),
        hull_max=ship.hull_max or 0,
        shields=float(ship.shields or 0),
        shields_max=ship.shields_max or 0,
        morale=float(ship.morale or 0),
        morale_max=ship.morale_max or 0,
    )
