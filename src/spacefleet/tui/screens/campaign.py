"""Campaign screens: New/Continue menu, new-campaign form and the interval.

``CampaignMenuScreen`` offers New / Continue / Back.  ``NewCampaignScreen``
collects faction, commander name and seed, confirms replacing an existing
save, runs the fleet builder in campaign mode and dismisses with the new
(autosaved) campaign.  ``CampaignScreen`` is the between-battle interval:
galaxy map, fleet, next enemy and commander, with battle, hangar, shipyard,
repair and save actions.

The battle, hangar and fleet-builder screens are injected through factories
so tests can replace them with small fakes.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from spacefleet.campaign.battle import build_battle, close_battle
from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.campaign.rules import (
    INITIAL_CREDITS,
    enemy_fleet_for,
    new_campaign,
    validate_campaign_fleet,
    validate_campaign_state,
)
from spacefleet.commander.doctrine_effects import apply_doctrine_to_hull
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.models.fleet_spec import fleet_points
from spacefleet.persistence.campaign_save import (
    CampaignSaveError,
    default_campaign_path,
    load_campaign,
)
from spacefleet.tui.model import campaign_ops
from spacefleet.tui.model.galaxy import generate
from spacefleet.tui.screens.shell import ShellScreen
from spacefleet.tui.widgets.confirm import ConfirmScreen
from spacefleet.tui.widgets.galaxy_map import GalaxyMap
from spacefleet.tui.widgets.status_panel import bar

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from textual.app import ComposeResult

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.campaign.models import CampaignState
    from spacefleet.models.fleet_spec import FleetSpec, ShipSpec


type BattleScreenFactory = Callable[[BattleSession], Screen[BattleOutcome]]
"""``session -> battle screen`` dismissing with the battle outcome."""

type HangarScreenFactory = Callable[[CampaignState, Path, bool], Screen[CampaignState]]
"""``(campaign, save path, shipyard) -> hangar`` dismissing with the campaign."""

type FleetBuilderFactory = Callable[
    [Faction, int, str, Callable[[FleetSpec], None]], Screen[FleetSpec | None]
]
"""``(faction, budget, fleet name, validator) -> builder`` in campaign mode."""


def default_battle_screen(session: BattleSession) -> Screen[BattleOutcome]:
    from spacefleet.tui.screens.battle import BattleScreen

    return BattleScreen(session)


def default_hangar_screen(
    campaign: CampaignState, path: Path, shipyard: bool
) -> Screen[CampaignState]:
    module = importlib.import_module("spacefleet.tui.screens.hangar")
    screen_cls = cast("Callable[..., Screen[CampaignState]]", module.HangarScreen)
    return screen_cls(campaign, path, shipyard=shipyard)


def default_fleet_builder_screen(
    faction: Faction,
    budget: int,
    name: str,
    validator: Callable[[FleetSpec], None],
) -> Screen[FleetSpec | None]:
    module = importlib.import_module("spacefleet.tui.screens.fleet_builder")
    screen_cls = cast("Callable[..., Screen[FleetSpec | None]]", module.FleetBuilderScreen)
    return screen_cls(faction=faction, budget=budget, name=name, validator=validator)


def faction_label(faction: Faction) -> str:
    return faction.value.replace("_", " ").title()


def ship_hull_max(spec: ShipSpec) -> int:
    """Maximum hull of a campaign ship, including its doctrine's hull change."""
    hull = HullRegistry.get(spec.hull_id)
    if spec.doctrine_id is None:
        return hull.hull_hits
    return apply_doctrine_to_hull(hull, DoctrineRegistry.get(spec.doctrine_id)).hull_hits


def _outcome_text(outcome: BattleOutcome) -> str:
    return outcome.value.replace("_", " ")


# ── menu ─────────────────────────────────────────────────────────────


class CampaignMenuScreen(Screen[None]):
    """New / Continue / Back; a closed campaign returns here."""

    DEFAULT_CSS = """
    CampaignMenuScreen { align: center middle; }
    CampaignMenuScreen > Vertical {
        width: 48; height: auto;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    CampaignMenuScreen #title { text-style: bold; margin-bottom: 1; content-align: center middle; }
    CampaignMenuScreen OptionList { height: auto; border: none; }
    CampaignMenuScreen #message { height: auto; margin-top: 1; color: $warning; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "new", "New"),
        Binding("c", "continue_campaign", "Continue"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(
        self,
        path: Path | None = None,
        *,
        battle_screen_factory: BattleScreenFactory | None = None,
        hangar_screen_factory: HangarScreenFactory | None = None,
        fleet_builder_factory: FleetBuilderFactory | None = None,
    ) -> None:
        super().__init__()
        self.path = path if path is not None else default_campaign_path()
        self.battle_screen_factory = battle_screen_factory or default_battle_screen
        self.hangar_screen_factory = hangar_screen_factory or default_hangar_screen
        self.fleet_builder_factory = fleet_builder_factory or default_fleet_builder_screen

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("CAMPAIGN", id="title", markup=False)
            yield OptionList(
                Option("[n] New campaign", id="new"),
                Option("[c] Continue campaign", id="continue"),
                Option("[Esc] Back", id="back"),
                id="menu",
                markup=False,
            )
            yield Static("", id="message", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()

    @property
    def message(self) -> str:
        return str(self.query_one("#message", Static).content)

    def show_message(self, text: str) -> None:
        self.query_one("#message", Static).update(text)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id == "new":
            self.action_new()
        elif event.option.id == "continue":
            self.action_continue_campaign()
        else:
            self.action_back()

    def action_new(self) -> None:
        self.show_message("")
        self.app.push_screen(
            NewCampaignScreen(self.path, fleet_builder_factory=self.fleet_builder_factory),
            self._on_created,
        )

    def _on_created(self, created: CreatedCampaign | None) -> None:
        if created is not None:
            self._open(created.campaign, created.messages)

    def action_continue_campaign(self) -> None:
        if not self.path.is_file():
            self.show_message("No saved campaign exists.")
            return
        try:
            campaign = load_campaign(self.path)
        except (CampaignSaveError, UnicodeError) as exc:
            self.show_message(f"Could not continue campaign: {exc}")
            return
        self.show_message("")
        self._open(campaign, ())

    def _open(self, campaign: CampaignState, messages: Sequence[str]) -> None:
        self.app.push_screen(
            CampaignScreen(
                campaign,
                self.path,
                battle_screen_factory=self.battle_screen_factory,
                hangar_screen_factory=self.hangar_screen_factory,
                messages=messages,
            )
        )

    def action_back(self) -> None:
        self.dismiss(None)


# ── new campaign ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CreatedCampaign:
    """Result of :class:`NewCampaignScreen`: the campaign and its log lines."""

    campaign: CampaignState
    messages: tuple[str, ...]


def parse_seed(raw: str) -> int | None:
    """Empty → None; raises ValueError unless a non-negative integer."""
    raw = raw.strip()
    if not raw:
        return None
    seed = int(raw)
    if seed < 0:
        raise ValueError("negative seed")
    return seed


class NewCampaignScreen(Screen[CreatedCampaign | None]):
    """Faction, commander name and seed; then the fleet builder in campaign mode."""

    DEFAULT_CSS = """
    NewCampaignScreen { align: center middle; }
    NewCampaignScreen > Vertical {
        width: 72; height: auto;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    NewCampaignScreen #title { text-style: bold; margin-bottom: 1; }
    NewCampaignScreen .label { margin-top: 1; }
    NewCampaignScreen #error { height: auto; color: $error; margin-top: 1; }
    NewCampaignScreen Horizontal { height: auto; margin-top: 1; }
    NewCampaignScreen Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Back"),
    ]

    def __init__(
        self,
        path: Path,
        *,
        fleet_builder_factory: FleetBuilderFactory | None = None,
    ) -> None:
        super().__init__()
        self.path = path
        self.fleet_builder_factory = fleet_builder_factory or default_fleet_builder_screen
        self._pending: tuple[Faction, str, int | None] | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("New Campaign", id="title", markup=False)
            yield Static("Faction", classes="label", markup=False)
            yield Select(
                [(faction_label(faction), faction) for faction in Faction],
                value=next(iter(Faction)),
                allow_blank=False,
                id="faction",
            )
            yield Static("Commander name", classes="label", markup=False)
            yield Input(id="name", placeholder="required")
            yield Static("Seed (optional)", classes="label", markup=False)
            yield Input(id="seed", placeholder="random")
            yield Static("", id="error", markup=False)
            with Horizontal():
                yield Button("Build fleet [Enter]", id="create", variant="primary")
                yield Button("Back [Esc]", id="back")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    @property
    def error(self) -> str:
        return str(self.query_one("#error", Static).content)

    def show_error(self, text: str) -> None:
        self.query_one("#error", Static).update(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "create":
            self.action_create()
        else:
            self.action_cancel()

    def action_create(self) -> None:
        faction = cast("Faction", self.query_one("#faction", Select).value)
        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.show_error("Commander name is required.")
            self.query_one("#name", Input).focus()
            return
        try:
            seed = parse_seed(self.query_one("#seed", Input).value)
        except ValueError:
            self.show_error("Seed must be a non-negative integer.")
            self.query_one("#seed", Input).focus()
            return
        self.show_error("")
        self._pending = (faction, name, seed)
        if self.path.exists():
            self.app.push_screen(
                ConfirmScreen("Replace the existing campaign save?"), self._on_replace
            )
        else:
            self._build_fleet()

    def _on_replace(self, replace: bool | None) -> None:
        if replace:
            self._build_fleet()
        else:
            self.show_error("Existing campaign save kept.")

    def _build_fleet(self) -> None:
        assert self._pending is not None
        faction, name, _seed = self._pending
        builder = self.fleet_builder_factory(
            faction, INITIAL_CREDITS, name, validate_campaign_fleet
        )
        self.app.push_screen(builder, self._on_fleet)

    def _on_fleet(self, fleet: FleetSpec | None) -> None:
        assert self._pending is not None
        _faction, name, seed = self._pending
        if fleet is None:
            self.show_error("Fleet building cancelled; existing save unchanged.")
            return
        try:
            campaign = new_campaign(fleet, name, seed)
        except ValueError as exc:
            self.show_error(f"Campaign cannot start: {exc}")
            return
        error = campaign_ops.autosave(campaign, self.path)
        message = error or f"Campaign saved to {self.path}."
        self.dismiss(CreatedCampaign(campaign, (message,)))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── interval ─────────────────────────────────────────────────────────

_HELP = """\
b   Battle — fight the next encounter
h   Hangar — refit, flagship, discard, repair ships
y   Shipyard — buy a new hull
r   Repair all ships
w   Save the campaign
?   This help
Esc Back to the campaign menu"""


class CampaignHelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    CampaignHelpScreen { align: center middle; }
    CampaignHelpScreen > Vertical {
        width: 60; height: auto;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    CampaignHelpScreen #hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,question_mark,enter,q", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Campaign keys", markup=False)
            yield Static(_HELP, id="keys", markup=False)
            yield Static("Esc to close", id="hint", markup=False)

    def action_close(self) -> None:
        self.dismiss(None)


class CampaignScreen(ShellScreen[None]):
    """Between-battle interval of a campaign."""

    DEFAULT_CSS = """
    CampaignScreen #side Static { height: auto; }
    CampaignScreen #enemy, CampaignScreen #commander, CampaignScreen #actions { margin-top: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("b", "battle", "Battle"),
        Binding("h", "hangar", "Hangar"),
        Binding("y", "shipyard", "Shipyard"),
        Binding("r", "repair", "Repair"),
        Binding("w", "save", "Save"),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "back", "Menu"),
    ]

    def __init__(
        self,
        campaign: CampaignState,
        path: Path,
        *,
        battle_screen_factory: BattleScreenFactory | None = None,
        hangar_screen_factory: HangarScreenFactory | None = None,
        messages: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self.campaign = campaign
        self.path = path
        self.battle_screen_factory = battle_screen_factory or default_battle_screen
        self.hangar_screen_factory = hangar_screen_factory or default_hangar_screen
        self._messages = tuple(messages)
        self._galaxy = generate(campaign.seed)

    # ── layout ──────────────────────────────────────────────────────

    def compose_main(self) -> ComposeResult:
        yield GalaxyMap(id="galaxy")

    def compose_side(self) -> ComposeResult:
        yield Static(id="fleet")
        yield Static(id="enemy")
        yield Static(id="commander")
        yield Static(id="actions")

    def on_mount(self) -> None:
        self.refresh_view()
        for line in self._messages:
            self.write_log(line)

    def header_text(self) -> str:
        c = self.campaign
        text = (
            f"Campaign · Encounter {c.encounter}/5 · Credits {c.credits} · "
            f"{c.commander.name} L{c.commander.level} (XP {c.commander.xp})"
        )
        if c.status is not CampaignStatus.ACTIVE:
            text += f" · {c.status.value.upper()}"
        return text

    def fleet_text(self) -> Text:
        text = Text("Fleet\n", style="bold")
        if not self.campaign.roster:
            text.append("  (empty)\n", style="dim")
        for ship in self.campaign.roster:
            hull = HullRegistry.get(ship.spec.hull_id)
            text.append(f"  {ship.spec.name}")
            text.append(f" · {hull.name}", style="dim")
            if ship.id == self.campaign.flagship_id:
                text.append(" ★", style="bold yellow")
            text.append("\n")
            hull_max = ship_hull_max(ship.spec)
            current = max(0, hull_max - ship.hull_damage)
            text.append("    Hull ")
            text.append_text(bar(current, hull_max))
            text.append(f" {current}/{hull_max}\n")
        if self.campaign.flagship_id is None:
            text.append("  No flagship — choose one in the hangar.\n", style="yellow")
        return text

    def enemy_text(self) -> Text:
        c = self.campaign
        if c.status is not CampaignStatus.ACTIVE:
            style = "bold green" if c.status is CampaignStatus.COMPLETED else "bold red"
            return Text(f"Campaign {c.status.value}.", style=style)
        enemy = enemy_fleet_for(c.faction, c.encounter)
        text = Text("Next enemy\n", style="bold")
        text.append(
            f"  {faction_label(enemy.faction)} · {len(enemy.ships)} ships · "
            f"{fleet_points(enemy)} pt"
        )
        return text

    def commander_text(self) -> Text:
        commander = self.campaign.commander
        abilities = [
            definition.name
            for ability_id in commander.active_ability_ids
            if (definition := SkillRegistry.get_active(ability_id)) is not None
        ]
        passives = [
            passive.name
            for passive_id in commander.passive_skill_ids
            if (passive := SkillRegistry.get_passive(passive_id)) is not None
        ]
        text = Text(f"Commander {commander.name}\n", style="bold")
        text.append(f"  Level {commander.level} · XP {commander.xp}\n")
        text.append(f"  Abilities: {', '.join(abilities) or '(none)'}\n")
        text.append(f"  Passives: {', '.join(passives) or '(none)'}")
        return text

    def actions_text(self) -> Text:
        if self.campaign.status is CampaignStatus.ACTIVE:
            return Text("[B]attle [H]angar [Y]ard\n[R]epair all  [W] save  [?] help", style="dim")
        return Text("[W] save  [Esc] menu", style="dim")

    def refresh_view(self) -> None:
        c = self.campaign
        self.set_header(self.header_text())
        enemy_faction = (
            enemy_fleet_for(c.faction, c.encounter).faction
            if c.status is CampaignStatus.ACTIVE
            else None
        )
        self.query_one("#galaxy", GalaxyMap).set_state(
            self._galaxy, c.encounter, c.status, enemy_faction
        )
        self.query_one("#fleet", Static).update(self.fleet_text())
        self.query_one("#enemy", Static).update(self.enemy_text())
        self.query_one("#commander", Static).update(self.commander_text())
        self.query_one("#actions", Static).update(self.actions_text())

    def side_text(self) -> str:
        """Plain text of the side column (for tests)."""
        return "\n".join(
            text.plain
            for text in (
                self.fleet_text(),
                self.enemy_text(),
                self.commander_text(),
                self.actions_text(),
            )
        )

    # ── helpers ─────────────────────────────────────────────────────

    def _blocked(self) -> bool:
        if self.campaign.status is CampaignStatus.ACTIVE:
            return False
        self.write_log(f"Campaign is {self.campaign.status.value}.")
        return True

    def _autosave(self, *, explicit: bool = False) -> bool:
        error = campaign_ops.autosave(self.campaign, self.path)
        if error is not None:
            self.write_log(error)
            return False
        self.write_log(f"Campaign saved to {self.path}." if explicit else "Autosaved.")
        return True

    def _adopt(self, campaign: CampaignState | None) -> None:
        if campaign is not None:
            self.campaign = campaign
        self.refresh_view()

    # ── actions ─────────────────────────────────────────────────────

    def action_battle(self) -> None:
        if self._blocked():
            return
        try:
            validate_campaign_state(self.campaign, require_battle_ready=True)
            session = build_battle(self.campaign)
            screen = self.battle_screen_factory(session)
        except ValueError as exc:
            self.write_log(f"Battle cannot start: {exc}")
            return
        ship_names = {ship.id: ship.spec.name for ship in self.campaign.roster}

        def finished(outcome: BattleOutcome | None) -> None:
            self._close_battle(session, outcome, ship_names)

        self.app.push_screen(screen, finished)

    def _close_battle(
        self,
        session: BattleSession,
        outcome: BattleOutcome | None,
        ship_names: dict[str, str],
    ) -> None:
        if outcome is None or outcome is BattleOutcome.ABANDONED:
            self.write_log("Battle abandoned; campaign interval unchanged and not saved.")
            return
        try:
            report = close_battle(self.campaign, session, outcome)
        except ValueError as exc:
            self.write_log(f"Battle could not close: {exc}")
            self.refresh_view()
            return
        self.write_log(campaign_ops.battle_result_line(report, ship_names))
        self._autosave()
        if self.campaign.status is CampaignStatus.COMPLETED:
            self.write_log("Campaign completed after five victories.")
        elif self.campaign.status is CampaignStatus.DEFEATED:
            self.write_log(f"Campaign defeated ({_outcome_text(report.outcome)}).")
        self.refresh_view()

    def _open_hangar(self, shipyard: bool) -> None:
        if self._blocked():
            return
        screen = self.hangar_screen_factory(self.campaign, self.path, shipyard)
        self.app.push_screen(screen, self._adopt)

    def action_hangar(self) -> None:
        self._open_hangar(False)

    def action_shipyard(self) -> None:
        self._open_hangar(True)

    def action_repair(self) -> None:
        if self._blocked():
            return
        if not any(ship.hull_damage for ship in self.campaign.roster):
            self.write_log("No ships need repair.")
            return
        try:
            quote = campaign_ops.quote_repair_all(self.campaign)
        except ValueError as exc:
            self.write_log(f"Cannot repair: {exc}")
            return
        candidate = quote.candidate
        if candidate is None:
            self.write_log(f"Cannot repair all ships: {quote.reason} ({quote.preview}).")
            return

        def confirmed(yes: bool | None) -> None:
            if not yes:
                self.write_log("Repair cancelled.")
                return
            self.campaign = candidate
            self.write_log(f"Repaired all ships: {campaign_ops.credit_change(quote.charge)}.")
            self._autosave()
            self.refresh_view()

        self.app.push_screen(ConfirmScreen(f"Repair all ships? {quote.preview}"), confirmed)

    def action_save(self) -> None:
        self._autosave(explicit=True)

    def action_help(self) -> None:
        self.app.push_screen(CampaignHelpScreen())

    def action_back(self) -> None:
        self.dismiss(None)
