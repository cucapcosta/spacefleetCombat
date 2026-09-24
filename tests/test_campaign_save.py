from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import TYPE_CHECKING, Any, cast

import pytest

from spacefleet.campaign.models import CampaignStatus
from spacefleet.commander.commander import ActiveBuff
from spacefleet.persistence.campaign_save import (
    CAMPAIGN_SAVE_VERSION,
    CampaignSaveError,
    campaign_to_dict,
    default_campaign_path,
    load_campaign,
    save_campaign,
)
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _write_payload(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_campaign_round_trip_preserves_persistent_state_and_discards_runtime(
    tmp_path: Path,
) -> None:
    campaign = campaign_state()
    campaign.commander.xp = 250
    campaign.commander.level = 2
    campaign.roster[0].hull_damage = 1
    campaign.roster[0].battles_survived = 4
    campaign.last_resolved_battle_id = "battle-previous"
    campaign.commander.active_buffs.append(
        ActiveBuff(id="focus", source_ability_id="concentrated_fire", turns_remaining=2)
    )

    path = save_campaign(campaign, tmp_path / "campaign.json")
    loaded = load_campaign(path)

    assert loaded.fleet_name == campaign.fleet_name
    assert loaded.seed == campaign.seed
    assert loaded.encounter == campaign.encounter
    assert loaded.status is campaign.status
    assert loaded.credits == campaign.credits
    assert loaded.next_ship_id == campaign.next_ship_id
    assert loaded.faction is campaign.faction
    assert loaded.roster == campaign.roster
    assert loaded.flagship_id == campaign.flagship_id
    assert loaded.last_resolved_battle_id == "battle-previous"
    assert loaded.commander.id == campaign.commander.id
    assert loaded.commander.name == campaign.commander.name
    assert loaded.commander.faction is campaign.commander.faction
    assert loaded.commander.level == 2
    assert loaded.commander.xp == 250
    assert loaded.commander.active_ability_ids == campaign.commander.active_ability_ids
    assert loaded.commander.passive_skill_ids == campaign.commander.passive_skill_ids
    assert loaded.commander.trait_ids == []
    assert loaded.commander.ability_state == {}
    assert loaded.commander.active_buffs == []


def test_valid_interval_round_trips_without_flagship(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.flagship_id = None

    loaded = load_campaign(save_campaign(campaign, tmp_path / "campaign.json"))

    assert loaded.roster == campaign.roster
    assert loaded.flagship_id is None


def test_terminal_empty_roster_round_trips(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.status = CampaignStatus.DEFEATED
    campaign.roster.clear()
    campaign.flagship_id = None

    loaded = load_campaign(save_campaign(campaign, tmp_path / "campaign.json"))

    assert loaded.status is CampaignStatus.DEFEATED
    assert loaded.roster == []
    assert loaded.flagship_id is None


@pytest.mark.parametrize("payload", ["not json", '{"version": 999}'])
def test_invalid_or_unknown_save_does_not_replace_current_session(
    tmp_path: Path, payload: str
) -> None:
    current = campaign_state()
    before = deepcopy(current)
    path = tmp_path / "bad.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(CampaignSaveError):
        load_campaign(path)

    assert current == before


@pytest.mark.parametrize(
    "bad_credit",
    [True, -1, 1.0, float("nan"), float("inf"), -float("inf"), "10"],
)
def test_malformed_or_nonfinite_credit_is_rejected(tmp_path: Path, bad_credit: object) -> None:
    data = campaign_to_dict(campaign_state())
    data["credits"] = bad_credit
    path = tmp_path / "bad-number.json"
    _write_payload(path, data)

    with pytest.raises(CampaignSaveError, match="credits"):
        load_campaign(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", True),
        ("seed", -1),
        ("encounter", False),
        ("encounter", 0),
        ("encounter", 6),
        ("next_ship_id", True),
        ("next_ship_id", 0),
    ],
)
def test_invalid_top_level_integer_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    data = campaign_to_dict(campaign_state())
    data[field] = value
    path = tmp_path / "bad.json"
    _write_payload(path, data)

    message = "next[_ ]ship" if field == "next_ship_id" else field
    with pytest.raises(CampaignSaveError, match=message):
        load_campaign(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["roster"][1].__setitem__("id", "ship-1"), "duplicate"),
        (lambda data: data.__setitem__("next_ship_id", 2), "next ship"),
        (lambda data: data.__setitem__("flagship_id", "ship-99"), "flagship"),
        (lambda data: data["commander"].__setitem__("faction", "chaos_fleet"), "faction"),
        (lambda data: data["commander"].__setitem__("trait_ids", ["veteran"]), "trait"),
        (
            lambda data: data["commander"].__setitem__("active_ability_ids", ["not_in_catalog"]),
            "not_in_catalog",
        ),
        (
            lambda data: data["roster"][1]["spec"].__setitem__("upgrade_ids", ["power_ram"]),
            "power_ram",
        ),
        (
            lambda data: data["roster"][1]["spec"].__setitem__(
                "upgrade_ids", ["navigators_chamber"]
            ),
            "flagship",
        ),
    ],
)
def test_invalid_campaign_invariants_are_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    data = campaign_to_dict(campaign_state())
    mutate(data)
    path = tmp_path / "invalid-state.json"
    _write_payload(path, data)

    with pytest.raises(CampaignSaveError, match=message):
        load_campaign(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.__setitem__("roster", {}), "roster"),
        (lambda data: data["roster"][0].__setitem__("spec", []), "spec"),
        (lambda data: data["roster"][0]["spec"].__setitem__("weapons", []), "weapons"),
        (lambda data: data["roster"][0]["spec"].__setitem__("upgrade_ids", {}), "upgrade_ids"),
        (
            lambda data: data["commander"].__setitem__("active_ability_ids", "concentrated_fire"),
            "active_ability_ids",
        ),
        (lambda data: data["roster"][0].__setitem__("hull_damage", True), "hull_damage"),
        (lambda data: data["roster"][0].__setitem__("battles_survived", 1.0), "battles_survived"),
        (lambda data: data["commander"].__setitem__("level", True), "level"),
        (lambda data: data["commander"].__setitem__("xp", -1), "xp"),
        (lambda data: data.__setitem__("last_resolved_battle_id", 7), "last_resolved"),
    ],
)
def test_malformed_nested_values_are_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    data = campaign_to_dict(campaign_state())
    mutate(data)
    path = tmp_path / "malformed.json"
    _write_payload(path, data)

    with pytest.raises(CampaignSaveError, match=message):
        load_campaign(path)


def test_noncanonical_weapon_slot_key_is_rejected(tmp_path: Path) -> None:
    data = campaign_to_dict(campaign_state())
    data["roster"][0]["spec"]["weapons"]["01"] = "macro_cannon_2"
    path = tmp_path / "bad-slot.json"
    _write_payload(path, data)

    with pytest.raises(CampaignSaveError, match="weapon slot"):
        load_campaign(path)


def test_failed_replace_preserves_old_file_cleans_temp_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = campaign_state()
    original.credits = 10
    path = save_campaign(original, tmp_path / "campaign.json")
    old_bytes = path.read_bytes()
    replacement = campaign_state()
    replacement.credits = 99
    real_replace = os.replace

    def fail_replace(_source: str | bytes, _target: str | bytes) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(CampaignSaveError, match="disk"):
        save_campaign(replacement, path)
    assert path.read_bytes() == old_bytes
    assert list(tmp_path.glob(".campaign.json.*.tmp")) == []

    monkeypatch.setattr(os, "replace", real_replace)
    save_campaign(replacement, path)
    assert load_campaign(path).credits == 99


def test_invalid_campaign_is_validated_before_old_save_is_replaced(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "campaign.json")
    old_bytes = path.read_bytes()
    invalid = campaign_state()
    invalid.credits = -1

    with pytest.raises(CampaignSaveError, match="credits"):
        save_campaign(invalid, path)

    assert path.read_bytes() == old_bytes
    assert list(tmp_path.glob(".campaign.json.*.tmp")) == []


def test_malformed_in_memory_campaign_is_wrapped_before_writing(tmp_path: Path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "campaign.json")
    old_bytes = path.read_bytes()
    invalid = campaign_state()
    invalid.status = cast("Any", "active")

    with pytest.raises(CampaignSaveError, match="status"):
        save_campaign(invalid, path)

    assert path.read_bytes() == old_bytes
    assert list(tmp_path.glob(".campaign.json.*.tmp")) == []


def test_parent_creation_and_missing_file_errors_are_wrapped(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("block", encoding="utf-8")

    with pytest.raises(CampaignSaveError, match="could not save"):
        save_campaign(campaign_state(), blocker / "campaign.json")
    with pytest.raises(CampaignSaveError, match="could not load"):
        load_campaign(tmp_path / "missing.json")


def test_default_campaign_path_uses_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert default_campaign_path() == tmp_path / "campaign-save.json"
    assert CAMPAIGN_SAVE_VERSION == 1
