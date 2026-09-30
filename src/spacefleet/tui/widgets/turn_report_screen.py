"""Modal end-of-turn report, shown once a turn's playback finishes."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from spacefleet.tui.model.turn_report import format_turn_report

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from spacefleet.tui.model.turn_report import TurnReport


class TurnReportScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    TurnReportScreen { align: center middle; }
    TurnReportScreen > Vertical {
        width: auto; min-width: 60; max-width: 95%; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    TurnReportScreen VerticalScroll { height: auto; max-height: 30; }
    TurnReportScreen #report { width: auto; height: auto; }
    TurnReportScreen #hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        # Priority so the app's own Enter / Space bindings never see the key.
        Binding("enter,escape,space", "dismiss", "Close", priority=True),
    ]

    def __init__(self, report: TurnReport) -> None:
        super().__init__()
        self.report = report

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll():
                yield Static("\n".join(format_turn_report(self.report)), id="report", markup=False)
            yield Static("Enter / Esc / Space to continue", id="hint", markup=False)
