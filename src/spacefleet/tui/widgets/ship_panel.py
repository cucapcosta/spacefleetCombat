"""Right-column ship panel shared by the hangar and the fleet builder.

The panel shows one ship: its name and hull class, any header lines the screen
supplies (hull bar, damage, battles, points...), then the configurable slots.
``Enter`` on a slot opens its options (:func:`slot_choices`), each priced by
the screen's ``preview`` callable -- credits in the campaign, points in the
fleet builder -- with the reason inline when the option is unavailable.
Picking an available option posts :class:`ShipPanel.FittingChosen`; the panel
never changes the ship itself.

``Esc`` only belongs to the panel while options are open; in slots mode it
bubbles to the screen (usually "back").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.widget import Widget

from spacefleet.data.hull_registry import HullRegistry
from spacefleet.tui.model.fitting import FittingChoice, Slot, ship_slots, slot_choices

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rich.console import RenderableType

    from spacefleet.core.types import Faction
    from spacefleet.models.fleet_spec import ShipSpec

PanelMode = Literal["slots", "options"]

MAX_WIDTH = 42
CURSOR = "▸ "
BLANK = "  "


def _fit(text: str, width: int) -> str:
    """*text* cut to *width* columns, ending with an ellipsis when cut."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _no_preview(_choice: FittingChoice) -> tuple[str, str | None]:
    return "", None


class ShipPanel(Widget, can_focus=True):
    """Slot list and fitting options for one ship."""

    DEFAULT_CSS = """
    ShipPanel { height: auto; padding: 0 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "cursor(-1)", "Up", show=False),
        Binding("down", "cursor(1)", "Down", show=False),
        Binding("enter", "select", "Options"),
        Binding("escape", "back", "Slots"),
    ]

    class FittingChosen(Message):
        """The player picked an available *choice* for *slot*."""

        def __init__(self, panel: ShipPanel, slot: Slot, choice: FittingChoice) -> None:
            super().__init__()
            self.panel = panel
            self.slot = slot
            self.choice = choice

        @property
        def control(self) -> ShipPanel:
            return self.panel

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - Textual's keyword
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._spec: ShipSpec | None = None
        self._faction: Faction | None = None
        self._is_flagship = False
        self._header_lines: tuple[str | Text, ...] = ()
        self._candidate_validator: Callable[[ShipSpec], None] | None = None
        self._preview: Callable[[FittingChoice], tuple[str, str | None]] = _no_preview
        self._mode: PanelMode = "slots"
        self._slots: list[Slot] = []
        self._slot_index = 0
        self._options: list[FittingChoice] = []
        self._previews: list[tuple[str, str | None]] = []
        self._option_index = 0

    # ------------------------------------------------------------------ state

    def set_ship(
        self,
        spec: ShipSpec | None,
        faction: Faction,
        *,
        is_flagship: bool,
        header_lines: Sequence[str | Text] = (),
        candidate_validator: Callable[[ShipSpec], None] | None = None,
        preview: Callable[[FittingChoice], tuple[str, str | None]],
    ) -> None:
        """Show *spec* in slots mode, keeping the slot cursor where possible."""
        self._spec = spec
        self._faction = faction
        self._is_flagship = is_flagship
        self._header_lines = tuple(header_lines)
        self._candidate_validator = candidate_validator
        self._preview = preview
        self._slots = [] if spec is None else ship_slots(spec)
        self._slot_index = min(self._slot_index, max(len(self._slots) - 1, 0))
        self._close_options()
        self.refresh(layout=True)

    @property
    def mode(self) -> PanelMode:
        return self._mode

    @property
    def slots(self) -> list[Slot]:
        return list(self._slots)

    @property
    def slot_index(self) -> int:
        return self._slot_index

    @property
    def options(self) -> list[FittingChoice]:
        return list(self._options)

    @property
    def option_index(self) -> int:
        return self._option_index

    @property
    def current_slot(self) -> Slot | None:
        if not self._slots:
            return None
        return self._slots[self._slot_index]

    @property
    def current_option(self) -> FittingChoice | None:
        if self._mode != "options" or not self._options:
            return None
        return self._options[self._option_index]

    def _close_options(self) -> None:
        self._mode = "slots"
        self._options = []
        self._previews = []
        self._option_index = 0

    def _open_options(self) -> None:
        slot = self.current_slot
        if slot is None or self._spec is None or self._faction is None:
            return
        self._options = slot_choices(
            self._spec,
            self._faction,
            slot,
            is_flagship=self._is_flagship,
            candidate_validator=self._candidate_validator,
        )
        self._previews = [self._preview(choice) for choice in self._options]
        self._option_index = 0
        self._mode = "options"

    # ---------------------------------------------------------------- actions

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Esc must bubble to the screen while the slot list is showing.
        if action == "back":
            return self._mode == "options"
        return True

    def action_cursor(self, step: int) -> None:
        if self._mode == "options":
            if self._options:
                self._option_index = (self._option_index + step) % len(self._options)
        elif self._slots:
            self._slot_index = (self._slot_index + step) % len(self._slots)
        self.refresh(layout=True)

    def action_select(self) -> None:
        if self._mode == "slots":
            self._open_options()
            self.refresh(layout=True)
            return
        if not self._options:
            return
        slot = self.current_slot
        choice = self._options[self._option_index]
        _cost, reason = self._previews[self._option_index]
        if reason is not None:
            self.notify(reason, severity="warning")
            return
        assert slot is not None
        self._close_options()
        self.refresh(layout=True)
        self.post_message(self.FittingChosen(self, slot, choice))

    def action_back(self) -> None:
        self._close_options()
        self.refresh(layout=True)

    # ----------------------------------------------------------------- render

    def _width(self) -> int:
        inner = self.content_size.width
        return min(MAX_WIDTH, inner) if inner > 0 else MAX_WIDTH

    def render(self) -> RenderableType:
        width = self._width()
        text = Text(no_wrap=False, overflow="fold")
        if self._spec is None:
            text.append("No ship selected", style="dim")
            return text
        title = self._spec.name + (" ★" if self._is_flagship else "")
        text.append(_fit(title, width), style="bold")
        hull = HullRegistry.get_or_none(self._spec.hull_id)
        text.append("\n" + _fit(hull.name if hull else self._spec.hull_id, width), style="dim")
        for line in self._header_lines:
            text.append("\n")
            if isinstance(line, Text):
                piece = line.copy()
                piece.truncate(width, overflow="ellipsis")
                text.append_text(piece)
            else:
                text.append(_fit(line, width))
        text.append("\n")
        if self._mode == "slots":
            self._render_slots(text, width)
        else:
            self._render_options(text, width)
        return text

    def _render_slots(self, text: Text, width: int) -> None:
        text.append("\nSlots", style="bold underline")
        for index, slot in enumerate(self._slots):
            selected = index == self._slot_index and self.has_focus
            marker = CURSOR if index == self._slot_index else BLANK
            style = "bold reverse" if selected else "bold" if index == self._slot_index else ""
            text.append("\n" + marker, style="bold cyan")
            text.append(_fit(slot.label, width - len(marker)), style=style)
            current_style = "dim" if slot.current in ("Empty", "None") else "green"
            text.append("\n    " + _fit(slot.current, width - 4), style=current_style)
        text.append("\n\n" + _fit("↑/↓ slot  enter options", width), style="dim")

    def _render_options(self, text: Text, width: int) -> None:
        slot = self.current_slot
        assert slot is not None
        text.append("\n" + _fit(f"Options for {slot.label}", width), style="bold underline")
        if not self._options:
            text.append("\nNo fitting available", style="dim")
        for index, choice in enumerate(self._options):
            cost, reason = self._previews[index]
            here = index == self._option_index
            marker = CURSOR if here else BLANK
            label_width = width - len(marker) - (len(cost) + 1 if cost else 0)
            label = _fit(choice.label, max(label_width, 4))
            gap = max(width - len(marker) - len(label) - len(cost), 1) if cost else 0
            label_style = "dim" if reason is not None else "bold" if here else ""
            text.append("\n" + marker, style="bold cyan")
            text.append(label, style=label_style)
            if cost:
                cost_style = "dim red" if reason is not None else "yellow"
                text.append(" " * gap + _fit(cost, width - len(marker) - 1), style=cost_style)
            if reason is not None:
                text.append("\n    " + _fit(f"✗ {reason}", width - 4), style="red")
        current = self.current_option
        if current is not None and current.details:
            text.append("\n")
            for line in current.details.splitlines():
                text.append("\n" + line, style="dim")
        text.append("\n\n" + _fit("↑/↓ choose  enter fit  esc slots", width), style="dim")

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()
