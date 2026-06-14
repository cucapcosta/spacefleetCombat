"""Doctrine effects — build-time stat mods, handlers, validation."""

from __future__ import annotations

import dataclasses

from spacefleet.commander.doctrine_effects import (
    apply_doctrine_to_hull,
    build_ship_with_doctrine,
)
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
