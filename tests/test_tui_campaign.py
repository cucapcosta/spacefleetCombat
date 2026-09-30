"""Campaign menu, new-campaign form and interval screen (Pilot)."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest
from textual.app import App
from textual.screen import Screen
from textual.widgets import Input, Select, Static

from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.campaign.rules import INITIAL_CREDITS, validate_campaign_fleet
from spacefleet.core.types import Faction
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.persistence.campaign_save import CampaignSaveError, load_campaign, save_campaign
from spacefleet.tui.model import campaign_ops
from spacefleet.tui.screens.campaign import (
    CampaignHelpScreen,
    CampaignMenuScreen,
    CampaignScreen,
    NewCampaignScreen,
    parse_seed,
    ship_hull_max,
)
from spacefleet.tui.widgets.confirm import ConfirmScreen
from tests.campaign_helpers import campaign_state, supported_fleet

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from textual.app import ComposeResult
    from textual.pilot import Pilot

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.campaign.models import CampaignState
    from spacefleet.models.fleet_spec import FleetSpec

SIZE = (140, 45)


# ── fakes ────────────────────────────────────────────────────────────


def destroy_enemies(session: BattleSession) -> None:
    for ship_id in session.enemy_runtime_ids:
        ship = session.state.ships[ship_id]
        ship.take_hull_damage(ship.hull_max)


def destroy_players(session: BattleSession) -> None:
    for ship_id in session.player_runtime_by_campaign.values():
        ship = session.state.ships[ship_id]
        ship.take_hull_damage(ship.hull_max)


class FakeBattle(Screen[BattleOutcome]):
    """Mutates the session, then dismisses with a fixed outcome."""

    def __init__(
        self,
        session: BattleSession,
        outcome: BattleOutcome,
        mutate: Callable[[BattleSession], None] | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.outcome = outcome
        self.mutate = mutate

    def compose(self) -> ComposeResult:
        yield Static("battle")

    def on_mount(self) -> None:
        if self.mutate is not None:
            self.mutate(self.session)
        self.call_after_refresh(self._finish)

    def _finish(self) -> None:
        self.dismiss(self.outcome)


class BattleFactory:
    def __init__(
        self,
        outcome: BattleOutcome,
        mutate: Callable[[BattleSession], None] | None = None,
    ) -> None:
        self.outcome = outcome
        self.mutate = mutate
        self.calls = 0

    def __call__(self, session: BattleSession) -> Screen[BattleOutcome]:
        self.calls += 1
        return FakeBattle(session, self.outcome, self.mutate)


def winning() -> BattleFactory:
    return BattleFactory(BattleOutcome.VICTORY, destroy_enemies)


class FakeHangar(Screen[Any]):
    def __init__(self, result: CampaignState) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        yield Static("hangar")

    def on_mount(self) -> None:
        self.call_after_refresh(self._finish)

    def _finish(self) -> None:
        self.dismiss(self.result)


class HangarFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, bool]] = []

    def __call__(self, campaign: CampaignState, path: Path, shipyard: bool) -> Screen[Any]:
        self.calls.append((path, shipyard))
        changed = deepcopy(campaign)
        changed.credits -= 10
        changed.roster[0].spec.name = "Renamed Flag"
        return FakeHangar(changed)


class FakeBuilder(Screen[Any]):
    def __init__(self, result: FleetSpec | None) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        yield Static("builder")

    def on_mount(self) -> None:
        self.call_after_refresh(self._finish)

    def _finish(self) -> None:
        self.dismiss(self.result)


class BuilderFactory:
    def __init__(self, result: FleetSpec | None) -> None:
        self.result = result
        self.calls: list[tuple[Faction, int, str, Callable[[FleetSpec], None]]] = []

    def __call__(
        self,
        faction: Faction,
        budget: int,
        name: str,
        validator: Callable[[FleetSpec], None],
    ) -> Screen[Any]:
        self.calls.append((faction, budget, name, validator))
        return FakeBuilder(self.result)


# ── harness ──────────────────────────────────────────────────────────


class Host(App[None]):
    def __init__(self, screen: Screen[Any]) -> None:
        super().__init__()
        self.first = screen
        self.results: list[Any] = []

    def compose(self) -> ComposeResult:
        yield Static("home", id="home")

    def on_mount(self) -> None:
        self.push_screen(self.first, self.results.append)


def run(screen: Screen[Any], script: Callable[[Pilot[None], Host], Awaitable[None]]) -> Host:
    app = Host(screen)

    async def go() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await script(pilot, app)

    asyncio.run(go())
    return app


async def press(pilot: Pilot[None], *keys: str) -> None:
    for key in keys:
        await pilot.press(key)
        await pilot.pause()
        await pilot.pause()


def interval(
    campaign: CampaignState,
    path: Path,
    battle: BattleFactory | None = None,
    hangar: HangarFactory | None = None,
) -> CampaignScreen:
    return CampaignScreen(
        campaign,
        path,
        battle_screen_factory=battle or winning(),
        hangar_screen_factory=hangar or HangarFactory(),
    )


def log_text(screen: CampaignScreen) -> str:
    return "\n".join(screen.log_lines)


# ── pure helpers ─────────────────────────────────────────────────────


def test_parse_seed() -> None:
    assert parse_seed("") is None
    assert parse_seed(" 19 ") == 19
    for bad in ("-1", "x", "1.5"):
        with pytest.raises(ValueError):
            parse_seed(bad)


def test_ship_hull_max_matches_hull() -> None:
    campaign = campaign_state()
    ship = campaign.roster[0]
    assert ship_hull_max(ship.spec) == HullRegistry.get(ship.spec.hull_id).hull_hits


# ── interval: layout ─────────────────────────────────────────────────


def test_interval_shows_header_fleet_enemy_and_commander(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    path = save_campaign(campaign, tmp_path / "save.json")
    before = path.read_bytes()
    screen = interval(campaign, path)
    seen: dict[str, str] = {}

    async def script(pilot: Pilot[None], app: Host) -> None:
        assert app.screen is screen
        seen["header"] = str(screen.query_one("#header", Static).content)
        seen["side"] = screen.side_text()
        await press(pilot, "escape")
        assert app.screen is not screen

    app = run(screen, script)
    assert seen["header"] == (
        f"Campaign · Encounter 1/5 · Credits {campaign.credits} · Test Commander L1 (XP 0)"
    )
    side = seen["side"]
    hull_max = ship_hull_max(campaign.roster[0].spec)
    assert "Test Flag · Dauntless" in side
    assert "★" in side
    assert f"{hull_max - 2}/{hull_max}" in side
    assert "Next enemy" in side and "Chaos Fleet" in side and "pt" in side
    assert "Commander Test Commander" in side
    assert app.results == [None]
    assert path.read_bytes() == before


def test_help_modal_lists_keys(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    screen = interval(campaign_state(), path)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "question_mark")
        assert isinstance(app.screen, CampaignHelpScreen)
        assert "Shipyard" in str(app.screen.query_one("#keys", Static).content)
        await press(pilot, "escape")
        assert app.screen is screen

    run(screen, script)


# ── interval: battle ─────────────────────────────────────────────────


def test_victory_closes_battle_autosaves_and_logs(tmp_path: Path) -> None:
    campaign = campaign_state()
    credits = campaign.credits
    path = save_campaign(campaign, tmp_path / "save.json")
    battle = winning()
    screen = interval(campaign, path, battle)
    seen: dict[str, str] = {}

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "b")
        assert app.screen is screen
        seen["header"] = str(screen.query_one("#header", Static).content)

    run(screen, script)
    assert battle.calls == 1
    loaded = load_campaign(path)
    assert loaded.encounter == 2
    assert loaded.credits > credits
    log = log_text(screen)
    assert "Battle victory:" in log and "credits awarded" in log
    assert "Autosaved." in log
    assert "Encounter 2/5" in seen["header"]
    assert screen.campaign.encounter == 2


def test_victory_reports_casualty_names(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")

    def costly(session: BattleSession) -> None:
        casualty = session.state.ships[session.player_runtime_by_campaign["ship-2"]]
        casualty.take_hull_damage(casualty.hull_max)
        destroy_enemies(session)

    screen = interval(campaign_state(), path, BattleFactory(BattleOutcome.VICTORY, costly))

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "b")

    run(screen, script)
    assert "casualties: ship-2 (Test Escort)" in log_text(screen)
    assert [ship.id for ship in load_campaign(path).roster] == ["ship-1"]


def test_abandoned_battle_does_not_close_or_save(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    before = path.read_bytes()
    screen = interval(campaign_state(), path, BattleFactory(BattleOutcome.ABANDONED))

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "b")

    run(screen, script)
    assert path.read_bytes() == before
    assert screen.campaign.encounter == 1
    assert "Battle abandoned; campaign interval unchanged and not saved." in screen.log_lines


@pytest.mark.parametrize("invalid_state", ["empty", "flagship"])
def test_battle_blocked_without_roster_or_flagship(tmp_path: Path, invalid_state: str) -> None:
    campaign = campaign_state()
    if invalid_state == "empty":
        campaign.roster.clear()
    campaign.flagship_id = None
    path = save_campaign(campaign, tmp_path / "save.json")
    battle = winning()
    screen = interval(campaign, path, battle)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "b")
        assert app.screen is screen

    run(screen, script)
    assert battle.calls == 0
    assert any(line.startswith("Battle cannot start:") for line in screen.log_lines)


@pytest.mark.parametrize("status", [CampaignStatus.COMPLETED, CampaignStatus.DEFEATED])
def test_finished_campaign_blocks_everything_but_save(
    tmp_path: Path, status: CampaignStatus
) -> None:
    campaign = campaign_state()
    campaign.status = status
    campaign.roster[0].hull_damage = 1
    path = save_campaign(campaign, tmp_path / "save.json")
    battle = winning()
    hangar = HangarFactory()
    screen = interval(campaign, path, battle, hangar)
    seen: dict[str, str] = {}

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "b", "h", "y", "r", "w")
        assert app.screen is screen
        seen["header"] = str(screen.query_one("#header", Static).content)

    run(screen, script)
    assert battle.calls == 0 and hangar.calls == []
    blocked = f"Campaign is {status.value}."
    assert screen.log_lines[:4] == [blocked] * 4
    assert screen.log_lines[4] == f"Campaign saved to {path}."
    assert seen["header"].endswith(status.value.upper())


@pytest.mark.parametrize(
    "outcome",
    [BattleOutcome.DEFEAT, BattleOutcome.SURRENDER, BattleOutcome.TURN_LIMIT],
)
def test_every_defeat_outcome_reports_defeated(tmp_path: Path, outcome: BattleOutcome) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")

    def lose(session: BattleSession) -> None:
        if outcome is BattleOutcome.DEFEAT:
            destroy_players(session)
        elif outcome is BattleOutcome.TURN_LIMIT:
            session.state.turn = 60

    screen = interval(campaign_state(), path, BattleFactory(outcome, lose))

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "b")

    run(screen, script)
    assert load_campaign(path).status is CampaignStatus.DEFEATED
    text = outcome.value.replace("_", " ")
    assert f"Campaign defeated ({text})." in screen.log_lines
    assert f"Battle {text}:" in log_text(screen)


def test_final_victory_with_failed_autosave_then_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign = campaign_state()
    campaign.encounter = 5
    path = save_campaign(campaign, tmp_path / "save.json")
    real_save = save_campaign
    calls = 0

    def flaky_save(current: CampaignState, target: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CampaignSaveError("disk full")
        return real_save(current, target)

    monkeypatch.setattr(campaign_ops, "save_campaign", flaky_save)
    battle = winning()
    screen = interval(campaign, path, battle)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "b")
        assert load_campaign(path).status is CampaignStatus.ACTIVE
        await press(pilot, "b", "w")

    run(screen, script)
    assert battle.calls == 1
    assert calls == 2
    assert load_campaign(path).status is CampaignStatus.COMPLETED
    log = log_text(screen)
    assert "UNSAVED: disk full" in log
    assert "Campaign completed after five victories." in log
    assert "Campaign is completed." in log
    assert screen.log_lines[-1] == f"Campaign saved to {path}."


# ── interval: repair, hangar, save ───────────────────────────────────


def test_repair_confirmed_applies_and_saves(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    path = save_campaign(campaign, tmp_path / "save.json")
    screen = interval(campaign, path)
    seen: list[str] = []

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "r")
        assert isinstance(app.screen, ConfirmScreen)
        seen.append(app.screen.message)
        await press(pilot, "y")

    run(screen, script)
    assert seen == [
        f"Repair all ships? charge 16 credits; resulting credits {campaign.credits - 16}"
    ]
    loaded = load_campaign(path)
    assert loaded.roster[0].hull_damage == 0
    assert loaded.credits == campaign.credits - 16
    assert screen.campaign.credits == campaign.credits - 16
    assert "Autosaved." in screen.log_lines


def test_repair_declined_leaves_campaign_and_save(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    path = save_campaign(campaign, tmp_path / "save.json")
    before = path.read_bytes()
    screen = interval(campaign, path)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "r", "n")
        assert app.screen is screen

    run(screen, script)
    assert path.read_bytes() == before
    assert screen.campaign.roster[0].hull_damage == 2


def test_repair_nothing_or_unaffordable_logs_reason(tmp_path: Path) -> None:
    campaign = campaign_state()
    path = save_campaign(campaign, tmp_path / "save.json")
    screen = interval(campaign, path)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "r")
        screen.campaign.roster[0].hull_damage = 2
        screen.campaign.credits = 1
        await press(pilot, "r")
        assert app.screen is screen

    run(screen, script)
    assert screen.log_lines[0] == "No ships need repair."
    assert "insufficient credits" in screen.log_lines[1]


def test_repair_autosave_failure_keeps_memory_and_w_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 1
    path = save_campaign(campaign, tmp_path / "save.json")
    broken = [True]
    real_save = save_campaign

    def flaky_save(current: CampaignState, target: Path) -> Path:
        if broken[0]:
            raise CampaignSaveError("disk full")
        return real_save(current, target)

    monkeypatch.setattr(campaign_ops, "save_campaign", flaky_save)
    screen = interval(campaign, path)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "r", "y")
        assert load_campaign(path).roster[0].hull_damage == 1
        await press(pilot, "w")
        broken[0] = False
        await press(pilot, "w")

    run(screen, script)
    assert screen.campaign.roster[0].hull_damage == 0
    assert load_campaign(path).roster[0].hull_damage == 0
    assert sum("UNSAVED" in line for line in screen.log_lines) == 2
    assert screen.log_lines[-1] == f"Campaign saved to {path}."


@pytest.mark.parametrize(("key", "shipyard"), [("h", False), ("y", True)])
def test_hangar_result_is_adopted(tmp_path: Path, key: str, shipyard: bool) -> None:
    campaign = campaign_state()
    path = save_campaign(campaign, tmp_path / "save.json")
    hangar = HangarFactory()
    screen = interval(campaign, path, hangar=hangar)
    seen: list[str] = []

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, key)
        assert app.screen is screen
        seen.append(screen.side_text())
        seen.append(str(screen.query_one("#header", Static).content))

    run(screen, script)
    assert hangar.calls == [(path, shipyard)]
    assert screen.campaign.credits == campaign.credits - 10
    assert "Renamed Flag" in seen[0]
    assert f"Credits {campaign.credits - 10}" in seen[1]


# ── menu ─────────────────────────────────────────────────────────────


def menu(path: Path, builder: BuilderFactory | None = None) -> CampaignMenuScreen:
    return CampaignMenuScreen(
        path,
        battle_screen_factory=winning(),
        hangar_screen_factory=HangarFactory(),
        fleet_builder_factory=builder or BuilderFactory(None),
    )


def test_menu_continue_missing_save(tmp_path: Path) -> None:
    screen = menu(tmp_path / "save.json")
    seen: list[str] = []

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "c")
        assert app.screen is screen
        seen.append(screen.message)
        await press(pilot, "escape")

    app = run(screen, script)
    assert seen == ["No saved campaign exists."]
    assert app.results == [None]


def test_menu_continue_invalid_save(tmp_path: Path) -> None:
    path = tmp_path / "save.json"
    path.write_text('{"version": 999}', encoding="utf-8")
    screen = menu(path)
    seen: list[str] = []

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "c")
        assert app.screen is screen
        seen.append(screen.message)

    run(screen, script)
    assert seen[0].startswith("Could not continue campaign:")
    assert "version" in seen[0]


def test_menu_continue_opens_interval_and_returns(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    screen = menu(path)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "c")
        assert isinstance(app.screen, CampaignScreen)
        assert app.screen.campaign.commander.name == "Test Commander"
        await press(pilot, "escape")
        assert app.screen is screen

    run(screen, script)


def test_menu_option_list_selects_with_enter(tmp_path: Path) -> None:
    screen = menu(tmp_path / "save.json")

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "down", "enter")
        assert screen.message == "No saved campaign exists."
        await press(pilot, "up", "enter")
        assert isinstance(app.screen, NewCampaignScreen)

    run(screen, script)


# ── new campaign ─────────────────────────────────────────────────────


async def fill_form(pilot: Pilot[None], app: Host, name: str, seed: str) -> NewCampaignScreen:
    form = app.screen
    assert isinstance(form, NewCampaignScreen)
    form.query_one("#name", Input).value = name
    form.query_one("#seed", Input).value = seed
    form.query_one("#name", Input).focus()
    await press(pilot, "enter")
    return form


@pytest.mark.parametrize(("name", "seed"), [("Voss", "-3"), ("Voss", "abc"), ("", "4")])
def test_new_campaign_rejects_invalid_form(tmp_path: Path, name: str, seed: str) -> None:
    builder = BuilderFactory(supported_fleet())
    screen = menu(tmp_path / "save.json", builder)
    errors: list[str] = []

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "n")
        form = await fill_form(pilot, app, name, seed)
        assert app.screen is form
        errors.append(form.error)

    run(screen, script)
    expected = "Commander name is required." if not name else "Seed must be a non-negative integer."
    assert errors == [expected]
    assert builder.calls == []
    assert not (tmp_path / "save.json").exists()


def test_new_campaign_replace_declined_keeps_save(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    before = path.read_bytes()
    builder = BuilderFactory(supported_fleet())
    screen = menu(path, builder)

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "n")
        await fill_form(pilot, app, "Voss", "9")
        assert isinstance(app.screen, ConfirmScreen)
        assert app.screen.message == "Replace the existing campaign save?"
        await press(pilot, "n")
        assert isinstance(app.screen, NewCampaignScreen)

    run(screen, script)
    assert builder.calls == []
    assert path.read_bytes() == before


def test_new_campaign_builder_cancel_keeps_save(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    before = path.read_bytes()
    builder = BuilderFactory(None)
    screen = menu(path, builder)
    errors: list[str] = []

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "n")
        await fill_form(pilot, app, "Voss", "9")
        await press(pilot, "y")
        form = app.screen
        assert isinstance(form, NewCampaignScreen)
        errors.append(form.error)
        await press(pilot, "escape")
        assert app.screen is screen

    run(screen, script)
    assert len(builder.calls) == 1
    assert errors == ["Fleet building cancelled; existing save unchanged."]
    assert path.read_bytes() == before


def test_new_campaign_creates_saves_and_opens_interval(tmp_path: Path) -> None:
    path = tmp_path / "save.json"
    builder = BuilderFactory(supported_fleet(Faction.CHAOS_FLEET))
    screen = menu(path, builder)
    seen: list[str] = []

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "n")
        form = app.screen
        assert isinstance(form, NewCampaignScreen)
        form.query_one("#faction", Select).value = Faction.CHAOS_FLEET
        await fill_form(pilot, app, "Admiral Voss", "19")
        interval_screen = app.screen
        assert isinstance(interval_screen, CampaignScreen)
        seen.extend(interval_screen.log_lines)
        await press(pilot, "escape")
        assert app.screen is screen

    run(screen, script)
    faction, budget, name, validator = builder.calls[0]
    assert (faction, budget, name) == (Faction.CHAOS_FLEET, INITIAL_CREDITS, "Admiral Voss")
    assert validator is validate_campaign_fleet
    saved = load_campaign(path)
    assert (saved.commander.name, saved.seed, saved.faction) == (
        "Admiral Voss",
        19,
        Faction.CHAOS_FLEET,
    )
    assert seen == [f"Campaign saved to {path}."]


def test_new_campaign_back_returns_to_menu(tmp_path: Path) -> None:
    screen = menu(tmp_path / "save.json")

    async def script(pilot: Pilot[None], app: Host) -> None:
        await press(pilot, "n")
        assert isinstance(app.screen, NewCampaignScreen)
        await press(pilot, "escape")
        assert app.screen is screen

    run(screen, script)
