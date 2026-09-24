"""Command-phase validation: ownership, faction, flagship, range, target."""

from __future__ import annotations

import pytest

from spacefleet.commander.commander import AbilityState, Commander
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
    validate_ability_order,
)


def _setup(
    *,
    faction: Faction = Faction.IMPERIAL_NAVY,
    owns: list[str],
    flagship_alive: bool = True,
) -> tuple[CoreGameState, Commander]:
    state = CoreGameState()
    flag = Ship.from_profile(
        "flag", "Flag", HULK_HULL, make_hulk_weapons(), position=Vector2D(0, 0)
    )
    flag.faction = faction
    if not flagship_alive:
        flag.take_hull_damage(flag.hull.hull_hits)
    state.add_ship(flag)
    cmdr = Commander(id="c1", name="A", faction=faction, active_ability_ids=owns)
    state.fleets["f1"] = Fleet(id="f1", commander=cmdr, ship_ids=["flag"], flagship_ship_id="flag")
    return state, cmdr


def _reason(events: list[object]) -> str | None:
    for e in events:
        if isinstance(e, AbilityRejectedEvent):
            return e.reason
    return None


def test_reject_not_owned() -> None:
    state, _ = _setup(owns=[])
    order = AbilityOrder(fleet_id="f1", ability_id="emergency_repairs")
    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    assert _reason(events) == "not_owned"


def test_reject_faction_mismatch() -> None:
    # torpedo_barrage is imperial_navy; chaos commander owns it but cannot use it.
    state, _ = _setup(faction=Faction.CHAOS_FLEET, owns=["torpedo_barrage"])
    order = AbilityOrder(fleet_id="f1", ability_id="torpedo_barrage")
    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    assert _reason(events) == "faction_mismatch"


def test_reject_flagship_down() -> None:
    state, _ = _setup(owns=["emergency_repairs"], flagship_alive=False)
    order = AbilityOrder(fleet_id="f1", ability_id="emergency_repairs")
    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    assert _reason(events) == "flagship_down"


def test_reject_out_of_range() -> None:
    state, _ = _setup(owns=["concentrated_fire"])
    enemy = Ship.from_profile(
        "enemy", "E", HULK_HULL, make_hulk_weapons(), position=Vector2D(200, 0)
    )
    enemy.faction = Faction.CHAOS_FLEET
    state.add_ship(enemy)
    order = AbilityOrder(fleet_id="f1", ability_id="concentrated_fire", target_ship_id="enemy")
    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    assert _reason(events) == "out_of_range"


def test_reject_target_missing() -> None:
    state, _ = _setup(owns=["concentrated_fire"])
    order = AbilityOrder(fleet_id="f1", ability_id="concentrated_fire", target_ship_id="ghost")
    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))
    assert _reason(events) == "target_missing"


def test_reject_unknown_fleet() -> None:
    state, _ = _setup(owns=["emergency_repairs"])
    order = AbilityOrder(fleet_id="nope", ability_id="emergency_repairs")
    events = resolve_command_phase(state, {"nope": order}, DiceRoller(seed=1))
    assert _reason(events) == "no_fleet"


def test_preflight_is_pure_and_does_not_create_ability_state() -> None:
    state, commander = _setup(owns=["emergency_repairs"])
    fleet = state.fleets["f1"]
    order = AbilityOrder(fleet_id="f1", ability_id="emergency_repairs")

    assert validate_ability_order(state, fleet, commander, order) is None
    assert commander.ability_state == {}


def test_preflight_accounts_for_command_phase_cooldown_tick() -> None:
    state, commander = _setup(owns=["emergency_repairs"])
    fleet = state.fleets["f1"]
    order = AbilityOrder(fleet_id="f1", ability_id="emergency_repairs")
    commander.ability_state["emergency_repairs"] = AbilityState(
        remaining_charges=1,
        cooldown_remaining=1,
    )

    assert validate_ability_order(state, fleet, commander, order) == "cooldown"
    assert (
        validate_ability_order(
            state,
            fleet,
            commander,
            order,
            cooldown_will_tick=True,
        )
        is None
    )
    assert commander.ability_state["emergency_repairs"].cooldown_remaining == 1


def test_preflight_rejects_cooldown_that_will_remain_after_tick() -> None:
    state, commander = _setup(owns=["emergency_repairs"])
    commander.ability_state["emergency_repairs"] = AbilityState(
        remaining_charges=1,
        cooldown_remaining=2,
    )

    assert (
        validate_ability_order(
            state,
            state.fleets["f1"],
            commander,
            AbilityOrder(fleet_id="f1", ability_id="emergency_repairs"),
            cooldown_will_tick=True,
        )
        == "cooldown"
    )


@pytest.mark.parametrize(
    ("ability_id", "order", "reason"),
    [
        (
            "concentrated_fire",
            AbilityOrder(fleet_id="f1", ability_id="concentrated_fire"),
            "target_required",
        ),
        (
            "boarding_assault",
            AbilityOrder(fleet_id="f1", ability_id="boarding_assault"),
            "target_required",
        ),
        (
            "micro_warp_jump",
            AbilityOrder(fleet_id="f1", ability_id="micro_warp_jump"),
            "position_required",
        ),
        (
            "micro_warp_jump",
            AbilityOrder(
                fleet_id="f1",
                ability_id="micro_warp_jump",
                target_position=Vector2D(float("nan"), 0),
            ),
            "invalid_position",
        ),
    ],
)
def test_required_ability_target_is_rejected_without_consuming_charge(
    ability_id: str,
    order: AbilityOrder,
    reason: str,
) -> None:
    state, commander = _setup(owns=[ability_id])

    events = resolve_command_phase(state, {"f1": order}, DiceRoller(seed=1))

    assert _reason(events) == reason
    assert commander.ability_state == {}


@pytest.mark.parametrize(
    "order",
    [
        AbilityOrder(
            fleet_id="f1",
            ability_id="concentrated_fire",
            target_ship_id="enemy",
        ),
        AbilityOrder(
            fleet_id="f1",
            ability_id="boarding_assault",
            target_ship_id="enemy",
        ),
        AbilityOrder(
            fleet_id="f1",
            ability_id="micro_warp_jump",
            target_position=Vector2D(1, 1),
        ),
    ],
)
def test_required_ability_target_accepts_the_expected_target_shape(order: AbilityOrder) -> None:
    state, commander = _setup(owns=[order.ability_id])
    enemy = Ship.from_profile(
        "enemy",
        "Enemy",
        HULK_HULL,
        make_hulk_weapons(),
        position=Vector2D(1, 1),
    )
    enemy.faction = Faction.CHAOS_FLEET
    state.add_ship(enemy)

    assert validate_ability_order(state, state.fleets["f1"], commander, order) is None


def test_area_ability_may_default_to_flagship_position() -> None:
    state, commander = _setup(
        faction=Faction.CHAOS_FLEET,
        owns=["warp_rift"],
    )
    order = AbilityOrder(fleet_id="f1", ability_id="warp_rift")

    assert validate_ability_order(state, state.fleets["f1"], commander, order) is None
