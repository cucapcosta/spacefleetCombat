"""Upgrade build-time validation — slot caps, ids, flagship-only."""

from __future__ import annotations

import dataclasses

import pytest

from spacefleet.commander.upgrade_effects import (
    upgrade_effect_total,
    upgrade_has_effect,
    upgrade_slots_for,
    validate_upgrades,
)
from spacefleet.core.types import ShipClass
from spacefleet.data.demo_data import HULK_HULL
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.models.loadout import LoadoutError

_ESCORT_HULL = dataclasses.replace(HULK_HULL, classification=ShipClass.ESCORT)
_BATTLESHIP_HULL = dataclasses.replace(HULK_HULL, classification=ShipClass.BATTLESHIP)


def setup_function() -> None:
    UpgradeRegistry.reset()


def test_effect_total_sums_across_upgrades() -> None:
    total = upgrade_effect_total(["additional_void_shield", "turbo_weaponry"], "shields")
    assert total == 1
    assert upgrade_effect_total([], "shields") == 0
    assert upgrade_effect_total(["nonexistent"], "shields") == 0  # unknown ids skipped


def test_has_effect() -> None:
    assert upgrade_has_effect(["belt_armour"], "first_crit_ignored") is True
    assert upgrade_has_effect(["turbo_weaponry"], "first_crit_ignored") is False


def test_slots_by_class() -> None:
    assert upgrade_slots_for(_ESCORT_HULL) == 1
    assert upgrade_slots_for(_BATTLESHIP_HULL) == 4


def test_mechanicus_rites_grants_extra_slot() -> None:
    assert upgrade_slots_for(_ESCORT_HULL, doctrine_id="mechanicus_rites") == 2


def test_validate_rejects_unknown_id() -> None:
    with pytest.raises(LoadoutError, match="unknown upgrade"):
        validate_upgrades(_BATTLESHIP_HULL, ["warp_cannon_xxl"])


def test_validate_rejects_duplicates() -> None:
    with pytest.raises(LoadoutError, match="duplicate"):
        validate_upgrades(_BATTLESHIP_HULL, ["turbo_weaponry", "turbo_weaponry"])


def test_validate_rejects_over_slot_cap() -> None:
    with pytest.raises(LoadoutError, match="slots"):
        validate_upgrades(_ESCORT_HULL, ["turbo_weaponry", "reinforced_prow"])


def test_validate_rejects_flagship_only_on_escort() -> None:
    with pytest.raises(LoadoutError, match="flagship"):
        validate_upgrades(_ESCORT_HULL, ["navigators_chamber"], is_flagship=False)
    validate_upgrades(_ESCORT_HULL, ["navigators_chamber"], is_flagship=True)  # ok


def test_validate_accepts_valid_loadout() -> None:
    validate_upgrades(_BATTLESHIP_HULL, ["turbo_weaponry", "belt_armour", "crew_quarters"])
