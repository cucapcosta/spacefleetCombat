"""Game room — orchestrates one match with multiple players.

Manages the command-phase → resolve → report cycle.  Each player
connection is a pair of asyncio StreamReader/StreamWriter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship
    from spacefleet.net.game_state import GameState

from spacefleet.net.ai_controller import AIController
from spacefleet.net.commands import Command, validate_command
from spacefleet.net.protocol import (
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
from spacefleet.net.server_renderer import ServerRenderer
from spacefleet.net.turn_resolver import TurnLog, resolve_turn


@dataclass
class PlayerConnection:
    """A connected player with their network streams."""

    username: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    connected: bool = True


class GameRoom:
    """Orchestrates a single multiplayer match."""

    def __init__(self, room_id: str, state: GameState) -> None:
        self.room_id = room_id
        self.state = state
        self.players: dict[str, PlayerConnection] = {}
        self.renderer = ServerRenderer()
        self.ai = AIController()
        self._running = False
        self._done = asyncio.Event()  # set when game loop finishes
        self._last_log: TurnLog | None = None  # deferred turn results

    def add_player(self, conn: PlayerConnection) -> None:
        self.players[conn.username] = conn

    @property
    def expected_players(self) -> int:
        return len(self.state.player_ships)

    def is_ready(self) -> bool:
        """All expected players have connected."""
        return len(self.players) >= self.expected_players

    # ═══════════════════════════════════════════════════════════
    # Main game loop
    # ═══════════════════════════════════════════════════════════

    async def run_game_loop(self) -> None:
        """Run turns until the game ends or all players disconnect."""
        self._running = True
        try:
            # Send initial welcome (turn header only; per-ship status
            # will be shown before each ship's prompt in the command phase)
            for pid, conn in self.players.items():
                if conn.connected:
                    text = self.renderer.render_turn_header_with_results(
                        pid,
                        self.state,
                    )
                    await _safe_write(conn, {"type": MSG_DISPLAY, "text": text})

            while self._running and not self.state.is_game_over():
                self.state.turn += 1

                # ── Turn header + deferred results from previous turn ──
                for pid, conn in self.players.items():
                    if conn.connected:
                        text = self.renderer.render_turn_header_with_results(
                            pid,
                            self.state,
                            last_log=self._last_log,
                        )
                        await _safe_write(conn, {"type": MSG_DISPLAY, "text": text})

                # ── Command phase (per-ship status shown before each prompt) ──
                player_commands = await self._command_phase()
                if not self._running:
                    break

                # ── AI commands ──
                ai_commands = self.ai.generate_commands(self.state)

                # ── Merge all commands ──
                all_commands: dict[str, Command] = {}
                all_commands.update(ai_commands)
                for _pid, cmds in player_commands.items():
                    all_commands.update(cmds)

                # Fill in "pass" for any alive ship that didn't get a command
                for ship in self.state.alive_ships():
                    if ship.id not in all_commands:
                        all_commands[ship.id] = Command(ship_id=ship.id, action="pass")

                # ── Resolve turn — store for display at next turn start ──
                self._last_log = resolve_turn(self.state, all_commands)

            # ── Game over ──
            # Show the final turn's results before the game-over summary
            if self._last_log is not None:
                for pid, conn in self.players.items():
                    if conn.connected:
                        text = self.renderer.render_turn_result(
                            pid,
                            self._last_log,
                            self.state,
                        )
                        await _safe_write(
                            conn,
                            {
                                "type": MSG_TURN_RESULT,
                                "turn": self._last_log.turn,
                                "text": text,
                            },
                        )

            for pid, conn in self.players.items():
                if conn.connected:
                    text = self.renderer.render_game_over(pid, self.state)
                    await _safe_write(conn, {"type": MSG_GAME_OVER, "text": text})
        finally:
            self._running = False
            self._done.set()

    # ═══════════════════════════════════════════════════════════
    # Command phase — collect orders from all human players
    # ═══════════════════════════════════════════════════════════

    async def _command_phase(self) -> dict[str, dict[str, Command]]:
        """Prompt each player for commands for each of their ships.

        Returns mapping: player_id → {ship_id: Command}.
        """
        # Run all players' command collection concurrently
        tasks: dict[str, asyncio.Task[dict[str, Command]]] = {}
        for pid, conn in self.players.items():
            if conn.connected:
                task = asyncio.create_task(self._collect_player_commands(pid, conn))
                tasks[pid] = task

        # Wait for all players
        results: dict[str, dict[str, Command]] = {}
        for pid, task in tasks.items():
            try:
                cmds = await task
                results[pid] = cmds
            except Exception:
                results[pid] = {}

        return results

    async def _collect_player_commands(
        self,
        player_id: str,
        conn: PlayerConnection,
    ) -> dict[str, Command]:
        """Collect commands from a single player for all their alive ships."""
        commands: dict[str, Command] = {}
        alive_ships = self.state.alive_ships_for(player_id)

        if not alive_ships:
            return commands

        owner_lookup = self.state.owner_lookup()

        for i, ship in enumerate(alive_ships, 1):
            # Send this ship's brief status + contacts before its prompt
            status_text = self.renderer.render_ship_brief(
                ship,
                self.state,
                player_id,
            )
            await _safe_write(conn, {"type": MSG_DISPLAY, "text": status_text})

            # Send prompt
            prompt_text = self.renderer.render_prompt(
                ship,
                i,
                len(alive_ships),
                self.state,
                player_id,
            )
            await _safe_write(
                conn,
                {
                    "type": MSG_PROMPT,
                    "ship_id": ship.id,
                    "ship_name": ship.name,
                    "text": prompt_text,
                },
            )

            # Wait for a valid costed command
            cmd = await self._wait_for_command(
                player_id,
                conn,
                ship,
                owner_lookup,
            )
            if cmd is None:
                # Player disconnected — pass for remaining ships
                for remaining_ship in alive_ships[i:]:
                    commands[remaining_ship.id] = Command(
                        ship_id=remaining_ship.id,
                        action="pass",
                    )
                break
            commands[ship.id] = cmd

        # Signal waiting for other players
        await _safe_write(
            conn,
            {
                "type": MSG_WAITING,
                "text": f"  {_dim_text('Waiting for other players...')}",
            },
        )

        return commands

    async def _wait_for_command(
        self,
        player_id: str,
        conn: PlayerConnection,
        ship: Ship,
        owner_lookup: dict[str, str],
    ) -> Command | None:
        """Read messages until a valid costed command is received.

        Handles free queries inline (status, scan, weapons, help).
        Returns None if the player disconnects.
        """
        while True:
            msg = await read_message(conn.reader)
            if msg is None:
                # Disconnected
                conn.connected = False
                return None

            msg_type = msg.get("type", "")

            if msg_type == MSG_QUERY:
                # Free action — respond and re-prompt
                query = msg.get("query", "")

                # Stance switching is a free action that mutates state
                if query.startswith("stance"):
                    text = self._handle_stance_query(ship, query)
                else:
                    text = self.renderer.render_query(
                        player_id,
                        ship,
                        query,
                        self.state,
                    )
                await _safe_write(conn, {"type": MSG_QUERY_RESULT, "text": text})
                # Re-send prompt
                alive_ships = self.state.alive_ships_for(player_id)
                idx = next(
                    (i for i, s in enumerate(alive_ships, 1) if s.id == ship.id),
                    1,
                )
                prompt_text = self.renderer.render_prompt(
                    ship,
                    idx,
                    len(alive_ships),
                    self.state,
                    player_id,
                )
                await _safe_write(
                    conn,
                    {
                        "type": MSG_PROMPT,
                        "ship_id": ship.id,
                        "ship_name": ship.name,
                        "text": prompt_text,
                    },
                )
                continue

            if msg_type == MSG_COMMAND:
                # Validate the command
                result = validate_command(msg, ship, player_id, owner_lookup)
                if isinstance(result, str):
                    # Validation error
                    await _safe_write(
                        conn,
                        {
                            "type": MSG_COMMAND_REJECT,
                            "ship_id": ship.id,
                            "reason": result,
                        },
                    )
                    # Re-send prompt
                    alive_ships = self.state.alive_ships_for(player_id)
                    idx = next(
                        (i for i, s in enumerate(alive_ships, 1) if s.id == ship.id),
                        1,
                    )
                    prompt_text = self.renderer.render_prompt(
                        ship,
                        idx,
                        len(alive_ships),
                        self.state,
                    )
                    await _safe_write(
                        conn,
                        {
                            "type": MSG_PROMPT,
                            "ship_id": ship.id,
                            "ship_name": ship.name,
                            "text": prompt_text,
                        },
                    )
                    continue

                # Valid command
                await _safe_write(
                    conn,
                    {
                        "type": MSG_COMMAND_ACK,
                        "ship_id": ship.id,
                        "text": f"  Command accepted: {result.action}",
                    },
                )
                return result

            # Unknown message type
            await _safe_write(
                conn,
                {
                    "type": MSG_ERROR,
                    "message": f"Expected command or query, got '{msg_type}'",
                },
            )

    def _handle_stance_query(self, ship: Ship, query: str) -> str:
        """Process a stance query — show info or switch stance.

        This is a free action that may mutate ship state.
        """
        from spacefleet.core.types import Stance
        from spacefleet.data.stance_registry import StanceRegistry

        parts = query.split(None, 1)
        if len(parts) == 1:
            # "stance" with no arg → show current stance info
            data = StanceRegistry.get_for(ship.stance)
            name = data.name
            cd = ship.stance_cooldown_remaining
            cd_str = f" (locked for {cd} more turn(s))" if cd > 0 else " (can switch)"
            valid = ", ".join(s.value for s in Stance)
            return (
                f"  Current stance: \033[93m{name}\033[0m{cd_str}\n"
                f"  {data.description}\n"
                f"  Available: {valid}"
            )

        stance_name = parts[1].strip().lower()

        # Validate
        try:
            new_stance = Stance(stance_name)
        except ValueError:
            valid = ", ".join(s.value for s in Stance)
            return f"  Unknown stance: '{stance_name}'. Valid: {valid}"

        if ship.stance_cooldown_remaining > 0:
            return f"  Cannot switch stance for {ship.stance_cooldown_remaining} more turn(s)."
        if not ship.subsystem_deck:
            return "  Deck subsystem damaged — cannot switch stances."
        if ship.morale <= 0:
            return "  Crew has mutinied — cannot switch stances."
        if new_stance == ship.stance:
            return f"  Already in {StanceRegistry.get_for(new_stance).name} stance."

        old_name = StanceRegistry.get_for(ship.stance).name
        ship.switch_stance(new_stance)
        new_data = StanceRegistry.get_for(new_stance)
        return (
            f"  Stance changed: {old_name} → \033[93m{new_data.name}\033[0m"
            f" (locked for {new_data.switch_cooldown} turns)"
        )

    def handle_disconnect(self, username: str) -> None:
        """Handle a player disconnecting mid-game."""
        conn = self.players.get(username)
        if conn:
            conn.connected = False
        # Check if all players disconnected
        if not any(c.connected for c in self.players.values()):
            self._running = False


# ── Utilities ────────────────────────────────────────────────


async def _safe_write(
    conn: PlayerConnection,
    msg: dict[str, Any],
) -> None:
    """Write a message, silently handling connection errors."""
    if not conn.connected:
        return
    try:
        await write_message(conn.writer, msg)
    except (ConnectionResetError, BrokenPipeError, OSError):
        conn.connected = False


def _dim_text(text: str) -> str:
    """Apply dim ANSI formatting."""
    return f"\033[2m{text}\033[0m"
