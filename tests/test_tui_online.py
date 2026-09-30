"""ConnectScreen and OnlineScreen driven by Pilot with a fake session."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from textual.app import App
from textual.widgets import Input, Static

from spacefleet.net.ws_session import SessionEvent
from spacefleet.tui.screens.online import CommandInput, ConnectScreen, OnlineScreen

if TYPE_CHECKING:
    from collections.abc import Callable


class FakeSession:
    instances: list[FakeSession] = []

    def __init__(self, url: str, username: str, on_event: Callable[[SessionEvent], None]) -> None:
        self.url = url
        self.username = username
        self.on_event = on_event
        self.sent: list[str] = []
        self.closed = False
        self.started = asyncio.Event()
        FakeSession.instances.append(self)

    async def run(self) -> None:
        self.on_event(SessionEvent("connected", "  Connected."))
        self.on_event(SessionEvent("text", "  Your ships: Vengeful", ship_names=("Vengeful",)))
        self.on_event(SessionEvent("text", "\x1b[31mRED\x1b[0m alert"))
        self.on_event(SessionEvent("prompt", "Orders?", "s1", "Vengeful"))
        self.started.set()
        await asyncio.Event().wait()

    async def send_line(self, line: str) -> str | None:
        self.sent.append(line)
        return "  Unknown command. Type 'help' for options." if line == "bogus" else None

    async def close(self) -> None:
        self.closed = True


class Host(App[None]):
    def __init__(self, screen_factory: Callable[[], object]) -> None:
        super().__init__()
        self.screen_factory = screen_factory
        self.results: list[object] = []

    def on_mount(self) -> None:
        self.push_screen(self.screen_factory(), self.results.append)  # type: ignore[arg-type]


def _online() -> OnlineScreen:
    return OnlineScreen("ws://test/ws", "alice", session_factory=FakeSession)


def test_online_screen_shows_text_and_state() -> None:
    async def go() -> None:
        app = Host(_online)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, OnlineScreen)
            assert "RED alert" in screen.server_lines
            assert "Orders?" in screen.server_lines
            assert screen.state == "your turn: Vengeful"
            header = str(screen.query_one("#header", Static).render())
            assert "Online · ws://test/ws · alice · your turn: Vengeful" in header
            assert "Vengeful" in str(screen.query_one("#ships", Static).render())

            screen.handle_event(SessionEvent("game_over", "Victory!"))
            await pilot.pause()
            assert screen.state == "game over"
            assert screen.server_lines[-2:] == ["Victory!", "Press Esc to return."]
            screen.handle_event(SessionEvent("disconnected", "  Disconnected from server."))
            assert screen.state == "game over"

    asyncio.run(go())


def test_online_screen_sends_commands_with_history() -> None:
    async def go() -> None:
        FakeSession.instances.clear()
        app = Host(_online)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, OnlineScreen)
            fake = FakeSession.instances[-1]
            await pilot.press(*"fire 1 90", "enter")
            await pilot.pause()
            assert fake.sent == ["fire 1 90"]
            assert screen.state == "waiting"
            await pilot.press(*"bogus", "enter")
            await pilot.pause()
            assert fake.sent == ["fire 1 90", "bogus"]
            assert "  Unknown command. Type 'help' for options." in screen.server_lines

            command = screen.query_one("#command", CommandInput)
            assert command.value == ""
            await pilot.press("up")
            assert command.value == "bogus"
            await pilot.press("up")
            assert command.value == "fire 1 90"
            await pilot.press("up")
            assert command.value == "fire 1 90"
            await pilot.press("down")
            assert command.value == "bogus"
            await pilot.press("down")
            assert command.value == ""

    asyncio.run(go())


def test_online_screen_escape_confirms_and_disconnects() -> None:
    async def go() -> None:
        FakeSession.instances.clear()
        app = Host(_online)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            fake = FakeSession.instances[-1]
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, OnlineScreen)
            assert not fake.closed
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            await pilot.pause()
            assert fake.closed
            assert not isinstance(app.screen, OnlineScreen)
            assert app.results == [None]

    asyncio.run(go())


def test_connect_screen_requires_username_then_opens_online() -> None:
    async def go() -> None:
        FakeSession.instances.clear()
        app = Host(lambda: ConnectScreen("ws://host/ws", session_factory=FakeSession))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ConnectScreen)
            assert screen.query_one("#url", Input).value == "ws://host/ws"
            await pilot.press("enter")
            await pilot.pause()
            assert "Username is required." in str(screen.query_one("#error", Static).render())
            assert app.screen is screen

            await pilot.press(*"bob", "enter")
            await pilot.pause()
            online = app.screen
            assert isinstance(online, OnlineScreen)
            assert (online.url, online.username) == ("ws://host/ws", "bob")
            assert FakeSession.instances[-1].username == "bob"

    asyncio.run(go())


def test_connect_screen_escape_goes_back() -> None:
    async def go() -> None:
        app = Host(ConnectScreen)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.results == [None]

    asyncio.run(go())
