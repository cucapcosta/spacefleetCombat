"""No-server campaign acceptance through real battle and persistence APIs."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from spacefleet.campaign.battle import BattleSession, build_battle, close_battle
from spacefleet.campaign.economy import buy_ship, repair_ship
from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.cli.local_battle import LocalBattleController
from spacefleet.core.types import Vector2D
from spacefleet.dice import DiceRoller
from spacefleet.models.fleet_spec import ship_points
from spacefleet.persistence.campaign_save import load_campaign, save_campaign
from tests.campaign_helpers import ScriptedIO, campaign_state, supported_fleet

if TYPE_CHECKING:
    from pathlib import Path


class _AlwaysHitDice(DiceRoller):
    def roll_d6(self, count: int) -> list[int]:
        return [6] * count


def _prepare_one_shot_battle(session: BattleSession) -> tuple[str, ScriptedIO]:
    """Keep one harmless enemy in the authoritative runtime memberships."""
    state = session.state
    target_id = session.enemy_runtime_ids[0]
    target = state.ships[target_id]
    for unused_id in session.enemy_runtime_ids[1:]:
        state.ships.pop(unused_id)

    session.enemy_runtime_ids[:] = [target_id]
    session.initial_enemy_count = 1
    state.player_ships["enemy"] = [target_id]
    state.ai_ships = [target_id]
    enemy_fleet = state.fleets["enemy"]
    enemy_fleet.ship_ids = [target_id]
    enemy_fleet.ships = [target]
    enemy_fleet.flagship_ship_id = target_id

    flagship = state.fleets[session.player_id].flagship_in(state)
    assert flagship is not None
    flagship.position = Vector2D(0.0, 0.0)
    flagship.heading = 0.0
    target.position = Vector2D(0.0, 20.0)
    target.shields_current = 0
    target.hull_current = 1
    target.weapons.clear()
    state.dice = _AlwaysHitDice(seed=1)

    lines = [
        "fire 3 0" if ship_id == flagship.id else "pass"
        for ship_id in state.player_ships[session.player_id]
    ]
    lines.extend(["ability skip", "review", "confirm"])
    return flagship.id, ScriptedIO(lines)


def _win_real_controller_battle(session: BattleSession) -> BattleOutcome:
    _, io = _prepare_one_shot_battle(session)
    outcome = LocalBattleController(
        session,
        input_fn=io.input,
        output_fn=io.output,
    ).run()
    assert session.state.turn == 1
    assert outcome is BattleOutcome.VICTORY
    assert any("TARGET DESTROYED" in output for output in io.outputs)
    return outcome


def test_two_real_controller_battles_link_economy_and_save_load(tmp_path: Path) -> None:
    campaign = campaign_state()
    starting_credits = campaign.credits
    original_ids = [ship.id for ship in campaign.roster]

    first = build_battle(campaign)
    first_flagship_id, first_io = _prepare_one_shot_battle(first)
    first.state.ships[first_flagship_id].take_hull_damage(1)
    first_outcome = LocalBattleController(
        first,
        input_fn=first_io.input,
        output_fn=first_io.output,
    ).run()
    assert first_outcome is BattleOutcome.VICTORY
    first_report = close_battle(campaign, first, first_outcome)
    xp_after_first = campaign.commander.xp

    assert first_report.enemy_destroyed == 1
    assert campaign.roster[0].hull_damage == 1
    assert [ship.battles_survived for ship in campaign.roster] == [1, 1]
    assert campaign.credits == starting_credits + 150

    repair_cost = repair_ship(campaign, original_ids[0])
    reinforcement = deepcopy(supported_fleet().ships[1])
    reinforcement.name = "Reinforcement"
    bought_id = buy_ship(campaign, reinforcement)
    credits_before_second = campaign.credits
    expected_interval_credits = starting_credits + 150 - repair_cost - ship_points(reinforcement)
    assert credits_before_second == expected_interval_credits

    save_path = save_campaign(campaign, tmp_path / "campaign.json")
    campaign = load_campaign(save_path)
    assert [ship.id for ship in campaign.roster[:2]] == original_ids
    assert campaign.roster[0].hull_damage == 0
    assert campaign.commander.xp == xp_after_first
    assert campaign.credits == expected_interval_credits

    second = build_battle(campaign)
    assert bought_id in second.player_runtime_by_campaign
    bought_runtime_id = second.player_runtime_by_campaign[bought_id]
    assert bought_runtime_id in second.state.player_ships[second.player_id]
    assert second.state.ships[bought_runtime_id].battles_survived == 0
    for stable_id in original_ids:
        runtime_id = second.player_runtime_by_campaign[stable_id]
        assert second.state.ships[runtime_id].battles_survived == 1
    runtime_commander = second.state.fleets[second.player_id].commander
    assert runtime_commander is not None
    assert runtime_commander.xp == xp_after_first

    second_outcome = _win_real_controller_battle(second)
    second_report = close_battle(campaign, second, second_outcome)

    persisted = {ship.id: ship for ship in campaign.roster}
    assert campaign.encounter == 3
    assert campaign.commander.xp > xp_after_first
    assert campaign.credits == credits_before_second + 165
    assert second_report.player_survivors == 3
    assert persisted[original_ids[0]].battles_survived == 2
    assert persisted[original_ids[1]].battles_survived == 2
    assert persisted[bought_id].battles_survived == 1


def test_five_real_controller_victories_complete_campaign() -> None:
    campaign = campaign_state()

    for encounter in range(1, 6):
        assert campaign.encounter == encounter
        session = build_battle(campaign)
        outcome = _win_real_controller_battle(session)
        report = close_battle(campaign, session, outcome)
        assert report.completed_campaign is (encounter == 5)

    assert campaign.encounter == 5
    assert campaign.status is CampaignStatus.COMPLETED
    assert [ship.battles_survived for ship in campaign.roster] == [5, 5]
