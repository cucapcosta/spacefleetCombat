"""Core (network-free) game state.

Holds the ship roster, current turn, and lookup helpers.  The
``net.game_state.GameState`` server class composes/extends this for
multiplayer-specific bookkeeping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.dice import DiceRoller

if TYPE_CHECKING:
    from spacefleet.core.types import Faction
    from spacefleet.models.ship import Ship


@dataclass
class CoreGameState:
    """Battle-only state shared by CLI, AI and server layers."""

    turn: int = 0
    ships: dict[str, Ship] = field(default_factory=dict)
    dice: DiceRoller = field(default_factory=DiceRoller)

    def add_ship(self, ship: Ship) -> None:
        self.ships[ship.id] = ship

    def remove_ship(self, ship_id: str) -> None:
        self.ships.pop(ship_id, None)

    def get_ship(self, ship_id: str) -> Ship:
        return self.ships[ship_id]

    def alive_ships(self) -> list[Ship]:
        return [s for s in self.ships.values() if s.alive]

    def enemies_of(self, ship: Ship) -> list[Ship]:
        return [
            s for s in self.ships.values()
            if s.alive and s.faction != ship.faction
        ]

    def friendlies_of(self, ship: Ship) -> list[Ship]:
        return [
            s for s in self.ships.values()
            if s.alive and s.faction == ship.faction and s.id != ship.id
        ]

    def advance_turn(self) -> None:
        self.turn += 1

    def is_game_over(self) -> bool:
        factions: set[Faction] = set()
        for s in self.ships.values():
            if s.alive:
                factions.add(s.faction)
        return len(factions) < 2
