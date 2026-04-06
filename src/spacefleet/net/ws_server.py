"""Spacefleet WebSocket server — aiohttp-based, deployable on Railway.

Adapts WebSocket connections to look like asyncio StreamReader/StreamWriter
so GameRoom works unchanged.

Usage::

    uv run spacefleet-ws-server
    # or via env vars: PORT=8080 GAME_MODE=pve EXPECTED_PLAYERS=2
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, cast

from aiohttp import WSMsgType, web

from spacefleet.core.types import Faction
from spacefleet.net.game_room import GameRoom, PlayerConnection
from spacefleet.net.game_state import GameState
from spacefleet.net.protocol import (
    MSG_AUTH,
    MSG_AUTH_FAIL,
    MSG_AUTH_OK,
    MSG_ERROR,
    write_message,
)

# ── WebSocket → StreamReader/StreamWriter adapters ────────────


class _WSReader:
    """Adapts an aiohttp WebSocketResponse to behave like asyncio.StreamReader."""

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self._ws = ws

    async def readline(self) -> bytes:
        msg = await self._ws.receive()
        if msg.type in (WSMsgType.TEXT,):
            data: str = msg.data
            return data.encode("utf-8") + b"\n"
        # CLOSE, ERROR, BINARY, CLOSING → signal EOF
        return b""


class _WSWriter:
    """Adapts an aiohttp WebSocketResponse to behave like asyncio.StreamWriter."""

    def __init__(self, ws: web.WebSocketResponse, request: web.Request) -> None:
        self._ws = ws
        self._request = request
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        if self._buf:
            text = bytes(self._buf).decode("utf-8", errors="replace").rstrip("\n")
            self._buf.clear()
            await self._ws.send_str(text + "\n")

    def close(self) -> None:
        asyncio.ensure_future(self._ws.close())

    def get_extra_info(self, key: str, default: Any = None) -> Any:
        if key == "peername":
            peername = self._request.remote or "unknown"
            return (peername, 0)
        return default


# ── HTTP + WebSocket server ───────────────────────────────────


class SpacefleetWSServer:
    """aiohttp server exposing health-check and WebSocket endpoints."""

    def __init__(
        self,
        port: int = 8080,
        mode: str = "pve",
        expected_players: int = 1,
        ships_per_player: int = 3,
    ) -> None:
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

    def _reset(self) -> None:
        """Reset state so the server can host another game."""
        self._connected_users = {}
        self._room = None
        self._game_started = asyncio.Event()
        self._auth_complete_count = 0
        self._all_auth_sent = asyncio.Event()
        self._game_loop_launched = False

    # ── HTTP handlers ─────────────────────────────────────────

    async def handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "game": "spacefleet-combat",
                "mode": self.mode,
                "players": f"{len(self._connected_users)}/{self.expected_players}",
            }
        )

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        reader = _WSReader(ws)
        writer = _WSWriter(ws, request)

        addr = writer.get_extra_info("peername")
        print(f"[WS] Connection from {addr}")

        try:
            await self._handle_session(
                cast("asyncio.StreamReader", reader),
                cast("asyncio.StreamWriter", writer),
            )
        except Exception as exc:
            print(f"[WS] Session error: {exc}")
        finally:
            if not ws.closed:
                await ws.close()

        return ws

    # ── Session logic (mirrors server.py) ─────────────────────

    async def _handle_session(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        from spacefleet.net.protocol import read_message

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
            return

        if username in self._connected_users:
            await write_message(
                writer,
                {
                    "type": MSG_AUTH_FAIL,
                    "reason": f"Username '{username}' already connected.",
                },
            )
            return

        if len(self._connected_users) >= self.expected_players:
            await write_message(
                writer,
                {
                    "type": MSG_AUTH_FAIL,
                    "reason": "Game is full.",
                },
            )
            return

        # Register the player
        conn = PlayerConnection(username=username, reader=reader, writer=writer)
        self._connected_users[username] = conn
        count = len(self._connected_users)
        print(f"[WS] Player '{username}' authenticated ({count}/{self.expected_players})")

        # ── 2. Create game if all players are in ──
        if len(self._connected_users) == self.expected_players:
            self._create_game()

        # ── 3. Send auth OK ──
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

        await self._all_auth_sent.wait()

        # Start the game loop exactly once
        if not self._game_loop_launched:
            self._game_loop_launched = True
            print("[WS] Starting game loop...")
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
            print(f"[WS] Player '{username}' disconnected")

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
            state = GameState.create_pve(players, self.ships_per_player)

        self._room = GameRoom(room_id="main", state=state)

        for _uname, uconn in self._connected_users.items():
            self._room.add_player(uconn)

        print("[WS] All players connected! Creating game...")
        self._game_started.set()

    async def _run_game(self) -> None:
        """Run the game loop; reset state when done so a new game can start."""
        if self._room is None:
            return
        try:
            await self._room.run_game_loop()
        except Exception as exc:
            print(f"[WS] Game loop error: {exc}")
            import traceback

            traceback.print_exc()
        finally:
            print("[WS] Game ended. Ready for new connections.")
            await asyncio.sleep(1)
            self._reset()

    # ── App factory ───────────────────────────────────────────

    def create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.handle_health)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/ws", self.handle_ws)
        return app

    def run(self) -> None:
        print(f"[WS] Starting on port {self.port}")
        print(f"[WS] Mode: {self.mode}, expecting {self.expected_players} player(s)")
        print(f"[WS] Ships per player: {self.ships_per_player}")
        print("[WS] Endpoints: /health (HTTP), /ws (WebSocket)\n")
        app = self.create_app()
        web.run_app(app, host="0.0.0.0", port=self.port, print=None)


def main() -> None:
    """Entry point — configured via environment variables."""
    port = int(os.environ.get("PORT", "8080"))
    mode = os.environ.get("GAME_MODE", "pve")
    expected = int(os.environ.get("EXPECTED_PLAYERS", "1"))
    ships = int(os.environ.get("SHIPS_PER_PLAYER", "3"))

    server = SpacefleetWSServer(
        port=port,
        mode=mode,
        expected_players=expected,
        ships_per_player=ships,
    )
    server.run()


if __name__ == "__main__":
    main()
