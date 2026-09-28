from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.campaign.rules import validate_campaign_fleet
from spacefleet.cli.fitting import fitting_choices
from spacefleet.cli.fleet_builder_cmd import FleetBuilderSession, _roster_options, run_fleet_builder
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import FleetSpec, FleetSpecError, ShipSpec
from spacefleet.persistence.fleet_save import save_fleet
from tests.terminal_ui_helpers import FakeTerminalUI

if TYPE_CHECKING:
    from pathlib import Path


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def test_builder_buys_fits_removes_and_completes_without_ids() -> None:
    choices = [
        "add_ship",
        "sword_frigate",
        "ship:0",
        "weapon:1",
        "macro_cannon_1",
        "weapon:1",
        "remove",
        "weapon:1",
        "macro_cannon_1",
        "flagship",
        "done",
    ]
    ui = FakeTerminalUI(choices=choices, texts=["ISS Blade"], confirmations=[True])

    fleet = run_fleet_builder(
        faction=Faction.IMPERIAL_NAVY,
        budget=800,
        name="Campaign Fleet",
        ui=ui,
    )

    assert fleet is not None
    assert fleet.ships[0].name == "ISS Blade"
    assert fleet.ships[0].weapons == {1: "macro_cannon_1"}
    assert fleet.flagship_index == 0


def test_roster_labels_disambiguate_positions_and_hulls() -> None:
    session = FleetBuilderSession(Faction.IMPERIAL_NAVY)
    session.fleet.ships = [
        ShipSpec("Escort", "sword_frigate"),
        ShipSpec("Escort", "cobra_destroyer"),
    ]

    labels = [
        option.label for option in _roster_options(session) if option.value.startswith("ship:")
    ]

    assert labels[0].startswith("1. Escort — Sword-class Frigate")
    assert labels[1].startswith("2. Escort — Cobra-class Destroyer")


def test_upgrade_capacity_is_presented_as_positions_without_persisted_slot_ids() -> None:
    ui = FakeTerminalUI(
        choices=[
            "add_ship",
            "sword_frigate",
            "ship:0",
            "upgrade:0",
            "reinforced_prow",
            "back",
            "done",
        ],
        texts=["ISS Blade"],
        confirmations=[True],
    )

    fleet = run_fleet_builder(
        faction=Faction.IMPERIAL_NAVY,
        budget=800,
        name="Fleet",
        ui=ui,
    )

    assert fleet is not None
    assert fleet.ships[0].upgrade_ids == ["reinforced_prow"]
    ship_menu = next(call for call in ui.choose_calls if call[0] == "Configure ship")
    upgrade_options = [option for option in ship_menu[1] if option.value.startswith("upgrade:")]
    assert [option.label for option in upgrade_options] == ["Upgrade position 1: Empty"]


def test_registry_names_and_descriptions_are_shown_in_fitting_details() -> None:
    choices = fitting_choices(
        ShipSpec("ISS Blade", "sword_frigate"),
        Faction.IMPERIAL_NAVY,
        kind="weapon",
        slot_id=1,
        is_flagship=True,
    )
    macro = next(choice for choice in choices if choice.value == "macro_cannon_1")

    assert macro.label == WeaponRegistry.get("macro_cannon_1").name
    assert WeaponRegistry.get("macro_cannon_1").description in macro.details
    assert "strength 2" in macro.details
    assert "range 30" in macro.details


def test_every_nested_cancel_preserves_the_draft() -> None:
    ui = FakeTerminalUI(
        choices=[
            "add_ship",
            "sword_frigate",
            "ship:0",
            "weapon:1",
            None,
            "upgrade:0",
            None,
            "doctrine",
            None,
            "back",
            "done",
        ],
        texts=["ISS Blade"],
        confirmations=[True],
    )

    fleet = run_fleet_builder(
        faction=Faction.IMPERIAL_NAVY,
        budget=800,
        name="Fleet",
        ui=ui,
    )

    assert fleet is not None
    assert fleet.ships == [ShipSpec("ISS Blade", "sword_frigate")]


def test_fitting_choices_omit_engine_and_callback_invalid_candidates() -> None:
    spec = ShipSpec("ISS Blade", "sword_frigate")
    weapons = fitting_choices(
        spec,
        Faction.IMPERIAL_NAVY,
        kind="weapon",
        slot_id=1,
        is_flagship=True,
    )
    assert "macro_cannon_1" in {choice.value for choice in weapons}
    assert "lance_1" not in {choice.value for choice in weapons}

    def reject_power_ram(candidate: ShipSpec) -> None:
        if "power_ram" in candidate.upgrade_ids:
            raise FleetSpecError("blocked")

    upgrades = fitting_choices(
        spec,
        Faction.IMPERIAL_NAVY,
        kind="upgrade",
        slot_id=None,
        is_flagship=True,
        candidate_validator=reject_power_ram,
    )
    assert "power_ram" not in {choice.value for choice in upgrades}
    assert "reinforced_prow" in {choice.value for choice in upgrades}


def test_legal_unaffordable_fitting_remains_visible_and_disabled() -> None:
    ui = FakeTerminalUI(
        choices=[
            "add_ship",
            "sword_frigate",
            "ship:0",
            "weapon:1",
            None,
            "back",
            "cancel",
        ],
        texts=["ISS Blade"],
        confirmations=[True],
    )

    assert (
        run_fleet_builder(
            faction=Faction.IMPERIAL_NAVY,
            budget=30,
            name="Fleet",
            ui=ui,
        )
        is None
    )

    fitting_call = next(call for call in ui.choose_calls if call[0] == "Choose weapon")
    macro = next(option for option in fitting_call[1] if option.value == "macro_cannon_1")
    assert macro.disabled_reason is not None
    assert "budget" in macro.disabled_reason


def test_campaign_invalid_load_is_rejected_without_replacing_draft(tmp_path: Path) -> None:
    blocked = FleetSpec(
        "Blocked",
        Faction.IMPERIAL_NAVY,
        [ShipSpec("Loaded Ship", "sword_frigate", upgrade_ids=["power_ram"])],
    )
    path = save_fleet(blocked, tmp_path / "blocked.json")
    ui = FakeTerminalUI(
        choices=["add_ship", "sword_frigate", "load", "done"],
        texts=["Original Ship", str(path)],
        confirmations=[True, True],
    )

    fleet = run_fleet_builder(
        faction=Faction.IMPERIAL_NAVY,
        budget=800,
        name="Fleet",
        ui=ui,
        candidate_validator=validate_campaign_fleet,
    )

    assert fleet is not None
    assert [ship.name for ship in fleet.ships] == ["Original Ship"]
    assert any("not supported in campaign" in message for message in ui.show_calls)


def test_default_save_and_load_actions_remain_reachable(tmp_path: Path) -> None:
    path = tmp_path / "fleet.json"
    ui = FakeTerminalUI(
        choices=[
            "add_ship",
            "cobra_destroyer",
            "ship:0",
            "default",
            "back",
            "save",
            "load",
            "done",
        ],
        texts=["ISS Cobra", str(path), str(path)],
        confirmations=[True, True],
    )

    fleet = run_fleet_builder(
        faction=Faction.IMPERIAL_NAVY,
        budget=800,
        name="Fleet",
        ui=ui,
    )

    assert fleet is not None
    assert fleet.ships[0].weapons == {1: "macro_cannon_1", 2: "standard_torpedoes"}
    assert path.is_file()
    values = {option.value for call in ui.choose_calls for option in call[1]}
    assert {"default", "save", "load"} <= values


def test_finish_rejects_empty_fleet_before_confirmation() -> None:
    ui = FakeTerminalUI(choices=["done", "cancel"], confirmations=[True])

    assert (
        run_fleet_builder(
            faction=Faction.IMPERIAL_NAVY,
            budget=800,
            name="Fleet",
            ui=ui,
        )
        is None
    )
    assert ui.confirm_calls == ["Discard this fleet draft?"]
    assert any("at least one ship" in message for message in ui.show_calls)
