"""Weapon definitions and mounted-weapon runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.core.types import Arc, WeaponSize, WeaponType


@dataclass(frozen=True)
class WeaponProfile:
    """Immutable definition of a weapon that can be equipped."""

    id: str
    name: str
    weapon_type: WeaponType
    size: WeaponSize
    strength: int
    range: float
    cost: int
    description: str = ""
    # Torpedo-specific
    speed: float = 0
    # Specials
    critical_chance_bonus: float = 0.0
    damage_per_hit: int = 1
    ignores_armor: bool = False


@dataclass
class WeaponMount:
    """A weapon installed in a specific slot on a ship, with runtime state."""

    slot_id: int
    slot_name: str
    arc: Arc
    weapon: WeaponProfile

    # Runtime
    can_fire: bool = True
    cooldown: int = 0

    @property
    def display_name(self) -> str:
        return f"{self.slot_name}: {self.weapon.name}"

    @property
    def tag(self) -> str:
        """Short identifier players can type, e.g. 'port_battery'."""
        return self.slot_name.lower().replace(" ", "_")
