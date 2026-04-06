"""AI controller — generates commands for AI-controlled ships.

Ports the ``DemoBattle._enemy_fire()`` logic: each alive AI ship has
a 20% chance to fire its weapon at the nearest enemy.  Otherwise it
passes.  Generates :class:`Command` objects identical to human commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.net.commands import Command
from spacefleet.spatial.geometry import bearing_from_to, distance, is_in_arc

if TYPE_CHECKING:
    from spacefleet.net.game_state import GameState


class AIController:
    """Simple AI that generates one command per alive AI ship per turn."""

    def __init__(self, fire_chance: float = 0.20) -> None:
        self.fire_chance = fire_chance

    def generate_commands(self, state: GameState) -> dict[str, Command]:
        """Return one Command per alive AI ship."""
        commands: dict[str, Command] = {}

        for ship_id in state.ai_ships:
            ship = state.get_ship(ship_id)
            if not ship.alive:
                continue

            commands[ship_id] = self._decide(ship_id, state)

        return commands

    def _decide(self, ship_id: str, state: GameState) -> Command:
        """Pick an action for one AI ship."""
        ship = state.get_ship(ship_id)

        # No weapons → pass
        if not ship.weapons:
            return Command(ship_id=ship_id, action="pass")

        # Roll for fire chance
        if not state.dice.chance(self.fire_chance):
            return Command(ship_id=ship_id, action="pass")

        # Find nearest enemy
        enemies = state.enemy_ships_of(ship)
        if not enemies:
            return Command(ship_id=ship_id, action="pass")

        nearest = min(
            enemies,
            key=lambda e: distance(ship.position, e.position),
        )

        bearing = bearing_from_to(ship.position, nearest.position)
        weapon = ship.weapons[0]

        # Check arc
        if not is_in_arc(ship.heading, bearing, weapon.arc):
            return Command(ship_id=ship_id, action="pass")

        # Check range
        dist = distance(ship.position, nearest.position)
        if dist > weapon.weapon.range:
            return Command(ship_id=ship_id, action="pass")

        return Command(
            ship_id=ship_id,
            action="fire",
            args={"slot": weapon.slot_id, "bearing": bearing},
        )
