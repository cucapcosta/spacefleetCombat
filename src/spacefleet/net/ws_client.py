"""Spacefleet WebSocket client — connects to WS server, displays text, sends commands.

Mirrors the TCP client (``client.py``) but communicates over WebSocket,
allowing connection to the Railway-deployed server.

Usage::

    spacefleet-ws-client wss://game.forjadeguerra.com.br/ws --user alice
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import aiohttp

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


class SpacefleetWSClient:
    """WebSocket client for Spacefleet Combat."""

    def __init__(self, url: str, username: str) -> None:
        self.url = url
        self.username = username
        self._running = True

    async def run(self) -> None:
        try:
            async with aiohttp.ClientSession() as session, session.ws_connect(self.url) as ws:
                # Authenticate
                await ws.send_str(json.dumps({"type": MSG_AUTH, "username": self.username}))

                # Wait for auth response
                response = await self._recv(ws)
                if response is None:
                    print("  Connection closed by server.")
                    return

                if response.get("type") == MSG_AUTH_FAIL:
                    print(f"  Authentication failed: {response.get('reason', 'unknown')}")
                    return

                if response.get("type") == MSG_AUTH_OK:
                    ships = response.get("ship_names") or response.get("ships", [])
                    msg = response.get("message", "")
                    if msg:
                        print(f"  {msg}")
                    if ships:
                        print(f"  Your ships: {', '.join(str(s) for s in ships)}")

                # Main receive loop
                await self._receive_loop(ws)

        except aiohttp.ClientError as e:
            print(f"  Cannot connect to {self.url}: {e}")
        except (ConnectionResetError, BrokenPipeError):
            print("\n  Connection lost.")

    async def _recv(self, ws: aiohttp.ClientWebSocketResponse) -> dict[str, Any] | None:
        """Receive and decode one JSON message from the WebSocket."""
        msg = await ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                return json.loads(msg.data)  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                return None
        return None

    async def _receive_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while self._running:
            msg = await self._recv(ws)
            if msg is None:
                print("\n  Disconnected from server.")
                return

            msg_type = msg.get("type", "")

            if msg_type == MSG_DISPLAY:
                print(msg.get("text", ""))

            elif msg_type == MSG_AUTH_OK:
                ships = msg.get("ship_names") or msg.get("ships", [])
                if ships:
                    print(f"  Your fleet: {', '.join(str(s) for s in ships)}")

            elif msg_type == MSG_PROMPT:
                print(msg.get("text", ""))
                await self._input_loop(ws, msg.get("ship_id", ""), msg.get("ship_name", ""))

            elif msg_type == MSG_QUERY_RESULT:
                print(msg.get("text", ""))

            elif msg_type == MSG_COMMAND_ACK:
                print(msg.get("text", "  Command accepted."))

            elif msg_type == MSG_COMMAND_REJECT:
                print(f"  \033[31mRejected:\033[0m {msg.get('reason', 'Unknown error')}")

            elif msg_type == MSG_TURN_RESULT:
                print(msg.get("text", ""))

            elif msg_type == MSG_WAITING:
                print(msg.get("text", "  Waiting for other players..."))

            elif msg_type == MSG_GAME_OVER:
                print(msg.get("text", ""))
                self._running = False
                return

            elif msg_type == MSG_ERROR:
                print(f"  \033[31mServer error:\033[0m {msg.get('message', '')}")

    async def _input_loop(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        ship_id: str,
        ship_name: str,
    ) -> None:
        loop = asyncio.get_event_loop()
        prompt = f"  \033[96m{ship_name}\033[0m> "

        while True:
            try:
                raw = await loop.run_in_executor(None, lambda: input(prompt).strip())
            except (EOFError, KeyboardInterrupt):
                print()
                self._running = False
                return

            if not raw:
                continue

            parts = raw.split()
            cmd = parts[0].lower()
            args = parts[1:]

            # Free actions → query
            if cmd in ("status", "scan", "weapons", "help", "?"):
                query = "help" if cmd == "?" else cmd
                await ws.send_str(
                    json.dumps({"type": MSG_QUERY, "ship_id": ship_id, "query": query})
                )
                return

            if cmd == "quit":
                self._running = False
                return

            # Costed actions → command
            payload = _parse_action(ship_id, cmd, args)
            if payload is None:
                print("  Unknown command. Type 'help' for options.")
                continue

            await ws.send_str(json.dumps(payload))
            return


def _parse_action(ship_id: str, cmd: str, args: list[str]) -> dict[str, Any] | None:
    """Parse user input into a command message dict."""
    if cmd == "fire":
        if len(args) < 2:
            print("  Usage: fire <weapon#> <bearing>")
            return None
        try:
            return {
                "type": MSG_COMMAND,
                "ship_id": ship_id,
                "action": "fire",
                "args": {"slot": int(args[0]), "bearing": float(args[1])},
            }
        except ValueError:
            print("  Invalid fire arguments. Use: fire <number> <bearing>")
            return None

    if cmd == "ahead":
        speed = float(args[0]) if args else None
        return {
            "type": MSG_COMMAND,
            "ship_id": ship_id,
            "action": "ahead",
            "args": {"speed": speed},
        }

    if cmd == "stop":
        return {"type": MSG_COMMAND, "ship_id": ship_id, "action": "stop", "args": {}}

    if cmd == "turn":
        if len(args) < 2:
            print("  Usage: turn <port|starboard> <degrees>")
            return None
        try:
            return {
                "type": MSG_COMMAND,
                "ship_id": ship_id,
                "action": "turn",
                "args": {"direction": args[0], "degrees": float(args[1])},
            }
        except ValueError:
            print("  Invalid turn degrees.")
            return None

    if cmd == "pass":
        return {"type": MSG_COMMAND, "ship_id": ship_id, "action": "pass", "args": {}}

    return None


# ── CLI ───────────────────────────────────────────────────────

DEFAULT_URL = "wss://game.forjadeguerra.com.br/ws"

_BANNER = """
\033[96m╔══════════════════════════════════════════════════╗\033[0m
\033[96m║\033[0m  \033[1mS P A C E F L E E T   C O M B A T\033[0m           \033[96m║\033[0m
\033[96m║\033[0m  \033[2mWebSocket Client\033[0m                              \033[96m║\033[0m
\033[96m╚══════════════════════════════════════════════════╝\033[0m
"""


def _interactive_setup() -> tuple[str, str] | None:
    """Prompt for URL and username when no CLI args are given."""
    print(_BANNER)
    try:
        url = input(f"  Server URL [\033[2m{DEFAULT_URL}\033[0m]: ").strip()
        url = url or DEFAULT_URL
        username = input("  Username: ").strip()
        if not username:
            print("  \033[31mUsername is required.\033[0m")
            return None
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    print()
    return url, username


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
    """Entry point for the WebSocket client."""
    import sys

    args = parse_args(argv)

    if args.url and args.user:
        url, username = args.url, args.user
    elif argv is None and len(sys.argv) == 1:
        result = _interactive_setup()
        if result is None:
            return
        url, username = result
    else:
        if not args.user:
            print("  Error: --user is required")
            return
        url = args.url or DEFAULT_URL
        username = args.user

    print(f"  Connecting to \033[96m{url}\033[0m as \033[93m{username}\033[0m...\n")
    client = SpacefleetWSClient(url=url, username=username)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\n  Disconnected.")


if __name__ == "__main__":
    main()
