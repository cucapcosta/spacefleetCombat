"""Fleet container — ships under one commander's control."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from spacefleet.commander.commander import Commander
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Faction
    from spacefleet.models.ship import Ship


@dataclass
class Fleet:
    """A fleet identified by ``id`` (player_id for humans, ``ai_<n>`` for AI).

    Holds the commander (optional — AI hulks have none), the flagship
    ship id, and the list of ship ids that make up the fleet.  Ships
    themselves live in :class:`CoreGameState.ships`; this fleet
    resolves them on demand via ``ships_in``.

    Legacy fields (``commander_name``, ``ships``, ``add``, ``remove``,
    ``alive``, ``total_hull_points``, ``faction``, iterators) are kept
    for back-compat with pre-Sprint-5 tests.  New code should prefer
    ``ships_in(state)`` / ``alive_ships_in(state)`` / ``flagship_in(state)``.
    """

    id: str = ""
    commander: Commander | None = None
    flagship_ship_id: str | None = None
    ship_ids: list[str] = field(default_factory=list)
    commander_name: str = ""
    ships: list[Ship] = field(default_factory=list)

    # ── State-aware accessors ───────────────────────

    def ships_in(self, state: CoreGameState) -> list[Ship]:
        return [state.ships[sid] for sid in self.ship_ids if sid in state.ships]

    def alive_ships_in(self, state: CoreGameState) -> list[Ship]:
        return [s for s in self.ships_in(state) if s.alive]

    def flagship_in(self, state: CoreGameState) -> Ship | None:
        if self.flagship_ship_id is None:
            return None
        ship = state.ships.get(self.flagship_ship_id)
        return ship if (ship is not None and ship.alive) else None

    # ── Legacy passthroughs ─────────────────────────

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
