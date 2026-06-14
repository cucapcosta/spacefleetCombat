"""Doctrine effects — build-time stat mods, handlers, validation."""

from __future__ import annotations

import dataclasses

from spacefleet.commander.doctrine_effects import (
    apply_doctrine_to_hull,
    build_ship_with_doctrine,
)
from spacefleet.commander.passive_skills import (
    PassiveBus,
    assault_action_bonus,
    hit_column_shift,
    lance_hit_threshold,
)
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.models.ship import Ship


def test_morale_floor_clamps_losses() -> None:
    s = Ship.from_profile("s", "S", HULK_HULL, make_hulk_weapons(), morale_floor=20)
    s.apply_morale_change(-1000)
    assert s.morale == 20


def test_default_floor_is_zero() -> None:
    s = Ship.from_profile("s", "S", HULK_HULL, make_hulk_weapons())
    assert s.morale_floor == 0
    assert s.doctrine_id is None
    s.apply_morale_change(-1000)
    assert s.morale == 0


def test_apply_stat_mods_nurgle() -> None:
    # HULK speed is 0 (would clamp); use a moving hull so the -5 delta is
    # observable without hitting the >=0 floor.
    base = dataclasses.replace(HULK_HULL, speed=20.0)
    nurgle = DoctrineRegistry.get("mark_of_nurgle")
    modded = apply_doctrine_to_hull(base, nurgle)
    assert modded.hull_hits == base.hull_hits + 2
    assert modded.speed == base.speed - 5.0


def test_apply_stat_mods_clamps_minimums() -> None:
    # HULK speed is 0; Nurgle -5 must clamp to 0, not go negative.
    modded = apply_doctrine_to_hull(HULK_HULL, DoctrineRegistry.get("mark_of_nurgle"))
    assert modded.speed >= 0.0


def test_build_ship_applies_doctrine() -> None:
    ship = build_ship_with_doctrine(
        "s",
        "S",
        HULK_HULL,
        make_hulk_weapons(),
        doctrine_id="commissariat",
    )
    assert ship.doctrine_id == "commissariat"
    assert ship.morale_floor == 20


def test_build_ship_none_doctrine_is_plain() -> None:
    ship = build_ship_with_doctrine("s", "S", HULK_HULL, make_hulk_weapons(), doctrine_id=None)
    assert ship.doctrine_id is None and ship.morale_floor == 0


def _state_with_doctrine(doctrine_id: str, faction: Faction) -> tuple[CoreGameState, Ship, Ship]:
    state = CoreGameState()
    ship = build_ship_with_doctrine(
        "s",
        "S",
        HULK_HULL,
        make_hulk_weapons(),
        doctrine_id=doctrine_id,
        position=Vector2D(0, 0),
    )
    ship.faction = faction
    enemy = Ship.from_profile("e", "E", HULK_HULL, make_hulk_weapons(), position=Vector2D(2, 0))
    enemy.faction = (
        Faction.CHAOS_FLEET if faction == Faction.IMPERIAL_NAVY else Faction.IMPERIAL_NAVY
    )
    state.add_ship(ship)
    state.add_ship(enemy)
    state.passives = PassiveBus.build(state)
    return state, ship, enemy


def test_navy_gunnery_column_shift() -> None:
    state, ship, enemy = _state_with_doctrine("navy_gunnery_school", Faction.IMPERIAL_NAVY)
    assert hit_column_shift(state, ship, enemy, ship.weapons[0]) == 1


def test_tzeentch_lance_threshold() -> None:
    state, ship, _ = _state_with_doctrine("mark_of_tzeentch", Faction.CHAOS_FLEET)
    assert lance_hit_threshold(state, ship) == 3


def test_space_marine_assault_bonus() -> None:
    state, ship, _ = _state_with_doctrine("space_marine_detachment", Faction.IMPERIAL_NAVY)
    assert assault_action_bonus(state, ship) == 2


def test_khorne_assault_bonus() -> None:
    state, ship, _ = _state_with_doctrine("mark_of_khorne", Faction.CHAOS_FLEET)
    assert assault_action_bonus(state, ship) == 3
