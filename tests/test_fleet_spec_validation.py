"""FleetSpec validation — reuses loadout/upgrade/doctrine rules."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    ShipSpec,
    fleet_points,
    validate_fleet_spec,
    validate_ship_spec,
)
from spacefleet.models.loadout import LoadoutError


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def test_valid_ship_passes() -> None:
    spec = ShipSpec(
        name="OK",
        hull_id="sword_frigate",
        weapons={1: "macro_cannon_1", 2: "macro_cannon_1"},
        upgrade_ids=["reinforced_prow"],
        doctrine_id="commissariat",
    )
    validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_hull_faction_must_match_fleet() -> None:
    spec = ShipSpec(name="Traitor", hull_id="murder_cruiser")
    with pytest.raises(FleetSpecError, match="faction"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_weapon_slot_rules_enforced() -> None:
    # sword_frigate slots are SMALL battery mounts: a medium gun must not fit
    spec = ShipSpec(name="Big gun", hull_id="sword_frigate", weapons={1: "macro_cannon_3"})
    with pytest.raises(LoadoutError):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_doctrine_faction_lock() -> None:
    spec = ShipSpec(name="Heretic", hull_id="sword_frigate", doctrine_id="mark_of_khorne")
    with pytest.raises(FleetSpecError, match="faction"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_khorne_lance_ban() -> None:
    # iconoclast_destroyer slot 2 ("Secondary Mount") accepts small lances
    spec = ShipSpec(
        name="Khorne",
        hull_id="iconoclast_destroyer",
        weapons={2: "lance_1"},
        doctrine_id="mark_of_khorne",
    )
    with pytest.raises(FleetSpecError, match="lance"):
        validate_ship_spec(spec, Faction.CHAOS_FLEET)


def test_upgrade_slot_cap_via_existing_validator() -> None:
    spec = ShipSpec(
        name="Overloaded",
        hull_id="sword_frigate",  # escort: 1 upgrade slot
        upgrade_ids=["reinforced_prow", "crew_quarters"],
    )
    with pytest.raises(LoadoutError, match="slots"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_flagship_only_upgrade_gated() -> None:
    spec = ShipSpec(name="Nav", hull_id="sword_frigate", upgrade_ids=["navigators_chamber"])
    with pytest.raises(LoadoutError, match="flagship"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY, is_flagship=False)
    validate_ship_spec(spec, Faction.IMPERIAL_NAVY, is_flagship=True)  # ok


def _two_ship_fleet() -> FleetSpec:
    return FleetSpec(
        name="BF Calixis",
        faction=Faction.IMPERIAL_NAVY,
        ships=[
            ShipSpec(name="Flag", hull_id="dauntless_light_cruiser"),
            ShipSpec(name="Escort", hull_id="sword_frigate"),
        ],
        flagship_index=0,
    )


def test_valid_fleet_passes_with_budget() -> None:
    fleet = _two_ship_fleet()
    validate_fleet_spec(fleet, budget=fleet_points(fleet))


def test_fleet_rules() -> None:
    with pytest.raises(FleetSpecError, match="at least one ship"):
        validate_fleet_spec(FleetSpec(name="Empty", faction=Faction.IMPERIAL_NAVY))
    bad_flag = _two_ship_fleet()
    bad_flag.flagship_index = 5
    with pytest.raises(FleetSpecError, match="flagship"):
        validate_fleet_spec(bad_flag)
    dup = _two_ship_fleet()
    dup.ships[1].name = "Flag"
    with pytest.raises(FleetSpecError, match="duplicate ship name"):
        validate_fleet_spec(dup)


def test_fleet_budget_enforced() -> None:
    fleet = _two_ship_fleet()
    with pytest.raises(FleetSpecError, match="budget"):
        validate_fleet_spec(fleet, budget=fleet_points(fleet) - 1)
