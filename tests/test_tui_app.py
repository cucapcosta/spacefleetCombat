from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
from textual.screen import Screen
from textual.widgets import OptionList, Static

from spacefleet import __main__ as entry
from spacefleet.campaign.battle import build_battle
from spacefleet.models.fleet_spec import fleet_points
from spacefleet.tui import app as app_module
from spacefleet.tui.app import SpacefleetApp
from spacefleet.tui.screens.battle import BattleScreen, QuitScreen
from spacefleet.tui.screens.title import TitleScreen, banner, mirror
from tests.campaign_helpers import campaign_state, supported_fleet

if TYPE_CHECKING:
    from spacefleet.models.fleet_spec import FleetSpec

SIZE = (120, 40)


class FakeScreen(Screen[Any]):
    def __init__(self, label: str, result: object = None) -> None:
        super().__init__()
        self.label = label
        self.result = result

    def compose(self) -> Any:
        yield Static(self.label)

    def key_escape(self) -> None:
        self.dismiss(self.result)


class Recorder:
    def __init__(self, label: str, result: object = None) -> None:
        self.label = label
        self.result = result
        self.made: list[FakeScreen] = []

    def __call__(self) -> Screen[Any]:
        screen = FakeScreen(self.label, self.result)
        self.made.append(screen)
        return screen


def make_app(fleet: FleetSpec | None = None) -> tuple[SpacefleetApp, dict[str, Recorder]]:
    fakes = {
        "campaign": Recorder("campaign"),
        "fleet": Recorder("fleet", fleet),
        "connect": Recorder("connect"),
    }
    app = SpacefleetApp(
        campaign_factory=fakes["campaign"],
        fleet_builder_factory=fakes["fleet"],
        connect_factory=fakes["connect"],
    )
    return app, fakes


def screen_text(screen: Screen[Any]) -> str:
    return "\n".join(str(widget.render()) for widget in screen.query(Static))


def test_title_shows_banner_version_and_menu() -> None:
    async def scenario() -> None:
        app, _ = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, TitleScreen)
            text = screen_text(app.screen)
            assert banner("SPACEFLEET")[0].strip() in text
            assert "Campaign Edition v0.2" in text
            menu = app.screen.query_one("#menu", OptionList)
            prompts = [str(menu.get_option_at_index(i).prompt) for i in range(menu.option_count)]
            assert prompts == [
                "[C] Campaign",
                "[O] Connect to Server",
                "[F] Fleet Builder",
                "[Q] Quit",
            ]

    asyncio.run(scenario())


@pytest.mark.parametrize(("key", "fake"), [("c", "campaign"), ("o", "connect"), ("f", "fleet")])
def test_letter_keys_push_screens_and_escape_returns(key: str, fake: str) -> None:
    async def scenario() -> None:
        app, fakes = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert fakes[fake].made
            assert app.screen is fakes[fake].made[0]
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, TitleScreen)

    asyncio.run(scenario())


def test_enter_on_campaign_pushes_campaign() -> None:
    async def scenario() -> None:
        app, fakes = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is fakes["campaign"].made[0]

    asyncio.run(scenario())


def test_arrow_navigation_and_enter() -> None:
    async def scenario() -> None:
        app, fakes = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("down", "down", "up", "down")
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is fakes["fleet"].made[0]
            assert not fakes["campaign"].made and not fakes["connect"].made

    asyncio.run(scenario())


def test_enter_on_quit_exits() -> None:
    async def scenario() -> None:
        app, _ = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("up")  # wraps from Campaign to Quit
            await pilot.press("enter")
            await pilot.pause()
            assert not app.is_running

    asyncio.run(scenario())


def test_fleet_builder_result_is_notified() -> None:
    fleet = supported_fleet()

    async def scenario() -> None:
        app, _ = make_app(fleet)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, TitleScreen)
            messages = [n.message for n in app._notifications]
            expected = f"Fleet 'Test Fleet' — {fleet_points(fleet)} pts."
            assert expected in messages

    asyncio.run(scenario())


def test_fleet_builder_cancel_has_no_notification() -> None:
    async def scenario() -> None:
        app, _ = make_app(None)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not list(app._notifications)

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["q", "ctrl+q"])
def test_quit_keys_exit_app(key: str) -> None:
    async def scenario() -> None:
        app, _ = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert not app.is_running

    asyncio.run(scenario())


def test_switch_screen_from_pushed_screen_returns_to_title() -> None:
    """ConnectScreen switches itself for OnlineScreen, which pops back to the title."""

    class Online(FakeScreen):
        def key_escape(self) -> None:
            self.app.pop_screen()

    class Connect(FakeScreen):
        def key_enter(self) -> None:
            self.app.switch_screen(Online("online"))

    async def scenario() -> None:
        app = SpacefleetApp(connect_factory=lambda: Connect("connect"))
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, Online)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, TitleScreen)
            assert app.is_running

    asyncio.run(scenario())


def test_real_connect_screen_back_returns_to_title() -> None:
    async def scenario() -> None:
        app = SpacefleetApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            assert type(app.screen).__name__ == "ConnectScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, TitleScreen)

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["ctrl+q", "ctrl+c"])
def test_ctrl_q_in_battle_asks_instead_of_exiting(key: str) -> None:
    async def scenario() -> None:
        app, _ = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app.push_screen(BattleScreen(build_battle(campaign_state())))
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert isinstance(app.screen, QuitScreen)
            assert app.is_running

    asyncio.run(scenario())


def test_mirror_swaps_direction_and_keeps_styles() -> None:
    from rich.console import Console
    from rich.style import Style
    from rich.text import Text

    line = Text()
    line.append("◀", style="red")
    line.append("█▄", style="blue")
    line.append("▶", style="green")
    flipped = mirror(line)
    assert flipped.plain == "◀▄█▶"
    console = Console()
    assert flipped.get_style_at_offset(console, 0) == Style.parse("green")
    assert flipped.get_style_at_offset(console, 1) == Style.parse("blue")
    assert flipped.get_style_at_offset(console, 3) == Style.parse("red")


def test_main_default_branch_runs_tui_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(app_module, "main", lambda: calls.append("tui"))
    entry.main([])
    assert calls == ["tui"]


def test_app_main_prints_farewell(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(SpacefleetApp, "run", lambda self: None)
    app_module.main()
    assert "Ave Imperator. The Emperor protects." in capsys.readouterr().out


def test_module_help_still_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "spacefleet", "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0
    assert "--server" in result.stdout and "--client" in result.stdout
