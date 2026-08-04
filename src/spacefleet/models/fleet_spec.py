"""Serializable fleet/ship build specs — points math, validation, round-trip.

A *spec* describes what a player bought (hull, weapons per slot, upgrades,
doctrine); it carries no runtime state.  ``net.game_state.add_custom_fleet``
materialises specs into ships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry


class FleetSpecError(ValueError):
    """Raised when a fleet/ship spec references unknown ids or breaks rules."""


@dataclass
class ShipSpec:
    """One ship build: hull + weapon choices per slot + upgrades + doctrine."""

    name: str
    hull_id: str
    weapons: dict[int, str] = field(default_factory=dict)  # slot_id -> weapon_id
    upgrade_ids: list[str] = field(default_factory=list)
    doctrine_id: str | None = None


@dataclass
class FleetSpec:
    """A named, faction-pure list of ship builds with a designated flagship."""

    name: str
    faction: Faction
    ships: list[ShipSpec] = field(default_factory=list)
    flagship_index: int = 0


def ship_points(spec: ShipSpec) -> int:
    """hull_cost + weapon costs + upgrade costs + doctrine cost."""
    hull = HullRegistry.get_or_none(spec.hull_id)
    if hull is None:
        raise FleetSpecError(f"unknown hull id {spec.hull_id!r}")
    total = hull.hull_cost
    for slot_id, weapon_id in spec.weapons.items():
        weapon = WeaponRegistry.get_or_none(weapon_id)
        if weapon is None:
            raise FleetSpecError(f"unknown weapon id {weapon_id!r} (slot {slot_id})")
        total += weapon.cost
    for upgrade_id in spec.upgrade_ids:
        upgrade = UpgradeRegistry.get_or_none(upgrade_id)
        if upgrade is None:
            raise FleetSpecError(f"unknown upgrade id {upgrade_id!r}")
        total += upgrade.cost
    if spec.doctrine_id is not None:
        doctrine = DoctrineRegistry.get_or_none(spec.doctrine_id)
        if doctrine is None:
            raise FleetSpecError(f"unknown doctrine id {spec.doctrine_id!r}")
        total += doctrine.cost
    return total


def fleet_points(fleet: FleetSpec) -> int:
    """Total points across all ships."""
    return sum(ship_points(s) for s in fleet.ships)


def fleet_to_dict(fleet: FleetSpec) -> dict[str, Any]:
    """JSON-safe dict (weapon slot keys serialise as strings)."""
    return {
        "name": fleet.name,
        "faction": fleet.faction.value,
        "flagship_index": fleet.flagship_index,
        "ships": [
            {
                "name": s.name,
                "hull_id": s.hull_id,
                "weapons": {str(k): v for k, v in s.weapons.items()},
                "upgrade_ids": list(s.upgrade_ids),
                "doctrine_id": s.doctrine_id,
            }
            for s in fleet.ships
        ],
    }


def fleet_from_dict(data: dict[str, Any]) -> FleetSpec:
    """Inverse of :func:`fleet_to_dict`; coerces weapon slot keys back to int."""
    try:
        ships = [
            ShipSpec(
                name=str(raw["name"]),
                hull_id=str(raw["hull_id"]),
                weapons={int(k): str(v) for k, v in (raw.get("weapons") or {}).items()},
                upgrade_ids=[str(u) for u in (raw.get("upgrade_ids") or [])],
                doctrine_id=raw.get("doctrine_id"),
            )
            for raw in data.get("ships", [])
        ]
        return FleetSpec(
            name=str(data["name"]),
            faction=Faction(str(data["faction"])),
            ships=ships,
            flagship_index=int(data.get("flagship_index", 0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise FleetSpecError(f"malformed fleet data: {exc}") from exc
