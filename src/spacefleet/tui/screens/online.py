"""Online play: the connect form and the websocket game screen.

``ConnectScreen`` asks for the server URL and username, then switches to
``OnlineScreen``, which runs a :class:`~spacefleet.net.ws_session.WSSession`
in a Textual worker, shows the server text (ANSI → Rich) and sends the
player's orders from a command line with history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Button, Input, RichLog, Static

from spacefleet.net.ws_client import DEFAULT_URL
from spacefleet.net.ws_session import SessionEvent, WSSession
from spacefleet.tui.screens.shell import ShellScreen
from spacefleet.tui.widgets.confirm import ConfirmScreen

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult


class SessionLike(Protocol):
    """What :class:`OnlineScreen` needs from a session (tests inject fakes)."""

    async def run(self) -> None: ...

    async def send_line(self, line: str) -> str | None: ...

    async def close(self) -> None: ...


type SessionFactory = Callable[[str, str, Callable[[SessionEvent], None]], SessionLike]
"""``(url, username, on_event) -> session``; defaults to :class:`WSSession`."""


class ConnectScreen(Screen[None]):
    """Form with server URL and username; Enter/Connect opens the game."""

    DEFAULT_CSS = """
    ConnectScreen { align: center middle; }
    ConnectScreen > Vertical {
        width: 72; height: auto;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    ConnectScreen #title { text-style: bold; margin-bottom: 1; }
    ConnectScreen .label { margin-top: 1; }
    ConnectScreen #error { height: auto; color: $error; }
    ConnectScreen Horizontal { height: auto; margin-top: 1; }
    ConnectScreen Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Back"),
    ]

    def __init__(
        self,
        url: str = DEFAULT_URL,
        username: str = "",
        session_factory: SessionFactory | None = None,
    ) -> None:
        super().__init__()
        self.default_url = url or DEFAULT_URL
        self.default_username = username
        self.session_factory = session_factory

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Connect to Server", id="title", markup=False)
            yield Static("Server URL", classes="label", markup=False)
            yield Input(value=self.default_url, id="url")
            yield Static("Username", classes="label", markup=False)
            yield Input(value=self.default_username, id="username", placeholder="required")
            yield Static("", id="error", markup=False)
            with Horizontal():
                yield Button("Connect [Enter]", id="connect", variant="primary")
                yield Button("Back [Esc]", id="back")

    def on_mount(self) -> None:
        self.query_one("#username", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_connect()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "connect":
            self.action_connect()
        else:
            self.action_cancel()

    def action_connect(self) -> None:
        url = self.query_one("#url", Input).value.strip() or DEFAULT_URL
        username = self.query_one("#username", Input).value.strip()
        if not username:
            self.query_one("#error", Static).update("Username is required.")
            self.query_one("#username", Input).focus()
            return
        self.app.switch_screen(OnlineScreen(url, username, self.session_factory))

    def action_cancel(self) -> None:
        self.dismiss(None)


class CommandInput(Input):
    """Single-line input with ↑/↓ history of submitted commands."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "history(-1)", "Previous", show=False),
        Binding("down", "history(1)", "Next", show=False),
    ]

    def __init__(self, placeholder: str = "", id: str | None = None) -> None:  # noqa: A002
        super().__init__(placeholder=placeholder, id=id)
        self.history: list[str] = []
        self._cursor = 0

    def remember(self, line: str) -> None:
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self._cursor = len(self.history)

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        self._cursor = max(0, min(len(self.history), self._cursor + step))
        self.value = self.history[self._cursor] if self._cursor < len(self.history) else ""
        self.cursor_position = len(self.value)


_HELP = """\
Commands
  move <speed|-> [port|starboard <deg>]
  fire <weapon#> <bearing>
  strike <target_id> <subsystem>
  pass
Free actions
  status · scan · weapons
  stance <name> · help (?)
  quit"""


class OnlineScreen(ShellScreen[None]):
    """A websocket game: server text on the left, orders on the command line."""

    DEFAULT_CSS = """
    OnlineScreen #server { height: 1fr; }
    OnlineScreen #command { height: 3; }
    OnlineScreen #help { margin-bottom: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "leave", "Disconnect"),
    ]

    def __init__(
        self,
        url: str,
        username: str,
        session_factory: SessionFactory | None = None,
    ) -> None:
        super().__init__()
        self.url = url
        self.username = username
        factory = session_factory or WSSession
        self.session: SessionLike = factory(url, username, self.handle_event)
        self.state = "connecting"
        self.ship_names: tuple[str, ...] = ()
        self.server_lines: list[str] = []
        """Plain text of everything written to the server log (for tests)."""

    def compose_main(self) -> ComposeResult:
        yield RichLog(id="server", wrap=True, markup=False, highlight=False, min_width=1)
        yield CommandInput(id="command", placeholder="Waiting for the server...")

    def compose_side(self) -> ComposeResult:
        yield Static(_HELP, id="help", markup=False)
        yield Static("", id="ships", markup=False)

    def on_mount(self) -> None:
        self._refresh_header()
        self.query_one("#command", CommandInput).focus()
        self.write_log(f"Connecting to {self.url} as {self.username}...")
        self.run_worker(self.session.run(), exclusive=True, group="ws-session")

    # ── view ──────────────────────────────────────────────────

    def _refresh_header(self) -> None:
        self.set_header(f"Online · {self.url} · {self.username} · {self.state}")

    def _set_state(self, state: str) -> None:
        self.state = state
        self._refresh_header()

    def write_server(self, text: str) -> None:
        """Append server text (ANSI escapes allowed) to the main log."""
        rich_text = Text.from_ansi(text)
        self.server_lines.append(rich_text.plain)
        self.query_one("#server", RichLog).write(rich_text)

    def _show_ships(self) -> None:
        body = "\n".join(f"  {name}" for name in self.ship_names)
        self.query_one("#ships", Static).update(f"Your ships\n{body}" if body else "")

    # ── session events ────────────────────────────────────────

    def handle_event(self, event: SessionEvent) -> None:
        """Session callback; runs on the app's event loop."""
        if not self.is_attached:
            return
        try:
            self._apply_event(event)
        except NoMatches:  # screen is being torn down
            return

    def _apply_event(self, event: SessionEvent) -> None:
        command = self.query_one("#command", CommandInput)
        if event.kind == "connected":
            self._set_state("connected")
            self.write_log(event.text.strip())
        elif event.kind == "prompt":
            self._set_state(f"your turn: {event.ship_name}")
            command.placeholder = f"Orders for {event.ship_name} (help for commands)"
            if event.text:
                self.write_server(event.text)
        elif event.kind == "game_over":
            self._set_state("game over")
            command.placeholder = "Game over. Press Esc to return."
            if event.text:
                self.write_server(event.text)
            self.write_server("Press Esc to return.")
        elif event.kind == "disconnected":
            if self.state != "game over":
                self._set_state("disconnected")
                command.placeholder = "Disconnected. Press Esc to return."
            self.write_log(event.text.strip())
        else:  # text / error
            if event.ship_names:
                self.ship_names = event.ship_names
                self._show_ships()
            if event.text.lstrip().startswith("Waiting"):
                self._set_state("waiting")
            elif event.kind == "text" and self.state == "connecting":
                self._set_state("connected")
            self.write_server(event.text)

    # ── input ─────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        command = self.query_one("#command", CommandInput)
        line = event.value.strip()
        command.value = ""
        if not line:
            return
        command.remember(line)
        self.write_server(f"> {line}")
        error = await self.session.send_line(line)
        if error:
            self.write_server(error)
        elif self.state.startswith("your turn"):
            self._set_state("waiting")

    def action_leave(self) -> None:
        if self.state in ("game over", "disconnected"):
            self.run_worker(self._disconnect(), group="ws-leave")
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self.run_worker(self._disconnect(), group="ws-leave")

        self.app.push_screen(ConfirmScreen("Disconnect from the server?"), answered)

    async def _disconnect(self) -> None:
        await self.session.close()
        self.dismiss(None)
