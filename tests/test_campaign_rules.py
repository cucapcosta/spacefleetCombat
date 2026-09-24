from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.models import CampaignStatus
from spacefleet.campaign.rules import (
    campaign_fleet_spec,
    enemy_fleet_for,
    new_campaign,
    validate_campaign_fleet,
    validate_campaign_state,
)
from spacefleet.core.types import Faction
from spacefleet.models.fleet_spec import FleetSpecError, fleet_points, validate_fleet_spec
from tests.campaign_helpers import campaign_state, supported_fleet

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.models.fleet_spec import FleetSpec


def test_new_campaign_converts_builder_remainder_to_real_credits() -> None:
    fleet = supported_fleet()

    campaign = new_campaign(fleet, "Admiral Voss", seed=41)

    assert campaign.fleet_name == fleet.name
    assert campaign.credits == 800 - fleet_points(fleet)
    assert [ship.id for ship in campaign.roster] == ["ship-1", "ship-2"]
    assert campaign.next_ship_id == 3
    assert campaign.flagship_id == "ship-1"
    assert campaign.commander.name == "Admiral Voss"
    assert campaign.status is CampaignStatus.ACTIVE


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda fleet: fleet.ships[0].weapons.__setitem__(3, "standard_torpedoes"), "torpedo"),
        (lambda fleet: fleet.ships[0].upgrade_ids.append("power_ram"), "power_ram"),
        (lambda fleet: fleet.ships[0].upgrade_ids.append("automated_reload"), "automated_reload"),
    ],
)
def test_campaign_eligibility_rejects_implemented_later_fleet_content(
    mutate: Callable[[FleetSpec], None], message: str
) -> None:
    fleet = supported_fleet()
    mutate(fleet)

    with pytest.raises((FleetSpecError, ValueError), match=message):
        validate_campaign_fleet(fleet)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("active_ability_ids", ["augur_probe"], "augur_probe"),
        ("active_ability_ids", ["torpedo_barrage"], "torpedo_barrage"),
        ("passive_skill_ids", ["short_burn_torpedoes"], "short_burn_torpedoes"),
        ("passive_skill_ids", ["reload_drills"], "reload_drills"),
        ("active_ability_ids", ["not_in_catalog"], "not_in_catalog"),
        ("trait_ids", ["veteran_of_cadia"], "traits"),
    ],
)
def test_campaign_eligibility_rejects_unsupported_commander_content(
    field: str, value: list[str], message: str
) -> None:
    campaign = campaign_state()
    setattr(campaign.commander, field, value)

    with pytest.raises(FleetSpecError, match=message):
        validate_campaign_fleet(campaign_fleet_spec(campaign), campaign.commander)


def test_campaign_eligibility_rejects_foreign_faction_commander_content() -> None:
    campaign = campaign_state(Faction.CHAOS_FLEET)
    campaign.commander.active_ability_ids = ["boarding_assault"]

    with pytest.raises(FleetSpecError, match="faction"):
        validate_campaign_fleet(campaign_fleet_spec(campaign), campaign.commander)


def test_improved_augur_array_remains_supported() -> None:
    fleet = supported_fleet()
    fleet.ships[1].upgrade_ids.append("improved_augur_array")

    validate_campaign_fleet(fleet)


def test_enemy_presets_are_legal_supported_and_strictly_increase_in_cost() -> None:
    for player_faction in Faction:
        fleets = [enemy_fleet_for(player_faction, encounter) for encounter in range(1, 6)]
        for fleet in fleets:
            validate_fleet_spec(fleet)
            validate_campaign_fleet(fleet)
        assert [fleet_points(fleet) for fleet in fleets] == sorted(
            {fleet_points(fleet) for fleet in fleets}
        )


@pytest.mark.parametrize("encounter", [0, 6])
def test_enemy_presets_reject_unknown_encounters(encounter: int) -> None:
    with pytest.raises(ValueError, match="encounter"):
        enemy_fleet_for(Faction.IMPERIAL_NAVY, encounter)


def test_interval_state_allows_empty_roster_without_flagship() -> None:
    campaign = campaign_state()
    campaign.roster.clear()
    campaign.flagship_id = None

    validate_campaign_state(campaign)
    with pytest.raises(FleetSpecError, match="battle-ready"):
        validate_campaign_state(campaign, require_battle_ready=True)


def test_interval_state_allows_missing_flagship_but_battle_does_not() -> None:
    campaign = campaign_state()
    campaign.flagship_id = None

    validate_campaign_state(campaign)
    with pytest.raises(FleetSpecError, match="flagship"):
        validate_campaign_state(campaign, require_battle_ready=True)


@pytest.mark.parametrize("status", [CampaignStatus.COMPLETED, CampaignStatus.DEFEATED])
def test_terminal_campaign_is_valid_to_store_but_cannot_start_battle(
    status: CampaignStatus,
) -> None:
    campaign = campaign_state()
    campaign.status = status

    validate_campaign_state(campaign)
    with pytest.raises(FleetSpecError, match="active"):
        validate_campaign_state(campaign, require_battle_ready=True)


def test_campaign_state_rejects_duplicate_or_stale_stable_ids() -> None:
    duplicate = campaign_state()
    duplicate.roster[1].id = "ship-1"
    with pytest.raises(FleetSpecError, match="duplicate"):
        validate_campaign_state(duplicate)

    stale = campaign_state()
    stale.next_ship_id = 2
    with pytest.raises(FleetSpecError, match="next ship"):
        validate_campaign_state(stale)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "paused", "status"),
        ("faction", "imperial_navy", "faction"),
    ],
)
def test_campaign_state_rejects_invalid_enums(field: str, value: str, message: str) -> None:
    campaign = campaign_state()
    setattr(campaign, field, value)

    with pytest.raises(FleetSpecError, match=message):
        validate_campaign_state(campaign)


def test_campaign_copies_initial_specs() -> None:
    fleet = supported_fleet()
    campaign = new_campaign(fleet, "Admiral Voss", seed=41)

    fleet.ships[0].name = "Mutated outside campaign"

    assert campaign.roster[0].spec.name == "Test Flag"
    assert campaign_fleet_spec(deepcopy(campaign)).name == "Test Fleet"
