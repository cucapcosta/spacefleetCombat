"""BattleApp / BattleScreen state machine driven headless through Textual's Pilot."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import pytest
from textual.widgets import Static
from textual.widgets._footer import FooterKey

from spacefleet.campaign.battle import BattleSession, build_battle
from spacefleet.campaign.models import BattleOutcome
from spacefleet.core.types import Stance
from spacefleet.net.ai_controller import AIController
from spacefleet.net.commands import AbilityOrder, Command, Maneuver
from spacefleet.net.turn_resolver import TurnLog
from spacefleet.tui import battle_app
from spacefleet.tui.battle_app import (
    PLANNING,
    PLAYBACK,
    BattleApp,
    BattleScreen,
    ConfirmTurnScreen,
    HelpScreen,
    QuitScreen,
    TuiBattleRunner,
    format_pending,
)
from spacefleet.tui.model.orders import OrderDraft, alive_player_ids, predict_move
from spacefleet.tui.screens import battle as battle_screen
from spacefleet.tui.widgets.log_screen import LogScreen
from spacefleet.tui.widgets.turn_report_screen import TurnReportScreen
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    from textual.pilot import Pilot

    from spacefleet.net.game_state import GameState


class RecordingAI(AIController):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def generate_commands(
        self, state: GameState, controlled_ids: list[str] | None = None
    ) -> dict[str, Command]:
        ids = list(controlled_ids or [])
        self.calls.append((ids, state.turn))
        return {ship_id: Command(ship_id=ship_id, action="pass") for ship_id in ids}


Scenario = Callable[[BattleScreen, "Pilot[BattleOutcome]"], Awaitable[None]]


def _run(
    session: BattleSession,
    scenario: Scenario,
    *,
    size: tuple[int, int] = (140, 45),
    **kwargs: Any,
) -> tuple[BattleApp, BattleOutcome | None]:
    app = BattleApp(session, **kwargs)

    async def go() -> None:
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app.battle, pilot)
            await pilot.pause()

    asyncio.run(go())
    return app, app.return_value


async def _confirm_turn(pilot: Pilot[BattleOutcome]) -> None:
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(pilot.app.screen, ConfirmTurnScreen)
    await pilot.press("enter")
    await pilot.pause()


async def _close_report(pilot: Pilot[BattleOutcome], key: str = "enter") -> None:
    assert isinstance(pilot.app.screen, TurnReportScreen)
    await pilot.press(key)
    await pilot.pause()
    assert not isinstance(pilot.app.screen, TurnReportScreen)


def test_orders_confirm_skip_advances_turn_and_returns_to_planning() -> None:
    session = build_battle(campaign_state())
    ai = RecordingAI()

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        assert app.phase == PLANNING
        first = alive_player_ids(session)[0]
        assert app.selected == first
        await pilot.press("p")  # pass for the selected ship
        await pilot.pause()
        assert app.draft.commands[first].action == "pass"
        await _confirm_turn(pilot)
        assert app.phase == PLAYBACK
        assert session.state.turn == 1
        await pilot.press("space")
        await pilot.pause()
        await _close_report(pilot)
        assert app.phase == PLANNING
        assert app.draft.commands == {}
        assert any("Turn 1" in line for line in app.event_log.entries)
        await pilot.press("q")
        await pilot.press("y")

    _app, outcome = _run(session, scenario, ai=ai)
    assert outcome is BattleOutcome.ABANDONED
    assert ai.calls == [(session.enemy_runtime_ids, 1)]


def test_revise_keeps_planning_without_resolving(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(battle_screen, "resolve_turn", lambda *_a, **_k: pytest.fail("resolved"))
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await pilot.press("enter", "escape")
        await pilot.pause()
        assert app.phase == PLANNING
        assert session.state.turn == 0
        await pilot.press("q", "y")

    _run(session, scenario)


def test_playback_end_frame_matches_end_snapshot() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await _confirm_turn(pilot)
        timeline = app.timeline
        assert timeline is not None
        await pilot.press("space")
        await pilot.pause()
        await _close_report(pilot, "escape")
        end = timeline.snapshots["end"]
        assert app.playhead == timeline.duration
        assert timeline.sample(app.playhead).ships == end.ships
        planning = app.tactical_map.ship(end.ships[0].id)
        assert planning is not None
        assert planning.position == end.ships[0].position
        # Replay restarts from t=0 and returns to the same planning turn.
        await pilot.press("r")
        await pilot.pause()
        assert app.phase == PLAYBACK
        assert app.playhead < timeline.duration
        await pilot.press("space")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, TurnReportScreen)  # no report after a replay
        assert app.phase == PLANNING
        assert session.state.turn == 1
        await pilot.press("q", "y")

    _run(session, scenario, ai=RecordingAI())


def test_playback_runs_to_the_end_by_itself_and_speed_keys_change_speed() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await _confirm_turn(pilot)
        assert app.phase == PLAYBACK
        await pilot.press("plus")
        assert app.speed == 2.0
        await pilot.press("plus")
        assert app.speed == 2.0
        await pilot.press("minus", "minus", "minus")
        assert app.speed == 0.5
        await pilot.press("plus", "plus")
        assert app.timeline is not None
        for _ in range(100):
            if isinstance(pilot.app.screen, TurnReportScreen):
                break
            await pilot.pause(0.05)
        await _close_report(pilot, "space")
        assert app.phase == PLANNING
        await pilot.press("q", "y")

    _run(session, scenario, ai=RecordingAI())


def _kill(session: BattleSession, ship_ids: list[str]) -> None:
    for ship_id in ship_ids:
        ship = session.state.ships[ship_id]
        ship.take_hull_damage(ship.hull_max + ship.shields_max + 100)
        assert not ship.alive


def test_victory_after_resolution_returns_victory(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())

    def win(
        state: GameState, commands: dict[str, Command], ability_orders: Any, **kw: Any
    ) -> TurnLog:
        _kill(session, session.enemy_runtime_ids)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(battle_screen, "resolve_turn", win)

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await _confirm_turn(pilot)
        await pilot.press("space")

    _app, outcome = _run(session, scenario, ai=RecordingAI())
    assert outcome is BattleOutcome.VICTORY


def test_already_won_battle_exits_immediately() -> None:
    session = build_battle(campaign_state())
    _kill(session, session.enemy_runtime_ids)

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        return

    _app, outcome = _run(session, scenario)
    assert outcome is BattleOutcome.VICTORY


def test_simultaneous_elimination_is_a_defeat(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())

    def eliminate_both(
        state: GameState, commands: dict[str, Command], ability_orders: Any, **kw: Any
    ) -> TurnLog:
        _kill(session, state.player_ships["player"] + session.enemy_runtime_ids)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(battle_screen, "resolve_turn", eliminate_both)

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await _confirm_turn(pilot)
        await pilot.press("space")

    _app, outcome = _run(session, scenario, ai=RecordingAI())
    assert outcome is BattleOutcome.DEFEAT


def test_turn_limit_ends_battle_and_ai_gets_only_enemy_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = build_battle(campaign_state())
    ai = RecordingAI()
    seen: list[tuple[dict[str, Command], dict[str, AbilityOrder]]] = []

    def resolve_once(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
        **kw: Any,
    ) -> TurnLog:
        seen.append((commands, ability_orders))
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(battle_screen, "resolve_turn", resolve_once)
    player_ids = alive_player_ids(session)

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        app.draft.stances[player_ids[0]] = Stance.LOCK_ON
        await _confirm_turn(pilot)
        await pilot.press("space")

    _app, outcome = _run(session, scenario, ai=ai, turn_limit=1)
    assert outcome is BattleOutcome.TURN_LIMIT
    assert ai.calls == [(session.enemy_runtime_ids, 1)]
    commands, abilities = seen[0]
    assert all(commands[ship_id].action == "pass" for ship_id in player_ids)
    assert abilities == {}
    assert session.state.ships[player_ids[0]].stance is Stance.LOCK_ON


def test_invalid_stance_at_resolution_returns_to_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(battle_screen, "resolve_turn", lambda *_a, **_k: pytest.fail("resolved"))
    session = build_battle(campaign_state())
    ship_id = alive_player_ids(session)[0]

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        app.draft.stances[ship_id] = Stance.LOCK_ON
        session.state.ships[ship_id].morale = 0  # mutiny: stance no longer allowed
        await _confirm_turn(pilot)
        assert app.phase == PLANNING
        assert session.state.turn == 0
        await pilot.press("q", "y")

    _run(session, scenario)


@pytest.mark.parametrize(
    ("key", "outcome"),
    [("y", BattleOutcome.ABANDONED), ("s", BattleOutcome.SURRENDER)],
)
def test_quit_asks_then_abandons_or_surrenders(
    monkeypatch: pytest.MonkeyPatch, key: str, outcome: BattleOutcome
) -> None:
    monkeypatch.setattr(battle_screen, "resolve_turn", lambda *_a, **_k: pytest.fail("resolved"))
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(pilot.app.screen, QuitScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, QuitScreen)
        assert pilot.app.return_value is None
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert isinstance(pilot.app.screen, QuitScreen)
        await pilot.press(key)

    _app, result = _run(session, scenario)
    assert result is outcome
    assert session.state.turn == 0


def test_tab_cycles_own_alive_ships() -> None:
    session = build_battle(campaign_state())
    ids = alive_player_ids(session)

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        assert app.selected == ids[0]
        await pilot.press("tab")
        assert app.selected == ids[1]
        assert app.order_panel.ship_id == ids[1]
        assert app.tactical_map.selected == ids[1]
        await pilot.press("shift+tab")
        assert app.selected == ids[0]
        await pilot.press("q", "y")

    _run(session, scenario)


def test_map_keys_work_regardless_of_focus() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        tmap = app.tactical_map
        app.order_panel.focus()
        await pilot.pause()
        for key, overlay in (("A", "arcs"), ("S", "sensor"), ("D", "drift")):
            await pilot.press(key)
            assert overlay in tmap.overlays
        assert app.selected is not None
        arcs, sensor, drift = tmap._overlay_data[app.selected]
        assert arcs and sensor is not None and drift is not None
        tmap.camera.center = tmap.camera.center.__class__(9999.0, 9999.0)
        await pilot.press("C")
        view = tmap.ship(app.selected)
        assert view is not None
        assert tmap.camera.center == view.position
        await pilot.press("F")
        assert tmap.camera.center != view.position or len(session.state.ships) == 1
        await pilot.press("q", "y")

    _run(session, scenario)


def test_small_terminal_shows_warning_until_resized() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        assert app.too_small
        assert app.query_one("#too-small").display
        assert not app.query_one("#body").display
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert not app.query_one("#too-small").display
        assert app.query_one("#body").display
        await pilot.press("q", "y")

    _run(session, scenario, size=(70, 20))


def test_narrow_terminal_side_panel_is_a_toggleable_overlay() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        side = app.query_one("#side")
        assert side.has_class("-narrow")
        assert not side.display
        map_width = app.tactical_map.size.width
        await pilot.press("o")
        await pilot.pause()
        assert side.display
        assert app.tactical_map.size.width == map_width  # overlays, map keeps width
        await pilot.press("o")
        await pilot.pause()
        assert not side.display
        await pilot.resize_terminal(140, 40)
        await pilot.pause()
        assert not side.has_class("-narrow")
        assert side.display
        await pilot.press("q", "y")

    _run(session, scenario, size=(100, 30))


def test_format_pending_is_human_readable_and_complete() -> None:
    session = build_battle(campaign_state())
    state = session.state
    ids = alive_player_ids(session)
    ship = state.ships[ids[0]]
    target = state.ships[session.enemy_runtime_ids[0]]
    draft = OrderDraft(
        commands={ship.id: Command(ship.id, "fire", {"slot": 3, "bearing": 17.0})},
        stances={ship.id: Stance.LOCK_ON},
        ability=AbilityOrder("player", "concentrated_fire", target_ship_id=target.id),
    )

    text = format_pending(session, draft)

    assert ship.name in text
    assert ship.weapons[2].display_name in text
    assert "17°" in text
    assert "Lock On" in text
    assert "Concentrated Fire" in text
    assert target.id not in text
    assert f"{state.ships[ids[1]].name}: hold course; pass (no order)" in text


def test_format_pending_lists_every_salvo_weapon() -> None:
    session = build_battle(campaign_state())
    ship = session.state.ships[alive_player_ids(session)[0]]
    shots = [{"slot": 1, "bearing": 270.0}, {"slot": 2, "bearing": 90.0}]
    draft = OrderDraft(commands={ship.id: Command(ship.id, "fire", {"shots": shots})})

    text = format_pending(session, draft)

    assert ship.weapons[0].display_name in text
    assert "bearing 270° rel" in text
    assert ship.weapons[1].display_name in text
    assert "bearing 90° rel" in text


def test_runner_suspends_terminal_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class FakeUI:
        from contextlib import contextmanager

        @contextmanager
        def suspended(self):  # type: ignore[no-untyped-def]
            events.append("leave")
            yield
            events.append("enter")

    def fake_run(session: BattleSession, **kwargs: Any) -> BattleOutcome:
        events.append("run")
        return BattleOutcome.VICTORY

    monkeypatch.setattr(battle_app, "run_battle", fake_run)
    session = build_battle(campaign_state())
    runner = TuiBattleRunner(session, ui=FakeUI())  # type: ignore[arg-type]
    assert runner.run() is BattleOutcome.VICTORY
    assert events == ["leave", "run", "enter"]


def test_turn_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="turn limit"):
        BattleApp(build_battle(campaign_state()), turn_limit=0)


def test_maneuver_preview_reaches_map_and_action_marks_status() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        tmap = app.tactical_map
        tmap.focus()
        await pilot.press("up")  # the map owns the arrows while focused
        await pilot.pause()
        assert tmap._preview is None
        assert app.draft.maneuvers == {}
        app.order_panel.focus()
        await pilot.press("up", "right")
        await pilot.pause()
        selected = app.selected
        assert selected is not None
        ship = session.state.ships[selected]
        maneuver = app.draft.maneuvers[selected]
        assert maneuver == Maneuver(speed=ship.speed + 1.0, turn=15.0)
        assert tmap._preview is not None and tmap._preview[0] == "route"
        assert len(tmap._preview[1]["path"]) == 3
        expected = predict_move(ship, maneuver, state=session.state)
        _arcs, _sensor, drift = tmap._overlay_data[selected]
        assert drift == (expected.end_heading, expected.end, expected.mid)
        assert "✓" not in app.status_panel.plain_text()
        await pilot.press("p")
        await pilot.pause()
        assert app.draft.commands[selected].action == "pass"
        assert "✓" in app.status_panel.plain_text()
        await pilot.press("q", "y")

    _run(session, scenario)


def test_confirmed_turn_resolves_maneuver_with_the_action() -> None:
    session = build_battle(campaign_state())
    first = alive_player_ids(session)[0]
    ship = session.state.ships[first]
    start_heading = ship.heading
    expected = predict_move(ship, Maneuver(turn=15.0), state=session.state)

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await pilot.press("right", "p")
        await pilot.pause()
        await _confirm_turn(pilot)
        await pilot.press("q", "y")

    _run(session, scenario, ai=RecordingAI())
    assert ship.heading != start_heading
    assert ship.heading == pytest.approx(expected.end_heading)


def test_format_pending_joins_maneuver_and_action() -> None:
    session = build_battle(campaign_state())
    first, second = alive_player_ids(session)[:2]
    ship = session.state.ships[first]
    target = session.state.ships[session.enemy_runtime_ids[0]]
    shots = [
        {"slot": 1, "bearing": 10.0, "target": target.id},
        {"slot": 2, "bearing": 12.0, "target": target.id},
    ]
    draft = OrderDraft(
        commands={first: Command(first, "fire", {"shots": shots})},
        maneuvers={first: Maneuver(speed=8.0, turn=30.0), second: Maneuver(turn=-15.0)},
    )

    text = format_pending(session, draft, labels={target.id: "E1"})

    assert f"{ship.name}: speed 8, turn 30° starboard; fire 2 weapons at E1" in text
    second_name = session.state.ships[second].name
    assert f"{second_name}: turn 15° port; pass (no order)" in text


def test_format_pending_says_hold_course_without_maneuver() -> None:
    session = build_battle(campaign_state())
    first = alive_player_ids(session)[0]
    draft = OrderDraft(commands={first: Command(first, "pass")})
    text = format_pending(session, draft)
    assert f"{session.state.ships[first].name}: hold course; pass" in text


def test_clicking_own_ship_on_map_selects_it() -> None:
    session = build_battle(campaign_state())
    ids = alive_player_ids(session)

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        tmap = app.tactical_map
        view = tmap.ship(ids[1])
        assert view is not None
        col, row = tmap.camera.world_to_cell(view.position)
        await pilot.click("#map", offset=(col, row))
        await pilot.pause()
        assert app.selected == ids[1]
        await pilot.press("q", "y")

    _run(session, scenario)


def test_tab_keeps_the_fitted_camera_when_the_ship_is_visible() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        cam = app.tactical_map.camera
        before = (cam.center, cam.gu_per_dot)
        await pilot.press("tab")
        assert (cam.center, cam.gu_per_dot) == before
        await pilot.press("q", "y")

    _run(session, scenario)


@pytest.mark.parametrize("close_key", ["escape", "question_mark", "q"])
def test_help_screen_opens_and_closes_without_side_effects(close_key: str) -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(pilot.app.screen, HelpScreen)
        assert "Replay the last resolved turn" in str(
            pilot.app.screen.query_one("#keys", Static).content
        )
        await pilot.press(close_key)
        await pilot.pause()
        assert not isinstance(pilot.app.screen, HelpScreen | QuitScreen)
        assert app.phase == PLANNING
        assert pilot.app.return_value is None
        await pilot.press("q", "y")

    _run(session, scenario)


def test_help_key_is_visible_in_the_footer_at_120_columns() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        keys = {k.action: k for k in app.query(FooterKey)}
        assert "help" in keys
        assert keys["help"].region.right <= 120
        assert not {"fit", "center", "overlay('arcs')"} & set(keys)
        await pilot.press("q", "y")

    _run(session, scenario, size=(120, 40))


def test_report_opens_after_skip_and_enter_returns_to_planning() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await _confirm_turn(pilot)
        await pilot.press("space")
        await pilot.pause()
        assert isinstance(pilot.app.screen, TurnReportScreen)
        assert app.phase != PLANNING
        assert app.last_report is not None and app.last_report.turn == 1
        report = str(pilot.app.screen.query_one("#report", Static).content)
        assert "Turn 1 report" in report
        assert session.state.ships[alive_player_ids(session)[0]].name in report
        await pilot.press("enter")
        await pilot.pause()
        assert app.phase == PLANNING
        assert session.state.turn == 1
        await pilot.press("q", "y")

    _run(session, scenario, ai=RecordingAI())


def test_victory_exits_without_a_report(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())
    screens: list[str] = []

    def win(
        state: GameState, commands: dict[str, Command], ability_orders: Any, **kw: Any
    ) -> TurnLog:
        _kill(session, session.enemy_runtime_ids)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(battle_screen, "resolve_turn", win)
    monkeypatch.setattr(
        battle_screen,
        "TurnReportScreen",
        lambda *_a: screens.append("report") or pytest.fail("report"),
    )

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await _confirm_turn(pilot)
        await pilot.press("space")

    _app, outcome = _run(session, scenario, ai=RecordingAI())
    assert outcome is BattleOutcome.VICTORY
    assert screens == []


def test_log_screen_opens_with_history_and_closes_with_l_or_escape() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        await pilot.press("L")
        await pilot.pause()
        assert isinstance(pilot.app.screen, LogScreen)
        await pilot.press("L")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, LogScreen)
        await _confirm_turn(pilot)
        await pilot.press("L")  # not during playback
        await pilot.pause()
        assert not isinstance(pilot.app.screen, LogScreen)
        await pilot.press("space")
        await pilot.pause()
        await _close_report(pilot)
        assert [turn for turn, _lines in app.history] == [1]
        await pilot.press("L")
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, LogScreen)
        lines = screen.visible_lines
        assert lines[0] == "Turn 1 report"
        assert "── Turn 1 ──" in lines
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, LogScreen)
        assert app.phase == PLANNING
        # Replay still works once the report and the log are closed.
        await pilot.press("r")
        await pilot.pause()
        assert app.phase == PLAYBACK
        await pilot.press("space")
        await pilot.pause()
        assert app.phase == PLANNING
        await pilot.press("q", "y")

    _run(session, scenario, ai=RecordingAI())


def test_log_key_is_in_the_footer_and_help() -> None:
    session = build_battle(campaign_state())

    async def scenario(app: BattleScreen, pilot: Pilot[BattleOutcome]) -> None:
        keys = {k.action: k for k in app.query(FooterKey)}
        assert "log" in keys
        await pilot.press("question_mark")
        await pilot.pause()
        assert "Battle log" in str(pilot.app.screen.query_one("#keys", Static).content)
        await pilot.press("escape")
        await pilot.press("q", "y")

    _run(session, scenario)
