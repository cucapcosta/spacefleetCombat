"""Custom fleet assembly into a live GameState."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import FleetSpec, FleetSpecError, ShipSpec
from spacefleet.net.game_state import GameState, add_custom_fleet


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def _fleet() -> FleetSpec:
    return FleetSpec(
        name="BF Custom",
        faction=Faction.IMPERIAL_NAVY,
        ships=[
            ShipSpec(
                name="ISS Flag",
                hull_id="dauntless_light_cruiser",
                weapons={1: "macro_cannon_3", 2: "macro_cannon_3"},
                upgrade_ids=["additional_void_shield", "navigators_chamber"],
                doctrine_id="commissariat",
            ),
            ShipSpec(
                name="ISS Escort",
                hull_id="sword_frigate",
                weapons={1: "macro_cannon_1"},
            ),
        ],
        flagship_index=0,
    )


def test_assembly_materialises_specs() -> None:
    state = GameState()
    ship_ids = add_custom_fleet(state, "paulo", _fleet())
    assert len(ship_ids) == 2
    assert state.player_ships["paulo"] == ship_ids

    flag = state.ships[ship_ids[0]]
    assert flag.name == "ISS Flag"
    assert flag.doctrine_id == "commissariat"
    assert flag.morale_floor == 20  # doctrine applied via build_ship_with_upgrades
    assert flag.shields_max == HullRegistry.get("dauntless_light_cruiser").shields + 1
    assert [w.weapon.id for w in flag.weapons] == ["macro_cannon_3", "macro_cannon_3"]
    assert flag.faction is Faction.IMPERIAL_NAVY

    escort = state.ships[ship_ids[1]]
    assert escort.hull.id == "sword_frigate"
    assert len(escort.weapons) == 1


def test_assembly_sets_spec_flagship_and_charges() -> None:
    state = GameState()
    fleet_spec = _fleet()
    fleet_spec.flagship_index = 0
    ship_ids = add_custom_fleet(state, "paulo", fleet_spec)
    fleet = state.fleets["paulo"]
    assert fleet.flagship_ship_id == ship_ids[0]
    assert fleet.commander is not None


def test_assembly_rejects_invalid_fleet() -> None:
    state = GameState()
    bad = _fleet()
    bad.ships[1].name = "ISS Flag"  # duplicate name
    with pytest.raises(FleetSpecError):
        add_custom_fleet(state, "paulo", bad)
    assert "paulo" not in state.player_ships  # nothing half-assembled


def test_create_pve_custom_spawns_enemies() -> None:
    state = GameState.create_pve_custom("paulo", _fleet(), seed=42, num_hulks=3)
    assert len(state.player_ships["paulo"]) == 2
    assert len(state.ai_ships) == 3
    factions = {state.ships[s].faction for s in state.ai_ships}
    assert factions == {Faction.CHAOS_FLEET}


def test_custom_fleet_full_turn_integration() -> None:
    """Session-built fleet → create_pve_custom → one resolve_turn."""
    from spacefleet.net.commands import Command
    from spacefleet.net.turn_resolver import resolve_turn
    from spacefleet.tui.model.fleet_builder import FleetBuilderSession

    s = FleetBuilderSession(Faction.IMPERIAL_NAVY, budget=1000)
    s.execute("buy dauntless_light_cruiser ISS Flag")
    s.execute("equip 1")
    s.execute("slot 1 macro_cannon_3")
    s.execute("upgrade auxiliary_shield_capacitor")
    # dauntless_light_cruiser has 1 base shield; add capacity so the
    # regen bonus below has room to land (2 upgrade slots on a light cruiser).
    s.execute("upgrade additional_void_shield")
    s.execute("doctrine commissariat")
    s.execute("back")
    s.execute("buy sword_frigate ISS Escort")
    s.execute("done")

    state = GameState.create_pve_custom("paulo", s.fleet, seed=7, num_hulks=2)
    flag = state.ships[state.player_ships["paulo"][0]]
    flag.shields_current = 0  # force regen to be observable

    commands = {
        sid: Command(ship_id=sid, action="pass", args={}) for sid in state.player_ships["paulo"]
    }
    log = resolve_turn(state, commands)
    assert log is not None
    # Base regen 1 + capacitor 1 = 2 shields back (capacity raised to 2 via
    # additional_void_shield so the capacitor's extra point has room to land)
    assert flag.shields_current == 2
    # Commissariat doctrine wired through assembly
    assert flag.morale_floor == 20
