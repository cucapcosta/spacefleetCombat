"""Command phase resolver — ticks ability clocks, validates and dispatches
commander ability orders.

Runs first in a turn (before fire/movement).  Resolution order:

1. Tick cooldowns, preparation timers, and active-buff durations for every
   commander; emit ``BuffExpiredEvent`` for buffs that lapse.
2. Resolve any prep-gated orders whose preparation has completed.
3. Validate + dispatch incoming orders (ownership, faction, charges,
   cooldown, target range), honouring the preparation gate.

``AbilityUsedEvent`` / ``BuffAppliedEvent`` are produced inside
``commander.abilities`` (the step resolvers); the command-phase-specific
lifecycle events live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.commander.commander import AbilityState
from spacefleet.core.events import TurnEvent
from spacefleet.data.skill_registry import SkillRegistry

if TYPE_CHECKING:
    from spacefleet.commander.commander import Commander
    from spacefleet.core.events import Event
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.dice import DiceRoller
    from spacefleet.models.fleet import Fleet
    from spacefleet.net.commands import AbilityOrder


@dataclass
class AbilityRejectedEvent(TurnEvent):
    ability_id: str
    fleet_id: str
    reason: str


@dataclass
class AbilityPrepStartedEvent(TurnEvent):
    ability_id: str
    fleet_id: str
    turns: int


@dataclass
class AbilityInterruptedEvent(TurnEvent):
    ability_id: str
    fleet_id: str
    reason: str


@dataclass
class BuffExpiredEvent(TurnEvent):
    fleet_id: str
    buff_id: str


def resolve_command_phase(
    state: CoreGameState,
    ability_orders: dict[str, AbilityOrder],
    dice: DiceRoller,
) -> list[Event]:
    """Resolve the command sub-phase; return events in resolution order."""
    events: list[Event] = []

    # 1. Tick clocks + buffs for all commanders.
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue
        for st in cmdr.ability_state.values():
            if st.cooldown_remaining > 0:
                st.cooldown_remaining -= 1
            if st.pending_order is not None and st.preparation_turns_left > 0:
                st.preparation_turns_left -= 1
        kept = []
        for buff in cmdr.active_buffs:
            buff.turns_remaining -= 1
            if buff.turns_remaining > 0:
                kept.append(buff)
            else:
                events.append(BuffExpiredEvent(fleet_id=fleet.id, buff_id=buff.id))
        cmdr.active_buffs = kept

    # 2. Resolve prep orders whose preparation has just completed.
    for fleet in sorted(state.fleets.values(), key=lambda f: f.id):
        cmdr = fleet.commander
        if cmdr is None:
            continue
        for aid, st in list(cmdr.ability_state.items()):
            if st.pending_order is not None and st.preparation_turns_left == 0:
                order = st.pending_order
                st.pending_order = None
                events.extend(_resolve_one(state, fleet, cmdr, aid, order, dice))

    # 3. Resolve incoming orders (sorted by fleet_id for determinism).
    for fleet_id in sorted(ability_orders.keys()):
        order = ability_orders[fleet_id]
        target_fleet = state.fleets.get(fleet_id)
        if target_fleet is None:
            events.append(
                AbilityRejectedEvent(
                    ability_id=order.ability_id, fleet_id=fleet_id, reason="no_fleet"
                )
            )
            continue
        target_cmdr = target_fleet.commander
        if target_cmdr is None:
            events.append(
                AbilityRejectedEvent(
                    ability_id=order.ability_id, fleet_id=fleet_id, reason="no_commander"
                )
            )
            continue
        events.extend(_dispatch(state, target_fleet, target_cmdr, order, dice))

    return events


def _dispatch(
    state: CoreGameState,
    fleet: Fleet,
    cmdr: Commander,
    order: AbilityOrder,
    dice: DiceRoller,
) -> list[Event]:
    events: list[Event] = []
    ability_def = SkillRegistry.get_active(order.ability_id)

    def reject(reason: str) -> list[Event]:
        events.append(
            AbilityRejectedEvent(ability_id=order.ability_id, fleet_id=fleet.id, reason=reason)
        )
        return events

    if ability_def is None:
        return reject("unknown_ability")
    if order.ability_id not in cmdr.active_ability_ids:
        return reject("not_owned")
    if ability_def.faction is not None and cmdr.faction.value != ability_def.faction:
        return reject("faction_mismatch")

    flagship = fleet.flagship_in(state)
    if flagship is None:
        return reject("flagship_down")

    st = cmdr.ability_state.setdefault(
        order.ability_id, AbilityState(remaining_charges=ability_def.charges)
    )
    if st.remaining_charges <= 0:
        return reject("no_charges")
    if st.cooldown_remaining > 0:
        return reject("cooldown")

    if order.target_ship_id is not None:
        target = state.ships.get(order.target_ship_id)
        if target is None or not target.alive:
            return reject("target_missing")
        if ability_def.range_gu is not None:
            from spacefleet.spatial.geometry import distance

            if distance(flagship.position, target.position) > ability_def.range_gu:
                return reject("out_of_range")
    if order.target_position is not None and ability_def.range_gu is not None:
        from spacefleet.spatial.geometry import distance

        if distance(flagship.position, order.target_position) > ability_def.range_gu:
            return reject("out_of_range")

    # Preparation gate — consume charge now, resolve when prep completes.
    if ability_def.preparation_turns > 0 and st.pending_order is None:
        st.pending_order = order
        st.preparation_turns_left = ability_def.preparation_turns
        st.remaining_charges -= 1
        events.append(
            AbilityPrepStartedEvent(
                ability_id=order.ability_id,
                fleet_id=fleet.id,
                turns=ability_def.preparation_turns,
            )
        )
        return events

    events.extend(_resolve_one(state, fleet, cmdr, order.ability_id, order, dice))
    return events


def _resolve_one(
    state: CoreGameState,
    fleet: Fleet,
    cmdr: Commander,
    ability_id: str,
    order: AbilityOrder,
    dice: DiceRoller,
) -> list[Event]:
    from spacefleet.commander.abilities import StepContext, resolve_ability

    ability_def = SkillRegistry.get_active(ability_id)
    assert ability_def is not None
    flagship = fleet.flagship_in(state)
    assert flagship is not None
    st = cmdr.ability_state.setdefault(
        ability_id, AbilityState(remaining_charges=ability_def.charges)
    )
    # Normal abilities consume a charge on resolve; prep-gated abilities
    # already consumed theirs at prep start.
    if ability_def.preparation_turns == 0:
        st.remaining_charges -= 1
    st.cooldown_remaining = ability_def.cooldown

    ctx = StepContext(
        ability_id=ability_id,
        commander=cmdr,
        fleet=fleet,
        flagship=flagship,
        state=state,
        order=order,
        dice=dice,
    )
    return resolve_ability(ability_def=ability_def, ctx=ctx)
