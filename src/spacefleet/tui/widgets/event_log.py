"""Scrolling battle log, capped to the most recent lines."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.widgets import RichLog

if TYPE_CHECKING:
    from collections.abc import Iterable


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
            wrap=True,
            markup=False,
            auto_scroll=True,
            name=name,
            id=id,
            classes=classes,
        )
        self.entries: list[str] = []

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
