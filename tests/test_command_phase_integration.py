"""resolve_turn drives the command sub-phase and micro-warp interruption."""

from __future__ import annotations

import dataclasses

from spacefleet.commander.abilities import AbilityUsedEvent
from spacefleet.commander.commander import Commander
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship
from spacefleet.net.commands import AbilityOrder, Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import resolve_turn
from spacefleet.phases.command_phase import AbilityInterruptedEvent


def _attach_fleet(state: GameState, ship: Ship, abilities: list[str]) -> Commander:
    cmdr = Commander(id="cmd", name="Adm", faction=ship.faction, active_ability_ids=abilities)
    state.fleets["alice"] = Fleet(
        id="alice", commander=cmdr, ship_ids=[ship.id], flagship_ship_id=ship.id
    )
    return cmdr


def test_resolve_turn_runs_command_phase_and_repairs() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    sid = state.player_ships["alice"][0]
    ship = state.get_ship(sid)
    ship.hull_current = 1  # damaged but alive (HULK hull is small)
    _attach_fleet(state, ship, ["emergency_repairs"])

    order = AbilityOrder(fleet_id="alice", ability_id="emergency_repairs")
    log = resolve_turn(state, {}, {"alice": order})

    assert any(isinstance(e, AbilityUsedEvent) for e in log.events)
    assert ship.hull_current > 1  # hull was repaired


def test_micro_warp_interrupted_by_boarding_same_turn() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=3)
    flag_id = state.player_ships["alice"][0]
    flag = state.get_ship(flag_id)
    flag.shields_current = 0  # boardable
    cmdr = _attach_fleet(state, flag, ["micro_warp_jump"])

    # An adjacent attacker with assault capability.
    attacker_hull = dataclasses.replace(HULK_HULL, assault_actions=3)
    attacker = Ship.from_profile(
        "boarder",
        "Boarder",
        attacker_hull,
        make_hulk_weapons(),
        position=flag.position,
    )
    state.add_ship(attacker)

    warp = AbilityOrder(
        fleet_id="alice",
        ability_id="micro_warp_jump",
        target_position=Vector2D(20, 20),
    )
    strike = Command(ship_id="boarder", action="strike", args={"target": flag_id})
    log = resolve_turn(state, {"boarder": strike}, {"alice": warp})

    # Prep started this turn, then the boarding strike cancelled it.
    assert any(isinstance(e, AbilityInterruptedEvent) for e in log.events)
    st = cmdr.ability_state["micro_warp_jump"]
    assert st.pending_order is None
    assert st.preparation_turns_left == 0
    assert st.remaining_charges == 2  # charge restored (started at 2)
