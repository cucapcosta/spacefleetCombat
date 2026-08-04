"""Upgrade effects — build-time stat mods, runtime PassiveBus handlers,
and build-time validation. Interprets *effect keys* from the upgrade
catalog (data-driven): new upgrades reusing existing keys need only yaml."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.core.types import ShipClass
from spacefleet.data.upgrade_registry import UpgradeProfile, UpgradeRegistry
from spacefleet.models.loadout import LoadoutError

if TYPE_CHECKING:
    from spacefleet.models.ship_profile import HullProfile


UPGRADE_SLOT_CAPS: dict[ShipClass, int] = {
    ShipClass.ESCORT: 1,
    ShipClass.LIGHT_CRUISER: 2,
    ShipClass.CRUISER: 3,
    ShipClass.BATTLECRUISER: 3,
    ShipClass.BATTLESHIP: 4,
}


def _profiles(upgrade_ids: list[str]) -> list[UpgradeProfile]:
    """Resolve ids to profiles, silently skipping unknown ids
    (validation reports them; runtime helpers stay total)."""
    found = (UpgradeRegistry.get_or_none(uid) for uid in upgrade_ids)
    return [p for p in found if p is not None]


def upgrade_effect_total(upgrade_ids: list[str], key: str) -> float:
    """Sum of a numeric effect *key* across the ship's upgrades."""
    total = 0.0
    for prof in _profiles(upgrade_ids):
        value = prof.effect.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += value
    return total


def upgrade_has_effect(upgrade_ids: list[str], key: str) -> bool:
    """True if any of the ship's upgrades declares a truthy *key*."""
    return any(prof.effect.get(key) for prof in _profiles(upgrade_ids))


def upgrade_slots_for(hull: HullProfile, doctrine_id: str | None = None) -> int:
    """Upgrade slot cap for *hull*, plus any doctrine bonus (Mechanicus Rites)."""
    from spacefleet.data.doctrine_registry import DoctrineRegistry

    slots = UPGRADE_SLOT_CAPS.get(hull.classification, 1)
    doctrine = DoctrineRegistry.get_or_none(doctrine_id)
    if doctrine is not None:
        slots += doctrine.upgrade_slot_bonus
    return slots


def validate_upgrades(
    hull: HullProfile,
    upgrade_ids: list[str],
    *,
    doctrine_id: str | None = None,
    is_flagship: bool = False,
) -> None:
    """Raise :class:`LoadoutError` if *upgrade_ids* are illegal for *hull*."""
    for uid in upgrade_ids:
        if UpgradeRegistry.get_or_none(uid) is None:
            raise LoadoutError(f"unknown upgrade id {uid!r}")
    if len(set(upgrade_ids)) != len(upgrade_ids):
        raise LoadoutError(f"duplicate upgrade ids in {upgrade_ids}")
    slots = upgrade_slots_for(hull, doctrine_id)
    if len(upgrade_ids) > slots:
        raise LoadoutError(
            f"{len(upgrade_ids)} upgrades exceed {slots} slots for {hull.classification.value}"
        )
    if not is_flagship:
        for prof in _profiles(upgrade_ids):
            if prof.flagship_only:
                raise LoadoutError(f"upgrade {prof.id!r} is flagship-only")
