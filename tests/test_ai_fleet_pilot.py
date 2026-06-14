"""AI fleet pilot — controlled-ship selection and targeting."""

from __future__ import annotations

import dataclasses

from spacefleet.core.types import Arc, Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, SALVAGE_GUN
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.models.weapon import WeaponMount
from spacefleet.net.ai_controller import AIController
from spacefleet.net.game_state import GameState

# The HULK hull is immobile (speed/turn_rate 0) with a wide DORSAL gun — useless
# for testing maneuver/arc logic. Build a mobile ship with a narrow PROW weapon.
_MOBILE_HULL = dataclasses.replace(HULK_HULL, speed=20.0, turn_rate=45.0, hull_hits=8)
_PROW_GUN = WeaponMount(slot_id=1, slot_name="Gun", arc=Arc.PROW, weapon=SALVAGE_GUN)


def _ship(sid: str, faction: Faction, pos: Vector2D, heading: float = 0.0) -> Ship:
    hull = dataclasses.replace(_MOBILE_HULL, faction=faction)
    s = Ship.from_profile(
        sid, sid, hull, [dataclasses.replace(_PROW_GUN)], position=pos, heading=heading
    )
    s.faction = faction
    return s


def _state(*ships: Ship) -> GameState:
    state = GameState(dice=DiceRoller(seed=1))
    for s in ships:
        state.ships[s.id] = s
    return state


def test_controlled_ids_restricts_commands() -> None:
    a = _ship("a", Faction.CHAOS_FLEET, Vector2D(0, 0))
    b = _ship("b", Faction.CHAOS_FLEET, Vector2D(5, 0))
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 100))
    state = _state(a, b, enemy)
    ai = AIController()
    cmds = ai.generate_commands(state, controlled_ids=["a"])
    assert set(cmds.keys()) == {"a"}


def test_default_controls_ai_ships() -> None:
    hulk = _ship("ai_hulk_1", Faction.CHAOS_FLEET, Vector2D(0, 0))
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 100))
    state = _state(hulk, enemy)
    state.ai_ships.append("ai_hulk_1")
    ai = AIController()
    cmds = ai.generate_commands(state)
    assert set(cmds.keys()) == {"ai_hulk_1"}
