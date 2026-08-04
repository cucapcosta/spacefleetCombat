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


def validate_ship_spec(
    spec: ShipSpec,
    faction: Faction,
    *,
    is_flagship: bool = False,
) -> None:
    """Validate one ship build against hull, weapon, doctrine and upgrade rules.

    Raises :class:`FleetSpecError` for spec-level violations and lets
    :class:`~spacefleet.models.loadout.LoadoutError` propagate for slot and
    upgrade-cap violations (both are ``ValueError``).
    """
    from spacefleet.commander.doctrine_effects import doctrine_allows_weapon
    from spacefleet.commander.upgrade_effects import validate_upgrades
    from spacefleet.models.loadout import Loadout
    from spacefleet.models.weapon import WeaponMount

    hull = HullRegistry.get_or_none(spec.hull_id)
    if hull is None:
        raise FleetSpecError(f"unknown hull id {spec.hull_id!r}")
    if hull.faction is not faction:
        raise FleetSpecError(
            f"hull {spec.hull_id!r} belongs to faction {hull.faction.value!r},"
            f" not {faction.value!r}"
        )

    slot_index = {s.id: s for s in hull.weapon_slots}
    mounts: list[WeaponMount] = []
    for slot_id, weapon_id in sorted(spec.weapons.items()):
        weapon = WeaponRegistry.get_or_none(weapon_id)
        if weapon is None:
            raise FleetSpecError(f"unknown weapon id {weapon_id!r} (slot {slot_id})")
        slot = slot_index.get(slot_id)
        name = slot.name if slot is not None else f"slot {slot_id}"
        arc = slot.arc if slot is not None else hull.weapon_slots[0].arc
        mounts.append(WeaponMount(slot_id=slot_id, slot_name=name, arc=arc, weapon=weapon))
    Loadout(weapons=mounts).validate(hull)

    doctrine = None
    if spec.doctrine_id is not None:
        doctrine = DoctrineRegistry.get_or_none(spec.doctrine_id)
        if doctrine is None:
            raise FleetSpecError(f"unknown doctrine id {spec.doctrine_id!r}")
        if doctrine.faction != faction.value:
            raise FleetSpecError(
                f"doctrine {spec.doctrine_id!r} belongs to faction {doctrine.faction!r},"
                f" not {faction.value!r}"
            )
        for mount in mounts:
            if not doctrine_allows_weapon(doctrine, mount.weapon):
                raise FleetSpecError(
                    f"doctrine {spec.doctrine_id!r} forbids lance weapon {mount.weapon.id!r}"
                )

    validate_upgrades(
        hull,
        spec.upgrade_ids,
        doctrine_id=spec.doctrine_id,
        is_flagship=is_flagship,
    )


def validate_fleet_spec(fleet: FleetSpec, *, budget: int | None = None) -> None:
    """Validate the whole fleet: composition rules, per-ship rules, budget."""
    if not fleet.ships:
        raise FleetSpecError("fleet needs at least one ship")
    if not (0 <= fleet.flagship_index < len(fleet.ships)):
        raise FleetSpecError(
            f"flagship index {fleet.flagship_index} out of range"
            f" (fleet has {len(fleet.ships)} ships)"
        )
    names = [s.name for s in fleet.ships]
    if len(set(names)) != len(names):
        raise FleetSpecError(f"duplicate ship name in {names}")
    for idx, ship in enumerate(fleet.ships):
        validate_ship_spec(ship, fleet.faction, is_flagship=(idx == fleet.flagship_index))
    if budget is not None:
        total = fleet_points(fleet)
        if total > budget:
            raise FleetSpecError(f"fleet costs {total} pts, over budget {budget}")
