"""Fleet container — a collection of Ships under one commander."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from spacefleet.core.types import Faction
    from spacefleet.models.ship import Ship


@dataclass
class Fleet:
    """A homogeneous-faction fleet of ships."""

    commander_name: str = ""
    ships: list[Ship] = field(default_factory=list)

    def add(self, ship: Ship) -> None:
        self.ships.append(ship)

    def remove(self, ship_id: str) -> None:
        self.ships = [s for s in self.ships if s.id != ship_id]

    def alive(self) -> list[Ship]:
        return [s for s in self.ships if s.alive]

    def total_hull_points(self) -> int:
        return sum(s.hull_current for s in self.ships)

    @property
    def faction(self) -> Faction | None:
        return self.ships[0].faction if self.ships else None

    def __iter__(self) -> Iterator[Ship]:
        return iter(self.ships)

    def __len__(self) -> int:
        return len(self.ships)
