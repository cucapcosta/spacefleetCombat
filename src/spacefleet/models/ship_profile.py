"""Ship hull profile definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.core.types import Arc, Faction, ShipClass, WeaponSize, WeaponType


@dataclass(frozen=True)
class WeaponSlotDef:
    """Describes a weapon slot on a hull."""

    id: int
    name: str
    arc: Arc
    size: WeaponSize
    allowed_types: tuple[WeaponType, ...]


@dataclass(frozen=True)
class HullProfile:
    """Immutable hull data – the platform you build on."""

    id: str
    name: str
    classification: ShipClass
    faction: Faction
    hull_cost: int
    leadership: int

    # Structure
    hull_hits: int
    armor_prow: int
    armor_port: int
    armor_starboard: int
    armor_stern: int

    # Movement
    speed: float
    turn_rate: float  # max degrees per turn-action

    # Defences
    shields: int
    turrets: int

    # Detection
    sensor_range: float

    # Weapon slots
    weapon_slots: tuple[WeaponSlotDef, ...]

    # Misc
    assault_actions: int = 0
    base_morale: int = 100
