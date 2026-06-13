"""Command-phase validation: ownership, faction, flagship, range, target."""

from __future__ import annotations

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
