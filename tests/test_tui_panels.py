from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from spacefleet.campaign.battle import BattleSession, build_battle
from spacefleet.core.types import DetectionLevel, Faction, Stance, Vector2D, heading_to_vector
from spacefleet.net.commands import Maneuver
from spacefleet.tui.model.orders import (
    Aim,
    OrderDraft,
    finalize,
    fire_unavailable_reason,
    predict_move,
)
from spacefleet.tui.model.snapshot import BattleSnapshot, ShipView
from spacefleet.tui.model.timeline import Bars
from spacefleet.tui.widgets.event_log import EventLog
from spacefleet.tui.widgets.order_panel import (
    OrderPanel,
    OrderSet,
    PreviewChanged,
    PreviewCleared,
    StanceSet,
)
from spacefleet.tui.widgets.status_panel import ShipSelected, StatusPanel
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from textual.message import Message
    from textual.pilot import Pilot

    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount


def _session() -> BattleSession:
    return build_battle(campaign_state())


def _player_ship(session: BattleSession, index: int = 0) -> Ship:
    return session.state.ships[session.state.player_ships[session.player_id][index]]


def _forward_mount(session: BattleSession, ship: Ship) -> WeaponMount:
    return next(
        mount
        for mount in ship.weapons
        if fire_unavailable_reason(
            session, ship, mount.slot_id, aim=Aim(0.0, None), used_slots=set()
        )
        is None
    )


class _Harness(App[None]):
    def __init__(self, *widgets: Any) -> None:
        super().__init__()
        self._widgets = widgets
        self.messages: list[Message] = []

    def compose(self) -> ComposeResult:
        yield from self._widgets

    def on_preview_changed(self, message: PreviewChanged) -> None:
        self.messages.append(message)

    def on_preview_cleared(self, message: PreviewCleared) -> None:
        self.messages.append(message)

    def on_order_set(self, message: OrderSet) -> None:
        self.messages.append(message)

    def on_stance_set(self, message: StanceSet) -> None:
        self.messages.append(message)

    def on_ship_selected(self, message: ShipSelected) -> None:
        self.messages.append(message)

    def of(self, kind: type[Message]) -> list[Any]:
        return [message for message in self.messages if isinstance(message, kind)]


def _run(app: _Harness, script: Callable[[Pilot[None]], Awaitable[None]]) -> None:
    async def main() -> None:
        async with app.run_test(size=(100, 40)) as pilot:
            await script(pilot)

    asyncio.run(main())


# ── OrderPanel ──────────────────────────────────────────────────────


def _maneuver_text(panel: OrderPanel) -> str:
    return str(panel.query_one("#op-maneuver", Static).render())


def test_arrows_edit_maneuver_at_top_menu_and_preview_curved_route() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 3.0
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        panel.focus()
        await pilot.pause()
        assert panel.mode == "menu"
        assert "Speed 3 → 3 GU/turn" in _maneuver_text(panel)
        await pilot.press("up", "up", "right")
        await pilot.pause()
        assert draft.maneuvers[ship.id] == Maneuver(speed=5.0, turn=15.0)
        assert "Speed 3 → 5 GU/turn" in _maneuver_text(panel)
        assert "Turn 15° starboard" in _maneuver_text(panel)
        routes = [m for m in app.of(PreviewChanged) if m.kind == "route"]
        data = routes[-1].data
        expected = predict_move(ship, Maneuver(speed=5.0, turn=15.0), state=session.state)
        assert data["ship_id"] == ship.id
        assert data["path"] == expected.path
        assert data["pos"] == expected.end
        assert data["heading"] == expected.end_heading
        assert not app.of(OrderSet)
        assert "order ·" in str(panel.query_one("#op-title", Static).render())

    _run(app, script)


def test_maneuver_and_fire_on_same_ship() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 3.0
    mount = _forward_mount(session, ship)
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        panel.focus()
        await pilot.press("left")
        panel.action_fire()
        panel.choose("manual")
        panel.set_manual_bearing(0.0)
        panel.choose(f"slot:{mount.slot_id}")
        panel.choose("done")
        panel.choose("done")
        await pilot.pause()
        assert "order ✓" in str(panel.query_one("#op-title", Static).render())

    _run(app, script)
    assert draft.commands[ship.id].action == "fire"
    assert draft.maneuvers[ship.id] == Maneuver(speed=None, turn=-15.0)
    result = finalize(draft, session)
    assert not isinstance(result, str)
    command = result[0][ship.id]
    assert command.action == "fire"
    assert command.maneuver == Maneuver(speed=None, turn=-15.0)


def test_arrows_navigate_options_inside_submenus() -> None:
    session = _session()
    ship = _player_ship(session)
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        panel.focus()
        await pilot.press("t")
        await pilot.pause()
        options = panel.query_one("#op-options", OptionList)
        before = options.highlighted
        await pilot.press("down", "left")
        await pilot.pause()
        assert options.highlighted != before

    _run(app, script)
    assert ship.id not in draft.maneuvers


def test_turn_limit_shown_enforced_and_shrinks_when_ship_starts_moving() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 0.0
    pivot = ship.max_turn_this_turn(0.0)
    moving = ship.max_turn_this_turn(1.0)
    assert pivot > moving
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        panel.focus()
        await pilot.pause()
        assert f"(max {pivot:g}° this turn)" in _maneuver_text(panel)
        for _ in range(int(pivot // 15) + 3):
            await pilot.press("left")
        await pilot.pause()
        assert draft.maneuvers[ship.id].turn == -pivot
        assert f"Turn {pivot:g}° port" in _maneuver_text(panel)
        await pilot.press("up")
        await pilot.pause()
        assert draft.maneuvers[ship.id] == Maneuver(speed=1.0, turn=-moving)
        assert f"(max {moving:g}° this turn)" in _maneuver_text(panel)

    _run(app, script)


def test_editing_back_to_default_drops_the_maneuver() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 2.0
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        panel.focus()
        await pilot.press("down", "right")
        await pilot.pause()
        assert draft.maneuvers[ship.id] == Maneuver(speed=1.0, turn=15.0)
        await pilot.press("up", "left")
        await pilot.pause()

    _run(app, script)
    assert ship.id not in draft.maneuvers


def test_action_menu_offers_fire_boarding_pass_but_no_move() -> None:
    session = _session()
    ship = _player_ship(session)
    panel = OrderPanel(session, OrderDraft())
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.pause()
        labels = panel.option_labels()
        assert not any("Move" in label for label in labels)
        assert any("Fire" in label for label in labels)
        assert any("Boarding" in label for label in labels)
        assert any("Pass" in label for label in labels)

    _run(app, script)


def test_rejected_salvo_shows_reason_and_sets_no_order() -> None:
    session = _session()
    ship = _player_ship(session)
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)
    mount = _forward_mount(session, ship)
    slot = mount.slot_id

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.press("f")
        panel.choose("manual")
        await pilot.pause()
        panel.set_manual_bearing(0.0)
        await pilot.pause()
        aims = [m for m in app.of(PreviewChanged) if m.kind == "aim"]
        assert aims and aims[-1].data["origin"] == ship.position
        panel.choose(f"slot:{slot}")
        panel.choose("done")
        await pilot.pause()
        # Weapon breaks down before the salvo is queued.
        mount.can_fire, mount.cooldown = False, 3
        panel.choose("done")
        await pilot.pause()
        assert "cooldown" in panel.error_text
        assert not app.of(OrderSet)

    _run(app, script)
    assert ship.id not in draft.commands


def test_weapon_list_shows_blocker_inline() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.weapons[0].can_fire, ship.weapons[0].cooldown = False, 2
    panel = OrderPanel(session, OrderDraft())
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.press("f")
        panel.choose("manual")
        panel.set_manual_bearing(0.0)
        await pilot.pause()
        labels = panel.option_labels()
        assert any("cooldown" in label for label in labels)

    _run(app, script)


def test_valid_salvo_sets_fire_order() -> None:
    session = _session()
    ship = _player_ship(session)
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)
    mount = _forward_mount(session, ship)
    slot = mount.slot_id

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.press("f")
        panel.choose("manual")
        panel.set_manual_bearing(0.0)
        panel.choose(f"slot:{slot}")
        panel.choose("done")
        panel.choose("done")
        await pilot.pause()
        assert [m.ship_id for m in app.of(OrderSet)] == [ship.id]

    _run(app, script)
    assert draft.commands[ship.id].action == "fire"
    assert draft.commands[ship.id].args["shots"][0]["slot"] == slot


def test_stance_rejection_shown_and_not_queued() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.stance_cooldown_remaining = 2
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)
    other = next(stance for stance in Stance if stance is not ship.stance)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.press("t")
        await pilot.pause()
        assert any("Locked for 2" in label for label in panel.option_labels())
        panel.choose(f"stance:{other.value}")
        await pilot.pause()
        assert "Locked for 2" in panel.error_text
        assert not app.of(StanceSet)

    _run(app, script)
    assert ship.id not in draft.stances


def test_accepted_stance_goes_into_draft() -> None:
    session = _session()
    ship = _player_ship(session)
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)
    other = next(stance for stance in Stance if stance is not ship.stance)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.press("t")
        panel.choose(f"stance:{other.value}")
        await pilot.pause()
        assert [m.ship_id for m in app.of(StanceSet)] == [ship.id]

    _run(app, script)
    assert draft.stances[ship.id] is other


def test_pass_sets_order() -> None:
    session = _session()
    ship = _player_ship(session)
    draft = OrderDraft()
    panel = OrderPanel(session, draft)
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.press("p")
        await pilot.pause()
        assert [m.ship_id for m in app.of(OrderSet)] == [ship.id]

    _run(app, script)
    assert draft.commands[ship.id].action == "pass"


def test_map_click_in_manual_mode_aims_relative_to_prow() -> None:
    session = _session()
    ship = _player_ship(session)
    panel = OrderPanel(session, OrderDraft())
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        await pilot.press("f")
        panel.choose("manual")
        await pilot.pause()
        ahead = ship.position + heading_to_vector(ship.heading) * 10.0
        panel.handle_map_click(ahead)
        await pilot.pause()
        aims = [m for m in app.of(PreviewChanged) if m.kind == "aim"]
        assert abs((aims[-1].data["bearing_abs"] - ship.heading + 180) % 360 - 180) < 0.5

    _run(app, script)


# ── StatusPanel ─────────────────────────────────────────────────────


def _view(ship_id: str, name: str, hull: int = 8) -> ShipView:
    return ShipView(
        id=ship_id,
        label="V1",
        name=name,
        faction=Faction.IMPERIAL_NAVY,
        class_letter="C",
        position=Vector2D(0.0, 0.0),
        heading=0.0,
        detection=DetectionLevel.IDENTIFIED,
        is_player=True,
        alive=True,
        hull=hull,
        hull_max=10,
        shields=2,
        shields_max=4,
        morale=6,
        morale_max=6,
    )


def _snapshot() -> BattleSnapshot:
    return BattleSnapshot(
        turn=1,
        phase="start",
        ships=(_view("a", "Vindicator"), _view("b", "Resolute", hull=3)),
        projectiles=(),
    )


def test_status_panel_renders_bars_and_order_marker() -> None:
    panel = StatusPanel()
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_snapshot(_snapshot(), {"a"})
        await pilot.pause()
        text = panel.plain_text()
        assert "Vindicator" in text and "Resolute" in text
        assert "✓" in text and "·" in text
        assert "8/10" in text and "2/4" in text and "6/6" in text
        assert "█" in text

    _run(app, script)


def test_status_panel_accepts_fractional_bars() -> None:
    panel = StatusPanel()
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_snapshot(_snapshot(), set())
        panel.set_bars({"a": Bars(4.5, 10, 1.25, 4, 3.0, 6)})
        await pilot.pause()
        text = panel.plain_text()
        assert "4.5/10" in text or "5/10" in text
        assert "✓" not in text

    _run(app, script)


def test_status_panel_click_posts_ship_selected() -> None:
    panel = StatusPanel()
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_snapshot(_snapshot(), set())
        await pilot.pause()
        panel.select_row(1)
        await pilot.pause()
        assert [m.ship_id for m in app.of(ShipSelected)] == ["b"]

    _run(app, script)


# ── EventLog ────────────────────────────────────────────────────────


def test_event_log_append_set_lines_and_clear() -> None:
    log = EventLog()
    app = _Harness(log)

    async def script(pilot: Pilot[None]) -> None:
        log.append("first")
        log.append("second")
        await pilot.pause()
        assert log.entries == ["first", "second"]
        log.set_lines(["x", "y", "z"])
        assert log.entries == ["x", "y", "z"]
        for index in range(250):
            log.append(f"line {index}")
        assert len(log.entries) == EventLog.MAX_LINES
        assert log.entries[-1] == "line 249"
        log.clear()
        assert log.entries == []

    _run(app, script)


def test_enter_on_freshly_opened_submenu_picks_first_option() -> None:
    session = _session()
    ship = _player_ship(session)
    panel = OrderPanel(session, OrderDraft())
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        panel.focus()
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        opened = panel.mode
        await pilot.press("enter")
        await pilot.pause()
        assert panel.mode != opened

    _run(app, script)


def test_cursor_stays_put_when_the_same_menu_rebuilds() -> None:
    session = _session()
    ship = _player_ship(session)
    panel = OrderPanel(session, OrderDraft())
    app = _Harness(panel)

    async def script(pilot: Pilot[None]) -> None:
        panel.set_ship(ship.id)
        panel.focus()
        await pilot.pause()
        panel.set_manual_bearing(0.0)
        await pilot.pause()
        options = panel.query_one("#op-options", OptionList)
        slot = options.highlighted
        assert slot is not None
        await pilot.press("enter")  # toggles the weapon; menu rebuilds
        await pilot.pause()
        assert panel.mode == "fire_weapons"
        assert options.highlighted == slot

    _run(app, script)
