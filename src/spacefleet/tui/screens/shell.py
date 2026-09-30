"""Layout shared by every non-battle screen, matching the battle screen.

::

    ┌ header (1 line) ────────────────────────────┐
    │ #main (1fr)                    │ #side (44) │
    ├────────────────────────────────┴────────────┤
    │ #log (6 lines)                              │
    └ footer (key bindings) ──────────────────────┘

Subclasses override :meth:`compose_main` and :meth:`compose_side`, call
:meth:`set_header` and write player-facing messages with :meth:`write_log`
(:attr:`log_lines` keeps them for tests).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, RichLog, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ShellScreen[ResultType](Screen[ResultType]):
    DEFAULT_CSS = """
    ShellScreen #header { height: 1; background: $primary-background; padding: 0 1; }
    ShellScreen #body { height: 1fr; }
    ShellScreen #main { width: 1fr; height: 1fr; }
    ShellScreen #side { width: 44; height: 1fr; border-left: solid $primary; padding: 0 1; }
    ShellScreen #log { height: 6; border-top: solid $primary; }
    """

    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - Textual's keyword
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static(id="header", markup=False)
        with Horizontal(id="body"):
            with Vertical(id="main"):
                yield from self.compose_main()
            with VerticalScroll(id="side"):
                yield from self.compose_side()
        yield RichLog(id="log", wrap=True, markup=False, max_lines=200, min_width=1)
        yield Footer()

    def compose_main(self) -> ComposeResult:
        yield from ()

    def compose_side(self) -> ComposeResult:
        yield from ()

    def set_header(self, text: str) -> None:
        self.query_one("#header", Static).update(text)

    def write_log(self, line: str) -> None:
        """Append *line* to the message log at the bottom of the screen."""
        self.log_lines.append(line)
        self.query_one("#log", RichLog).write(line)
