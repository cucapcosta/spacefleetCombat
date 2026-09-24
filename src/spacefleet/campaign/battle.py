"""Materialize persistent campaign state into a fresh battle state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.commander.commander import AbilityState, Commander
from spacefleet.commander.passive_skills import PassiveBus
from spacefleet.commander.upgrade_effects import apply_flagship_upgrade_charges
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.dice import DiceRoller
from spacefleet.net.game_state import GameState, add_custom_fleet

from .models import BattleOutcome, CampaignShip, CampaignStatus
from .rules import campaign_fleet_spec, enemy_fleet_for, validate_campaign_state

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .models import CampaignState


VICTORY_BASE_CREDITS = 100
CREDITS_PER_ENEMY_DESTROYED = 20
CREDITS_PER_PLAYER_SURVIVOR = 15


@dataclass
class BattleSession:
    battle_id: str
    encounter: int
    state: GameState
    player_id: str
    player_runtime_by_campaign: dict[str, str]
    enemy_runtime_ids: list[str]
    initial_enemy_count: int


@dataclass(frozen=True)
class BattleReport:
    battle_id: str
    outcome: BattleOutcome
    enemy_destroyed: int
    player_survivors: int
    credits_awarded: int
    casualties: Sequence[str]
    completed_campaign: bool


def _runtime_commander_copy(saved: Commander) -> Commander:
    """Copy persistent commander fields and reset all battle-only state."""
    ability_state: dict[str, AbilityState] = {}
    for ability_id in saved.active_ability_ids:
        definition = SkillRegistry.get_active(ability_id)
        assert definition is not None
        ability_state[ability_id] = AbilityState(remaining_charges=definition.charges)
    return Commander(
        id=saved.id,
        name=saved.name,
        faction=saved.faction,
        level=saved.level,
        xp=saved.xp,
        active_ability_ids=list(saved.active_ability_ids),
        passive_skill_ids=list(saved.passive_skill_ids),
        trait_ids=list(saved.trait_ids),
        ability_state=ability_state,
    )


def build_battle(campaign: CampaignState) -> BattleSession:
    """Build a deterministic fresh battle without mutating persistent state."""
    validate_campaign_state(campaign, require_battle_ready=True)
    flagship_id = campaign.flagship_id
    assert flagship_id is not None

    state = GameState(dice=DiceRoller(seed=campaign.seed + campaign.encounter))
    player_ids = add_custom_fleet(
        state,
        "player",
        campaign_fleet_spec(campaign),
        start_x=-50,
    )
    mapping = dict(zip((ship.id for ship in campaign.roster), player_ids, strict=True))

    enemy_spec = enemy_fleet_for(campaign.faction, campaign.encounter)
    enemy_ids = add_custom_fleet(
        state,
        "enemy",
        enemy_spec,
        start_x=50,
        heading=180,
    )
    state.ai_ships = list(enemy_ids)

    for saved in campaign.roster:
        runtime = state.ships[mapping[saved.id]]
        runtime.hull_current = runtime.hull_max - saved.hull_damage
        runtime.battles_survived = saved.battles_survived

    player_fleet = state.fleets["player"]
    runtime_commander = _runtime_commander_copy(campaign.commander)
    player_fleet.commander = runtime_commander
    player_fleet.commander_name = runtime_commander.name
    player_fleet.flagship_ship_id = mapping[flagship_id]
    apply_flagship_upgrade_charges(
        runtime_commander,
        state.ships[player_fleet.flagship_ship_id],
    )
    state.passives = PassiveBus.build(state)

    return BattleSession(
        battle_id=f"{campaign.seed}:{campaign.encounter}",
        encounter=campaign.encounter,
        state=state,
        player_id="player",
        player_runtime_by_campaign=mapping,
        enemy_runtime_ids=list(enemy_ids),
        initial_enemy_count=len(enemy_ids),
    )


def _validate_closure_session(campaign: CampaignState, session: BattleSession) -> None:
    validate_campaign_state(campaign)
    if campaign.last_resolved_battle_id == session.battle_id:
        raise ValueError(f"battle {session.battle_id!r} was already resolved")
    if campaign.status is not CampaignStatus.ACTIVE:
        raise ValueError("campaign is not active")
    validate_campaign_state(campaign, require_battle_ready=True)

    expected_battle_id = f"{campaign.seed}:{campaign.encounter}"
    if session.encounter != campaign.encounter or session.battle_id != expected_battle_id:
        raise ValueError("battle session does not match the active campaign encounter")
    if session.player_id != "player":
        raise ValueError("battle session has an invalid player fleet")

    player_runtime_ids = session.state.player_ships.get(session.player_id)
    stable_ids = {ship.id for ship in campaign.roster}
    mapped_runtime_ids = list(session.player_runtime_by_campaign.values())
    if (
        player_runtime_ids is None
        or set(session.player_runtime_by_campaign) != stable_ids
        or len(mapped_runtime_ids) != len(set(mapped_runtime_ids))
        or set(mapped_runtime_ids) != set(player_runtime_ids)
        or len(player_runtime_ids) != len(set(player_runtime_ids))
    ):
        raise ValueError("battle session player roster does not match the campaign")

    enemy_runtime_ids = session.state.player_ships.get("enemy")
    if (
        enemy_runtime_ids != session.enemy_runtime_ids
        or session.state.ai_ships != session.enemy_runtime_ids
        or session.initial_enemy_count != len(session.enemy_runtime_ids)
        or not session.enemy_runtime_ids
    ):
        raise ValueError("battle session enemy roster is invalid")

    runtime_ids = [*player_runtime_ids, *session.enemy_runtime_ids]
    if len(runtime_ids) != len(set(runtime_ids)) or any(
        runtime_id not in session.state.ships for runtime_id in runtime_ids
    ):
        raise ValueError("battle session contains invalid runtime ship ids")
    player_fleet = session.state.fleets.get(session.player_id)
    if (
        player_fleet is None
        or player_fleet.commander is None
        or set(player_fleet.ship_ids) != set(player_runtime_ids)
        or len(player_fleet.ship_ids) != len(set(player_fleet.ship_ids))
    ):
        raise ValueError("battle session has no player commander")


def _validate_outcome(
    session: BattleSession,
    outcome: BattleOutcome,
    *,
    player_survivors: int,
    enemy_survivors: int,
) -> None:
    valid = False
    if outcome is BattleOutcome.VICTORY:
        valid = player_survivors > 0 and enemy_survivors == 0
    elif outcome is BattleOutcome.DEFEAT:
        valid = player_survivors == 0
    elif outcome is BattleOutcome.SURRENDER:
        valid = player_survivors > 0 and enemy_survivors > 0
    elif outcome is BattleOutcome.TURN_LIMIT:
        valid = player_survivors > 0 and enemy_survivors > 0 and session.state.turn >= 60
    if not valid:
        raise ValueError("battle outcome does not match the runtime battle state")


def _persistent_commander_copy(runtime: Commander) -> Commander:
    return Commander(
        id=runtime.id,
        name=runtime.name,
        faction=runtime.faction,
        level=runtime.level,
        xp=runtime.xp,
        active_ability_ids=list(runtime.active_ability_ids),
        passive_skill_ids=list(runtime.passive_skill_ids),
        trait_ids=list(runtime.trait_ids),
    )


def close_battle(
    campaign: CampaignState,
    session: BattleSession,
    outcome: BattleOutcome,
) -> BattleReport:
    """Persist one terminal battle result into the next campaign interval."""
    if not isinstance(outcome, BattleOutcome):
        raise ValueError("invalid battle outcome")
    if outcome is BattleOutcome.ABANDONED:
        raise ValueError("abandoned battles cannot be resolved")
    _validate_closure_session(campaign, session)

    player_survivors = sum(
        session.state.ships[runtime_id].alive
        for runtime_id in session.player_runtime_by_campaign.values()
    )
    enemy_survivors = sum(
        session.state.ships[runtime_id].alive for runtime_id in session.enemy_runtime_ids
    )
    _validate_outcome(
        session,
        outcome,
        player_survivors=player_survivors,
        enemy_survivors=enemy_survivors,
    )

    survivors: list[CampaignShip] = []
    casualties: list[str] = []
    for saved in campaign.roster:
        runtime = session.state.ships[session.player_runtime_by_campaign[saved.id]]
        if runtime.alive:
            survivors.append(
                CampaignShip(
                    id=saved.id,
                    spec=deepcopy(saved.spec),
                    hull_damage=runtime.hull_max - runtime.hull_current,
                    battles_survived=runtime.battles_survived,
                )
            )
        else:
            casualties.append(saved.id)

    enemy_destroyed = session.initial_enemy_count - enemy_survivors
    credits_awarded = 0
    if outcome is BattleOutcome.VICTORY:
        credits_awarded = (
            VICTORY_BASE_CREDITS
            + CREDITS_PER_ENEMY_DESTROYED * enemy_destroyed
            + CREDITS_PER_PLAYER_SURVIVOR * player_survivors
        )

    runtime_commander = session.state.fleets[session.player_id].commander
    assert runtime_commander is not None
    candidate = deepcopy(campaign)
    candidate.roster = survivors
    candidate.flagship_id = (
        campaign.flagship_id
        if campaign.flagship_id is not None
        and any(ship.id == campaign.flagship_id for ship in survivors)
        else None
    )
    candidate.commander = _persistent_commander_copy(runtime_commander)
    candidate.credits += credits_awarded
    if outcome is BattleOutcome.VICTORY:
        if campaign.encounter == 5:
            candidate.status = CampaignStatus.COMPLETED
        else:
            candidate.encounter += 1
    else:
        candidate.status = CampaignStatus.DEFEATED
    candidate.last_resolved_battle_id = session.battle_id
    validate_campaign_state(candidate)

    campaign.roster = candidate.roster
    campaign.flagship_id = candidate.flagship_id
    campaign.commander = candidate.commander
    campaign.credits = candidate.credits
    campaign.encounter = candidate.encounter
    campaign.status = candidate.status
    campaign.last_resolved_battle_id = candidate.last_resolved_battle_id

    return BattleReport(
        battle_id=session.battle_id,
        outcome=outcome,
        enemy_destroyed=enemy_destroyed,
        player_survivors=player_survivors,
        credits_awarded=credits_awarded,
        casualties=tuple(casualties),
        completed_campaign=candidate.status is CampaignStatus.COMPLETED,
    )
