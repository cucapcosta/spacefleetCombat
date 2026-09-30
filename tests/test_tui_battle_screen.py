"""BattleScreen pushed from a generic host App, not BattleApp."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.app import App
from textual.widgets import Static

from spacefleet.campaign.battle import BattleSession, build_battle
from spacefleet.campaign.models import BattleOutcome
from spacefleet.net.turn_resolver import TurnLog
from spacefleet.tui.battle_app import BattleApp
from spacefleet.tui.screens import battle as battle_screen
from spacefleet.tui.screens.battle import (
    PLAYBACK,
    BattleScreen,
    ConfirmTurnScreen,
    HelpScreen,
    QuitScreen,
)
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    import pytest
    from textual.app import ComposeResult

    from spacefleet.net.commands import Command
    from spacefleet.net.game_state import GameState


class HostApp(App[None]):
    """Stands in for the future single app: a home screen plus the battle."""

    def __init__(self, session: BattleSession) -> None:
        super().__init__()
        self.battle = BattleScreen(session)
        self.outcomes: list[BattleOutcome | None] = []

    def compose(self) -> ComposeResult:
        yield Static("home", id="home")

    def on_mount(self) -> None:
        self.push_screen(self.battle, self.outcomes.append)


def _leave_with(key: str) -> tuple[HostApp, bool]:
    app = HostApp(build_battle(campaign_state()))
    running: list[bool] = []

    async def go() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.screen is app.battle
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, QuitScreen)
            await pilot.press(key)
            await pilot.pause()
            running.append(app.is_running)
            assert pilot.app.screen is not app.battle
            assert app.screen.query_one("#home", Static)

    asyncio.run(go())
    return app, running[0]


def test_abandon_dismisses_to_the_host_which_keeps_running() -> None:
    app, running = _leave_with("y")
    assert app.outcomes == [BattleOutcome.ABANDONED]
    assert running
    assert app.return_value is None


def test_surrender_dismisses_with_surrender() -> None:
    app, running = _leave_with("s")
    assert app.outcomes == [BattleOutcome.SURRENDER]
    assert running


def test_victory_during_playback_under_a_modal_still_dismisses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = build_battle(campaign_state())

    def win(
        state: GameState, commands: dict[str, Command], ability_orders: Any, **kw: Any
    ) -> TurnLog:
        for ship_id in session.enemy_runtime_ids:
            ship = session.state.ships[ship_id]
            ship.take_hull_damage(ship.hull_max + ship.shields_max + 100)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(battle_screen, "resolve_turn", win)
    app = HostApp(session)

    async def go() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmTurnScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert app.battle.phase == PLAYBACK
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            app.battle.action_skip()  # playback ends while help is open
            for _ in range(20):
                await pilot.pause()
                if app.outcomes:
                    break
            assert app.screen.query_one("#home", Static)

    asyncio.run(go())
    assert app.outcomes == [BattleOutcome.VICTORY]


def test_resize_under_a_modal_applies_when_the_battle_resumes() -> None:
    app = HostApp(build_battle(campaign_state()))

    async def go() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert not app.battle.query_one("#side").has_class("-narrow")
            await pilot.press("question_mark")
            await pilot.pause()
            await pilot.resize_terminal(100, 30)
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is app.battle
            assert app.battle.query_one("#side").has_class("-narrow")

    asyncio.run(go())


def test_battle_app_ctrl_q_asks_instead_of_quitting() -> None:
    app = BattleApp(build_battle(campaign_state()))

    async def go() -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert isinstance(app.screen, QuitScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert pilot.app.screen is app.battle
            await pilot.press("ctrl+q", "s")

    asyncio.run(go())
    assert app.return_value is BattleOutcome.SURRENDER
