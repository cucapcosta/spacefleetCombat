"""Full-screen battle log: every turn so far, with the last turn's report on top.

Keys: arrows / PgUp / PgDn / Home / End (and the mouse wheel) scroll; ``/``
opens a filter that keeps only lines containing the typed text (any case),
with a turn's header kept only when one of its lines matches.  While a
filter is set the report is hidden.  Esc closes the filter first, then the
screen; ``L`` closes the screen from anywhere but the filter box.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from spacefleet.tui.model.turn_report import format_turn_report
from spacefleet.tui.widgets.event_log import turn_separator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from textual.app import ComposeResult

    from spacefleet.tui.model.turn_report import TurnReport


def history_lines(history: Sequence[tuple[int, Sequence[str]]], query: str = "") -> list[str]:
    """Turn headers and their lines; with *query*, only matching lines."""
    needle = query.strip().lower()
    lines: list[str] = []
    for turn, entries in history:
        kept = [line for line in entries if needle in line.lower()]
        if kept or not needle:
            lines.append(turn_separator(turn))
            lines.extend(kept)
    return lines


class LogScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    LogScreen { background: $background; }
    LogScreen > Vertical { width: 1fr; height: 1fr; padding: 0 1; }
    LogScreen #log-title { height: 1; background: $primary-background; padding: 0 1; }
    LogScreen #log-filter { display: none; }
    LogScreen #log-filter.-open { display: block; }
    LogScreen #log-scroll { height: 1fr; }
    LogScreen #log-body { height: auto; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Close"),
        Binding("L", "dismiss", "Close", show=False),
        Binding("slash", "open_filter", "Filter"),
    ]

    def __init__(
        self,
        history: Sequence[tuple[int, Sequence[str]]],
        report: TurnReport | None = None,
    ) -> None:
        super().__init__()
        self.history = history
        self.report = report
        self.query_text = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="log-title", markup=False)
            yield Input(placeholder="Filter (ship name or label)…", id="log-filter")
            with VerticalScroll(id="log-scroll"):
                yield Static(id="log-body", markup=False)

    def on_mount(self) -> None:
        self._refresh_body()
        self.query_one("#log-scroll").focus()

    @property
    def visible_lines(self) -> list[str]:
        """Everything the body shows, top to bottom."""
        lines: list[str] = []
        if self.report is not None and not self.query_text:
            lines.extend(format_turn_report(self.report))
            lines.append("")
        body = history_lines(self.history, self.query_text)
        if not body:
            body = ["No matching lines."] if self.query_text else ["Nothing has happened yet."]
        return lines + body

    def _refresh_body(self) -> None:
        title = "Battle log · / filter · Esc close"
        if self.query_text:
            title += f" · filter: {self.query_text!r}"
        self.query_one("#log-title", Static).update(title)
        self.query_one("#log-body", Static).update("\n".join(self.visible_lines))

    @property
    def filter_open(self) -> bool:
        return self.query_one("#log-filter", Input).has_class("-open")

    def action_open_filter(self) -> None:
        box = self.query_one("#log-filter", Input)
        box.add_class("-open")
        box.focus()

    def action_back(self) -> None:
        if not self.filter_open:
            self.dismiss(None)
            return
        box = self.query_one("#log-filter", Input)
        box.remove_class("-open")
        box.value = ""
        self.query_text = ""
        self._refresh_body()
        self.query_one("#log-scroll").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_text = event.value
        self._refresh_body()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Keep the filter and hand the keys back to scrolling.
        self.query_one("#log-scroll").focus()
