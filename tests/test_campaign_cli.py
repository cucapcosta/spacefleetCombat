from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.cli import campaign_cmd
from spacefleet.cli.campaign_cmd import run_campaign_menu
from spacefleet.cli.local_battle import LocalBattleController
from spacefleet.persistence.campaign_save import (
    CampaignSaveError,
    load_campaign,
    save_campaign,
)
from tests.campaign_helpers import ScriptedIO, campaign_state, supported_fleet

if TYPE_CHECKING:
    from pathlib import Path

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.campaign.models import CampaignState
    from spacefleet.models.fleet_spec import FleetSpec


class WinningController(LocalBattleController):
    def __init__(self, session: BattleSession) -> None:
        self.session = session

    def run(self) -> BattleOutcome:
        for ship_id in self.session.enemy_runtime_ids:
            ship = self.session.state.ships[ship_id]
            ship.take_hull_damage(ship.hull_max)
        return BattleOutcome.VICTORY


class AbandoningController(LocalBattleController):
    calls = 0

    def __init__(self, _session: BattleSession) -> None:
        type(self).calls += 1

    def run(self) -> BattleOutcome:
        return BattleOutcome.ABANDONED


def _output(io: ScriptedIO) -> str:
    return "\n".join(io.outputs).lower()


def test_continue_without_save_and_invalid_save_return_to_menu(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    io = ScriptedIO(["continue", "back"])

    run_campaign_menu(save_path=missing, input_fn=io.input, output_fn=io.output)

    assert "no saved campaign" in _output(io)

    missing.write_text('{"version": 999}', encoding="utf-8")
    io = ScriptedIO(["continue", "back"])
    run_campaign_menu(save_path=missing, input_fn=io.input, output_fn=io.output)
    assert "version" in _output(io)


def test_new_campaign_replacement_or_builder_cancel_preserves_existing_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    old_bytes = path.read_bytes()
    builder_calls = 0

    def builder(**_kwargs: object) -> None:
        nonlocal builder_calls
        builder_calls += 1
        return None

    monkeypatch.setattr(campaign_cmd, "run_fleet_builder", builder)
    io = ScriptedIO(["new", "no", "back"])
    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)
    assert builder_calls == 0
    assert path.read_bytes() == old_bytes

    io = ScriptedIO(["new", "confirm", "imperial_navy", "Replacement", "9", "back"])
    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)
    assert builder_calls == 1
    assert path.read_bytes() == old_bytes


def test_seed_cancellation_does_not_run_builder_or_create_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "save.json"
    monkeypatch.setattr(
        campaign_cmd,
        "run_fleet_builder",
        lambda **_kwargs: pytest.fail("builder must not run after seed cancellation"),
    )
    io = ScriptedIO(["new", "imperial_navy", "Cancelled", "cancel", "back"])

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    assert not path.exists()


def test_new_campaign_uses_800_credit_builder_and_saves_valid_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "save.json"
    seen: dict[str, object] = {}

    def builder(**kwargs: object) -> FleetSpec:
        seen.update(kwargs)
        return supported_fleet()

    monkeypatch.setattr(campaign_cmd, "run_fleet_builder", builder)
    io = ScriptedIO(["new", "imperial_navy", "Admiral Voss", "19", "back"])

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    loaded = load_campaign(path)
    assert seen == {
        "faction": loaded.faction,
        "budget": 800,
        "name": "Admiral Voss",
    }
    assert loaded.seed == 19
    assert loaded.commander.name == "Admiral Voss"


def test_interval_status_shows_stable_ids_damage_credits_and_commander(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    campaign.roster[0].battles_survived = 3
    campaign.commander.xp = 275
    campaign.commander.level = 2
    path = save_campaign(campaign, tmp_path / "save.json")
    io = ScriptedIO(["continue", "status", "help", "back"])

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    output = _output(io)
    assert "ship-1" in output
    assert "test flag" in output
    assert "damage 2" in output
    assert "survived 3" in output
    assert f"credits: {campaign.credits}" in output
    assert "level 2" in output
    assert "xp 275" in output
    assert "flagship" in output
    assert "3=lance_2" in output
    assert "upgrades: (none)" in output
    assert "doctrine: (none)" in output


def test_catalog_marks_campaign_unsupported_content(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    io = ScriptedIO(["continue", "catalog", "help", "back"])

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    output = _output(io)
    assert "hull only" in output
    assert "default loadout" not in output
    assert "standard_torpedoes" in output and "unsupported" in output
    assert "nova_cannon" in output and "unsupported" in output
    assert "power_ram" in output and "unsupported" in output
    assert "automated_reload" in output and "unsupported" in output
    assert "buy adds only the hull" in output
    assert "equip weapons afterwards" in output


def test_hulls_with_unsupported_defaults_can_be_bought_and_equipped(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.credits = 1_000
    path = save_campaign(campaign, tmp_path / "save.json")
    io = ScriptedIO(
        [
            "continue",
            "buy cobra_destroyer Cobra",
            "confirm",
            "equip ship-3 weapon 1 macro_cannon_1",
            "confirm",
            "buy lunar_cruiser Lunar",
            "confirm",
            "equip ship-4 weapon 1 macro_cannon_2",
            "confirm",
            "back",
        ]
    )

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    loaded = load_campaign(path)
    cobra = loaded.roster[2].spec
    lunar = loaded.roster[3].spec
    assert cobra.hull_id == "cobra_destroyer"
    assert cobra.weapons == {1: "macro_cannon_1"}
    assert lunar.hull_id == "lunar_cruiser"
    assert lunar.weapons == {1: "macro_cannon_2"}


def test_store_refits_use_exact_previews_and_autosave_each_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    path = save_campaign(campaign, tmp_path / "save.json")
    real_save = save_campaign
    snapshots: list[CampaignState] = []

    def tracking_save(current: CampaignState, target: Path) -> Path:
        snapshots.append(deepcopy(current))
        return real_save(current, target)

    monkeypatch.setattr(campaign_cmd, "save_campaign", tracking_save)
    io = ScriptedIO(
        [
            "continue",
            "equip ship-1 weapon 3 macro_cannon_2",
            "confirm",
            "remove ship-1 weapon 3",
            "confirm",
            "equip ship-2 upgrade reinforced_prow",
            "confirm",
            "remove ship-2 upgrade reinforced_prow",
            "confirm",
            "equip ship-2 doctrine commissariat",
            "confirm",
            "remove ship-2 doctrine",
            "confirm",
            "repair ship-1",
            "confirm",
            "back",
        ]
    )

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    loaded = load_campaign(path)
    assert len(snapshots) == 7
    assert loaded.roster[0].spec.weapons.get(3) is None
    assert loaded.roster[1].spec.upgrade_ids == []
    assert loaded.roster[1].spec.doctrine_id is None
    assert loaded.roster[0].hull_damage == 0
    output = _output(io)
    assert "charge" in output
    assert "refund" in output
    assert "16 credits" in output


def test_buy_flagship_and_discard_delegate_to_economy_with_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    real_save = save_campaign
    saved_states: list[CampaignState] = []

    def tracking_save(current: CampaignState, target: Path) -> Path:
        saved_states.append(deepcopy(current))
        return real_save(current, target)

    monkeypatch.setattr(campaign_cmd, "save_campaign", tracking_save)
    io = ScriptedIO(
        [
            "continue",
            "BUY sword_frigate Reinforcement",
            "confirm",
            "flagship ship-2",
            "confirm",
            "discard ship-3",
            "cancel",
            "discard ship-1",
            "confirm",
            "back",
        ]
    )

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    loaded = load_campaign(path)
    assert len(saved_states) == 3
    assert [ship.id for ship in loaded.roster] == ["ship-2", "ship-3"]
    assert loaded.flagship_id == "ship-2"
    assert loaded.next_ship_id == 4
    assert loaded.credits == campaign_state().credits - 25
    output = _output(io)
    assert "25 credits" in output
    assert "no refund" in output


def test_insufficient_purchase_does_not_prompt_or_mutate(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.credits = 0
    path = save_campaign(campaign, tmp_path / "save.json")
    before = path.read_bytes()
    io = ScriptedIO(["continue", "buy sword_frigate No Money", "back"])

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    assert path.read_bytes() == before
    output = _output(io)
    assert "insufficient credits" in output


def test_failed_autosave_keeps_memory_and_explicit_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 1
    path = save_campaign(campaign, tmp_path / "save.json")
    real_save = save_campaign
    calls = 0

    def flaky_save(current: CampaignState, target: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CampaignSaveError("disk full")
        return real_save(current, target)

    monkeypatch.setattr(campaign_cmd, "save_campaign", flaky_save)
    io = ScriptedIO(["continue", "repair ship-1", "confirm", "save", "back"])

    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)

    assert calls == 2
    assert load_campaign(path).roster[0].hull_damage == 0
    output = _output(io)
    assert "unsaved" in output
    assert "saved" in output


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
    io = ScriptedIO(["continue", "battle", "back"])

    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=AbandoningController,
    )

    assert AbandoningController.calls == 0
    assert "flagship" in _output(io) or "fleet" in _output(io)


def test_selecting_flagship_after_loss_allows_battle(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.flagship_id = None
    path = save_campaign(campaign, tmp_path / "save.json")
    AbandoningController.calls = 0
    io = ScriptedIO(["continue", "flagship ship-2", "confirm", "battle", "back"])

    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=AbandoningController,
    )

    assert AbandoningController.calls == 1
    assert load_campaign(path).flagship_id == "ship-2"


def test_abandoned_battle_does_not_close_or_save(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    old_bytes = path.read_bytes()
    io = ScriptedIO(["continue", "battle", "back"])

    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=AbandoningController,
    )

    assert path.read_bytes() == old_bytes
    assert "unchanged" in _output(io)


def test_continue_links_two_battles_through_store(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    io = ScriptedIO(
        [
            "continue",
            "battle",
            "buy sword_frigate Reinforcement",
            "confirm",
            "battle",
            "back",
        ]
    )

    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=WinningController,
    )

    loaded = load_campaign(path)
    assert loaded.encounter == 3
    assert any(ship.spec.name == "Reinforcement" for ship in loaded.roster)
    assert "credits awarded" in _output(io)


def test_battle_report_shows_casualty_names_and_updated_persistent_state(
    tmp_path: Path,
) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")

    class CostlyVictory(LocalBattleController):
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

    io = ScriptedIO(["continue", "battle", "back"])
    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=CostlyVictory,
    )

    output = _output(io)
    assert "casualties: ship-2 (test escort)" in output
    assert "damage 1" in output
    assert "level 2" in output and "xp 275" in output
    assert "credits:" in output


def test_terminal_autosave_failure_allows_retry_but_not_another_battle(
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
    io = ScriptedIO(["continue", "battle", "battle", "save", "back"])
    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=CountingVictory,
    )

    assert battle_calls == 1
    assert save_calls == 2
    assert load_campaign(path).status is CampaignStatus.COMPLETED
    output = _output(io)
    assert "unsaved" in output
    assert "must be active" in output
    assert "campaign saved" in output


def test_fifth_victory_reports_completion_and_terminal_continue_starts_no_battle(
    tmp_path: Path,
) -> None:
    campaign = campaign_state()
    campaign.encounter = 5
    path = save_campaign(campaign, tmp_path / "save.json")
    io = ScriptedIO(["continue", "battle"])

    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=WinningController,
    )

    assert load_campaign(path).status is CampaignStatus.COMPLETED
    assert "campaign completed" in _output(io)

    AbandoningController.calls = 0
    io = ScriptedIO(["continue", "back"])
    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=AbandoningController,
    )
    assert AbandoningController.calls == 0
    assert "completed" in _output(io)


@pytest.mark.parametrize(
    "outcome",
    [BattleOutcome.DEFEAT, BattleOutcome.SURRENDER, BattleOutcome.TURN_LIMIT],
)
def test_every_defeat_outcome_reports_terminal_status(
    tmp_path: Path, outcome: BattleOutcome
) -> None:
    path = save_campaign(campaign_state(), tmp_path / f"{outcome.value}.json")

    class LosingController(LocalBattleController):
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

    io = ScriptedIO(["continue", "battle"])
    run_campaign_menu(
        save_path=path,
        input_fn=io.input,
        output_fn=io.output,
        controller_factory=LosingController,
    )

    loaded = load_campaign(path)
    assert loaded.status is CampaignStatus.DEFEATED
    assert outcome.value.replace("_", " ") in _output(io)
    assert "campaign defeated" in _output(io)


def test_app_routes_campaign_menu_from_one_stable_item(monkeypatch: pytest.MonkeyPatch) -> None:
    from spacefleet.cli import app

    calls = 0

    def run_menu() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(campaign_cmd, "run_campaign_menu", run_menu)
    answers = iter(["4", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)

    app.main()

    assert calls == 1
