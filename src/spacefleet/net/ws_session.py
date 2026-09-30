"""WebSocket game session without terminal I/O.

:class:`WSSession` holds the client side of the Spacefleet websocket protocol
(auth, receive loop, orders for the prompted ship) and reports everything
the player should see as :class:`SessionEvent` objects through a callback,
so any front end (the Textual online screen, tests) can drive it.
"""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp
import certifi

from spacefleet.net.ws_client import (
    MSG_AUTH,
    MSG_AUTH_FAIL,
    MSG_AUTH_OK,
    MSG_COMMAND_ACK,
    MSG_COMMAND_REJECT,
    MSG_DISPLAY,
    MSG_ERROR,
    MSG_GAME_OVER,
    MSG_PROMPT,
    MSG_QUERY,
    MSG_QUERY_RESULT,
    MSG_TURN_RESULT,
    MSG_WAITING,
    _parse_action_checked,
)

if TYPE_CHECKING:
    from collections.abc import Callable

QUERY_WORDS = frozenset({"status", "scan", "weapons", "help", "?", "stance"})
"""Free actions answered by the server with a ``query_result``."""


@dataclass(frozen=True)
class SessionEvent:
    """Something the player should see.

    *kind* is one of ``connected``, ``text`` (display, turn/query results,
    acks, waiting and auth info), ``error`` (auth failure, rejected command,
    server or connection error), ``prompt`` (the server wants orders for
    *ship_id*/*ship_name*), ``game_over`` and ``disconnected``.  *text* may
    contain ANSI escapes.  *ship_names* is filled on the auth info event.
    """

    kind: str
    text: str
    ship_id: str = ""
    ship_name: str = ""
    ship_names: tuple[str, ...] = ()


class WSSession:
    """Client side of one websocket game, reporting through *on_event*."""

    def __init__(
        self,
        url: str,
        username: str,
        on_event: Callable[[SessionEvent], None],
    ) -> None:
        self.url = url
        self.username = username
        self.on_event = on_event
        self.awaiting_input = False
        self.ship_id = ""
        self.ship_name = ""
        self.ship_names: tuple[str, ...] = ()
        self.game_over = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._closing = False

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    def _emit(self, kind: str, text: str, ship_id: str = "", ship_name: str = "") -> None:
        self.on_event(SessionEvent(kind, text, ship_id, ship_name))

    # ── connection ────────────────────────────────────────────

    async def run(self) -> None:
        """Connect, authenticate and process server messages until the end.

        Always finishes with a ``disconnected`` event.
        """
        farewell = "  Disconnected from server."
        try:
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with (
                aiohttp.ClientSession(connector=connector) as http,
                http.ws_connect(self.url) as ws,
            ):
                self._ws = ws
                self._emit("connected", f"  Connected to {self.url} as {self.username}.")
                await ws.send_str(json.dumps({"type": MSG_AUTH, "username": self.username}))

                response = await self._recv(ws)
                if response is None:
                    farewell = "  Connection closed by server."
                elif response.get("type") == MSG_AUTH_FAIL:
                    self._emit(
                        "error",
                        f"  Authentication failed: {response.get('reason', 'unknown')}",
                    )
                else:
                    if response.get("type") == MSG_AUTH_OK:
                        self._auth_info(response, "Your ships")
                    else:
                        self._dispatch(response)
                    if not self.game_over:
                        await self._receive_loop(ws)
        except aiohttp.ClientError as e:
            self._emit("error", f"  Cannot connect to {self.url}: {e}")
        except (ConnectionResetError, BrokenPipeError):
            farewell = "  Connection lost."
        except OSError as e:
            self._emit("error", f"  Cannot connect to {self.url}: {e}")
        finally:
            self._ws = None
            self.awaiting_input = False
        if self._closing:
            farewell = "  Disconnected."
        self._emit("disconnected", farewell)

    async def close(self) -> None:
        """Leave the game; :meth:`run` then ends with ``disconnected``."""
        self._closing = True
        self.awaiting_input = False
        ws = self._ws
        if ws is not None and not ws.closed:
            await ws.close()

    async def _recv(self, ws: aiohttp.ClientWebSocketResponse) -> dict[str, Any] | None:
        """Receive and decode one JSON message (None when closed or invalid)."""
        msg = await ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                return json.loads(msg.data)  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                return None
        return None

    async def _receive_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not self._closing:
            msg = await self._recv(ws)
            if msg is None:
                return
            self._dispatch(msg)
            if self.game_over:
                return

    def _auth_info(self, msg: dict[str, Any], label: str) -> None:
        ships = msg.get("ship_names") or msg.get("ships", [])
        self.ship_names = tuple(str(s) for s in ships)
        lines = []
        text = msg.get("message", "")
        if text and label == "Your ships":
            lines.append(f"  {text}")
        if ships:
            lines.append(f"  {label}: {', '.join(self.ship_names)}")
        if lines:
            self.on_event(SessionEvent("text", "\n".join(lines), ship_names=self.ship_names))

    def _dispatch(self, msg: dict[str, Any]) -> None:
        """Translate one server message into events (as the old client printed it)."""
        msg_type = msg.get("type", "")

        if msg_type in (MSG_DISPLAY, MSG_QUERY_RESULT, MSG_TURN_RESULT):
            self._emit("text", msg.get("text", ""))
        elif msg_type == MSG_AUTH_OK:
            self._auth_info(msg, "Your fleet")
        elif msg_type == MSG_PROMPT:
            self.ship_id = str(msg.get("ship_id", ""))
            self.ship_name = str(msg.get("ship_name", ""))
            self.awaiting_input = True
            self._emit("prompt", msg.get("text", ""), self.ship_id, self.ship_name)
        elif msg_type == MSG_COMMAND_ACK:
            self._emit("text", msg.get("text", "  Command accepted."))
        elif msg_type == MSG_COMMAND_REJECT:
            reason = msg.get("reason", "Unknown error")
            self._emit("error", f"  \033[31mRejected:\033[0m {reason}")
        elif msg_type == MSG_WAITING:
            self.awaiting_input = False
            self._emit("text", msg.get("text", "  Waiting for other players..."))
        elif msg_type == MSG_GAME_OVER:
            self.game_over = True
            self.awaiting_input = False
            self._emit("game_over", msg.get("text", ""))
        elif msg_type == MSG_ERROR:
            self._emit("error", f"  \033[31mServer error:\033[0m {msg.get('message', '')}")

    # ── orders ────────────────────────────────────────────────

    async def send_line(self, line: str) -> str | None:
        """Send one line typed by the player for the prompted ship.

        Query words become a ``query``, ``quit`` closes the session and
        anything else is parsed into a ``command``.  Returns an error
        message to show (usage, unknown command, not your turn) or None.
        """
        parts = line.split()
        if not parts:
            return None
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "quit":
            await self.close()
            return None

        ws = self._ws
        if ws is None or ws.closed:
            return "  Not connected."
        if not self.awaiting_input:
            return "  Not your turn yet. Wait for the prompt."

        payload: dict[str, Any] | None
        if cmd in QUERY_WORDS:
            if cmd == "?":
                query = "help"
            elif cmd == "stance":
                query = f"stance {' '.join(args)}".strip()
            else:
                query = cmd
            payload = {"type": MSG_QUERY, "ship_id": self.ship_id, "query": query}
        else:
            payload, error = _parse_action_checked(self.ship_id, cmd, args)
            if payload is None:
                return error

        self.awaiting_input = False
        await ws.send_str(json.dumps(payload))
        return None
