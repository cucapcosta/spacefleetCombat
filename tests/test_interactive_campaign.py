from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.models import CampaignStatus
from spacefleet.campaign.rules import validate_campaign_fleet
from spacefleet.cli import campaign_cmd
from spacefleet.cli.campaign_cmd import run_campaign_menu
from spacefleet.persistence.campaign_save import CampaignSaveError, load_campaign, save_campaign
from tests.campaign_helpers import campaign_state, supported_fleet
from tests.terminal_ui_helpers import FakeTerminalUI

if TYPE_CHECKING:
    from pathlib import Path

    from spacefleet.campaign.models import CampaignState
    from spacefleet.models.fleet_spec import FleetSpec


def _shown(ui: FakeTerminalUI) -> str:
    return "\n".join(ui.show_calls).lower()


def test_campaign_menu_uses_selectors_and_text_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def builder(**kwargs: object) -> FleetSpec:
        seen.update(kwargs)
        return supported_fleet()

    monkeypatch.setattr(campaign_cmd, "run_fleet_builder", builder)
    ui = FakeTerminalUI(
        choices=["new", "imperial_navy", "save", "back"],
        texts=["Admiral Voss", "19"],
    )
    path = tmp_path / "campaign.json"

    run_campaign_menu(save_path=path, ui=ui)

    saved = load_campaign(path)
    assert (saved.commander.name, saved.seed) == ("Admiral Voss", 19)
    assert ("Campaign seed", "campaign.seed", "") in ui.text_calls
    assert seen["ui"] is ui
    assert seen["candidate_validator"] is validate_campaign_fleet
    assert seen["budget"] == 800


def test_continue_missing_or_invalid_save_returns_to_menu(tmp_path: Path) -> None:
    path = tmp_path / "campaign.json"
    ui = FakeTerminalUI(choices=["continue", "back"])
    run_campaign_menu(save_path=path, ui=ui)
    assert "no saved campaign" in _shown(ui)

    path.write_text('{"version": 999}', encoding="utf-8")
    ui = FakeTerminalUI(choices=["continue", "back"])
    run_campaign_menu(save_path=path, ui=ui)
    assert "version" in _shown(ui)


def test_overwrite_and_builder_cancel_preserve_existing_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = save_campaign(campaign_state(), tmp_path / "campaign.json")
    before = path.read_bytes()
    calls = 0

    def builder(**_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(campaign_cmd, "run_fleet_builder", builder)
    ui = FakeTerminalUI(choices=["new", "back"], confirmations=[False])
    run_campaign_menu(save_path=path, ui=ui)
    assert calls == 0
    assert path.read_bytes() == before

    ui = FakeTerminalUI(
        choices=["new", "imperial_navy", "back"],
        texts=["Replacement", "9"],
        confirmations=[True],
    )
    run_campaign_menu(save_path=path, ui=ui)
    assert calls == 1
    assert path.read_bytes() == before


def test_interval_context_contains_status_and_back_preserves_save(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    campaign.roster[0].battles_survived = 3
    path = save_campaign(campaign, tmp_path / "campaign.json")
    before = path.read_bytes()
    ui = FakeTerminalUI(choices=["continue", "back"])

    run_campaign_menu(save_path=path, ui=ui)

    interval = next(call for call in ui.choose_calls if call[0] == "Campaign interval")
    context = interval[2].lower()
    assert "1. test flag — dauntless-class light cruiser" in context
    assert "damage 2" in context and "survived 3" in context
    assert "lance mk.ii" in context
    assert "lance_2" not in context and "dauntless_light_cruiser" not in context
    assert "next enemy" in context and "credits:" in context
    assert path.read_bytes() == before


def test_buy_hull_refit_flagship_discard_and_autosave(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.credits = 1_000
    path = save_campaign(campaign, tmp_path / "campaign.json")
    ui = FakeTerminalUI(
        choices=[
            "continue",
            "buy",
            "sword_frigate",
            "manage",
            "ship-3",
            "weapon:1",
            "macro_cannon_1",
            "flagship",
            "back",
            "back",
            "manage",
            "ship-1",
            "discard",
            "back",
            "back",
        ],
        texts=["Reinforcement"],
        confirmations=[True, True, True, True],
    )

    run_campaign_menu(save_path=path, ui=ui)

    loaded = load_campaign(path)
    assert [ship.id for ship in loaded.roster] == ["ship-2", "ship-3"]
    assert loaded.roster[1].spec.weapons == {1: "macro_cannon_1"}
    assert loaded.flagship_id == "ship-3"
    ship_menu = next(call for call in ui.choose_calls if call[0] == "Manage ship")
    assert "Credits: 975" in ship_menu[2]
    assert "Forward Battery | prow | small | Empty" in ship_menu[2]


def test_refit_confirmation_cancel_preserves_save_bytes(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "campaign.json")
    before = path.read_bytes()
    ui = FakeTerminalUI(
        choices=[
            "continue",
            "manage",
            "ship-1",
            "weapon:3",
            "macro_cannon_2",
            "back",
            "back",
            "back",
        ],
        confirmations=[False],
    )

    run_campaign_menu(save_path=path, ui=ui)

    assert path.read_bytes() == before


def test_refit_options_classify_compatibility_and_insufficient_credits(
    tmp_path: Path,
) -> None:
    campaign = campaign_state()
    campaign.credits = 0
    path = save_campaign(campaign, tmp_path / "campaign.json")
    before = path.read_bytes()
    ui = FakeTerminalUI(
        choices=["continue", "manage", "ship-1", "weapon:3", None, "back", "back", "back"]
    )

    run_campaign_menu(save_path=path, ui=ui)

    fitting = next(call for call in ui.choose_calls if call[0] == "Choose weapon")
    options = {option.value: option for option in fitting[1]}
    assert "macro_cannon_2" in options
    assert options["macro_cannon_2"].disabled_reason == "insufficient credits"
    assert "resulting credits -8" in options["macro_cannon_2"].details
    assert "standard_torpedoes" not in options
    assert path.read_bytes() == before


def test_repair_confirmation_applies_exact_candidate_and_autosaves(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    path = save_campaign(campaign, tmp_path / "campaign.json")
    ui = FakeTerminalUI(
        choices=["continue", "repair", "ship-1", "back"],
        confirmations=[True],
    )

    run_campaign_menu(save_path=path, ui=ui)

    loaded = load_campaign(path)
    assert loaded.roster[0].hull_damage == 0
    assert loaded.credits == campaign.credits - 16


def test_failed_autosave_keeps_memory_and_explicit_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 1
    path = save_campaign(campaign, tmp_path / "campaign.json")
    real_save = save_campaign
    calls = 0
    snapshots: list[CampaignState] = []

    def flaky_save(current: CampaignState, target: Path) -> Path:
        nonlocal calls
        calls += 1
        snapshots.append(deepcopy(current))
        if calls == 1:
            raise CampaignSaveError("disk full")
        return real_save(current, target)

    monkeypatch.setattr(campaign_cmd, "save_campaign", flaky_save)
    ui = FakeTerminalUI(
        choices=["continue", "repair", "ship-1", "save", "back"],
        confirmations=[True],
    )

    run_campaign_menu(save_path=path, ui=ui)

    assert calls == 2
    assert snapshots[0].roster[0].hull_damage == 0
    assert load_campaign(path).roster[0].hull_damage == 0
    assert "unsaved" in _shown(ui) and "saved" in _shown(ui)


@pytest.mark.parametrize("status", [CampaignStatus.COMPLETED, CampaignStatus.DEFEATED])
def test_terminal_continue_has_only_save_and_back_enabled(
    tmp_path: Path,
    status: CampaignStatus,
) -> None:
    campaign = campaign_state()
    campaign.status = status
    path = save_campaign(campaign, tmp_path / "campaign.json")
    ui = FakeTerminalUI(choices=["continue", "manage", "buy", "repair", "battle", "save", "back"])

    run_campaign_menu(save_path=path, ui=ui)

    interval = next(call for call in ui.choose_calls if call[0] == "Campaign interval")
    by_value = {option.value: option for option in interval[1]}
    for value in ("battle", "manage", "buy", "repair"):
        assert by_value[value].disabled_reason == f"campaign is {status.value}"
    assert by_value["save"].disabled_reason is None
    assert by_value["back"].disabled_reason is None
    assert not any(
        call[0] in {"Manage ships", "Buy hull", "Repair ships"} for call in ui.choose_calls
    )
    assert "campaign saved" in _shown(ui)
