"""AI controller — generates commands for AI-controlled ships.

A greedy per-ship fleet pilot: each controlled ship manages its stance,
picks the nearest enemy (preferring one already exposed by downed shields
when a firing solution exists), then fires the best bearing weapon, turns
to face, or accelerates to close.  One ``Command`` per ship per turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.net.commands import Command
from spacefleet.spatial.geometry import bearing_from_to, distance, is_in_arc

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount
    from spacefleet.net.game_state import GameState

# Engage at ~60% of the ship's best weapon range.
ENGAGE_RANGE_FRACTION = 0.6
# Brace when hull drops below this fraction of max.
BRACE_HULL_FRACTION = 0.4


class AIController:
    """Greedy fleet pilot.  One command per alive controlled ship per turn."""

    def __init__(self, fire_chance: float = 1.0) -> None:
        self.fire_chance = fire_chance

    def generate_commands(
        self,
        state: GameState,
        controlled_ids: list[str] | None = None,
    ) -> dict[str, Command]:
        ids = controlled_ids if controlled_ids is not None else state.ai_ships
        commands: dict[str, Command] = {}
        for ship_id in ids:
            ship = state.ships.get(ship_id)
            if ship is None or not ship.alive:
                continue
            commands[ship_id] = self._decide(ship, state)
        return commands

    def _decide(self, ship: Ship, state: GameState) -> Command:
        if not ship.weapons:
            return Command(ship_id=ship.id, action="pass")
        enemies = [e for e in state.enemy_ships_of(ship) if e.alive]
        if not enemies:
            return Command(ship_id=ship.id, action="pass")
        return Command(ship_id=ship.id, action="pass")  # decision logic added in later tasks

    def _choose_target(self, ship: Ship, enemies: list[Ship]) -> Ship:
        """Nearest alive enemy; among those in a firing solution, prefer
        a shields-down target.  Deterministic tie-break by id."""
        in_solution = [e for e in enemies if self._firing_solution(ship, e) is not None]
        exposed = [e for e in in_solution if e.shields_current == 0]
        pool = exposed or enemies
        return min(pool, key=lambda e: (distance(ship.position, e.position), e.id))

    def _firing_solution(self, ship: Ship, target: Ship) -> WeaponMount | None:
        """Best (highest-strength) weapon that bears on *target* in-arc and
        in-range, or None."""
        bearing = bearing_from_to(ship.position, target.position)
        dist = distance(ship.position, target.position)
        candidates = [
            w
            for w in ship.weapons
            if dist <= w.weapon.range and is_in_arc(ship.heading, bearing, w.arc)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda w: w.weapon.strength)

    def _manage_stance(self, ship: Ship, target: Ship) -> None:
        """Free stance side effect (filled in Task 5)."""
