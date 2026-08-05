"""FleetSpec model — points math and dict round-trip."""

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
    apply_default_loadout,
    fleet_from_dict,
    fleet_points,
    fleet_to_dict,
    ship_points,
)


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def _lunar() -> ShipSpec:
    return ShipSpec(
        name="ISS Hammer",
        hull_id="lunar_cruiser",
        weapons={1: "macro_cannon_3", 2: "macro_cannon_3"},
        upgrade_ids=["armour_piercing_ammo"],
        doctrine_id="navy_gunnery_school",
    )


def test_ship_points_is_hull_plus_parts() -> None:
    spec = _lunar()
    hull = HullRegistry.get("lunar_cruiser")
    expected = (
        hull.hull_cost
        + 2 * WeaponRegistry.get("macro_cannon_3").cost
        + UpgradeRegistry.get("armour_piercing_ammo").cost
        + DoctrineRegistry.get("navy_gunnery_school").cost
    )
    assert ship_points(spec) == expected


def test_ship_points_bare_hull() -> None:
    spec = ShipSpec(name="Bare", hull_id="sword_frigate")
    assert ship_points(spec) == HullRegistry.get("sword_frigate").hull_cost


def test_ship_points_unknown_ids_raise() -> None:
    with pytest.raises(FleetSpecError, match="unknown hull"):
        ship_points(ShipSpec(name="X", hull_id="starfort"))
    with pytest.raises(FleetSpecError, match="unknown weapon"):
        ship_points(ShipSpec(name="X", hull_id="sword_frigate", weapons={1: "railgun"}))
    with pytest.raises(FleetSpecError, match="unknown upgrade"):
        ship_points(ShipSpec(name="X", hull_id="sword_frigate", upgrade_ids=["cloak"]))
    with pytest.raises(FleetSpecError, match="unknown doctrine"):
        ship_points(ShipSpec(name="X", hull_id="sword_frigate", doctrine_id="mark_of_ork"))


def test_fleet_points_sums_ships() -> None:
    fleet = FleetSpec(
        name="Battlefleet",
        faction=Faction.IMPERIAL_NAVY,
        ships=[_lunar(), ShipSpec(name="Bare", hull_id="sword_frigate")],
    )
    assert fleet_points(fleet) == ship_points(fleet.ships[0]) + ship_points(fleet.ships[1])


def test_dict_round_trip() -> None:
    fleet = FleetSpec(
        name="Battlefleet",
        faction=Faction.IMPERIAL_NAVY,
        ships=[_lunar()],
        flagship_index=0,
    )
    data = fleet_to_dict(fleet)
    # JSON-safe: weapons keys become strings on the wire
    import json

    restored = fleet_from_dict(json.loads(json.dumps(data)))
    assert restored == fleet
    assert restored.ships[0].weapons == {1: "macro_cannon_3", 2: "macro_cannon_3"}
    assert restored.faction is Faction.IMPERIAL_NAVY


def test_hull_registry_exposes_default_loadout() -> None:
    dl = HullRegistry.default_loadout("cobra_destroyer")
    assert dl["weapons"] == {1: "macro_cannon_1", 2: "standard_torpedoes"}
    assert dl["upgrades"] == []
    assert dl["doctrine"] is None
    assert HullRegistry.default_loadout("no_such_hull") == {}


def test_apply_default_loadout_fills_spec() -> None:
    spec = ShipSpec(name="Cobra", hull_id="cobra_destroyer")
    apply_default_loadout(spec)
    assert spec.weapons == {1: "macro_cannon_1", 2: "standard_torpedoes"}
    assert spec.upgrade_ids == []
    assert spec.doctrine_id is None


def test_default_loadout_returns_defensive_copy() -> None:
    dl = HullRegistry.default_loadout("cobra_destroyer")
    dl["weapons"][1] = "corrupted"
    dl["upgrades"].append("corrupted")

    dl2 = HullRegistry.default_loadout("cobra_destroyer")
    assert dl2["weapons"] == {1: "macro_cannon_1", 2: "standard_torpedoes"}
    assert dl2["upgrades"] == []


def test_apply_default_loadout_noop_without_default_section() -> None:
    # Unknown hull: HullRegistry.default_loadout returns {} -> apply is a no-op.
    spec = ShipSpec(
        name="Ghost",
        hull_id="no_such_hull",
        weapons={1: "macro_cannon_1"},
        upgrade_ids=["armour_piercing_ammo"],
        doctrine_id="navy_gunnery_school",
    )
    apply_default_loadout(spec)
    assert spec.weapons == {1: "macro_cannon_1"}
    assert spec.upgrade_ids == ["armour_piercing_ammo"]
    assert spec.doctrine_id == "navy_gunnery_school"

    # Real hull WITH a default_loadout: existing choices are overwritten.
    spec2 = ShipSpec(
        name="Cobra",
        hull_id="cobra_destroyer",
        weapons={1: "macro_cannon_1"},
        upgrade_ids=["armour_piercing_ammo"],
        doctrine_id="navy_gunnery_school",
    )
    apply_default_loadout(spec2)
    assert spec2.weapons == {1: "macro_cannon_1", 2: "standard_torpedoes"}
    assert spec2.upgrade_ids == []
    assert spec2.doctrine_id is None
