from __future__ import annotations

from copy import deepcopy

import pytest

from spacefleet.campaign.battle import build_battle
from spacefleet.campaign.models import CampaignStatus
from spacefleet.commander.commander import AbilityState, ActiveBuff
from spacefleet.commander.passive_skills import PassiveContext, PassiveHook
from spacefleet.core.types import Stance
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.models.fleet_spec import FleetSpecError
from tests.campaign_helpers import campaign_state


def test_build_battle_restores_identity_damage_crew_and_commander_before_passives() -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    campaign.roster[0].battles_survived = 3
    campaign.commander.xp = 275
    campaign.commander.passive_skill_ids = ["swift_maneuvers"]

    session = build_battle(campaign)

    runtime_id = session.player_runtime_by_campaign[campaign.roster[0].id]
    ship = session.state.ships[runtime_id]
    runtime_commander = session.state.fleets["player"].commander
    assert ship.hull_current == ship.hull_max - 2
    assert ship.battles_survived == 3
    assert runtime_commander is not None
    assert runtime_commander is not campaign.commander
    assert runtime_commander.xp == 275
    assert session.state.passives is not None
    context = PassiveContext(
        ship=ship,
        fleet=session.state.fleets["player"],
        state=session.state,
        value=0,
    )
    assert session.state.passives.dispatch(PassiveHook.FLEET_SPEED_MAX, context) == 5


def test_mapping_survives_roster_reorder() -> None:
    campaign = campaign_state()
    campaign.roster.reverse()

    session = build_battle(campaign)

    assert set(session.player_runtime_by_campaign) == {ship.id for ship in campaign.roster}
    assert len(set(session.player_runtime_by_campaign.values())) == len(campaign.roster)
    for saved in campaign.roster:
        runtime_id = session.player_runtime_by_campaign[saved.id]
        assert session.state.ships[runtime_id].name == saved.spec.name
    assert (
        session.state.fleets["player"].flagship_ship_id
        == session.player_runtime_by_campaign[campaign.flagship_id]
    )


def test_build_battle_is_deterministic_and_uses_encounter_preset() -> None:
    campaign = campaign_state()
    campaign.encounter = 3

    first = build_battle(campaign)
    second = build_battle(campaign)

    assert first.battle_id == second.battle_id == "7:3"
    assert first.encounter == 3
    assert first.state.dice.roll_d6(5) == second.state.dice.roll_d6(5)
    assert [first.state.ships[ship_id].hull.id for ship_id in first.enemy_runtime_ids] == [
        "murder_cruiser",
        "slaughter_cruiser",
    ]
    assert first.initial_enemy_count == 2
    assert first.state.ai_ships == first.enemy_runtime_ids


def test_runtime_flagship_and_commander_state_are_fresh() -> None:
    campaign = campaign_state()
    campaign.roster[0].spec.upgrade_ids.append("navigators_chamber")
    campaign.commander.level = 3
    campaign.commander.active_ability_ids.append("micro_warp_jump")
    campaign.commander.ability_state["micro_warp_jump"] = AbilityState(
        remaining_charges=0,
        cooldown_remaining=4,
        preparation_turns_left=2,
    )
    campaign.commander.active_buffs.append(
        ActiveBuff(id="old", source_ability_id="concentrated_fire", turns_remaining=2)
    )
    saved_before = deepcopy(campaign)

    session = build_battle(campaign)

    fleet = session.state.fleets["player"]
    assert fleet.flagship_ship_id == session.player_runtime_by_campaign[campaign.flagship_id]
    assert fleet.commander_name == campaign.commander.name
    assert fleet.commander is not None
    assert fleet.commander.id == campaign.commander.id
    assert fleet.commander.name == campaign.commander.name
    assert fleet.commander.faction is campaign.commander.faction
    assert fleet.commander.level == 3
    assert fleet.commander.xp == campaign.commander.xp
    assert fleet.commander.active_ability_ids == campaign.commander.active_ability_ids
    assert fleet.commander.active_ability_ids is not campaign.commander.active_ability_ids
    assert fleet.commander.passive_skill_ids == campaign.commander.passive_skill_ids
    assert fleet.commander.passive_skill_ids is not campaign.commander.passive_skill_ids
    ability = fleet.commander.ability_state["micro_warp_jump"]
    base_charges = SkillRegistry.get_active("micro_warp_jump").charges  # type: ignore[union-attr]
    assert ability.remaining_charges == base_charges + 1
    assert ability.cooldown_remaining == 0
    assert ability.preparation_turns_left == 0
    assert ability.pending_order is None
    assert fleet.commander.active_buffs == []
    assert campaign == saved_before


def test_runtime_ship_transient_state_starts_fresh() -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 1

    session = build_battle(campaign)

    ship = session.state.ships[session.player_runtime_by_campaign[campaign.roster[0].id]]
    assert ship.hull_current == ship.hull_max - 1
    assert ship.shields_current == ship.shields_max
    assert ship.morale == ship.morale_max
    assert ship.fires == 0
    assert ship.subsystems.all_operational()
    assert ship.stance is Stance.STANDARD
    assert ship.stance_cooldown_remaining == 0
    assert ship.combustion == ship.combustion_max
    assert ship.crit_temporary_repairs == []
    assert ship.pending_turn == 0.0


@pytest.mark.parametrize("status", [CampaignStatus.COMPLETED, CampaignStatus.DEFEATED])
def test_build_battle_rejects_terminal_campaign(status: CampaignStatus) -> None:
    campaign = campaign_state()
    campaign.status = status
    before = deepcopy(campaign)

    with pytest.raises(FleetSpecError, match="active"):
        build_battle(campaign)

    assert campaign == before


@pytest.mark.parametrize("invalid_state", ["empty", "missing_flagship", "damage", "eligibility"])
def test_build_battle_rejects_invalid_campaign_without_mutating_it(invalid_state: str) -> None:
    campaign = campaign_state()
    if invalid_state == "empty":
        campaign.roster.clear()
        campaign.flagship_id = None
    elif invalid_state == "missing_flagship":
        campaign.flagship_id = None
    elif invalid_state == "damage":
        campaign.roster[0].hull_damage = -1
    else:
        campaign.roster[0].spec.weapons[3] = "standard_torpedoes"
    before = deepcopy(campaign)

    with pytest.raises((FleetSpecError, ValueError)):
        build_battle(campaign)

    assert campaign == before
