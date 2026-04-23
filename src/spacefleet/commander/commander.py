"""Commander entity — per-fleet owner of active abilities + passive skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spacefleet.core.types import Faction

# AbilityOrder is defined in spacefleet.net.commands (Task 9).  Until that
# module exists we use Any so mypy --strict stays clean.
AbilityOrder = Any


@dataclass
class AbilityState:
    """Per-ability runtime state — charges, cooldown, pending prep order."""

    remaining_charges: int
    cooldown_remaining: int = 0
    preparation_turns_left: int = 0
    pending_order: AbilityOrder | None = None


@dataclass
class ActiveBuff:
    """A timed effect created by a resolved ability.

    Ticked down at the top of each turn inside the command phase;
    dropped when ``turns_remaining`` hits 0.  Passive dispatcher
    consults ``data`` for per-buff parameters.
    """

    id: str
    source_ability_id: str
    turns_remaining: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Commander:
    """Per-fleet commander: level, loadout, runtime state."""

    id: str
    name: str
    faction: Faction
    level: int = 1
    xp: int = 0
    active_ability_ids: list[str] = field(default_factory=list)
    passive_skill_ids: list[str] = field(default_factory=list)
    trait_ids: list[str] = field(default_factory=list)
    ability_state: dict[str, AbilityState] = field(default_factory=dict)
    active_buffs: list[ActiveBuff] = field(default_factory=list)
