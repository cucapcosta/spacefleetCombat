"""Upgrade effects — build-time stat mods, runtime PassiveBus handlers,
and build-time validation. Interprets *effect keys* from the upgrade
catalog (data-driven): new upgrades reusing existing keys need only yaml."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from spacefleet.commander.passive_skills import PassiveContext, PassiveHook
from spacefleet.core.types import ShipClass
from spacefleet.data.upgrade_registry import UpgradeProfile, UpgradeRegistry
from spacefleet.models.loadout import LoadoutError
from spacefleet.models.ship import Ship

if TYPE_CHECKING:
    from spacefleet.commander.passive_skills import PassiveBus
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Vector2D
    from spacefleet.models.ship_profile import HullProfile
    from spacefleet.models.weapon import WeaponMount


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


def apply_upgrades_to_hull(hull: HullProfile, upgrade_ids: list[str]) -> HullProfile:
    """Hull copy with all upgrade stat deltas applied (clamped sane)."""
    if not upgrade_ids:
        return hull
    return dataclasses.replace(
        hull,
        shields=max(0, hull.shields + int(upgrade_effect_total(upgrade_ids, "shields"))),
        armor_prow=max(0, hull.armor_prow + int(upgrade_effect_total(upgrade_ids, "armor_prow"))),
        turrets=max(0, hull.turrets + int(upgrade_effect_total(upgrade_ids, "turrets"))),
        speed=max(0.0, hull.speed + upgrade_effect_total(upgrade_ids, "speed")),
        turn_rate=max(0.0, hull.turn_rate + upgrade_effect_total(upgrade_ids, "turn_rate")),
        sensor_range=max(
            0.0, hull.sensor_range + upgrade_effect_total(upgrade_ids, "sensor_range")
        ),
        base_morale=max(1, hull.base_morale + int(upgrade_effect_total(upgrade_ids, "morale_max"))),
    )


def build_ship_with_upgrades(
    ship_id: str,
    name: str,
    hull: HullProfile,
    weapons: list[WeaponMount],
    *,
    upgrade_ids: list[str],
    doctrine_id: str | None = None,
    position: Vector2D | None = None,
    heading: float = 0.0,
) -> Ship:
    """Construct a Ship applying doctrine then upgrade effects.

    Doctrine hull mods apply first (same order the fleet builder will use),
    then upgrade hull mods, then upgrade-derived mutable state.
    """
    from spacefleet.commander.doctrine_effects import apply_doctrine_to_hull
    from spacefleet.data.doctrine_registry import DoctrineRegistry
    from spacefleet.data.skill_registry import SkillRegistry

    doctrine = DoctrineRegistry.get_or_none(doctrine_id)
    final_hull = apply_doctrine_to_hull(hull, doctrine) if doctrine is not None else hull
    final_hull = apply_upgrades_to_hull(final_hull, upgrade_ids)
    ship = Ship.from_profile(
        ship_id,
        name,
        final_hull,
        weapons,
        position=position,
        heading=heading,
        doctrine_id=doctrine_id,
        morale_floor=doctrine.morale_floor if doctrine is not None else 0,
        upgrade_ids=upgrade_ids,
    )

    combustion_bonus = int(upgrade_effect_total(upgrade_ids, "combustion_max"))
    ship.combustion_max += combustion_bonus
    ship.combustion += combustion_bonus
    ship.combustion_regen_bonus = int(upgrade_effect_total(upgrade_ids, "combustion_regen"))
    ship.stance_cooldown_reduction = int(
        upgrade_effect_total(upgrade_ids, "stance_cooldown_reduction")
    )

    tiers = [
        int(p.effect["starting_crew_tier"])
        for p in _profiles(upgrade_ids)
        if "starting_crew_tier" in p.effect
    ]
    if tiers:
        tier_def = SkillRegistry.get_crew_tier(max(tiers))
        if tier_def is not None:
            ship.battles_survived = max(ship.battles_survived, tier_def.battles_required)

    return ship


def register_upgrade_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Per-ship PassiveBus handlers keyed on ``ship.upgrade_ids``."""
    for ship in state.ships.values():
        if not ship.upgrade_ids:
            continue
        sid = ship.id

        battery = int(upgrade_effect_total(ship.upgrade_ids, "battery_strength"))
        if battery:

            def _battery(ctx: PassiveContext, s: str = sid, v: int = battery) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:upgrade_battery",
                hook=PassiveHook.BATTERY_FIREPOWER_BONUS,
                handler=_battery,
            )

        regen = int(upgrade_effect_total(ship.upgrade_ids, "shield_regen"))
        if regen:

            def _regen(ctx: PassiveContext, s: str = sid, v: int = regen) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:upgrade_shield_regen",
                hook=PassiveHook.END_OF_TURN_SHIELD_REGEN,
                handler=_regen,
            )

        reload_red = int(upgrade_effect_total(ship.upgrade_ids, "torpedo_reload_reduction"))
        if reload_red:

            def _reload(ctx: PassiveContext, s: str = sid, v: int = reload_red) -> Any:
                return ctx.value - v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            # Inert until Sprint-6 torpedoes exist — registration proves loadability.
            bus.register(
                source=f"{sid}:upgrade_reload",
                hook=PassiveHook.TORPEDO_RELOAD_REDUCTION,
                handler=_reload,
            )
