"""Tests for Loadout slot validation."""
from __future__ import annotations

import pytest

from spacefleet.core.types import Arc, Faction, ShipClass, WeaponSize, WeaponType
from spacefleet.models.loadout import Loadout, LoadoutError
from spacefleet.models.ship_profile import HullProfile, WeaponSlotDef
from spacefleet.models.weapon import WeaponMount, WeaponProfile


def _hull(slot: WeaponSlotDef) -> HullProfile:
    return HullProfile(
        id="test_hull",
        name="Test",
        classification=ShipClass.LIGHT_CRUISER,
        faction=Faction.IMPERIAL_NAVY,
        hull_cost=100,
        leadership=8,
        hull_hits=6,
        armor_prow=6, armor_port=5, armor_starboard=5, armor_stern=4,
        speed=20.0, turn_rate=45.0,
        shields=2, turrets=1, sensor_range=40.0,
        weapon_slots=(slot,),
    )


def _weapon(*, wtype: WeaponType, size: WeaponSize) -> WeaponProfile:
    return WeaponProfile(
        id="w", name="W", weapon_type=wtype, size=size,
        strength=4, range=30.0, cost=10,
    )


def test_valid_loadout_passes():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=1, slot_name="Prow", arc=Arc.PROW, weapon=wp)
    lo = Loadout(weapons=[mount])
    lo.validate(hull)  # must not raise


def test_disallowed_type_raises():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.LANCE, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=1, slot_name="Prow", arc=Arc.PROW, weapon=wp)
    with pytest.raises(LoadoutError, match="not allowed"):
        Loadout(weapons=[mount]).validate(hull)


def test_size_too_large_raises():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.SMALL,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.LARGE)
    mount = WeaponMount(slot_id=1, slot_name="Prow", arc=Arc.PROW, weapon=wp)
    with pytest.raises(LoadoutError, match="too large"):
        Loadout(weapons=[mount]).validate(hull)


def test_unknown_slot_raises():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=99, slot_name="Ghost", arc=Arc.PROW, weapon=wp)
    with pytest.raises(LoadoutError, match="unknown slot"):
        Loadout(weapons=[mount]).validate(hull)


def test_total_cost():
    _slot = WeaponSlotDef(
        id=1, name="P", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=1, slot_name="P", arc=Arc.PROW, weapon=wp)
    assert Loadout(weapons=[mount]).total_cost() == 10
