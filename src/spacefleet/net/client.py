"""Spacefleet thin client — connects to server, displays text, sends commands.

The client is deliberately minimal.  The server holds all game state and
renders all output.  The client just:

1. Connects and authenticates (username only).
2. Displays text received from the server.
3. Reads user input when prompted and sends it as JSON commands.

Usage::

    python -m spacefleet --client localhost --port 9876 --user alice
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from spacefleet.net.protocol import (
    MSG_AUTH,
    MSG_AUTH_FAIL,
    MSG_AUTH_OK,
    MSG_COMMAND,
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
    read_message,
    write_message,
)


class SpacefleetClient:
    """Minimal asyncio TCP client for Spacefleet Combat."""

    def __init__(self, host: str, port: int, username: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self._running = True

    async def run(self) -> None:
        """Connect to the server and enter the receive loop."""
        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
        except (ConnectionRefusedError, OSError) as e:
            print(f"  Cannot connect to {self.host}:{self.port}: {e}")
            return

        # ── Authenticate ──
        await write_message(writer, {"type": MSG_AUTH, "username": self.username})

        # Wait for auth response
        response = await read_message(reader)
        if response is None:
            print("  Connection closed by server.")
            writer.close()
            return

        if response.get("type") == MSG_AUTH_FAIL:
            print(f"  Authentication failed: {response.get('reason', 'unknown')}")
            writer.close()
            return

        if response.get("type") == MSG_AUTH_OK:
            ships = response.get("ship_names") or response.get("ships", [])
            msg = response.get("message", "")
            if msg:
                print(f"  {msg}")
            if ships:
                print(f"  Your ships: {', '.join(str(s) for s in ships)}")

        # ── Main receive loop ──
        try:
            await self._receive_loop(reader, writer)
        except (ConnectionResetError, BrokenPipeError):
            print("\n  Connection lost.")
        finally:
            writer.close()

    async def _receive_loop(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Process messages from the server."""
        while self._running:
            msg = await read_message(reader)
            if msg is None:
                print("\n  Disconnected from server.")
                return

            msg_type = msg.get("type", "")

            if msg_type == MSG_DISPLAY:
                print(msg.get("text", ""))

            elif msg_type == MSG_AUTH_OK:
                # Second auth_ok with ship list
                ships = msg.get("ship_names") or msg.get("ships", [])
                if ships:
                    print(f"  Your fleet: {', '.join(str(s) for s in ships)}")

            elif msg_type == MSG_PROMPT:
                # Interactive: read input for this ship
                print(msg.get("text", ""))
                await self._input_loop(writer, msg.get("ship_id", ""), msg.get("ship_name", ""))

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

            else:
                # Unknown message type — ignore
                pass

    async def _input_loop(
        self,
        writer: asyncio.StreamWriter,
        ship_id: str,
        ship_name: str,
    ) -> None:
        """Read one command from the user for a specific ship.

        Free actions (status, scan, weapons, help) are sent as queries;
        the receive_loop handles the response and the server re-sends
        the prompt.  Costed actions are sent as commands.
        """
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

            # ── Free actions → query ──
            if cmd in ("status", "scan", "weapons", "help", "?", "stance"):
                if cmd == "?":
                    query = "help"
                elif cmd == "stance":
                    query = f"stance {' '.join(args)}".strip()
                else:
                    query = cmd
                await write_message(
                    writer,
                    {
                        "type": MSG_QUERY,
                        "ship_id": ship_id,
                        "query": query,
                    },
                )
                return  # Return to receive_loop for query_result + re-prompt

            # ── Quit ──
            if cmd == "quit":
                self._running = False
                return

            # ── Costed actions → command ──
            msg = self._parse_action(ship_id, cmd, args)
            if msg is None:
                print("  Unknown command. Type 'help' for options.")
                continue

            await write_message(writer, msg)
            return  # Return to receive_loop for ack/reject

    def _parse_action(
        self,
        ship_id: str,
        cmd: str,
        args: list[str],
    ) -> dict[str, Any] | None:
        """Parse user input into a command message.

        Minimal client-side validation — the server validates fully.
        """
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
            return {
                "type": MSG_COMMAND,
                "ship_id": ship_id,
                "action": "stop",
                "args": {},
            }

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
            return {
                "type": MSG_COMMAND,
                "ship_id": ship_id,
                "action": "pass",
                "args": {},
            }

        if cmd == "strike":
            if len(args) < 2:
                print("  Usage: strike <target_id> <subsystem>")
                print("  Subsystems: generator, deck, engines, weapons")
                return None
            return {
                "type": MSG_COMMAND,
                "ship_id": ship_id,
                "action": "strike",
                "args": {"target": args[0], "subsystem": args[1]},
            }

        return None


def parse_client_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse client CLI arguments."""
    parser = argparse.ArgumentParser(description="Spacefleet Combat Client")
    parser.add_argument("host", help="Server address")
    parser.add_argument("--port", type=int, default=9876, help="Port")
    parser.add_argument("--user", required=True, help="Username")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the client.

    When invoked with no CLI arguments, shows an interactive connection menu.
    Otherwise uses the provided arguments (backward-compatible with Makefile).
    """
    import sys

    if argv is None and len(sys.argv) == 1:
        # No CLI args — interactive setup
        from spacefleet.cli.prompts import prompt_client_setup

        config = prompt_client_setup()
        if config is None:
            return
        host, port, username = config["host"], config["port"], config["username"]
        # Show connection feedback (interactive mode only)
        from spacefleet.cli.colors import C, colored

        print(
            f"\n  Connecting to {colored(host, C.BRIGHT_CYAN)}"
            f":{colored(str(port), C.BRIGHT_CYAN)}"
            f" as {colored(username, C.BRIGHT_YELLOW)}...\n"
        )
    else:
        args = parse_client_args(argv)
        host, port, username = args.host, args.port, args.user

    client = SpacefleetClient(host=host, port=port, username=username)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\n  Disconnected.")


if __name__ == "__main__":
    main()
