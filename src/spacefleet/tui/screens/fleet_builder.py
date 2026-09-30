"""Fleet builder: buy hulls, fit them and save/load drafts, with live points.

Free mode (no faction given) opens :class:`FleetSetupScreen` first; campaign
mode receives faction, budget, name and an extra ``validator`` (for example
``campaign.rules.validate_campaign_fleet``) applied to every candidate.

Every change is made on a detached candidate and adopted only when it passes
:func:`validate_candidate`; the reason goes to the log otherwise.  The screen
dismisses with a detached :class:`FleetSpec` (finish) or ``None`` (discard).
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from spacefleet.core.types import Faction
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    apply_default_loadout,
    fleet_points,
    ship_points,
)
from spacefleet.persistence.fleet_save import default_fleet_dir, save_fleet
from spacefleet.tui.model.fleet_builder import (
    BUDGET_ERROR,
    HullOption,
    candidate_error,
    default_save_path,
    faction_label,
    finished_fleet_error,
    fitting_preview,
    hull_details,
    hull_options,
    load_draft,
    parse_budget,
    unique_ship_name,
    validate_candidate,
    with_ship_added,
    with_ship_replaced,
    without_ship,
)
from spacefleet.tui.model.ship_art import render_art
from spacefleet.tui.screens.shell import ShellScreen
from spacefleet.tui.widgets.confirm import ConfirmScreen, TextInputScreen
from spacefleet.tui.widgets.hangar_view import HangarEntry, HangarView
from spacefleet.tui.widgets.ship_panel import ShipPanel

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from spacefleet.models.fleet_spec import ShipSpec
    from spacefleet.tui.model.fitting import FittingChoice

DEFAULT_BUDGET = 1000
DEFAULT_NAME = "My Fleet"
EMPTY_HINT = "Press a to add a ship."

FleetSetup = tuple[Faction, int, str]


class FleetSetupScreen(ModalScreen[FleetSetup | None]):
    """Free-mode form: faction, points budget and fleet name (Esc → None)."""

    DEFAULT_CSS = """
    FleetSetupScreen { align: center middle; }
    FleetSetupScreen > Vertical {
        width: 64; height: auto;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    FleetSetupScreen .label { height: auto; margin-top: 1; }
    FleetSetupScreen #error { height: auto; color: $error; }
    FleetSetupScreen Horizontal { height: auto; margin-top: 1; }
    FleetSetupScreen Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("New fleet", markup=False)
            yield Static("Faction", classes="label", markup=False)
            yield Select(
                [(faction_label(member), member) for member in Faction],
                value=Faction.IMPERIAL_NAVY,
                allow_blank=False,
                id="faction",
            )
            yield Static("Points budget", classes="label", markup=False)
            yield Input(value=str(DEFAULT_BUDGET), id="budget")
            yield Static("Fleet name", classes="label", markup=False)
            yield Input(value=DEFAULT_NAME, id="name")
            yield Static("", id="error", markup=False)
            with Horizontal():
                yield Button("Build [Enter]", id="ok", variant="primary")
                yield Button("Cancel [Esc]", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#budget", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self.submit()
        else:
            self.dismiss(None)

    def submit(self) -> None:
        error = self.query_one("#error", Static)
        budget = parse_budget(self.query_one("#budget", Input).value)
        if budget is None:
            error.update(BUDGET_ERROR)
            return
        name = self.query_one("#name", Input).value.strip()
        if not name:
            error.update("Fleet name cannot be empty.")
            return
        faction = self.query_one("#faction", Select).value
        assert isinstance(faction, Faction)
        self.dismiss((faction, budget, name))

    def action_cancel(self) -> None:
        self.dismiss(None)


class HullPickerScreen(ModalScreen[str | None]):
    """Pick a hull to add; the highlighted hull's art and stats are shown.

    Unaffordable hulls are listed with their reason and cannot be picked.
    """

    DEFAULT_CSS = """
    HullPickerScreen { align: center middle; }
    HullPickerScreen > Vertical {
        width: 80; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    HullPickerScreen #hulls { height: auto; max-height: 14; }
    HullPickerScreen #art { height: auto; margin-top: 1; }
    HullPickerScreen #details { height: auto; color: $text-muted; }
    HullPickerScreen #error { height: auto; color: $error; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, options: list[HullOption], remaining: int) -> None:
        super().__init__()
        self.hull_choices = options
        self.remaining = remaining

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"Add ship · {self.remaining} pts remaining", markup=False)
            yield OptionList(
                *(self._option(option) for option in self.hull_choices),
                id="hulls",
            )
            yield Static("", id="art")
            yield Static("", id="details", markup=False)
            yield Static("", id="error", markup=False)

    @staticmethod
    def _option(option: HullOption) -> Option:
        hull = option.hull
        label = Text()
        style = "dim" if option.reason else ""
        label.append(f"{hull.name:34s} {hull.hull_cost:4d} pts", style=style)
        if option.reason:
            label.append(f"  ✗ {option.reason}", style="red")
        return Option(label, id=hull.id)

    def on_mount(self) -> None:
        hulls = self.query_one("#hulls", OptionList)
        hulls.focus()
        if self.hull_choices:
            hulls.highlighted = 0
            self._show(0)
        else:
            self.query_one("#details", Static).update("No hull can join this fleet.")

    def _show(self, index: int | None) -> None:
        if index is None or not 0 <= index < len(self.hull_choices):
            return
        hull = self.hull_choices[index].hull
        self.query_one("#art", Static).update(Text("\n").join(render_art(hull)))
        self.query_one("#details", Static).update(hull_details(hull))
        self.query_one("#error", Static).update("")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._show(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        option = self.hull_choices[event.option_index]
        if option.reason is not None:
            self.query_one("#error", Static).update(option.reason)
            return
        self.dismiss(option.hull.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FleetBuilderScreen(ShellScreen[FleetSpec | None]):
    """Build a fleet within a points budget; dismisses with the fleet or ``None``."""

    DEFAULT_CSS = """
    FleetBuilderScreen #empty { color: $text-muted; padding: 1 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("a", "add_ship", "Add"),
        Binding("left", "ship(-1)", "Ship", show=False),
        Binding("right", "ship(1)", "Ship", show=False),
        Binding("f", "flagship", "Flagship"),
        Binding("x", "remove_ship", "Remove"),
        Binding("o", "default_loadout", "Default kit"),
        Binding("s", "save", "Save"),
        Binding("l", "load", "Load"),
        Binding("d", "done", "Done"),
        Binding("escape", "discard", "Discard"),
    ]

    def __init__(
        self,
        *,
        faction: Faction | None = None,
        budget: int | None = None,
        name: str | None = None,
        validator: Callable[[FleetSpec], None] | None = None,
    ) -> None:
        super().__init__()
        self.budget = budget if budget is not None else DEFAULT_BUDGET
        self.validator = validator
        self._needs_setup = faction is None
        self.fleet = FleetSpec(
            name=name if name is not None else DEFAULT_NAME,
            faction=faction if faction is not None else Faction.IMPERIAL_NAVY,
            ships=[],
        )
        self.selected = 0

    # ---------------------------------------------------------------- layout

    def compose_main(self) -> ComposeResult:
        yield HangarView(id="hangar")
        yield Static(EMPTY_HINT, id="empty", markup=False)

    def compose_side(self) -> ComposeResult:
        yield ShipPanel(id="panel")

    def on_mount(self) -> None:
        self.refresh_view()
        self.query_one(ShipPanel).focus()
        if self._needs_setup:
            self.app.push_screen(FleetSetupScreen(), self._on_setup)

    def _on_setup(self, setup: FleetSetup | None) -> None:
        if setup is None:
            self.dismiss(None)
            return
        faction, budget, name = setup
        self._needs_setup = False
        self.budget = budget
        self.fleet = FleetSpec(name=name, faction=faction, ships=[])
        self.refresh_view()

    @property
    def used_points(self) -> int:
        return fleet_points(self.fleet)

    def header_text(self) -> str:
        used = self.used_points
        return (
            f"Fleet Builder · {faction_label(self.fleet.faction)} · {self.fleet.name} · "
            f"{used} / {self.budget} pts · {self.budget - used} remaining"
        )

    def refresh_view(self) -> None:
        """Redraw header, hangar and ship panel from the current draft."""
        self.set_header(self.header_text())
        ships = self.fleet.ships
        self.selected = min(max(self.selected, 0), max(len(ships) - 1, 0))
        view = self.query_one(HangarView)
        view.set_entries(
            [
                HangarEntry(
                    HullRegistry.get(ship.hull_id),
                    ship.name,
                    flagship=index == self.fleet.flagship_index,
                )
                for index, ship in enumerate(ships)
            ],
            selected=self.selected,
        )
        view.display = bool(ships)
        self.query_one("#empty", Static).display = not ships
        self._refresh_panel()

    def _refresh_panel(self) -> None:
        panel = self.query_one(ShipPanel)
        if not self.fleet.ships:
            panel.set_ship(None, self.fleet.faction, is_flagship=False, preview=_no_preview)
            return
        index = self.selected
        ship = self.fleet.ships[index]
        hull = HullRegistry.get(ship.hull_id)
        panel.set_ship(
            ship,
            self.fleet.faction,
            is_flagship=index == self.fleet.flagship_index,
            header_lines=(
                f"{hull.classification.value.replace('_', ' ').title()} · {ship_points(ship)} pts",
                f"Speed {hull.speed:g} · Hull {hull.hull_hits} · Shields {hull.shields}",
            ),
            candidate_validator=self._ship_validator(index),
            preview=self._preview(index),
        )

    def _ship_validator(self, index: int) -> Callable[[ShipSpec], None]:
        def validate(replacement: ShipSpec) -> None:
            validate_candidate(
                with_ship_replaced(self.fleet, index, replacement), None, self.validator
            )

        return validate

    def _preview(self, index: int) -> Callable[[FittingChoice], tuple[str, str | None]]:
        def preview(choice: FittingChoice) -> tuple[str, str | None]:
            return fitting_preview(
                self.fleet, index, choice.replacement, self.budget, self.validator
            )

        return preview

    # --------------------------------------------------------------- helpers

    def adopt(self, candidate: FleetSpec, message: str) -> bool:
        """Make *candidate* the draft when valid; log *message* or the error."""
        error = candidate_error(candidate, self.budget, self.validator)
        if error is not None:
            self.write_log(error)
            return False
        self.fleet = candidate
        self.refresh_view()
        self.write_log(message)
        return True

    def _current(self) -> ShipSpec | None:
        if not self.fleet.ships:
            self.write_log("No ship selected. " + EMPTY_HINT)
            return None
        return self.fleet.ships[self.selected]

    # ----------------------------------------------------------- ship choice

    def action_ship(self, step: int) -> None:
        self.query_one(HangarView).action_move(step)

    def on_hangar_view_selection_changed(self, event: HangarView.SelectionChanged) -> None:
        event.stop()
        self.selected = event.index
        self._refresh_panel()

    # --------------------------------------------------------------- fitting

    def on_ship_panel_fitting_chosen(self, event: ShipPanel.FittingChosen) -> None:
        event.stop()
        if not self.fleet.ships:
            return
        index = self.selected
        before = ship_points(self.fleet.ships[index])
        delta = ship_points(event.choice.replacement) - before
        candidate = with_ship_replaced(self.fleet, index, event.choice.replacement)
        self.adopt(
            candidate,
            f"{self.fleet.ships[index].name}: {event.slot.label} → {event.choice.label} "
            f"({delta:+} pts, {fleet_points(candidate)} / {self.budget}).",
        )

    # ------------------------------------------------------------------ add

    def action_add_ship(self) -> None:
        options = hull_options(self.fleet, self.budget, self.validator)
        remaining = self.budget - self.used_points
        self.app.push_screen(HullPickerScreen(options, remaining), self._on_hull_picked)

    def _on_hull_picked(self, hull_id: str | None) -> None:
        if hull_id is None:
            return
        hull = HullRegistry.get(hull_id)
        used = {ship.name for ship in self.fleet.ships}

        def check(value: str) -> str | None:
            if not value:
                return "Ship name cannot be empty."
            if value in used:
                return f"A ship named {value!r} is already in the fleet."
            return None

        def named(name: str | None) -> None:
            if name is None:
                return
            candidate = with_ship_added(self.fleet, hull_id, name)
            if self.adopt(
                candidate,
                f"Added {name} ({hull.name}, {hull.hull_cost} pts). "
                f"{self.budget - fleet_points(candidate)} pts remaining.",
            ):
                self.selected = len(self.fleet.ships) - 1
                self.refresh_view()

        default = unique_ship_name(self.fleet, hull.name)
        self.app.push_screen(TextInputScreen("Ship name", default, check), named)

    # ------------------------------------------------------- ship commands

    def action_flagship(self) -> None:
        ship = self._current()
        if ship is None:
            return
        if self.selected == self.fleet.flagship_index:
            self.write_log(f"{ship.name} is already the flagship.")
            return
        candidate = deepcopy(self.fleet)
        candidate.flagship_index = self.selected
        self.adopt(candidate, f"{ship.name} is now the flagship.")

    def action_remove_ship(self) -> None:
        ship = self._current()
        if ship is None:
            return
        index = self.selected

        def answer(yes: bool | None) -> None:
            if not yes:
                return
            candidate = without_ship(self.fleet, index)
            self.adopt(
                candidate,
                f"Removed {ship.name}. {self.budget - fleet_points(candidate)} pts remaining.",
            )

        self.app.push_screen(ConfirmScreen(f"Remove {ship.name}?"), answer)

    def action_default_loadout(self) -> None:
        ship = self._current()
        if ship is None:
            return
        candidate = deepcopy(self.fleet)
        apply_default_loadout(candidate.ships[self.selected])
        points = ship_points(candidate.ships[self.selected])
        self.adopt(candidate, f"Applied the default loadout to {ship.name} ({points} pts).")

    # ------------------------------------------------------------ save/load

    def action_save(self) -> None:
        def check(value: str) -> str | None:
            return None if value else "Enter a file path."

        default = str(default_save_path(self.fleet.name))
        self.app.push_screen(TextInputScreen("Save path", default, check), self._on_save_path)

    def _on_save_path(self, raw: str | None) -> None:
        if raw is None:
            return
        path = Path(raw).expanduser()

        def write(yes: bool | None = True) -> None:
            if not yes:
                return
            try:
                written = save_fleet(deepcopy(self.fleet), path)
            except OSError as exc:
                self.write_log(f"save failed: {exc}")
                return
            self.write_log(f"Saved to {written}")

        if path.exists():
            self.app.push_screen(ConfirmScreen(f"Replace {path}?"), write)
        else:
            write()

    def action_load(self) -> None:
        def check(value: str) -> str | None:
            return None if value else "Enter a file path."

        default = str(default_fleet_dir()) + "/"
        self.app.push_screen(TextInputScreen("Load path", default, check), self._on_load_path)

    def _on_load_path(self, raw: str | None) -> None:
        if raw is None:
            return
        path = Path(raw).expanduser()

        def load(yes: bool | None = True) -> None:
            if not yes:
                return
            try:
                loaded = load_draft(path, self.fleet.faction, self.budget, self.validator)
            except (FleetSpecError, ValueError, KeyError) as exc:
                self.write_log(str(exc))
                return
            self.fleet = loaded
            self.selected = 0
            self.refresh_view()
            self.write_log(f"Loaded '{loaded.name}' from {path}.")

        if self.fleet.ships:
            self.app.push_screen(ConfirmScreen("Replace the current fleet draft?"), load)
        else:
            load()

    # -------------------------------------------------------------- finish

    def action_done(self) -> None:
        error = finished_fleet_error(self.fleet, self.budget, self.validator)
        if error is not None:
            self.write_log(error)
            return

        def answer(yes: bool | None) -> None:
            if yes:
                self.dismiss(deepcopy(self.fleet))

        self.app.push_screen(ConfirmScreen("Finish this fleet?"), answer)

    def action_discard(self) -> None:
        def answer(yes: bool | None) -> None:
            if yes:
                self.dismiss(None)

        self.app.push_screen(ConfirmScreen("Discard this fleet draft?"), answer)


def _no_preview(_choice: FittingChoice) -> tuple[str, str | None]:
    return "", None
