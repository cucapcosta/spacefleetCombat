"""Weapon + upgrade loadout container with slot validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.core.types import WeaponSize

if TYPE_CHECKING:
    from spacefleet.models.ship_profile import HullProfile
    from spacefleet.models.weapon import WeaponMount


class LoadoutError(ValueError):
    """Raised when a Loadout fails to validate against a HullProfile."""


_SIZE_ORDER: dict[WeaponSize, int] = {
    WeaponSize.SMALL: 1,
    WeaponSize.MEDIUM: 2,
    WeaponSize.LARGE: 3,
    WeaponSize.TORPEDO: 2,
    WeaponSize.SPECIAL: 2,
}


@dataclass
class Loadout:
    """A set of weapons (and, eventually, upgrades + doctrine) for a hull."""

    weapons: list[WeaponMount] = field(default_factory=list)
    upgrade_ids: list[str] = field(default_factory=list)
    doctrine_id: str | None = None

    def validate(self, hull: HullProfile) -> None:
        """Raise :class:`LoadoutError` if any mount is illegal for *hull*."""
        slot_index = {s.id: s for s in hull.weapon_slots}
        for mount in self.weapons:
            slot = slot_index.get(mount.slot_id)
            if slot is None:
                raise LoadoutError(
                    f"unknown slot id {mount.slot_id} on hull {hull.id}",
                )
            if mount.weapon.weapon_type not in slot.allowed_types:
                raise LoadoutError(
                    f"{mount.weapon.weapon_type.value} not allowed in slot {slot.name} ({hull.id})",
                )
            if _SIZE_ORDER[mount.weapon.size] > _SIZE_ORDER[slot.size]:
                raise LoadoutError(
                    f"weapon {mount.weapon.id} too large for slot {slot.name}",
                )

    def total_cost(self) -> int:
        return sum(m.weapon.cost for m in self.weapons)
