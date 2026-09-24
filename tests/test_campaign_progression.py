"""Battle closure persists one validated campaign interval exactly once."""

from __future__ import annotations

from copy import deepcopy

import pytest

from spacefleet.campaign import battle
from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.commander.commander import ActiveBuff
from spacefleet.net.turn_resolver import resolve_turn
from tests.campaign_helpers import campaign_state


def _destroy_ship(session: battle.BattleSession, runtime_id: str) -> None:
    ship = session.state.ships[runtime_id]
    ship.take_hull_damage(ship.hull_current)


def _resolve_victory(session: battle.BattleSession) -> None:
    for enemy_id in session.enemy_runtime_ids:
        _destroy_ship(session, enemy_id)
    resolve_turn(session.state, {})


def test_victory_copies_resolver_progress_and_rewards_once() -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)
    damaged_id = campaign.roster[0].id
    damaged_runtime = session.player_runtime_by_campaign[damaged_id]
    session.state.ships[damaged_runtime].take_hull_damage(2)
    _resolve_victory(session)
    runtime_commander = session.state.fleets["player"].commander
    assert runtime_commander is not None
    xp_after_resolver = runtime_commander.xp

    report = battle.close_battle(campaign, session, BattleOutcome.VICTORY)

    assert report.credits_awarded == 100 + 20 * session.initial_enemy_count + 15 * 2
    assert campaign.commander.xp == xp_after_resolver
    assert campaign.roster[0].hull_damage == 2
    assert [ship.battles_survived for ship in campaign.roster] == [1, 1]
    assert campaign.encounter == 2
    assert campaign.status is CampaignStatus.ACTIVE
    before = deepcopy(campaign)
    with pytest.raises(ValueError, match="already resolved"):
        battle.close_battle(campaign, session, BattleOutcome.VICTORY)
    assert campaign == before


def test_victory_removes_casualties_using_stable_mapping() -> None:
    campaign = campaign_state()
    lost_id = campaign.roster[1].id
    session = battle.build_battle(campaign)
    _destroy_ship(session, session.player_runtime_by_campaign[lost_id])
    _resolve_victory(session)

    report = battle.close_battle(campaign, session, BattleOutcome.VICTORY)

    assert report.casualties == (lost_id,)
    assert report.player_survivors == 1
    assert [ship.id for ship in campaign.roster] == [campaign.flagship_id]
    assert report.credits_awarded == 100 + 20 * session.initial_enemy_count + 15


def test_closure_uses_captured_mapping_after_campaign_roster_reorder() -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)
    first_id, second_id = (ship.id for ship in campaign.roster)
    first_runtime = session.state.ships[session.player_runtime_by_campaign[first_id]]
    second_runtime = session.state.ships[session.player_runtime_by_campaign[second_id]]
    first_runtime.take_hull_damage(1)
    first_runtime.battles_survived = 3
    second_runtime.battles_survived = 6
    campaign.roster.reverse()
    _resolve_victory(session)

    battle.close_battle(campaign, session, BattleOutcome.VICTORY)

    persisted = {ship.id: ship for ship in campaign.roster}
    assert persisted[first_id].hull_damage == 1
    assert persisted[first_id].battles_survived == 4
    assert persisted[second_id].hull_damage == 0
    assert persisted[second_id].battles_survived == 7


def test_destroyed_flagship_is_cleared_while_commander_survives() -> None:
    campaign = campaign_state()
    flagship_id = campaign.flagship_id
    assert flagship_id is not None
    session = battle.build_battle(campaign)
    _destroy_ship(session, session.player_runtime_by_campaign[flagship_id])
    _resolve_victory(session)

    battle.close_battle(campaign, session, BattleOutcome.VICTORY)

    assert campaign.flagship_id is None
    assert campaign.commander.name == "Test Commander"


def test_commander_copy_has_no_runtime_state_or_mutable_aliases() -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)
    runtime = session.state.fleets["player"].commander
    assert runtime is not None
    runtime.active_buffs.append(
        ActiveBuff(id="battle", source_ability_id="concentrated_fire", turns_remaining=2)
    )
    first_state = next(iter(runtime.ability_state.values()))
    first_state.cooldown_remaining = 4
    _resolve_victory(session)

    battle.close_battle(campaign, session, BattleOutcome.VICTORY)

    assert campaign.commander.active_ability_ids == runtime.active_ability_ids
    assert campaign.commander.active_ability_ids is not runtime.active_ability_ids
    assert campaign.commander.passive_skill_ids == runtime.passive_skill_ids
    assert campaign.commander.passive_skill_ids is not runtime.passive_skill_ids
    assert campaign.commander.trait_ids == runtime.trait_ids
    assert campaign.commander.trait_ids is not runtime.trait_ids
    assert campaign.commander.ability_state == {}
    assert campaign.commander.active_buffs == []


def test_defeat_is_terminal_and_awards_no_credits() -> None:
    campaign = campaign_state()
    starting_credits = campaign.credits
    session = battle.build_battle(campaign)
    for runtime_id in session.player_runtime_by_campaign.values():
        _destroy_ship(session, runtime_id)
    resolve_turn(session.state, {})

    report = battle.close_battle(campaign, session, BattleOutcome.DEFEAT)

    assert report.credits_awarded == 0
    assert report.player_survivors == 0
    assert campaign.credits == starting_credits
    assert campaign.roster == []
    assert campaign.flagship_id is None
    assert campaign.status is CampaignStatus.DEFEATED
    assert report.completed_campaign is False


def test_fifth_victory_completes_campaign_without_advancing_past_five() -> None:
    campaign = campaign_state()
    campaign.encounter = 5
    session = battle.build_battle(campaign)
    _resolve_victory(session)

    report = battle.close_battle(campaign, session, BattleOutcome.VICTORY)

    assert campaign.encounter == 5
    assert campaign.status is CampaignStatus.COMPLETED
    assert report.completed_campaign is True


def test_simultaneous_elimination_is_defeat_and_cannot_be_forged_as_victory() -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)
    for runtime_id in session.player_runtime_by_campaign.values():
        _destroy_ship(session, runtime_id)
    for enemy_id in session.enemy_runtime_ids:
        _destroy_ship(session, enemy_id)
    resolve_turn(session.state, {})
    before = deepcopy(campaign)

    with pytest.raises(ValueError, match="outcome"):
        battle.close_battle(campaign, session, BattleOutcome.VICTORY)
    assert campaign == before

    report = battle.close_battle(campaign, session, BattleOutcome.DEFEAT)
    assert report.outcome is BattleOutcome.DEFEAT
    assert campaign.status is CampaignStatus.DEFEATED


@pytest.mark.parametrize("outcome", [BattleOutcome.SURRENDER, BattleOutcome.TURN_LIMIT])
def test_noncombat_defeat_does_not_add_xp_or_credits(outcome: BattleOutcome) -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)
    if outcome is BattleOutcome.TURN_LIMIT:
        session.state.turn = 60
    starting_xp = campaign.commander.xp
    starting_credits = campaign.credits

    report = battle.close_battle(campaign, session, outcome)

    assert campaign.commander.xp == starting_xp
    assert campaign.credits == starting_credits
    assert report.credits_awarded == 0
    assert campaign.status is CampaignStatus.DEFEATED


def test_outcome_must_match_runtime_survival_and_turn_limit() -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)

    for outcome in (BattleOutcome.VICTORY, BattleOutcome.DEFEAT, BattleOutcome.TURN_LIMIT):
        before = deepcopy(campaign)
        with pytest.raises(ValueError, match="outcome"):
            battle.close_battle(campaign, session, outcome)
        assert campaign == before


@pytest.mark.parametrize(
    "bad_session",
    ["encounter", "battle_id", "mapping_missing", "mapping_wrong_id", "mapping_duplicate"],
)
def test_stale_or_mismatched_session_is_rejected_atomically(bad_session: str) -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)
    if bad_session == "encounter":
        campaign.encounter = 2
    elif bad_session == "battle_id":
        session.battle_id = "wrong"
    elif bad_session == "mapping_missing":
        session.player_runtime_by_campaign.pop(next(iter(session.player_runtime_by_campaign)))
    elif bad_session == "mapping_wrong_id":
        runtime_id = session.player_runtime_by_campaign.pop(
            next(iter(session.player_runtime_by_campaign))
        )
        session.player_runtime_by_campaign["ship-999"] = runtime_id
    else:
        first_id, second_id = session.player_runtime_by_campaign
        session.player_runtime_by_campaign[second_id] = session.player_runtime_by_campaign[first_id]
    before = deepcopy(campaign)

    with pytest.raises(ValueError, match="session"):
        battle.close_battle(campaign, session, BattleOutcome.SURRENDER)

    assert campaign == before


def test_abandoned_battle_is_never_committed() -> None:
    campaign = campaign_state()
    session = battle.build_battle(campaign)
    before = deepcopy(campaign)

    with pytest.raises(ValueError, match="abandoned"):
        battle.close_battle(campaign, session, BattleOutcome.ABANDONED)

    assert campaign == before
