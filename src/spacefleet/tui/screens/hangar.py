"""Hangar and shipyard: refit, flagship, discard, repair and buy campaign ships.

The screen works on its own copy of the campaign.  Every change is priced as a
detached candidate by :mod:`spacefleet.tui.model.campaign_ops`, confirmed with
a preview that includes the resulting credits, then adopted and autosaved.
``Esc`` dismisses with the current campaign.

Modes:

* **Hangar** -- main: the roster side by side (``HangarView``); side: the
  selected ship (``ShipPanel``).  ``←/→`` ship, ``↑/↓``/``Enter`` slots and
  fitting options, ``f`` flagship, ``x`` discard, ``r`` repair this ship,
  ``y`` shipyard, ``Esc`` back.
* **Shipyard** -- main: the highlighted hull's art and stats; side: every
  buyable hull with its cost and preview (unaffordable ones stay listed so
  their art can be browsed; ``Enter`` on them only logs the reason).
  ``Enter`` asks for a name and confirms the purchase, then returns to the
  hangar with the new ship selected.  ``h`` returns to the hangar; ``Esc``
  does too, unless the screen was opened directly in shipyard mode, in which
  case ``Esc`` dismisses the screen (back to where the player came from).
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, ClassVar, Literal

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from spacefleet.campaign.economy import CampaignEconomyError, discard_ship, set_flagship
from spacefleet.campaign.models import CampaignStatus
from spacefleet.campaign.rules import _ship_hull_max
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.models.fleet_spec import ShipSpec
from spacefleet.tui.model.campaign_ops import (
    autosave,
    credit_change,
    hull_offers,
    quote_buy,
    quote_refit,
    quote_repair_ship,
    refit_validator,
    unique_ship_name,
)
from spacefleet.tui.screens.shell import ShellScreen
from spacefleet.tui.widgets.confirm import ConfirmScreen, TextInputScreen
from spacefleet.tui.widgets.hangar_view import HangarEntry, HangarView
from spacefleet.tui.widgets.ship_panel import ShipPanel

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from textual.app import ComposeResult

    from spacefleet.campaign.models import CampaignShip, CampaignState
    from spacefleet.models.ship_profile import HullProfile
    from spacefleet.tui.model.campaign_ops import HullOffer
    from spacefleet.tui.model.fitting import FittingChoice

HangarMode = Literal["hangar", "shipyard"]

BAR_WIDTH = 10


def cost_text(charge: int, balance: int) -> str:
    """Compact option price: ``−40 → 120 cr``, ``+12 → 172 cr`` or ``0 → 160 cr``."""
    if charge > 0:
        return f"−{charge} → {balance} cr"
    if charge < 0:
        return f"+{-charge} → {balance} cr"
    return f"0 → {balance} cr"


def hull_bar(damage: int, hull_max: int) -> Text:
    remaining = max(hull_max - damage, 0)
    filled = round(BAR_WIDTH * remaining / hull_max) if hull_max > 0 else 0
    ratio = remaining / hull_max if hull_max > 0 else 0.0
    color = "green" if ratio > 0.66 else "yellow" if ratio > 0.33 else "red"
    text = Text("Hull ")
    text.append("█" * filled, style=color)
    text.append("░" * (BAR_WIDTH - filled), style="dim")
    text.append(f" {remaining}/{hull_max}")
    return text


def hull_stats(hull: HullProfile, offer: HullOffer | None = None) -> Text:
    """Player-facing summary of one hull for the shipyard."""
    text = Text()
    text.append(hull.name, style="bold")
    text.append(f"\nClass {hull.classification.value.replace('_', ' ')}")
    text.append(f" · cost {hull.hull_cost} credits")
    text.append(f"\nSpeed {hull.speed:g} · Turn {hull.turn_rate:g}°")
    text.append(f"\nHull {hull.hull_hits} · Shields {hull.shields} · Turrets {hull.turrets}")
    text.append(
        f"\nArmor prow {hull.armor_prow} · port {hull.armor_port} · "
        f"stbd {hull.armor_starboard} · stern {hull.armor_stern}"
    )
    text.append(f"\nWeapon slots {len(hull.weapon_slots)}")
    for slot in hull.weapon_slots:
        text.append(f"\n  {slot.name} · {slot.arc.value} · {slot.size.value}", style="dim")
    if offer is not None:
        text.append(f"\n\n{offer.quote.preview}")
        if offer.quote.reason is not None:
            text.append(f"\n✗ {offer.quote.reason}", style="red")
    return text


def _slot_name(label: str) -> str:
    return label.split(" · ", 1)[0]


class HangarScreen(ShellScreen["CampaignState"]):
    DEFAULT_CSS = """
    HangarScreen #yard-art { height: auto; }
    HangarScreen #yard-stats { height: auto; padding: 1 1 0 1; }
    HangarScreen #offers { height: auto; max-height: 100%; border: none; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "ship(-1)", "Ship", key_display="←"),
        Binding("right", "ship(1)", "Ship", key_display="→", show=False),
        Binding("f", "flagship", "Flagship"),
        Binding("x", "discard", "Discard"),
        Binding("r", "repair", "Repair"),
        Binding("y", "shipyard", "Shipyard"),
        Binding("h", "hangar", "Hangar"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, campaign: CampaignState, path: Path, *, shipyard: bool = False) -> None:
        super().__init__()
        self.campaign = deepcopy(campaign)
        self.path = path
        self.mode: HangarMode = "shipyard" if shipyard else "hangar"
        self._opened_in_shipyard = shipyard
        self._selected_id: str | None = campaign.roster[0].id if campaign.roster else None
        self._offers: list[HullOffer] = []

    # ---------------------------------------------------------------- compose

    def compose_main(self) -> ComposeResult:
        yield HangarView(id="roster")
        yield HangarView(id="yard-art")
        yield Static(id="yard-stats")

    def compose_side(self) -> ComposeResult:
        yield ShipPanel(id="panel")
        yield OptionList(id="offers")

    def on_mount(self) -> None:
        self._refresh()
        self._apply_mode()

    # ------------------------------------------------------------------ state

    @property
    def selected_ship(self) -> CampaignShip | None:
        for ship in self.campaign.roster:
            if ship.id == self._selected_id:
                return ship
        return None

    def _selected_index(self) -> int:
        for index, ship in enumerate(self.campaign.roster):
            if ship.id == self._selected_id:
                return index
        return 0

    def _refresh(self) -> None:
        if self.selected_ship is None:
            self._selected_id = self.campaign.roster[0].id if self.campaign.roster else None
        title = "Shipyard" if self.mode == "shipyard" else "Hangar"
        self.set_header(f"{title} · Credits {self.campaign.credits}")
        entries = [
            HangarEntry(
                HullRegistry.get(ship.spec.hull_id),
                ship.spec.name,
                damage_ratio=ship.hull_damage / max(_ship_hull_max(ship.spec), 1),
                flagship=ship.id == self.campaign.flagship_id,
            )
            for ship in self.campaign.roster
        ]
        self.query_one("#roster", HangarView).set_entries(entries, self._selected_index())
        self._refresh_panel()
        self._refresh_offers()

    def _refresh_panel(self) -> None:
        panel = self.query_one("#panel", ShipPanel)
        ship = self.selected_ship
        if ship is None:
            panel.set_ship(None, self.campaign.faction, is_flagship=False, preview=_no_cost)
            return
        hull_max = _ship_hull_max(ship.spec)
        panel.set_ship(
            ship.spec,
            self.campaign.faction,
            is_flagship=ship.id == self.campaign.flagship_id,
            header_lines=[
                hull_bar(ship.hull_damage, hull_max),
                f"Damage {ship.hull_damage}/{hull_max} · Battles survived {ship.battles_survived}",
            ],
            candidate_validator=refit_validator(self.campaign, ship.id),
            preview=self._refit_preview(ship.id),
        )

    def _refit_preview(self, ship_id: str) -> Callable[[FittingChoice], tuple[str, str | None]]:
        def preview(choice: FittingChoice) -> tuple[str, str | None]:
            try:
                quote = quote_refit(self.campaign, ship_id, choice.replacement)
            except CampaignEconomyError as exc:
                return "", str(exc)
            return cost_text(quote.charge, quote.balance), quote.reason

        return preview

    def _refresh_offers(self) -> None:
        offers_list = self.query_one("#offers", OptionList)
        highlighted = offers_list.highlighted
        self._offers = hull_offers(self.campaign)
        offers_list.clear_options()
        for offer in self._offers:
            prompt = Text(offer.hull.name, style="bold")
            prompt.append(f"\n  {offer.hull.hull_cost} cr · {offer.quote.preview}", style="dim")
            if offer.quote.reason is not None:
                prompt.stylize("dim", 0, len(offer.hull.name))
                prompt.append(f"\n  ✗ {offer.quote.reason}", style="red")
            offers_list.add_option(Option(prompt, id=offer.hull.id))
        if self._offers:
            index = highlighted if highlighted is not None else 0
            offers_list.highlighted = min(index, len(self._offers) - 1)
        self._show_offer(offers_list.highlighted)

    def _show_offer(self, index: int | None) -> None:
        art = self.query_one("#yard-art", HangarView)
        stats = self.query_one("#yard-stats", Static)
        if index is None or not 0 <= index < len(self._offers):
            art.set_entries([])
            stats.update("No hulls available.")
            return
        offer = self._offers[index]
        art.set_entries([HangarEntry(offer.hull, offer.hull.name)])
        stats.update(hull_stats(offer.hull, offer))

    def _apply_mode(self) -> None:
        shipyard = self.mode == "shipyard"
        self.query_one("#roster").display = not shipyard
        self.query_one("#panel").display = not shipyard
        self.query_one("#yard-art").display = shipyard
        self.query_one("#yard-stats").display = shipyard
        self.query_one("#offers").display = shipyard
        title = "Shipyard" if shipyard else "Hangar"
        self.set_header(f"{title} · Credits {self.campaign.credits}")
        self.query_one("#offers" if shipyard else "#panel").focus()
        self.refresh_bindings()

    def _adopt(self, candidate: CampaignState, message: str) -> None:
        self.campaign = candidate
        error = autosave(candidate, self.path)
        self.write_log(f"{message} {error}" if error else f"{message} Autosaved.")
        self._refresh()

    def _blocked(self) -> bool:
        if self.campaign.status is CampaignStatus.ACTIVE:
            return False
        self.write_log(
            f"Campaign is {self.campaign.status.value}; the fleet can no longer be changed."
        )
        return True

    def _confirm(self, message: str, on_yes: Callable[[], None]) -> None:
        def answered(answer: bool | None) -> None:
            if answer:
                on_yes()
            else:
                self.write_log("Cancelled; nothing changed.")

        self.app.push_screen(ConfirmScreen(message), answered)

    # ---------------------------------------------------------------- actions

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        hangar_only = {"ship", "flagship", "discard", "repair", "shipyard"}
        if action in hangar_only:
            return self.mode == "hangar"
        if action == "hangar":
            return self.mode == "shipyard"
        return True

    def action_ship(self, step: int) -> None:
        self.query_one("#roster", HangarView).action_move(step)

    def on_hangar_view_selection_changed(self, event: HangarView.SelectionChanged) -> None:
        event.stop()
        if not 0 <= event.index < len(self.campaign.roster):
            return
        self._selected_id = self.campaign.roster[event.index].id
        self._refresh_panel()

    def on_ship_panel_fitting_chosen(self, event: ShipPanel.FittingChosen) -> None:
        event.stop()
        ship = self.selected_ship
        if ship is None or self._blocked():
            return
        try:
            quote = quote_refit(self.campaign, ship.id, event.choice.replacement)
        except CampaignEconomyError as exc:
            self.write_log(f"Cannot refit {ship.spec.name}: {exc}.")
            return
        if quote.candidate is None:
            self.write_log(f"Cannot refit {ship.spec.name}: {quote.reason}.")
            return
        candidate = quote.candidate
        slot = _slot_name(event.slot.label)
        target = "empty" if event.choice.value == "remove" else event.choice.label
        message = f"Refit {ship.spec.name} {slot} → {target}? {quote.preview}."
        done = f"Refit {slot} → {target} ({credit_change(quote.charge)})."
        self._confirm(message, lambda: self._adopt(candidate, done))

    def action_flagship(self) -> None:
        ship = self.selected_ship
        if ship is None or self._blocked():
            return
        if ship.id == self.campaign.flagship_id:
            self.write_log(f"{ship.spec.name} is already the flagship.")
            return
        candidate = deepcopy(self.campaign)
        try:
            set_flagship(candidate, ship.id)
        except CampaignEconomyError as exc:
            self.write_log(f"Cannot make {ship.spec.name} flagship: {exc}.")
            return
        self._confirm(
            f"Make {ship.spec.name} the flagship?",
            lambda: self._adopt(candidate, f"{ship.spec.name} is now the flagship."),
        )

    def action_discard(self) -> None:
        ship = self.selected_ship
        if ship is None or self._blocked():
            return
        candidate = deepcopy(self.campaign)
        try:
            discard_ship(candidate, ship.id)
        except CampaignEconomyError as exc:
            self.write_log(f"Cannot discard {ship.spec.name}: {exc}.")
            return
        self._confirm(
            f"Discard {ship.spec.name} permanently with no refund?",
            lambda: self._adopt(candidate, f"Discarded {ship.spec.name}."),
        )

    def action_repair(self) -> None:
        ship = self.selected_ship
        if ship is None or self._blocked():
            return
        if ship.hull_damage == 0:
            self.write_log(f"{ship.spec.name} has no damage to repair.")
            return
        try:
            quote = quote_repair_ship(self.campaign, ship.id)
        except CampaignEconomyError as exc:
            self.write_log(f"Cannot repair {ship.spec.name}: {exc}.")
            return
        if quote.candidate is None:
            self.write_log(f"Cannot repair {ship.spec.name}: {quote.reason} ({quote.preview}).")
            return
        candidate = quote.candidate
        self._confirm(
            f"Repair {ship.spec.name} ({ship.hull_damage} hull)? {quote.preview}.",
            lambda: self._adopt(
                candidate, f"Repaired {ship.spec.name} ({credit_change(quote.charge)})."
            ),
        )

    def action_shipyard(self) -> None:
        if self._blocked():
            return
        self.mode = "shipyard"
        self._refresh_offers()
        self._apply_mode()

    def action_hangar(self) -> None:
        self.mode = "hangar"
        self._refresh()
        self._apply_mode()

    def action_back(self) -> None:
        if self.mode == "shipyard" and not self._opened_in_shipyard:
            self.action_hangar()
            return
        self.dismiss(self.campaign)

    # --------------------------------------------------------------- shipyard

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._show_offer(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self._blocked() or not 0 <= event.option_index < len(self._offers):
            return
        offer = self._offers[event.option_index]
        if offer.quote.reason is not None:
            self.write_log(f"Cannot buy {offer.hull.name}: {offer.quote.reason}.")
            return
        hull = offer.hull

        def validate(name: str) -> str | None:
            return None if name else "Ship name cannot be empty."

        def named(name: str | None) -> None:
            if name is None:
                self.write_log("Purchase cancelled; nothing changed.")
                return
            self._confirm_buy(hull, name)

        self.app.push_screen(
            TextInputScreen("Ship name", unique_ship_name(self.campaign, hull.name), validate),
            named,
        )

    def _confirm_buy(self, hull: HullProfile, name: str) -> None:
        try:
            quote = quote_buy(self.campaign, ShipSpec(name, hull.id))
        except CampaignEconomyError as exc:
            self.write_log(f"Cannot buy {name}: {exc}.")
            return
        if quote.candidate is None:
            self.write_log(f"Cannot buy {name}: {quote.reason}.")
            return
        candidate = quote.candidate
        new_id = candidate.roster[-1].id

        def buy() -> None:
            self._selected_id = new_id
            self.mode = "hangar"
            self._adopt(candidate, f"Bought {name} ({hull.name}, {credit_change(quote.charge)}).")
            self._apply_mode()

        self._confirm(f"Buy {name} ({hull.name})? {quote.preview}.", buy)


def _no_cost(_choice: FittingChoice) -> tuple[str, str | None]:
    return "", None
