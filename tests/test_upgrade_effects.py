"""Upgrade effects — Ship fields, hull mods, ship builder."""

from __future__ import annotations

from spacefleet.core.types import Stance
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.ship import Ship


def _ship(**kwargs: object) -> Ship:
    return Ship.from_profile("s1", "Test Ship", HULK_HULL, make_hulk_weapons(), **kwargs)  # type: ignore[arg-type]


def test_ship_upgrade_fields_default_noop() -> None:
    ship = _ship()
    assert ship.upgrade_ids == []
    assert ship.stance_cooldown_reduction == 0
    assert ship.combustion_regen_bonus == 0
    assert ship.belt_armour_spent is False


def test_from_profile_upgrade_ids_passthrough() -> None:
    ship = _ship(upgrade_ids=["turbo_weaponry"])
    assert ship.upgrade_ids == ["turbo_weaponry"]


def test_stance_cooldown_reduction_applies_on_switch() -> None:
    plain = _ship()
    reduced = _ship()
    reduced.stance_cooldown_reduction = 1
    assert plain.switch_stance(Stance.LOCK_ON) is True
    assert reduced.switch_stance(Stance.LOCK_ON) is True
    assert reduced.stance_cooldown_remaining == max(0, plain.stance_cooldown_remaining - 1)
