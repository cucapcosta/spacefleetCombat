"""Detached fitting candidates shared by fleet and campaign menus."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from spacefleet.data.doctrine_registry import DoctrineDef, DoctrineRegistry
from spacefleet.data.upgrade_registry import UpgradeProfile, UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import ShipSpec, validate_ship_spec

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.core.types import Faction
    from spacefleet.models.weapon import WeaponProfile


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
    kind: Literal["weapon", "upgrade", "doctrine"],
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
