"""Materialize persistent campaign state into a fresh battle state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.commander.commander import AbilityState, Commander
from spacefleet.commander.passive_skills import PassiveBus
from spacefleet.commander.upgrade_effects import apply_flagship_upgrade_charges
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.dice import DiceRoller
from spacefleet.net.game_state import GameState, add_custom_fleet

from .rules import campaign_fleet_spec, enemy_fleet_for, validate_campaign_state

if TYPE_CHECKING:
    from .models import CampaignState


@dataclass
class BattleSession:
    battle_id: str
    encounter: int
    state: GameState
    player_id: str
    player_runtime_by_campaign: dict[str, str]
    enemy_runtime_ids: list[str]
    initial_enemy_count: int


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
