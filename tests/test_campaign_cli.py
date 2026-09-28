from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.cli import campaign_cmd
from spacefleet.cli.campaign_cmd import _store_candidate, run_campaign_menu
from spacefleet.persistence.campaign_save import CampaignSaveError, load_campaign, save_campaign
from tests.campaign_helpers import campaign_state
from tests.terminal_ui_helpers import FakeTerminalUI

if TYPE_CHECKING:
    from pathlib import Path

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.campaign.models import CampaignState


class WinningController:
    def __init__(self, session: BattleSession) -> None:
        self.session = session

    def run(self) -> BattleOutcome:
        for ship_id in self.session.enemy_runtime_ids:
            ship = self.session.state.ships[ship_id]
            ship.take_hull_damage(ship.hull_max)
        return BattleOutcome.VICTORY


class AbandoningController:
    calls = 0

    def __init__(self, _session: BattleSession) -> None:
        type(self).calls += 1

    def run(self) -> BattleOutcome:
        return BattleOutcome.ABANDONED


def _shown(ui: FakeTerminalUI) -> str:
    return "\n".join(ui.show_calls).lower()


def test_store_candidate_uses_exact_economy_preview_without_mutating() -> None:
    campaign = campaign_state()
    before = deepcopy(campaign)

    equipped, preview = _store_candidate(
        campaign, ["equip", "ship-1", "weapon", "3", "macro_cannon_2"]
    )
    removed, refund = _store_candidate(equipped, ["remove", "ship-1", "weapon", "3"])

    assert campaign == before
    assert "charge 8 credits" in preview
    assert "refund 12 credits" in refund
    assert removed.roster[0].spec.weapons.get(3) is None


@pytest.mark.parametrize("invalid_state", ["empty", "flagship"])
def test_battle_rejects_interval_without_roster_or_flagship(
    tmp_path: Path, invalid_state: str
) -> None:
    campaign = campaign_state()
    if invalid_state == "empty":
        campaign.roster.clear()
    campaign.flagship_id = None
    path = save_campaign(campaign, tmp_path / "save.json")
    AbandoningController.calls = 0
    ui = FakeTerminalUI(choices=["continue", "battle", "back"])

    run_campaign_menu(save_path=path, ui=ui, controller_factory=AbandoningController)

    assert AbandoningController.calls == 0
    assert "flagship" in _shown(ui) or "ship" in _shown(ui)


def test_abandoned_battle_does_not_close_or_save(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    old_bytes = path.read_bytes()
    ui = FakeTerminalUI(choices=["continue", "battle", "back"])

    run_campaign_menu(save_path=path, ui=ui, controller_factory=AbandoningController)

    assert path.read_bytes() == old_bytes
    assert "unchanged" in _shown(ui)


def test_continue_links_two_battles_through_store(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    ui = FakeTerminalUI(
        choices=["continue", "battle", "buy", "sword_frigate", "battle", "back"],
        texts=["Reinforcement"],
        confirmations=[True],
    )

    run_campaign_menu(save_path=path, ui=ui, controller_factory=WinningController)

    loaded = load_campaign(path)
    assert loaded.encounter == 3
    assert any(ship.spec.name == "Reinforcement" for ship in loaded.roster)
    assert "credits awarded" in _shown(ui)


def test_battle_report_shows_casualty_names_and_updated_state(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")

    class CostlyVictory:
        def __init__(self, session: BattleSession) -> None:
            self.session = session

        def run(self) -> BattleOutcome:
            flagship_id = self.session.player_runtime_by_campaign["ship-1"]
            casualty_id = self.session.player_runtime_by_campaign["ship-2"]
            self.session.state.ships[flagship_id].take_hull_damage(1)
            casualty = self.session.state.ships[casualty_id]
            casualty.take_hull_damage(casualty.hull_max)
            commander = self.session.state.fleets["player"].commander
            assert commander is not None
            commander.level = 2
            commander.xp = 275
            for enemy_id in self.session.enemy_runtime_ids:
                enemy = self.session.state.ships[enemy_id]
                enemy.take_hull_damage(enemy.hull_max)
            return BattleOutcome.VICTORY

    ui = FakeTerminalUI(choices=["continue", "battle", "back"])
    run_campaign_menu(save_path=path, ui=ui, controller_factory=CostlyVictory)

    output = _shown(ui)
    assert "casualties: ship-2 (test escort)" in output
    assert "damage 1" in output
    assert "level 2" in output and "xp 275" in output


def test_terminal_autosave_failure_allows_retry_but_no_second_battle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign = campaign_state()
    campaign.encounter = 5
    path = save_campaign(campaign, tmp_path / "save.json")
    real_save = save_campaign
    save_calls = 0
    battle_calls = 0

    def flaky_save(current: CampaignState, target: Path) -> Path:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            raise CampaignSaveError("disk full")
        return real_save(current, target)

    class CountingVictory(WinningController):
        def run(self) -> BattleOutcome:
            nonlocal battle_calls
            battle_calls += 1
            return super().run()

    monkeypatch.setattr(campaign_cmd, "save_campaign", flaky_save)
    ui = FakeTerminalUI(choices=["continue", "battle", "battle", "save", "back"])
    run_campaign_menu(save_path=path, ui=ui, controller_factory=CountingVictory)

    assert battle_calls == 1
    assert save_calls == 2
    assert load_campaign(path).status is CampaignStatus.COMPLETED
    assert "unsaved" in _shown(ui)
    assert "campaign is completed" in _shown(ui)


@pytest.mark.parametrize(
    "outcome",
    [BattleOutcome.DEFEAT, BattleOutcome.SURRENDER, BattleOutcome.TURN_LIMIT],
)
def test_every_defeat_outcome_reports_terminal_status(
    tmp_path: Path, outcome: BattleOutcome
) -> None:
    path = save_campaign(campaign_state(), tmp_path / f"{outcome.value}.json")

    class LosingController:
        def __init__(self, session: BattleSession) -> None:
            self.session = session

        def run(self) -> BattleOutcome:
            if outcome is BattleOutcome.DEFEAT:
                for ship_id in self.session.player_runtime_by_campaign.values():
                    ship = self.session.state.ships[ship_id]
                    ship.take_hull_damage(ship.hull_max)
            elif outcome is BattleOutcome.TURN_LIMIT:
                self.session.state.turn = 60
            return outcome

    ui = FakeTerminalUI(choices=["continue", "battle"])
    run_campaign_menu(save_path=path, ui=ui, controller_factory=LosingController)

    loaded = load_campaign(path)
    assert loaded.status is CampaignStatus.DEFEATED
    assert outcome.value.replace("_", " ") in _shown(ui)
    assert "campaign defeated" in _shown(ui)


def test_app_routes_shared_ui_to_campaign(monkeypatch: pytest.MonkeyPatch) -> None:
    from spacefleet.cli import app

    seen: list[FakeTerminalUI] = []

    def run_menu(*, ui: FakeTerminalUI) -> None:
        seen.append(ui)

    monkeypatch.setattr(campaign_cmd, "run_campaign_menu", run_menu)
    ui = FakeTerminalUI(choices=["campaign", "quit"])

    app.main(ui=ui)

    assert seen == [ui]


def test_run_campaign_menu_builds_and_runs_first_battle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.campaign_helpers import supported_fleet

    fleet = supported_fleet()
    seen: dict[str, BattleSession] = {}
    monkeypatch.setattr(campaign_cmd, "run_fleet_builder", lambda **_kwargs: fleet)

    class Controller:
        def __init__(self, session: BattleSession) -> None:
            seen["session"] = session

        def run(self) -> BattleOutcome:
            return BattleOutcome.ABANDONED

    ui = FakeTerminalUI(
        choices=["new", "imperial_navy", "battle", "back"],
        texts=["Admiral Voss", "19"],
    )
    run_campaign_menu(save_path=tmp_path / "campaign.json", ui=ui, controller_factory=Controller)
    assert seen["session"].battle_id == "19:1"
    commander = seen["session"].state.fleets["player"].commander
    assert commander is not None
    assert commander.name == "Admiral Voss"


def test_default_battle_runner_is_the_tui(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from spacefleet.tui import battle_app

    runs: list[BattleSession] = []

    def fake_run(session: BattleSession, **_kwargs: object) -> BattleOutcome:
        runs.append(session)
        return BattleOutcome.ABANDONED

    monkeypatch.setattr(battle_app, "run_battle", fake_run)
    path = tmp_path / "campaign.json"
    save_campaign(campaign_state(), path)
    ui = FakeTerminalUI(choices=["continue", "battle", "back"])
    run_campaign_menu(save_path=path, ui=ui)
    assert len(runs) == 1


def test_app_menu_mentions_local_campaign() -> None:
    from spacefleet.cli.app import MENU

    assert "Campaign" in MENU
