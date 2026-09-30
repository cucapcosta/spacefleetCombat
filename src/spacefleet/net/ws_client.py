"""Spacefleet WebSocket client — connects to WS server, displays text, sends commands.

The network logic lives in :mod:`spacefleet.net.ws_session`; this module keeps
the protocol constants, the command parser and the ``spacefleet-ws-client``
entry point, which opens a minimal Textual app on the online screen.

Usage::

    spacefleet-ws-client wss://game.forjadeguerra.com.br/ws --user alice
"""

from __future__ import annotations

import argparse
from typing import Any

# Protocol constants (duplicated to keep the client self-contained for PyInstaller)
MSG_AUTH = "auth"
MSG_AUTH_OK = "auth_ok"
MSG_AUTH_FAIL = "auth_fail"
MSG_COMMAND = "command"
MSG_COMMAND_ACK = "command_ack"
MSG_COMMAND_REJECT = "command_reject"
MSG_DISPLAY = "display"
MSG_ERROR = "error"
MSG_GAME_OVER = "game_over"
MSG_PROMPT = "prompt"
MSG_QUERY = "query"
MSG_QUERY_RESULT = "query_result"
MSG_TURN_RESULT = "turn_result"
MSG_WAITING = "waiting"


_MOVE_USAGE = "  Usage: move <speed|-> [port|starboard <degrees>]"
_UNKNOWN_COMMAND = "  Unknown command. Type 'help' for options."

ParseResult = tuple[dict[str, Any] | None, str | None]
"""``(payload, None)`` on success, ``(None, error message)`` otherwise."""


def _command(ship_id: str, action: str, args: dict[str, Any]) -> ParseResult:
    return {"type": MSG_COMMAND, "ship_id": ship_id, "action": action, "args": args}, None


def _parse_move_checked(ship_id: str, args: list[str]) -> ParseResult:
    """``move <speed|-> [port|starboard <deg>]`` → free maneuver message.

    Mirrors ``spacefleet.cli.action_parser`` (kept local for PyInstaller).
    """
    if not args or len(args) not in (1, 3):
        return None, _MOVE_USAGE
    try:
        speed = None if args[0] == "-" else float(args[0])
        turn = 0.0
        if len(args) == 3:
            side = args[1].lower()
            if side not in ("port", "p", "left", "starboard", "stbd", "s", "right"):
                return None, _MOVE_USAGE
            degrees = float(args[2])
            if degrees < 0:
                return None, _MOVE_USAGE
            turn = -degrees if side in ("port", "p", "left") else degrees
    except ValueError:
        return None, _MOVE_USAGE
    return {
        "type": MSG_COMMAND,
        "ship_id": ship_id,
        "action": "move",
        "args": {},
        "maneuver": {"speed": speed, "turn": turn},
    }, None


def _parse_action_checked(ship_id: str, cmd: str, args: list[str]) -> ParseResult:
    """Parse user input into ``(command message, error message)``.

    ``move`` is free (the server holds it and re-prompts); fire, strike or
    pass then ends the ship's orders.  ahead/stop/turn are maneuver + pass.
    Exactly one of the two results is None.
    """
    if cmd == "move":
        return _parse_move_checked(ship_id, args)

    if cmd == "fire":
        if len(args) < 2:
            return None, (
                "  Usage: fire <weapon#> <bearing> (relative to prow: 0 ahead, 90 starboard)"
            )
        try:
            return _command(ship_id, "fire", {"slot": int(args[0]), "bearing": float(args[1])})
        except ValueError:
            return None, "  Invalid fire arguments. Use: fire <number> <bearing>"

    if cmd == "ahead":
        try:
            speed = float(args[0]) if args else None
        except ValueError:
            return None, "  Usage: ahead [speed]"
        return _command(ship_id, "ahead", {"speed": speed})

    if cmd == "stop":
        return _command(ship_id, "stop", {})

    if cmd == "turn":
        if len(args) < 2:
            return None, "  Usage: turn <port|starboard> <degrees>"
        try:
            return _command(ship_id, "turn", {"direction": args[0], "degrees": float(args[1])})
        except ValueError:
            return None, "  Invalid turn degrees."

    if cmd == "pass":
        return _command(ship_id, "pass", {})

    if cmd == "strike":
        if len(args) < 2:
            return None, "  Usage: strike <target_id> <subsystem>"
        return _command(ship_id, "strike", {"target": args[0], "subsystem": args[1]})

    return None, _UNKNOWN_COMMAND


def _parse_move(ship_id: str, args: list[str]) -> dict[str, Any] | None:
    """Payload-only variant of :func:`_parse_move_checked` (None on bad input)."""
    return _parse_move_checked(ship_id, args)[0]


def _parse_action(ship_id: str, cmd: str, args: list[str]) -> dict[str, Any] | None:
    """Payload-only variant of :func:`_parse_action_checked` (None on bad input)."""
    return _parse_action_checked(ship_id, cmd, args)[0]


# ── CLI ───────────────────────────────────────────────────────

DEFAULT_URL = "wss://game.forjadeguerra.com.br/ws"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spacefleet Combat WebSocket Client")
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help=f"WebSocket URL (default: {DEFAULT_URL})",
    )
    parser.add_argument("--user", "-u", default=None, help="Username")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the WebSocket client: a minimal Textual app.

    With both a URL and ``--user`` it opens the online screen directly;
    otherwise it shows the connect form (pre-filled with what was given).
    The app exits when that screen is left.
    """
    from textual.app import App
    from textual.screen import Screen

    from spacefleet.tui.screens.online import ConnectScreen, OnlineScreen

    args = parse_args(argv)
    url = args.url or DEFAULT_URL
    username = args.user or ""

    class Launcher(Screen[None]):
        """Blank base screen; the app exits once it is on top again."""

        launched = False

        def on_mount(self) -> None:
            if args.url and args.user:
                self.app.push_screen(OnlineScreen(url, username))
            else:
                self.app.push_screen(ConnectScreen(url, username))
            self.launched = True

        def on_screen_resume(self) -> None:
            if self.launched and self.app.screen is self:
                self.app.exit()

    class OnlineClientApp(App[None]):
        TITLE = "Spacefleet Combat"

        def get_default_screen(self) -> Screen[None]:
            return Launcher()

    OnlineClientApp().run()


if __name__ == "__main__":
    main()
