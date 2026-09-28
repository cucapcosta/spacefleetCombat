"""Kill credit uses ship identity across weapons, abilities, and fire."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.commander.commander import AbilityState
from spacefleet.core.types import Arc, Faction, Vector2D
from spacefleet.data.demo_data import LANCE_2
from spacefleet.dice import DiceRoller
from spacefleet.models.weapon import WeaponMount
from spacefleet.net import turn_resolver
from spacefleet.net.commands import AbilityOrder, Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import DestroyedEvent, resolve_turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.core.events import TurnEvent


def _mixed_state() -> GameState:
    return GameState.create_mixed(["imp"], ["cha"], ships_per_player=1, seed=1)


def _prepare_warp_rift(state: GameState, target_id: str) -> tuple[str, AbilityOrder]:
    caster_id = state.player_ships["cha"][0]
    caster = state.ships[caster_id]
    target = state.ships[target_id]

    for index, ship in enumerate(state.ships.values()):
        ship.position = Vector2D(500.0 + index * 100.0, 500.0)
    caster.position = Vector2D(-10.0, 0.0)
    target.position = Vector2D(10.0, 0.0)
    target.shields_current = 0
    target.hull_current = 1

    commander = state.fleets["cha"].commander
    assert commander is not None
    commander.active_ability_ids.append("warp_rift")
    commander.ability_state["warp_rift"] = AbilityState(remaining_charges=1)
    return caster_id, AbilityOrder(
        fleet_id="cha", ability_id="warp_rift", target_position=target.position
    )


def _collect_events() -> tuple[list[TurnEvent], Callable[[TurnEvent], None]]:
    events: list[TurnEvent] = []
    return events, events.append


class _AlwaysSixDice(DiceRoller):
    def d6(self) -> int:
        return 6


def test_warp_rift_enemy_kill_credits_casting_fleet() -> None:
    state = _mixed_state()
    enemy_id = state.player_ships["imp"][0]
    _, order = _prepare_warp_rift(state, enemy_id)

    log = resolve_turn(state, {}, {"cha": order})

    assert state.kills["cha"] == 1
    assert enemy_id in state.credited_destroyed_ship_ids
    destroyed = [event for event in log.events if isinstance(event, DestroyedEvent)]
    assert [event.ship.id for event in destroyed] == [enemy_id]
    assert destroyed[0].killer_player == "cha"


def test_warp_rift_friendly_kill_has_no_credit() -> None:
    state = _mixed_state()
    friendly_id = next(
        ship_id for ship_id in state.ai_ships if state.ships[ship_id].faction == Faction.CHAOS_FLEET
    )
    _, order = _prepare_warp_rift(state, friendly_id)

    log = resolve_turn(state, {}, {"cha": order})

    assert state.kills["cha"] == 0
    destroyed = [event for event in log.events if isinstance(event, DestroyedEvent)]
    assert [event.ship.id for event in destroyed] == [friendly_id]
    assert destroyed[0].killer_player is None


def test_destroyed_ship_is_credited_and_emitted_only_once() -> None:
    state = _mixed_state()
    attacker_id = state.player_ships["cha"][0]
    target_id = state.player_ships["imp"][0]
    state.ships[target_id].take_hull_damage(state.ships[target_id].hull_current)
    events, emit = _collect_events()

    turn_resolver._credit_destroyed_ship(state, target_id, killer_ship_id=attacker_id, emit=emit)
    turn_resolver._credit_destroyed_ship(state, target_id, killer_ship_id=attacker_id, emit=emit)

    assert state.kills["cha"] == 1
    assert len([event for event in events if isinstance(event, DestroyedEvent)]) == 1


def test_fire_death_has_no_kill_credit() -> None:
    state = _mixed_state()
    target_id = state.player_ships["imp"][0]
    target = state.ships[target_id]
    target.hull_current = 1
    target.fires = 1

    log = resolve_turn(state, {})

    assert not target.alive
    assert state.kills == {"imp": 0, "cha": 0}
    destroyed = [event for event in log.events if isinstance(event, DestroyedEvent)]
    assert [event.ship.id for event in destroyed] == [target_id]
    assert destroyed[0].killer_player is None


def test_weapon_kill_credits_attacking_ship_owner() -> None:
    state = _mixed_state()
    attacker_id = state.player_ships["cha"][0]
    target_id = state.player_ships["imp"][0]
    attacker = state.ships[attacker_id]
    target = state.ships[target_id]
    attacker.position = Vector2D(0.0, 0.0)
    attacker.heading = 0.0
    attacker.weapons = [WeaponMount(slot_id=1, slot_name="Lance", arc=Arc.PROW, weapon=LANCE_2)]
    target.position = Vector2D(0.0, 10.0)
    target.shields_current = 0
    target.hull_current = 1
    state.dice = _AlwaysSixDice(seed=1)

    log = resolve_turn(
        state,
        {
            attacker_id: Command(
                ship_id=attacker_id, action="fire", args={"slot": 1, "bearing": 0.0}
            )
        },
    )

    assert state.kills["cha"] == 1
    assert [event.ship.id for event in log.events if isinstance(event, DestroyedEvent)] == [
        target_id
    ]


def test_destroyed_ship_identity_disambiguates_duplicate_names() -> None:
    state = GameState.create_mixed(["imp"], ["cha"], ships_per_player=2, seed=1)
    attacker_id = state.player_ships["cha"][0]
    first_id = state.player_ships["imp"][0]
    second_id = state.player_ships["imp"][1]
    state.ships[first_id].name = "Duplicate"
    state.ships[second_id].name = "Duplicate"
    state.ships[first_id].take_hull_damage(state.ships[first_id].hull_current)
    state.ships[second_id].take_hull_damage(state.ships[second_id].hull_current)
    events, emit = _collect_events()

    turn_resolver._credit_destroyed_ship(state, second_id, killer_ship_id=attacker_id, emit=emit)

    destroyed = [event for event in events if isinstance(event, DestroyedEvent)]
    assert [event.ship.id for event in destroyed] == [second_id]
    assert second_id in state.credited_destroyed_ship_ids
    assert first_id not in state.credited_destroyed_ship_ids
