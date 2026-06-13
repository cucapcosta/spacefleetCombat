"""Commander XP/level math + ship crew veterancy tracking.

Pure functions.  Events are returned as a list; callers (turn_resolver)
publish them on ``state.events``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.core.events import TurnEvent
from spacefleet.data.skill_registry import SkillRegistry

if TYPE_CHECKING:
    from spacefleet.commander.commander import Commander
    from spacefleet.models.ship import Ship


MAX_LEVEL = 10
MAX_CREW_TIER = 4


@dataclass
class XpGainedEvent(TurnEvent):
    commander_id: str
    amount: int
    total_xp: int


@dataclass
class LevelUpEvent(TurnEvent):
    commander_id: str
    new_level: int
    unlocks: tuple[str, ...]
    title: str


@dataclass
class CrewTierUpEvent(TurnEvent):
    ship_id: str
    old_tier: int
    new_tier: int


def apply_xp(commander: Commander, amount: int) -> list[TurnEvent]:
    """Add *amount* xp to *commander*, level up as many times as xp allows."""
    events: list[TurnEvent] = []
    if amount <= 0:
        return events
    commander.xp += amount
    events.append(
        XpGainedEvent(
            commander_id=commander.id,
            amount=amount,
            total_xp=commander.xp,
        )
    )
    while commander.level < MAX_LEVEL:
        nxt = SkillRegistry.get_level(commander.level + 1)
        if nxt is None or commander.xp < nxt.xp_required:
            break
        commander.level += 1
        events.append(
            LevelUpEvent(
                commander_id=commander.id,
                new_level=commander.level,
                unlocks=tuple(nxt.unlocks),
                title=nxt.title,
            )
        )
    return events


def crew_tier_for(battles_survived: int) -> int:
    """Return highest tier whose ``battles_required <= battles_survived``."""
    tiers = SkillRegistry.all_crew_tiers()
    best = 0
    for t in tiers:
        if battles_survived >= t.battles_required:
            best = t.tier
    return min(best, MAX_CREW_TIER)


def bump_crew_veterancy(ship: Ship) -> list[TurnEvent]:
    """+1 battles_survived.  Emit ``CrewTierUpEvent`` if tier advanced."""
    events: list[TurnEvent] = []
    old_tier = ship.crew_tier
    ship.battles_survived += 1
    new_tier = ship.crew_tier
    if new_tier != old_tier:
        events.append(
            CrewTierUpEvent(
                ship_id=ship.id,
                old_tier=old_tier,
                new_tier=new_tier,
            )
        )
    return events


def compute_battle_xp_for_fleet(
    fleet_kill_capitals: int,
    fleet_kill_escorts: int,
    won: bool,
    survived: bool,
    first_blood: bool,
) -> int:
    """Pure computation: XP a single fleet earns from a finished battle."""
    xp = 0
    if won:
        xp += SkillRegistry.xp_source("battle_victory")
    elif survived:
        xp += SkillRegistry.xp_source("battle_defeat_survived")
    xp += fleet_kill_capitals * SkillRegistry.xp_source("enemy_capital_destroyed")
    xp += fleet_kill_escorts * SkillRegistry.xp_source("enemy_escort_destroyed")
    if first_blood:
        xp += SkillRegistry.xp_source("first_blood")
    return xp
