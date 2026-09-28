"""FleetBuilderSession — command interpreter, no I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.cli.fleet_builder_cmd import FleetBuilderSession
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry

if TYPE_CHECKING:
    from pathlib import Path


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


def test_equip_slot_upgrade_doctrine_flow() -> None:
    s = _session()
    s.execute("buy dauntless_light_cruiser ISS Flag")
    out = s.execute("equip 1")
    assert "ISS Flag" in out
    assert "slot 1 macro_cannon_3" != ""  # entering equip mode
    out = s.execute("slot 1 macro_cannon_3")
    assert "macro_cannon_3" in out
    out = s.execute("upgrade reinforced_prow")
    assert "reinforced_prow" in out
    out = s.execute("doctrine commissariat")
    assert "commissariat" in out
    out = s.execute("show")
    assert "macro_cannon_3" in out and "reinforced_prow" in out
    s.execute("back")
    ship = s.fleet.ships[0]
    assert ship.weapons[1] == "macro_cannon_3"
    assert ship.upgrade_ids == ["reinforced_prow"]
    assert ship.doctrine_id == "commissariat"


def test_equip_rejects_illegal_and_reverts() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    s.execute("equip 1")
    out = s.execute("slot 1 macro_cannon_3")  # medium gun in small slot
    assert "too large" in out or "not allowed" in out.lower() or "slot" in out.lower()
    assert s.fleet.ships[0].weapons == {}  # reverted


def test_unslot_and_remove_upgrade() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    s.execute("equip 1")
    s.execute("slot 1 macro_cannon_1")
    s.execute("upgrade reinforced_prow")
    s.execute("unslot 1")
    s.execute("remove-upgrade reinforced_prow")
    assert s.fleet.ships[0].weapons == {}
    assert s.fleet.ships[0].upgrade_ids == []


def test_default_command_applies_hull_kit() -> None:
    s = _session()
    s.execute("buy cobra_destroyer ISS Cobra")
    s.execute("equip 1")
    out = s.execute("default")
    assert "default" in out.lower()
    assert s.fleet.ships[0].weapons == {1: "macro_cannon_1", 2: "standard_torpedoes"}


def test_flagship_command() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS One")
    s.execute("buy sword_frigate ISS Two")
    s.execute("equip 2")
    out = s.execute("flagship")
    assert "flagship" in out.lower()
    assert s.fleet.flagship_index == 1


def test_remove_before_flagship_keeps_flagship() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS A")
    s.execute("buy sword_frigate ISS B")
    s.execute("buy sword_frigate ISS C")
    s.execute("equip 2")
    s.execute("flagship")
    s.execute("back")
    assert s.fleet.flagship_index == 1
    out = s.execute("remove 1")
    assert "removed" in out.lower()
    assert s.fleet.ships[s.fleet.flagship_index].name == "ISS B"


def test_remove_the_flagship_resets_to_zero() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS A")
    s.execute("buy sword_frigate ISS B")
    s.execute("buy sword_frigate ISS C")
    s.execute("equip 2")
    s.execute("flagship")
    s.execute("back")
    assert s.fleet.flagship_index == 1
    s.execute("remove 2")
    assert s.fleet.flagship_index == 0


def test_remove_after_flagship_unchanged() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS A")
    s.execute("buy sword_frigate ISS B")
    s.execute("buy sword_frigate ISS C")
    s.execute("equip 1")
    s.execute("flagship")
    s.execute("back")
    assert s.fleet.flagship_index == 0
    s.execute("remove 2")
    assert s.fleet.flagship_index == 0
    assert s.fleet.ships[s.fleet.flagship_index].name == "ISS A"


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    path = tmp_path / "myfleet.json"
    out = s.execute(f"save {path}")
    assert str(path) in out
    s2 = _session()
    out = s2.execute(f"load {path}")
    assert "ISS Blade" in out or "loaded" in out.lower()
    assert s2.fleet.ships[0].name == "ISS Blade"


def test_load_over_budget_rejected(tmp_path: Path) -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    path = tmp_path / "f.json"
    s.execute(f"save {path}")
    tiny = FleetBuilderSession(Faction.IMPERIAL_NAVY, budget=5)
    out = tiny.execute(f"load {path}")
    assert "budget" in out.lower()
    assert tiny.fleet.ships == []


def test_run_fleet_builder_is_exported() -> None:
    from spacefleet.cli.fleet_builder_cmd import run_fleet_builder

    assert callable(run_fleet_builder)


def test_run_fleet_builder_returns_completed_fleet(monkeypatch) -> None:
    from spacefleet.cli.fleet_builder_cmd import run_fleet_builder
    from spacefleet.core.types import Faction
    from tests.terminal_ui_helpers import FakeTerminalUI

    ui = FakeTerminalUI(
        choices=["add_ship", "sword_frigate", "done"],
        texts=["ISS Blade"],
        confirmations=[True],
    )

    fleet = run_fleet_builder(
        faction=Faction.IMPERIAL_NAVY,
        budget=800,
        name="Campaign Fleet",
        ui=ui,
    )

    assert fleet is not None
    assert fleet.name == "Campaign Fleet"
    assert [ship.name for ship in fleet.ships] == ["ISS Blade"]


def test_run_fleet_builder_cancel_returns_none(monkeypatch) -> None:
    from spacefleet.cli.fleet_builder_cmd import run_fleet_builder
    from spacefleet.core.types import Faction
    from tests.terminal_ui_helpers import FakeTerminalUI

    ui = FakeTerminalUI(choices=["cancel"], confirmations=[True])

    assert (
        run_fleet_builder(
            faction=Faction.IMPERIAL_NAVY,
            budget=800,
            name="Campaign Fleet",
            ui=ui,
        )
        is None
    )


def test_app_menu_mentions_fleet_builder() -> None:
    from spacefleet.cli.app import MENU

    assert "Fleet Builder" in MENU
    assert "not yet available" not in MENU
