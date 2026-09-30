"""FleetBuilderScreen driven by Pilot, plus its pure helpers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.app import App
from textual.widgets import Input, OptionList, Select, Static

from spacefleet.campaign.rules import validate_campaign_fleet
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import FleetSpec, ShipSpec, fleet_points
from spacefleet.persistence.fleet_save import save_fleet
from spacefleet.tui.model.fleet_builder import (
    BUDGET_ERROR,
    default_save_path,
    fitting_preview,
    hull_options,
    parse_budget,
    unique_ship_name,
    validate_candidate,
    without_ship,
)
from spacefleet.tui.screens.fleet_builder import (
    FleetBuilderScreen,
    FleetSetupScreen,
    HullPickerScreen,
)
from spacefleet.tui.widgets.confirm import ConfirmScreen, TextInputScreen
from spacefleet.tui.widgets.ship_panel import ShipPanel

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from textual.pilot import Pilot


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def _run(
    screen: FleetBuilderScreen,
    scenario: Callable[[Pilot[None], FleetBuilderScreen], Awaitable[None]],
) -> list[FleetSpec | None]:
    results: list[FleetSpec | None] = []

    class Host(App[None]):
        def on_mount(self) -> None:
            self.push_screen(screen, results.append)

    async def go() -> None:
        app = Host()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await scenario(pilot, screen)
            await pilot.pause()

    asyncio.run(go())
    return results


def _imperial(budget: int = 1000, **kwargs: Any) -> FleetBuilderScreen:
    return FleetBuilderScreen(faction=Faction.IMPERIAL_NAVY, budget=budget, name="Test", **kwargs)


def _header(screen: FleetBuilderScreen) -> str:
    return str(screen.query_one("#header", Static).render())


async def _press(pilot: Pilot[None], *keys: str) -> None:
    for key in keys:
        await pilot.press(key)
        await pilot.pause()


async def _add(pilot: Pilot[None], hull_id: str, name: str | None = None) -> None:
    await _press(pilot, "a")
    picker = pilot.app.screen
    assert isinstance(picker, HullPickerScreen)
    hulls = picker.query_one("#hulls", OptionList)
    hulls.highlighted = hulls.get_option_index(hull_id)
    await _press(pilot, "enter")
    prompt = pilot.app.screen
    assert isinstance(prompt, TextInputScreen)
    if name is not None:
        prompt.query_one("#value", Input).value = name
    await _press(pilot, "enter")


async def _fit(pilot: Pilot[None], screen: FleetBuilderScreen, slot: int, value: str) -> None:
    panel = screen.query_one(ShipPanel)
    panel.focus()
    while panel.slot_index != slot:
        await _press(pilot, "down")
    await _press(pilot, "enter")
    assert panel.mode == "options"
    target = [choice.value for choice in panel.options].index(value)
    for _ in range(target):
        await _press(pilot, "down")
    await _press(pilot, "enter")


async def _type_path(pilot: Pilot[None], path: Path) -> None:
    prompt = pilot.app.screen
    assert isinstance(prompt, TextInputScreen)
    prompt.query_one("#value", Input).value = str(path)
    await _press(pilot, "enter")


# ── pure helpers ─────────────────────────────────────────────────────────────


def test_parse_budget_bounds() -> None:
    assert parse_budget("1000") == 1000
    assert parse_budget(" 1 ") == 1
    assert parse_budget("100000") == 100_000
    assert parse_budget("0") is None
    assert parse_budget("100001") is None
    assert parse_budget("lots") is None


def test_without_ship_fixes_flagship_index() -> None:
    fleet = FleetSpec(
        "F",
        Faction.IMPERIAL_NAVY,
        [ShipSpec(n, "sword_frigate") for n in ("A", "B", "C")],
        flagship_index=1,
    )
    assert without_ship(fleet, 0).flagship_index == 0
    assert without_ship(fleet, 0).ships[0].name == "B"
    assert without_ship(fleet, 1).flagship_index == 0
    assert without_ship(fleet, 2).flagship_index == 1
    assert len(fleet.ships) == 3  # detached


def test_fitting_preview_and_candidate_validation() -> None:
    fleet = FleetSpec("F", Faction.IMPERIAL_NAVY, [ShipSpec("A", "sword_frigate")])
    fitted = ShipSpec("A", "sword_frigate", weapons={1: "macro_cannon_1"})
    assert fitting_preview(fleet, 0, fitted, 100) == ("+10 pts → 35/100", None)
    assert fitting_preview(fleet, 0, fitted, 30) == (
        "+10 pts → 35/30",
        "costs 35 pts; budget is 30",
    )
    validate_candidate(FleetSpec("E", Faction.IMPERIAL_NAVY), 10)  # empty draft is fine
    assert unique_ship_name(fleet, "A") == "A 2"
    assert default_save_path("My Fleet!").name == "my_fleet.json"


def test_hull_options_mark_unaffordable_hulls() -> None:
    fleet = FleetSpec("F", Faction.IMPERIAL_NAVY)
    options = {option.hull.id: option.reason for option in hull_options(fleet, 100)}
    assert options["sword_frigate"] is None
    assert options["emperor_battleship"] == "needs 280 pts; 100 remaining"
    assert "murder_cruiser" not in options


# ── free mode setup ──────────────────────────────────────────────────────────


def test_setup_form_rejects_bad_budget_and_cancel_returns_none() -> None:
    seen: list[str] = []

    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        form = pilot.app.screen
        assert isinstance(form, FleetSetupScreen)
        form.query_one("#budget", Input).value = "0"
        await _press(pilot, "enter")
        seen.append(str(form.query_one("#error", Static).render()))
        assert pilot.app.screen is form
        await _press(pilot, "escape")

    assert _run(FleetBuilderScreen(), scenario) == [None]
    assert seen == [BUDGET_ERROR]


def test_setup_form_configures_the_draft() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        form = pilot.app.screen
        assert isinstance(form, FleetSetupScreen)
        form.query_one("#faction", Select).value = Faction.CHAOS_FLEET
        form.query_one("#budget", Input).value = "500"
        form.query_one("#name", Input).value = "Raiders"
        await _press(pilot, "enter")
        assert pilot.app.screen is screen
        assert screen.fleet.faction is Faction.CHAOS_FLEET
        assert "Fleet Builder · Chaos Fleet · Raiders · 0 / 500 pts" in _header(screen)
        assert str(screen.query_one("#empty", Static).render()) == "Press a to add a ship."
        await _add(pilot, "iconoclast_destroyer")
        assert screen.fleet.ships[0].name == "Iconoclast-class Destroyer"
        assert "20 / 500 pts" in _header(screen)

    assert _run(FleetBuilderScreen(), scenario) == []


# ── building ────────────────────────────────────────────────────────────────


def test_add_ship_and_fit_weapon_update_points() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        await _add(pilot, "sword_frigate", "ISS Blade")
        assert [ship.name for ship in screen.fleet.ships] == ["ISS Blade"]
        assert "25 / 1000 pts · 975 remaining" in _header(screen)
        await _fit(pilot, screen, 0, "macro_cannon_1")
        assert screen.fleet.ships[0].weapons == {1: "macro_cannon_1"}
        assert "35 / 1000 pts" in _header(screen)
        assert any("+10 pts" in line for line in screen.log_lines)
        # Remove goes through the same preview and is adopted.
        await _fit(pilot, screen, 0, "remove")
        assert screen.fleet.ships[0].weapons == {}
        assert "25 / 1000 pts" in _header(screen)

    _run(_imperial(), scenario)


def test_unaffordable_fitting_and_hull_are_blocked_with_reason() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        await _add(pilot, "sword_frigate", "ISS Blade")
        panel = screen.query_one(ShipPanel)
        await _fit(pilot, screen, 0, "macro_cannon_1")
        # Still in options: the choice was refused with its reason shown.
        assert panel.mode == "options"
        assert "costs 35 pts; budget is 30" in str(panel.render())
        assert screen.fleet.ships[0].weapons == {}
        await _press(pilot, "escape")  # panel back to slots, screen stays
        assert pilot.app.screen is screen

        await _press(pilot, "a")
        picker = pilot.app.screen
        assert isinstance(picker, HullPickerScreen)
        hulls = picker.query_one("#hulls", OptionList)
        hulls.highlighted = hulls.get_option_index("dauntless_light_cruiser")
        await _press(pilot, "enter")
        assert pilot.app.screen is picker
        assert "needs 80 pts; 5 remaining" in str(picker.query_one("#error", Static).render())
        await _press(pilot, "escape")
        assert len(screen.fleet.ships) == 1

    _run(_imperial(budget=30), scenario)


def test_flagship_change_and_remove_with_fixup() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        for name in ("A", "B", "C"):
            await _add(pilot, "sword_frigate", name)
        assert screen.selected == 2
        await _press(pilot, "left", "f")
        assert screen.fleet.flagship_index == 1
        assert "B is now the flagship." in screen.log_lines
        await _press(pilot, "left", "x")
        assert isinstance(pilot.app.screen, ConfirmScreen)
        await _press(pilot, "y")
        assert [ship.name for ship in screen.fleet.ships] == ["B", "C"]
        assert screen.fleet.flagship_index == 0
        assert "50 / 1000 pts" in _header(screen)
        await _press(pilot, "x", "n")  # declined: nothing changes
        assert len(screen.fleet.ships) == 2

    _run(_imperial(), scenario)


def test_default_loadout_key() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        await _add(pilot, "cobra_destroyer", "ISS Cobra")
        await _press(pilot, "o")
        assert screen.fleet.ships[0].weapons == {1: "macro_cannon_1", 2: "standard_torpedoes"}
        assert f"{fleet_points(screen.fleet)} / 1000 pts" in _header(screen)

    _run(_imperial(), scenario)


# ── save / load ─────────────────────────────────────────────────────────────


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "fleet.json"
    chaos = tmp_path / "chaos.json"
    save_fleet(
        FleetSpec("Traitors", Faction.CHAOS_FLEET, [ShipSpec("X", "iconoclast_destroyer")]),
        chaos,
    )

    async def save(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        await _add(pilot, "sword_frigate", "ISS Blade")
        await _fit(pilot, screen, 0, "macro_cannon_1")
        await _press(pilot, "s")
        await _type_path(pilot, path)
        assert f"Saved to {path}" in screen.log_lines
        await _press(pilot, "s")
        await _type_path(pilot, path)
        assert isinstance(pilot.app.screen, ConfirmScreen)  # replace?
        await _press(pilot, "y")
        assert screen.log_lines.count(f"Saved to {path}") == 2

    _run(_imperial(), save)

    async def load(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        await _add(pilot, "cobra_destroyer", "Placeholder")
        await _press(pilot, "l")
        await _type_path(pilot, chaos)
        await _press(pilot, "y")  # replace the non-empty draft
        assert any("fleet is chaos_fleet" in line for line in screen.log_lines)
        assert [ship.name for ship in screen.fleet.ships] == ["Placeholder"]
        await _press(pilot, "l")
        await _type_path(pilot, path)
        await _press(pilot, "y")
        assert [ship.name for ship in screen.fleet.ships] == ["ISS Blade"]
        assert screen.fleet.ships[0].weapons == {1: "macro_cannon_1"}
        assert "35 / 1000 pts" in _header(screen)

    _run(_imperial(), load)


# ── campaign mode ───────────────────────────────────────────────────────────


def test_campaign_mode_rejects_invalid_candidates_and_finishes() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        assert "Imperial Navy · Cmdr · 0 / 800 pts" in _header(screen)
        await _add(pilot, "cobra_destroyer", "ISS Cobra")
        await _press(pilot, "o")  # the default kit carries torpedoes
        assert screen.fleet.ships[0].weapons == {}
        assert any("unsupported torpedo" in line for line in screen.log_lines)
        panel = screen.query_one(ShipPanel)
        await _press(pilot, "down", "enter")  # torpedo slot: nothing legal
        assert panel.mode == "options"
        assert panel.options == []
        await _press(pilot, "escape", "up")
        await _fit(pilot, screen, 0, "macro_cannon_1")
        await _press(pilot, "d")
        assert isinstance(pilot.app.screen, ConfirmScreen)
        await _press(pilot, "y")

    screen = FleetBuilderScreen(
        faction=Faction.IMPERIAL_NAVY,
        budget=800,
        name="Cmdr",
        validator=validate_campaign_fleet,
    )
    results = _run(screen, scenario)
    assert len(results) == 1
    fleet = results[0]
    assert fleet is not None
    assert fleet.name == "Cmdr"
    assert fleet.ships[0].weapons == {1: "macro_cannon_1"}
    validate_campaign_fleet(fleet)


# ── finishing / discarding ──────────────────────────────────────────────────


def test_done_on_empty_fleet_logs_error() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        await _press(pilot, "d")
        assert pilot.app.screen is screen
        assert "fleet needs at least one ship" in screen.log_lines

    assert _run(_imperial(), scenario) == []


def test_escape_confirms_discard() -> None:
    async def scenario(pilot: Pilot[None], screen: FleetBuilderScreen) -> None:
        await _add(pilot, "sword_frigate", "ISS Blade")
        await _press(pilot, "escape", "n")
        assert pilot.app.screen is screen
        await _press(pilot, "escape", "y")

    assert _run(_imperial(), scenario) == [None]
