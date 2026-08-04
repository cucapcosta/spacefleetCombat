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
