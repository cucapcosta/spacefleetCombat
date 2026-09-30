"""HangarScreen: refit, flagship, discard, repair and shipyard purchases (Pilot)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.app import App
from textual.widgets import Input, OptionList

from spacefleet.campaign.models import CampaignStatus
from spacefleet.persistence.campaign_save import load_campaign, save_campaign
from spacefleet.tui.screens.hangar import HangarScreen
from spacefleet.tui.widgets.confirm import ConfirmScreen, TextInputScreen
from spacefleet.tui.widgets.hangar_view import HangarView
from spacefleet.tui.widgets.ship_panel import ShipPanel
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from textual.pilot import Pilot

    from spacefleet.campaign.models import CampaignState


def _run(
    campaign: CampaignState,
    path: Path,
    script: Callable[[Pilot[Any], HangarScreen], Awaitable[None]],
    *,
    shipyard: bool = False,
) -> tuple[HangarScreen, list[CampaignState | None]]:
    results: list[CampaignState | None] = []
    screen = HangarScreen(campaign, path, shipyard=shipyard)

    class Host(App[None]):
        def on_mount(self) -> None:
            self.push_screen(screen, results.append)

    async def go() -> None:
        app = Host()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await script(pilot, screen)
            await pilot.pause()

    asyncio.run(go())
    return screen, results


async def _press(pilot: Pilot[Any], *keys: str) -> None:
    for key in keys:
        await pilot.press(key)
        await pilot.pause()


async def _open_option(pilot: Pilot[Any], screen: HangarScreen, slot: int, value: str) -> None:
    """Move to *slot* (0-based) of the selected ship, open it and highlight *value*."""
    panel = screen.query_one("#panel", ShipPanel)
    await _press(pilot, *(["down"] * slot), "enter")
    assert panel.mode == "options"
    index = [choice.value for choice in panel.options].index(value)
    await _press(pilot, *(["down"] * index))
    assert panel.current_option is not None and panel.current_option.value == value


def _saved(tmp_path: Path, campaign: CampaignState | None = None) -> Path:
    return save_campaign(campaign or campaign_state(), tmp_path / "campaign.json")


def test_refit_preview_shows_resulting_credits_and_autosaves(tmp_path: Path) -> None:
    campaign = campaign_state()
    path = _saved(tmp_path, campaign)
    seen: dict[str, str] = {}

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _open_option(pilot, screen, 2, "macro_cannon_2")
        panel = screen.query_one("#panel", ShipPanel)
        seen["panel"] = str(panel.render())
        await _press(pilot, "enter")
        modal = pilot.app.screen
        assert isinstance(modal, ConfirmScreen)
        seen["confirm"] = modal.message
        await _press(pilot, "y")

    screen, _ = _run(campaign, path, script)

    assert "−8 → 582 cr" in seen["panel"]
    assert "resulting credits 582" in seen["confirm"]
    loaded = load_campaign(path)
    assert loaded.roster[0].spec.weapons[3] == "macro_cannon_2"
    assert loaded.credits == 582
    assert screen.log_lines[-1] == (
        "Refit W3 Prow Weapon Bay → Macro-Cannon Mk.II (charge 8 credits). Autosaved."
    )
    assert screen.campaign.credits == 582


def test_refit_cancel_keeps_save_bytes(tmp_path: Path) -> None:
    campaign = campaign_state()
    path = _saved(tmp_path, campaign)
    before = path.read_bytes()

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _open_option(pilot, screen, 2, "macro_cannon_2")
        await _press(pilot, "enter", "n")
        assert isinstance(pilot.app.screen, HangarScreen)

    screen, _ = _run(campaign, path, script)

    assert path.read_bytes() == before
    assert screen.campaign.roster[0].spec.weapons[3] == "lance_2"


def test_unaffordable_option_shows_reason_and_does_nothing(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.credits = 0
    path = _saved(tmp_path, campaign)
    before = path.read_bytes()
    seen: dict[str, Any] = {}

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _open_option(pilot, screen, 2, "macro_cannon_2")
        panel = screen.query_one("#panel", ShipPanel)
        seen["values"] = [choice.value for choice in panel.options]
        seen["panel"] = str(panel.render())
        await _press(pilot, "enter")
        seen["screen"] = pilot.app.screen

    screen, _ = _run(campaign, path, script)

    assert "insufficient credits" in seen["panel"]
    assert "−8 → -8 cr" in seen["panel"]
    assert "standard_torpedoes" not in seen["values"]
    assert isinstance(seen["screen"], HangarScreen)
    assert path.read_bytes() == before


def test_flagship_change_is_confirmed_and_saved(tmp_path: Path) -> None:
    campaign = campaign_state()
    path = _saved(tmp_path, campaign)

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _press(pilot, "right")
        assert screen.selected_ship is not None and screen.selected_ship.id == "ship-2"
        await _press(pilot, "f")
        assert isinstance(pilot.app.screen, ConfirmScreen)
        await _press(pilot, "y")

    screen, _ = _run(campaign, path, script)

    assert load_campaign(path).flagship_id == "ship-2"
    assert screen.log_lines[-1] == "Test Escort is now the flagship. Autosaved."


def test_discard_is_confirmed_and_saved(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.credits = 1_000
    path = _saved(tmp_path, campaign)
    seen: dict[str, Any] = {}

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _press(pilot, "right", "x")
        modal = pilot.app.screen
        assert isinstance(modal, ConfirmScreen)
        seen["confirm"] = modal.message
        await _press(pilot, "y")
        seen["selected"] = screen.query_one("#roster", HangarView).selected

    screen, _ = _run(campaign, path, script)

    assert seen["confirm"] == "Discard Test Escort permanently with no refund?"
    loaded = load_campaign(path)
    assert [ship.id for ship in loaded.roster] == ["ship-1"]
    assert loaded.credits == 1_000
    assert seen["selected"] == 0


def test_repair_selected_ship(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    path = _saved(tmp_path, campaign)
    seen: dict[str, str] = {}

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _press(pilot, "right", "r")
        seen["undamaged"] = screen.log_lines[-1]
        await _press(pilot, "left", "r")
        modal = pilot.app.screen
        assert isinstance(modal, ConfirmScreen)
        seen["confirm"] = modal.message
        await _press(pilot, "y")

    screen, _ = _run(campaign, path, script)

    assert seen["undamaged"] == "Test Escort has no damage to repair."
    assert "resulting credits 574" in seen["confirm"]
    loaded = load_campaign(path)
    assert loaded.roster[0].hull_damage == 0
    assert loaded.credits == campaign.credits - 16


def test_shipyard_buy_names_ship_and_returns_to_hangar(tmp_path: Path) -> None:
    campaign = campaign_state()
    path = _saved(tmp_path, campaign)
    seen: dict[str, Any] = {}

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _press(pilot, "y")
        assert screen.mode == "shipyard"
        offers = screen.query_one("#offers", OptionList)
        index = next(
            i
            for i in range(offers.option_count)
            if offers.get_option_at_index(i).id == "sword_frigate"
        )
        offers.highlighted = index
        await pilot.pause()
        seen["stats"] = str(screen.query_one("#yard-stats").render())
        await _press(pilot, "enter")
        modal = pilot.app.screen
        assert isinstance(modal, TextInputScreen)
        seen["default"] = modal.default
        modal.query_one("#value", Input).value = ""
        await _press(pilot, "enter")
        seen["empty_error"] = str(modal.query_one("#error").render())
        await pilot.press(*"Reinforcement")
        await _press(pilot, "enter")
        confirm = pilot.app.screen
        assert isinstance(confirm, ConfirmScreen)
        seen["confirm"] = confirm.message
        await _press(pilot, "y")
        seen["selected"] = screen.query_one("#roster", HangarView).selected

    screen, _ = _run(campaign, path, script)

    assert "Sword-class Frigate" in seen["stats"] and "Speed" in seen["stats"]
    assert seen["default"] == "Sword-class Frigate"
    assert "cannot be empty" in seen["empty_error"]
    assert "resulting credits 565" in seen["confirm"]
    loaded = load_campaign(path)
    assert [ship.spec.name for ship in loaded.roster][-1] == "Reinforcement"
    assert loaded.credits == 565
    assert screen.mode == "hangar"
    assert screen.selected_ship is not None and screen.selected_ship.id == "ship-3"
    assert seen["selected"] == 2


def test_blocked_hull_is_listed_but_not_buyable(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.credits = 50
    path = _saved(tmp_path, campaign)
    before = path.read_bytes()
    seen: dict[str, Any] = {}

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        offers = screen.query_one("#offers", OptionList)
        index = next(
            i
            for i in range(offers.option_count)
            if offers.get_option_at_index(i).id == "emperor_battleship"
        )
        seen["prompt"] = str(offers.get_option_at_index(index).prompt)
        offers.highlighted = index
        await _press(pilot, "enter")
        seen["screen"] = pilot.app.screen

    screen, _ = _run(campaign, path, script, shipyard=True)

    assert "insufficient credits" in seen["prompt"]
    assert isinstance(seen["screen"], HangarScreen)
    assert screen.log_lines[-1] == "Cannot buy Emperor-class Battleship: insufficient credits."
    assert path.read_bytes() == before


def test_escape_returns_updated_campaign(tmp_path: Path) -> None:
    campaign = campaign_state()
    path = _saved(tmp_path, campaign)

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _press(pilot, "right", "f", "y")
        await _press(pilot, "down", "enter", "escape")  # Esc closes the options first
        assert isinstance(pilot.app.screen, HangarScreen)
        await _press(pilot, "escape")

    _, results = _run(campaign, path, script)

    assert len(results) == 1
    assert results[0] is not None
    assert results[0].flagship_id == "ship-2"
    assert campaign.flagship_id == "ship-1"  # the caller's object is untouched


def test_escape_in_shipyard(tmp_path: Path) -> None:
    campaign = campaign_state()
    path = _saved(tmp_path, campaign)

    async def via_hangar(pilot: Pilot[Any], screen: HangarScreen) -> None:
        await _press(pilot, "y", "escape")
        assert screen.mode == "hangar"
        assert isinstance(pilot.app.screen, HangarScreen)
        await _press(pilot, "y", "h")
        assert screen.mode == "hangar"

    _, results = _run(campaign, path, via_hangar)
    assert results == []

    async def direct(pilot: Pilot[Any], screen: HangarScreen) -> None:
        assert screen.mode == "shipyard"
        await _press(pilot, "escape")

    _, results = _run(campaign, path, direct, shipyard=True)
    assert len(results) == 1


def test_inactive_campaign_blocks_actions(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.status = CampaignStatus.COMPLETED
    campaign.roster[0].hull_damage = 1
    path = _saved(tmp_path, campaign)
    before = path.read_bytes()
    seen: dict[str, Any] = {}

    async def script(pilot: Pilot[Any], screen: HangarScreen) -> None:
        for key in ("f", "x", "r", "y"):
            await _press(pilot, key)
            seen[key] = pilot.app.screen
        await _open_option(pilot, screen, 2, "remove")
        seen["panel"] = str(screen.query_one("#panel", ShipPanel).render())
        await _press(pilot, "enter")
        seen["after"] = pilot.app.screen

    screen, _ = _run(campaign, path, script)

    assert all(isinstance(seen[key], HangarScreen) for key in ("f", "x", "r", "y", "after"))
    assert screen.mode == "hangar"
    assert screen.log_lines.count("Campaign is completed; the fleet can no longer be changed.") == 4
    assert "campaign is not active" in seen["panel"]
    assert path.read_bytes() == before
