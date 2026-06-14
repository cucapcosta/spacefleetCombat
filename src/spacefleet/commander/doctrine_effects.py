"""Doctrine effects — build-time stat mods, runtime PassiveBus handlers,
and build-time validation helpers."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from spacefleet.commander.passive_skills import PassiveContext, PassiveHook
from spacefleet.core.events import TurnEvent
from spacefleet.core.types import WeaponType
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.models.ship import Ship

if TYPE_CHECKING:
    from spacefleet.commander.passive_skills import PassiveBus
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Vector2D
    from spacefleet.data.doctrine_registry import DoctrineDef
    from spacefleet.models.ship_profile import HullProfile
    from spacefleet.models.weapon import WeaponMount, WeaponProfile


@dataclasses.dataclass
class BoardingRepelledByDoctrineEvent(TurnEvent):
    attacker_id: str
    target_id: str


def apply_doctrine_to_hull(hull: HullProfile, doctrine: DoctrineDef) -> HullProfile:
    """Hull copy with the doctrine's stat deltas applied; clamp hull_hits>=1,
    shields>=0, speed>=0.0."""
    return dataclasses.replace(
        hull,
        hull_hits=max(1, hull.hull_hits + doctrine.hull_delta),
        speed=max(0.0, hull.speed + doctrine.speed_delta),
        shields=max(0, hull.shields + doctrine.shield_delta),
    )


def build_ship_with_doctrine(
    ship_id: str,
    name: str,
    hull: HullProfile,
    weapons: list[WeaponMount],
    *,
    doctrine_id: str | None,
    position: Vector2D | None = None,
    heading: float = 0.0,
) -> Ship:
    """Construct a Ship applying its doctrine (stat-modded hull + doctrine_id +
    morale_floor). ``doctrine_id=None`` builds a plain ship."""
    doctrine = DoctrineRegistry.get_or_none(doctrine_id)
    final_hull = apply_doctrine_to_hull(hull, doctrine) if doctrine is not None else hull
    floor = doctrine.morale_floor if doctrine is not None else 0
    return Ship.from_profile(
        ship_id,
        name,
        final_hull,
        weapons,
        position=position,
        heading=heading,
        doctrine_id=doctrine_id,
        morale_floor=floor,
    )


def doctrine_allows_weapon(doctrine: DoctrineDef, weapon: WeaponProfile) -> bool:
    """False when the doctrine bans this weapon (Khorne bans lances)."""
    return not (not doctrine.lances_allowed and weapon.weapon_type == WeaponType.LANCE)


def register_doctrine_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Per-ship PassiveBus handlers keyed on ``ship.doctrine_id``."""
    for ship in state.ships.values():
        doctrine = DoctrineRegistry.get_or_none(ship.doctrine_id)
        if doctrine is None:
            continue
        doc = doctrine  # bind narrowed (mypy: avoid Optional default-arg attr access)
        sid = ship.id

        if doc.column_shift:
            cs = doc.column_shift

            def _col(ctx: PassiveContext, s: str = sid, v: int = cs) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:doctrine_column",
                hook=PassiveHook.HIT_COLUMN_SHIFT,
                handler=_col,
            )

        if doc.lance_threshold is not None:
            lt = doc.lance_threshold  # bind narrowed int (mypy: avoid int|None default)

            def _lance(ctx: PassiveContext, s: str = sid, t: int = lt) -> Any:
                return t if ctx.ship is not None and ctx.ship.id == s else None

            bus.register(
                source=f"{sid}:doctrine_lance",
                hook=PassiveHook.LANCE_HIT_THRESHOLD,
                handler=_lance,
            )

        if doc.assault_bonus:
            ab = doc.assault_bonus

            def _assault(ctx: PassiveContext, s: str = sid, v: int = ab) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:doctrine_assault",
                hook=PassiveHook.ASSAULT_ACTION_BONUS,
                handler=_assault,
            )

        if doc.morale_floor > 0:

            def _nomutiny(ctx: PassiveContext, s: str = sid) -> Any:
                return True if ctx.ship is not None and ctx.ship.id == s else None

            bus.register(
                source=f"{sid}:doctrine_nomutiny",
                hook=PassiveHook.ANTI_MUTINY_CHECK,
                handler=_nomutiny,
            )
