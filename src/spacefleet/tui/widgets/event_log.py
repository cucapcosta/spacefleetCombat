"""Scrolling battle log, capped to the most recent lines.

Long lines wrap to the widget width (re-wrapped when it resizes) instead of
being cut off, and each resolved turn starts with a :func:`turn_separator`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.widgets import RichLog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from textual import events


def turn_separator(turn: int) -> str:
    return f"── Turn {turn} ──"


class EventLog(RichLog):
    MAX_LINES: ClassVar[int] = 200

    DEFAULT_CSS = """
    EventLog { height: 6; }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - Textual's keyword
        classes: str | None = None,
    ) -> None:
        super().__init__(
            max_lines=self.MAX_LINES,
            min_width=1,  # wrap at the widget width, however narrow
            wrap=True,
            markup=False,
            auto_scroll=True,
            name=name,
            id=id,
            classes=classes,
        )
        self.entries: list[str] = []
        self._wrap_width = 0

    def append(self, line: str) -> None:
        self.entries.append(line)
        del self.entries[: -self.MAX_LINES]
        self.write(line, scroll_end=True)

    def set_lines(self, lines: Iterable[str]) -> None:
        self.clear()
        for line in lines:
            self.append(line)

    def clear(self) -> EventLog:
        self.entries = []
        super().clear()
        return self

    def on_resize(self, event: events.Resize) -> None:
        # RichLog's own handler (also dispatched) flushes the first deferred
        # writes; lines already written keep their old wrap, so redo them.
        width = event.size.width
        if self._wrap_width and width != self._wrap_width:
            self.set_lines(list(self.entries))
        self._wrap_width = width
