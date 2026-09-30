"""Ship panel: slot helpers and the Pilot-driven slot/options widget."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from textual.app import App
from textual.binding import Binding, BindingType

from spacefleet.cli.fitting import FittingChoice as ReexportedChoice
from spacefleet.tui.model.fitting import (
    FittingChoice,
    Slot,
    removal_choice,
    ship_slots,
    slot_choices,
)
from spacefleet.tui.widgets.ship_panel import ShipPanel
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.pilot import Pilot

    from spacefleet.models.fleet_spec import ShipSpec


def _spec() -> ShipSpec:
    return campaign_state().roster[0].spec


def test_reexport_keeps_cli_import_working() -> None:
    assert ReexportedChoice is FittingChoice


def test_ship_slots_lists_weapons_upgrades_and_doctrine() -> None:
    slots = ship_slots(_spec())
    kinds = [slot.kind for slot in slots]
    assert kinds == ["weapon", "weapon", "weapon", "upgrade", "upgrade", "doctrine"]
    first = slots[0]
    assert first.slot_id == 1
    assert first.label.startswith("W1 Port Battery")
    assert "port" in first.label and "medium" in first.label
    assert first.current == "Macro-Cannon Mk.II"
    assert slots[2].current == "Lance Mk.II"
    upgrades = [slot for slot in slots if slot.kind == "upgrade"]
    assert [slot.position for slot in upgrades] == [0, 1]
    assert all(slot.slot_id is None and slot.current == "Empty" for slot in upgrades)
    assert slots[-1] == Slot("doctrine", None, "Doctrine", "None")


def test_filled_upgrade_position_uses_its_index() -> None:
    spec = _spec()
    faction = campaign_state().faction
    empty_upgrade = next(slot for slot in ship_slots(spec) if slot.kind == "upgrade")
    fitted = slot_choices(spec, faction, empty_upgrade, is_flagship=True)[0].replacement
    upgrade = next(slot for slot in ship_slots(fitted) if slot.kind == "upgrade")
    assert upgrade.slot_id == 0 and upgrade.current != "Empty"
    removal = removal_choice(fitted, upgrade)
    assert removal is not None and removal.replacement.upgrade_ids == []


def test_slot_choices_offer_remove_only_for_filled_slots() -> None:
    spec = _spec()
    faction = campaign_state().faction
    weapon = ship_slots(spec)[0]
    choices = slot_choices(spec, faction, weapon, is_flagship=True)
    assert choices[0].value == "remove"
    assert choices[0].label == "Remove"
    assert 1 not in choices[0].replacement.weapons
    assert 1 in spec.weapons  # detached
    assert any(choice.value == "macro_cannon_3" for choice in choices)

    emptied = choices[0].replacement
    empty_weapon = ship_slots(emptied)[0]
    assert empty_weapon.current == "Empty"
    assert removal_choice(emptied, empty_weapon) is None
    assert all(
        choice.value != "remove"
        for choice in slot_choices(emptied, faction, empty_weapon, is_flagship=True)
    )
    doctrine = ship_slots(spec)[-1]
    assert removal_choice(spec, doctrine) is None


# ------------------------------------------------------------------ Pilot


class Host(App[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "host_back", "Back")]

    def __init__(self, blocked: str | None = None) -> None:
        super().__init__()
        self.blocked = blocked
        self.chosen: list[ShipPanel.FittingChosen] = []
        self.previewed: list[str] = []
        self.host_escapes = 0

    def compose(self) -> ComposeResult:
        yield ShipPanel()

    def on_mount(self) -> None:
        campaign = campaign_state()
        panel = self.query_one(ShipPanel)
        panel.set_ship(
            campaign.roster[0].spec,
            campaign.faction,
            is_flagship=True,
            header_lines=["Hull 6/6", "Battles 0"],
            preview=self.preview,
        )
        panel.focus()

    def preview(self, choice: FittingChoice) -> tuple[str, str | None]:
        self.previewed.append(choice.value)
        if choice.value == self.blocked:
            return "costs 999 pts", "over budget"
        return f"-{len(choice.value)} -> 100 cr", None

    def action_host_back(self) -> None:
        self.host_escapes += 1

    def on_ship_panel_fitting_chosen(self, message: ShipPanel.FittingChosen) -> None:
        self.chosen.append(message)


def _run(host: Host, script: object) -> None:
    async def go() -> None:
        async with host.run_test(size=(60, 60)) as pilot:
            await pilot.pause()
            await script(pilot, host.query_one(ShipPanel))  # type: ignore[operator]

    asyncio.run(go())


def _rendered(panel: ShipPanel) -> str:
    return str(panel.render())


def test_panel_lists_slots_and_header() -> None:
    async def script(pilot: Pilot[None], panel: ShipPanel) -> None:
        assert panel.mode == "slots"
        assert len(panel.slots) == 6
        text = _rendered(panel)
        assert "Test Flag ★" in text
        assert "Dauntless-class Light Cruiser" in text
        assert "Hull 6/6" in text
        assert "▸ W1 Port Battery" in text
        assert "Macro-Cannon Mk.II" in text
        assert "Doctrine" in text
        await pilot.press("down")
        assert panel.slot_index == 1
        assert panel.current_slot == panel.slots[1]
        await pilot.press("up", "up")
        assert panel.slot_index == len(panel.slots) - 1

    _run(Host(), script)


def test_enter_opens_options_with_preview_text() -> None:
    host = Host()

    async def script(pilot: Pilot[None], panel: ShipPanel) -> None:
        await pilot.press("enter")
        assert panel.mode == "options"
        assert panel.options[0].value == "remove"
        assert host.previewed == [choice.value for choice in panel.options]
        text = _rendered(panel)
        assert "Options for W1 Port Battery" in text
        assert "-6 -> 100 cr" in text  # "remove"
        await pilot.press("down")
        assert panel.option_index == 1
        details = panel.options[1].details.splitlines()[0]
        assert details in _rendered(panel)

    _run(host, script)


def test_unavailable_option_shows_reason_and_does_not_post() -> None:
    host = Host(blocked="macro_cannon_3")

    async def script(pilot: Pilot[None], panel: ShipPanel) -> None:
        await pilot.press("enter")
        target = next(i for i, c in enumerate(panel.options) if c.value == "macro_cannon_3")
        for _ in range(target):
            await pilot.press("down")
        assert "✗ over budget" in _rendered(panel)
        assert "costs 999 pts" in _rendered(panel)
        await pilot.press("enter")
        await pilot.pause()
        assert host.chosen == []
        assert panel.mode == "options"

    _run(host, script)


def test_available_option_posts_fitting_chosen_and_returns_to_slots() -> None:
    host = Host()

    async def script(pilot: Pilot[None], panel: ShipPanel) -> None:
        await pilot.press("down", "enter")  # W2 Starboard Battery
        target = next(i for i, c in enumerate(panel.options) if c.value == "macro_cannon_3")
        for _ in range(target):
            await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert panel.mode == "slots"
        assert len(host.chosen) == 1
        message = host.chosen[0]
        assert message.slot.slot_id == 2
        assert message.choice.value == "macro_cannon_3"
        assert message.choice.replacement.weapons[2] == "macro_cannon_3"

    _run(host, script)


def test_escape_closes_options_then_bubbles_to_host() -> None:
    host = Host()

    async def script(pilot: Pilot[None], panel: ShipPanel) -> None:
        await pilot.press("enter")
        assert panel.mode == "options"
        await pilot.press("escape")
        assert panel.mode == "slots"
        assert host.host_escapes == 0
        await pilot.press("escape")
        await pilot.pause()
        assert host.host_escapes == 1
        assert panel.mode == "slots"

    _run(host, script)
