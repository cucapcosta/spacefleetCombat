"""Tests for the shooting phase resolver."""

from __future__ import annotations

from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.phases.shooting_phase import FireOrder, resolve_shooting_phase


def _ship(name: str, *, x: float, faction: Faction) -> Ship:
    s = Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(x, 0.0),
        heading=90.0 if x < 0 else 270.0,
    )
    s.faction = faction
    return s


def test_no_orders_returns_empty():
    a = _ship("a", x=-30, faction=Faction.IMPERIAL_NAVY)
    b = _ship("b", x=30, faction=Faction.CHAOS_FLEET)
    results = resolve_shooting_phase(
        ships=[a, b],
        orders={},
        dice_roller=DiceRoller(seed=1),
    )
    assert results == []


def test_fire_order_produces_attack_result():
    a = _ship("a", x=-30, faction=Faction.IMPERIAL_NAVY)
    b = _ship("b", x=30, faction=Faction.CHAOS_FLEET)
    weapon = a.weapons[1]  # Starboard battery (faces +x)
    results = resolve_shooting_phase(
        ships=[a, b],
        orders={"a": [FireOrder(slot_id=weapon.slot_id, target_id="b")]},
        dice_roller=DiceRoller(seed=1),
    )
    assert len(results) == 1
    assert results[0].attacker_name == "a"
    assert results[0].target_name == "b"
