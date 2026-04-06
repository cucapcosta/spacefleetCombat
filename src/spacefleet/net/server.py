"""Spacefleet TCP server — accepts connections, authenticates, runs games.

Usage::

    python -m spacefleet --server --port 9876 --mode pve --players 2
"""

from __future__ import annotations

import argparse
import asyncio

from spacefleet.core.types import Faction
from spacefleet.net.game_room import GameRoom, PlayerConnection
from spacefleet.net.game_state import GameState
from spacefleet.net.protocol import (
    MSG_AUTH,
    MSG_AUTH_FAIL,
    MSG_AUTH_OK,
    MSG_ERROR,
    read_message,
    write_message,
)


class SpacefleetServer:
    """Asyncio TCP server for Spacefleet Combat."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9876,
        mode: str = "pve",
        expected_players: int = 1,
        ships_per_player: int = 3,
    ) -> None:
        self.host = host
        self.port = port
        self.mode = mode
        self.expected_players = expected_players
        self.ships_per_player = ships_per_player

        self._connected_users: dict[str, PlayerConnection] = {}
        self._room: GameRoom | None = None
        self._game_started = asyncio.Event()
        self._auth_complete_count = 0
        self._all_auth_sent = asyncio.Event()
        self._game_loop_launched = False

    async def start(self) -> None:
        """Start the server and wait for connections."""
        server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
        print(f"[SERVER] Listening on {addrs}")
        print(f"[SERVER] Mode: {self.mode}, expecting {self.expected_players} player(s)")
        print(f"[SERVER] Ships per player: {self.ships_per_player}")
        print("[SERVER] Waiting for players to connect...\n")

        async with server:
            await server.serve_forever()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new TCP connection."""
        addr = writer.get_extra_info("peername")
        print(f"[SERVER] Connection from {addr}")

        # ── 1. Authentication ──
        msg = await read_message(reader)
        if msg is None or msg.get("type") != MSG_AUTH:
            await write_message(
                writer,
                {
                    "type": MSG_ERROR,
                    "message": "Expected auth message.",
                },
            )
            writer.close()
            return

        username = str(msg.get("username", "")).strip()
        if not username:
            await write_message(
                writer,
                {
                    "type": MSG_AUTH_FAIL,
                    "reason": "Empty username.",
                },
            )
            writer.close()
            return

        if username in self._connected_users:
            await write_message(
                writer,
                {
                    "type": MSG_AUTH_FAIL,
                    "reason": f"Username '{username}' already connected.",
                },
            )
            writer.close()
            return

        if len(self._connected_users) >= self.expected_players:
            await write_message(
                writer,
                {
                    "type": MSG_AUTH_FAIL,
                    "reason": "Game is full.",
                },
            )
            writer.close()
            return

        # Register the player
        conn = PlayerConnection(username=username, reader=reader, writer=writer)
        self._connected_users[username] = conn
        count = len(self._connected_users)
        print(f"[SERVER] Player '{username}' authenticated ({count}/{self.expected_players})")

        # ── 2. Create game if all players are in ──
        if len(self._connected_users) == self.expected_players:
            self._create_game()

        # ── 3. Send auth OK ──
        # Early arrivals: send "waiting" ack, then block until game is created
        if not self._game_started.is_set():
            await write_message(
                writer,
                {
                    "type": MSG_AUTH_OK,
                    "player_id": username,
                    "ships": [],
                    "message": f"Welcome, {username}! Waiting for other players...",
                },
            )
        await self._game_started.wait()

        # Game exists — send full auth with ship list
        assert self._room is not None
        ship_ids = self._room.state.player_ships.get(username, [])
        ship_names = [self._room.state.get_ship(sid).name for sid in ship_ids]
        await write_message(
            writer,
            {
                "type": MSG_AUTH_OK,
                "player_id": username,
                "ships": ship_ids,
                "ship_names": ship_names,
            },
        )

        # Signal that this player's auth is fully sent
        self._auth_complete_count += 1
        if self._auth_complete_count >= self.expected_players:
            self._all_auth_sent.set()

        # Wait for all players to receive their auth before the game starts sending
        await self._all_auth_sent.wait()

        # Start the game loop exactly once (first handler to reach this wins)
        if not self._game_loop_launched:
            self._game_loop_launched = True
            print("[SERVER] Starting game loop...")
            asyncio.create_task(self._run_game())

        # ── 4. Keep connection alive until game ends ──
        try:
            await self._room._done.wait()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            conn.connected = False
            if self._room:
                self._room.handle_disconnect(username)
            print(f"[SERVER] Player '{username}' disconnected")
            writer.close()

    def _create_game(self) -> None:
        """Create the game state, room, add all players, and start the game."""
        players = list(self._connected_users.keys())

        if self.mode == "pvp":
            teams: dict[str, Faction] = {}
            for i, p in enumerate(players):
                teams[p] = Faction.IMPERIAL_NAVY if i % 2 == 0 else Faction.CHAOS_FLEET
            state = GameState.create_pvp(teams, self.ships_per_player)
        elif self.mode == "mixed":
            mid = len(players) // 2
            imperial = players[:mid] or players[:1]
            chaos = players[mid:] or []
            state = GameState.create_mixed(
                imperial,
                chaos,
                self.ships_per_player,
            )
        else:
            # Default: PvE
            state = GameState.create_pve(players, self.ships_per_player)

        self._room = GameRoom(room_id="main", state=state)

        # Add ALL players to the room atomically before signalling
        for _uname, uconn in self._connected_users.items():
            self._room.add_player(uconn)

        print("[SERVER] All players connected! Creating game...")
        self._game_started.set()

    async def _run_game(self) -> None:
        """Run the game loop in the background."""
        if self._room is None:
            return
        try:
            await self._room.run_game_loop()
        except Exception as exc:
            print(f"[SERVER] Game loop error: {exc}")
            import traceback

            traceback.print_exc()
        finally:
            print("[SERVER] Game ended. Shutting down.")
            # Give clients a moment to receive final messages
            await asyncio.sleep(1)
            # Stop the server
            asyncio.get_event_loop().stop()


def parse_server_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse server CLI arguments."""
    parser = argparse.ArgumentParser(description="Spacefleet Combat Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=9876, help="Port")
    parser.add_argument(
        "--mode",
        choices=["pve", "pvp", "mixed"],
        default="pve",
        help="Game mode (default: pve)",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=1,
        help="Expected number of players (default: 1)",
    )
    parser.add_argument(
        "--ships-per-player",
        type=int,
        default=3,
        help="Fleet size per player (default: 3)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the server.

    When invoked with no CLI arguments, shows an interactive setup menu.
    Otherwise uses the provided arguments (backward-compatible with Makefile).
    """
    import sys

    if argv is None and len(sys.argv) == 1:
        # No CLI args — interactive setup
        from spacefleet.cli.prompts import prompt_server_setup

        config = prompt_server_setup()
        if config is None:
            return
        server = SpacefleetServer(**config)
    else:
        args = parse_server_args(argv)
        server = SpacefleetServer(
            host=args.host,
            port=args.port,
            mode=args.mode,
            expected_players=args.players,
            ships_per_player=args.ships_per_player,
        )
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down.")


if __name__ == "__main__":
    main()
