"""Projectile (salvo) entity — a weapon discharge traveling through space."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.core.types import Faction, Vector2D, heading_to_vector

if TYPE_CHECKING:
    from spacefleet.models.weapon import WeaponMount


@dataclass
class Projectile:
    """A weapon salvo in flight.

    Created when a battery fires.  Travels in a straight line at
    *speed* GU/turn, checking for collisions with ships each phase.
    """

    id: str
    position: Vector2D
    bearing: float  # direction of travel (degrees, 0 = north, clockwise)
    speed: float  # GU per turn (from WeaponProfile.speed)
    weapon_mount: WeaponMount
    attacker_id: str  # ID of the ship that fired
    attacker_name: str  # display name
    attacker_faction: Faction
    origin: Vector2D  # where the projectile was created
    max_range: float  # from WeaponProfile.range
    distance_traveled: float = 0.0
    alive: bool = True  # False when expired or detonated

    # ── helpers ──────────────────────────────────────────────

    def advance(self, fraction: float) -> tuple[Vector2D, Vector2D]:
        """Move the projectile by ``speed × fraction`` GU.

        Returns ``(old_position, new_position)`` for collision checking.
        Does nothing if the projectile is dead.
        """
        if not self.alive:
            return (self.position, self.position)

        old = self.position
        move_dist = self.speed * fraction
        direction = heading_to_vector(self.bearing)
        self.position = self.position + direction * move_dist
        self.distance_traveled += move_dist

        # Expire if beyond max range
        if self.distance_traveled >= self.max_range:
            self.alive = False

        return (old, self.position)

    @property
    def weapon_name(self) -> str:
        return self.weapon_mount.weapon.name

    def __repr__(self) -> str:
        status = "alive" if self.alive else "dead"
        return (
            f"Projectile({self.weapon_name!r}, brg={self.bearing:.0f}°,"
            f" pos={self.position}, {self.distance_traveled:.0f}/{self.max_range:.0f} GU,"
            f" {status})"
        )
