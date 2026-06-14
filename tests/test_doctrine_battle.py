"""Doctrine effects exercised through resolve_turn."""

from __future__ import annotations

import dataclasses

from spacefleet.commander.doctrine_effects import (
    BoardingRepelledByDoctrineEvent,
    build_ship_with_doctrine,
)
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.ship import Ship
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import resolve_turn


def test_space_marine_repels_boarding() -> None:
    state = GameState()
    # Attacker with assault capability, adjacent to a board-immune Space Marine ship.
    attacker_hull = dataclasses.replace(HULK_HULL, assault_actions=3)
    attacker = Ship.from_profile(
        "boarder", "Boarder", attacker_hull, make_hulk_weapons(), position=Vector2D(0, 0)
    )
    attacker.faction = Faction.CHAOS_FLEET
    target = build_ship_with_doctrine(
        "marine",
        "Marine",
        HULK_HULL,
        make_hulk_weapons(),
        doctrine_id="space_marine_detachment",
        position=Vector2D(0, 0),
    )
    target.faction = Faction.IMPERIAL_NAVY
    target.shields_current = 0  # boardable
    state.add_ship(attacker)
    state.add_ship(target)

    strike = Command(ship_id="boarder", action="strike", args={"target": "marine"})
    log = resolve_turn(state, {"boarder": strike})

    assert any(isinstance(e, BoardingRepelledByDoctrineEvent) for e in log.events)
    assert target.morale == target.morale_max  # took no boarding morale damage
