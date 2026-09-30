"""Detached fitting candidates and ship slot helpers for the hangar and fleet builder.

Pure presentation-free logic: which slots a ship has, which items can go in
each, and the detached replacement :class:`ShipSpec` each choice produces.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from spacefleet.commander.upgrade_effects import upgrade_slots_for
from spacefleet.data.doctrine_registry import DoctrineDef, DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeProfile, UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import ShipSpec, validate_ship_spec

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.core.types import Faction
    from spacefleet.models.weapon import WeaponProfile


SlotKind = Literal["weapon", "upgrade", "doctrine"]


@dataclass(frozen=True, slots=True)
class FittingChoice:
    """One legal fitting candidate and its player-facing presentation."""

    value: str
    label: str
    details: str
    replacement: ShipSpec


def fitting_choices(
    spec: ShipSpec,
    faction: Faction,
    *,
    kind: SlotKind,
    slot_id: int | None,
    is_flagship: bool,
    candidate_validator: Callable[[ShipSpec], None] | None = None,
) -> list[FittingChoice]:
    """Return detached candidates accepted by the authoritative validators."""
    choices: list[FittingChoice] = []
    if kind == "weapon":
        if slot_id is None:
            raise ValueError("weapon choices require a slot id")
        candidates = (
            (profile.id, profile.name, _weapon_details(profile))
            for profile in WeaponRegistry.all().values()
        )
    elif kind == "upgrade":
        if slot_id is not None and not 0 <= slot_id < len(spec.upgrade_ids):
            raise ValueError("upgrade position is out of range")
        candidates = (
            (profile.id, profile.name, _upgrade_details(profile))
            for profile in UpgradeRegistry.all().values()
        )
    else:
        if slot_id is not None:
            raise ValueError("doctrine choices do not use a slot id")
        candidates = (
            (profile.id, profile.name, _doctrine_details(profile))
            for profile in DoctrineRegistry.for_faction(faction)
        )

    for value, label, details in candidates:
        replacement = deepcopy(spec)
        if kind == "weapon":
            assert slot_id is not None
            replacement.weapons[slot_id] = value
        elif kind == "upgrade":
            if slot_id is None:
                replacement.upgrade_ids.append(value)
            else:
                replacement.upgrade_ids[slot_id] = value
        else:
            replacement.doctrine_id = value
        try:
            validate_ship_spec(replacement, faction, is_flagship=is_flagship)
            if candidate_validator is not None:
                candidate_validator(replacement)
        except (KeyError, ValueError):
            continue
        choices.append(FittingChoice(value, label, details, replacement))
    return choices


@dataclass(frozen=True, slots=True)
class Slot:
    """One configurable position on a ship.

    ``slot_id`` is what :func:`fitting_choices` expects: the hull weapon slot
    id, the upgrade index for a filled upgrade position (``None`` for an empty
    one) and always ``None`` for the doctrine.  ``position`` is the 0-based
    upgrade position (``None`` for weapons and doctrine).
    """

    kind: SlotKind
    slot_id: int | None
    label: str
    current: str
    position: int | None = None


def ship_slots(spec: ShipSpec) -> list[Slot]:
    """Weapon slots (with arc and size), upgrade positions, then the doctrine."""
    hull = HullRegistry.get(spec.hull_id)
    slots: list[Slot] = []
    for number, weapon_slot in enumerate(hull.weapon_slots, start=1):
        weapon_id = spec.weapons.get(weapon_slot.id)
        current = "Empty" if weapon_id is None else _weapon_name(weapon_id)
        slots.append(
            Slot(
                "weapon",
                weapon_slot.id,
                f"W{number} {weapon_slot.name} · {weapon_slot.arc.value} · "
                f"{weapon_slot.size.value}",
                current,
            )
        )
    for position in range(upgrade_slots_for(hull, spec.doctrine_id)):
        if position < len(spec.upgrade_ids):
            slot_id: int | None = position
            current = _upgrade_name(spec.upgrade_ids[position])
        else:
            slot_id, current = None, "Empty"
        slots.append(Slot("upgrade", slot_id, f"U{position + 1} Upgrade", current, position))
    doctrine = DoctrineRegistry.get_or_none(spec.doctrine_id)
    slots.append(Slot("doctrine", None, "Doctrine", doctrine.name if doctrine else "None"))
    return slots


def removal_choice(spec: ShipSpec, slot: Slot) -> FittingChoice | None:
    """The "Remove" choice for a filled *slot*, or ``None`` when it is empty."""
    replacement = deepcopy(spec)
    if slot.kind == "weapon":
        if slot.slot_id is None or slot.slot_id not in replacement.weapons:
            return None
        replacement.weapons.pop(slot.slot_id)
    elif slot.kind == "upgrade":
        if slot.slot_id is None or not 0 <= slot.slot_id < len(replacement.upgrade_ids):
            return None
        replacement.upgrade_ids.pop(slot.slot_id)
    else:
        if replacement.doctrine_id is None:
            return None
        replacement.doctrine_id = None
    return FittingChoice("remove", "Remove", "", replacement)


def slot_choices(
    spec: ShipSpec,
    faction: Faction,
    slot: Slot,
    *,
    is_flagship: bool,
    candidate_validator: Callable[[ShipSpec], None] | None = None,
) -> list[FittingChoice]:
    """Removal (when the slot is filled) followed by every legal fitting."""
    choices: list[FittingChoice] = []
    removal = removal_choice(spec, slot)
    if removal is not None:
        choices.append(removal)
    choices.extend(
        fitting_choices(
            spec,
            faction,
            kind=slot.kind,
            slot_id=slot.slot_id,
            is_flagship=is_flagship,
            candidate_validator=candidate_validator,
        )
    )
    return choices


def _weapon_name(weapon_id: str) -> str:
    weapon = WeaponRegistry.get_or_none(weapon_id)
    return weapon.name if weapon is not None else weapon_id


def _upgrade_name(upgrade_id: str) -> str:
    upgrade = UpgradeRegistry.get_or_none(upgrade_id)
    return upgrade.name if upgrade is not None else upgrade_id


def _weapon_details(weapon: WeaponProfile) -> str:
    return (
        f"{weapon.cost} pts | {weapon.weapon_type.value} | {weapon.size.value} | "
        f"strength {weapon.strength} | range {weapon.range:g}\n{weapon.description}"
    )


def _upgrade_details(upgrade: UpgradeProfile) -> str:
    restriction = " | flagship only" if upgrade.flagship_only else ""
    effects = ", ".join(f"{key}: {value}" for key, value in upgrade.effect.items()) or "none"
    return (
        f"{upgrade.cost} pts | {upgrade.category}{restriction} | effects: {effects}\n"
        f"{upgrade.description}"
    )


def _doctrine_details(doctrine: DoctrineDef) -> str:
    return f"{doctrine.cost} pts\n{doctrine.description}"
