"""Generic modals shared by every screen: yes/no confirmation and a text prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult


class ConfirmScreen(ModalScreen[bool]):
    """Ask a yes/no question; ``y``/Enter on Yes → True, ``n``/Esc → False."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: 64; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    ConfirmScreen #message { height: auto; margin-bottom: 1; }
    ConfirmScreen Horizontal { height: auto; }
    ConfirmScreen Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "choose(True)", "Yes"),
        Binding("escape,n", "choose(False)", "No"),
    ]

    def __init__(self, message: str, yes: str = "Yes", no: str = "No") -> None:
        super().__init__()
        self.message = message
        self.yes = yes
        self.no = no

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.message, id="message", markup=False)
            with Horizontal():
                yield Button(f"{self.yes} [y]", id="yes", variant="primary")
                yield Button(f"{self.no} [Esc]", id="no")

    def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_choose(self, answer: bool) -> None:
        self.dismiss(answer)


class TextInputScreen(ModalScreen[str | None]):
    """Ask for one line of text; Enter submits, Esc → None.

    *validator* returns an error message (shown inline, the modal stays
    open) or None to accept.  The submitted value is stripped.
    """

    DEFAULT_CSS = """
    TextInputScreen { align: center middle; }
    TextInputScreen > Vertical {
        width: 64; height: auto;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    TextInputScreen #label { height: auto; }
    TextInputScreen #error { height: auto; color: $error; }
    TextInputScreen #hint { color: $text-muted; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        label: str,
        default: str = "",
        validator: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self.label = label
        self.default = default
        self.validator = validator

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.label, id="label", markup=False)
            yield Input(value=self.default, id="value")
            yield Static("", id="error", markup=False)
            yield Static("Enter to accept · Esc to cancel", id="hint", markup=False)

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value.strip()
        error = self.validator(value) if self.validator is not None else None
        if error:
            self.query_one("#error", Static).update(error)
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
