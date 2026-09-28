"""Immutable, fog-of-war-filtered views of a battle at one instant.

Snapshots are what the TUI draws and animates between.  They never hold
references to live engine objects, so later mutation of the game state
cannot change a snapshot already taken.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.core.types import DetectionLevel, Faction, Stance, Vector2D

# Phase boundaries reported by ``resolve_turn(on_phase=...)``, in order.
PHASES: tuple[str, ...] = ("start", "after_fire", "after_move", "end")


@dataclass(frozen=True)
class ShipView:
    """One ship as the observing player sees it.

    Stats are ``None`` when the observer's detection level does not reveal
    them (BLIP / CONTACT enemies).  ``heading`` is ``None`` for BLIPs.
    """

    id: str
    label: str  # short map label, e.g. "V1"; "?" for BLIPs
    name: str  # display name at the current detection level
    faction: Faction
    class_letter: str  # "E", "L", "C", "B", "S"; "?" for BLIPs
    position: Vector2D  # jittered for BLIPs
    heading: float | None
    detection: DetectionLevel  # IDENTIFIED for own ships
    is_player: bool
    alive: bool
    hull: int | None = None
    hull_max: int | None = None
    shields: int | None = None
    shields_max: int | None = None
    morale: int | None = None
    morale_max: int | None = None
    stance: Stance | None = None


@dataclass(frozen=True)
class ProjectileView:
    id: str
    position: Vector2D
    bearing: float
    attacker_id: str | None  # None when the firing ship is not visible


@dataclass(frozen=True)
class BattleSnapshot:
    turn: int
    phase: str  # one of PHASES
    ships: tuple[ShipView, ...]
    projectiles: tuple[ProjectileView, ...]

    def ship(self, ship_id: str) -> ShipView | None:
        return next((s for s in self.ships if s.id == ship_id), None)
