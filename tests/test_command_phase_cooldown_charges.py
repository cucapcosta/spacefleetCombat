"""Command-phase charge consumption + cooldown gating across turns."""

from __future__ import annotations

from spacefleet.commander.abilities import AbilityUsedEvent
from spacefleet.commander.commander import Commander
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.dice import DiceRoller
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship
from spacefleet.net.commands import AbilityOrder
from spacefleet.phases.command_phase import (
    AbilityRejectedEvent,
    resolve_command_phase,
)


def _state() -> tuple[CoreGameState, Commander]:
    state = CoreGameState()
    flag = Ship.from_profile(
        "flag", "Flag", HULK_HULL, make_hulk_weapons(), position=Vector2D(0, 0)
    )
    flag.faction = Faction.IMPERIAL_NAVY
    state.add_ship(flag)
    cmdr = Commander(
        id="c1",
        name="A",
        faction=Faction.IMPERIAL_NAVY,
        active_ability_ids=["emergency_repairs"],
    )
    state.fleets["f1"] = Fleet(id="f1", commander=cmdr, ship_ids=["flag"], flagship_ship_id="flag")
    return state, cmdr


def test_charge_decrements_on_use() -> None:
    state, cmdr = _state()
    order = AbilityOrder(fleet_id="f1", ability_id="emergency_repairs")
    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    assert any(isinstance(e, AbilityUsedEvent) for e in events)
    st = cmdr.ability_state["emergency_repairs"]
    assert st.remaining_charges == 1  # emergency_repairs starts with 2
    assert st.cooldown_remaining == 4


def test_cooldown_blocks_next_turn() -> None:
    state, cmdr = _state()
    order = AbilityOrder(fleet_id="f1", ability_id="emergency_repairs")
    # Turn 1: resolves.
    resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    # Turn 2: cooldown ticks 4→3 at top of phase, still > 0 → rejected.
    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    reasons = [e.reason for e in events if isinstance(e, AbilityRejectedEvent)]
    assert reasons == ["cooldown"]
    assert cmdr.ability_state["emergency_repairs"].remaining_charges == 1


def test_no_order_just_ticks_cooldown() -> None:
    state, cmdr = _state()
    order = AbilityOrder(fleet_id="f1", ability_id="emergency_repairs")
    resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    assert cmdr.ability_state["emergency_repairs"].cooldown_remaining == 4
    # Empty command phases tick the cooldown down to zero.
    for _ in range(4):
        resolve_command_phase(state, {}, DiceRoller(seed=1))
    assert cmdr.ability_state["emergency_repairs"].cooldown_remaining == 0
