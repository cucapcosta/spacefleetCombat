"""FleetBuilderSession — command interpreter, no I/O."""

from __future__ import annotations

from spacefleet.cli.fleet_builder_cmd import FleetBuilderSession
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def _session(budget: int = 1000) -> FleetBuilderSession:
    return FleetBuilderSession(Faction.IMPERIAL_NAVY, budget=budget)


def test_buy_adds_ship_and_charges_budget() -> None:
    s = _session()
    out = s.execute("buy sword_frigate ISS Blade")
    assert "ISS Blade" in out
    hull_cost = HullRegistry.get("sword_frigate").hull_cost
    assert s.remaining == 1000 - hull_cost
    assert s.fleet.ships[0].hull_id == "sword_frigate"


def test_buy_unknown_hull_errors_cleanly() -> None:
    s = _session()
    out = s.execute("buy starfort Fortress")
    assert "unknown hull" in out.lower()
    assert s.fleet.ships == []


def test_buy_wrong_faction_hull_rejected() -> None:
    s = _session()
    out = s.execute("buy murder_cruiser Traitor")
    assert "faction" in out.lower()
    assert s.fleet.ships == []


def test_buy_over_budget_rejected() -> None:
    s = _session(budget=10)
    out = s.execute("buy sword_frigate ISS Blade")
    assert "budget" in out.lower()
    assert s.fleet.ships == []
    assert s.remaining == 10


def test_remove_refunds() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    out = s.execute("remove 1")
    assert "removed" in out.lower()
    assert s.fleet.ships == []
    assert s.remaining == 1000


def test_status_lists_ships_and_budget() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    out = s.execute("status")
    assert "ISS Blade" in out
    assert str(s.remaining) in out


def test_catalogs_list_faction_items() -> None:
    s = _session()
    assert "sword_frigate" in s.execute("hulls")
    assert "murder_cruiser" not in s.execute("hulls")  # chaos hull hidden
    assert "macro_cannon_1" in s.execute("weapons")
    assert "reinforced_prow" in s.execute("upgrades")
    doctrines = s.execute("doctrines")
    assert "commissariat" in doctrines
    assert "mark_of_khorne" not in doctrines  # chaos doctrine hidden


def test_done_flag_and_unknown_command() -> None:
    s = _session()
    assert "unknown command" in s.execute("frobnicate").lower()
    assert not s.done
    s.execute("done")
    assert s.done
