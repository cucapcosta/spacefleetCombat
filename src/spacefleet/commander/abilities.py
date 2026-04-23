"""Commander active abilities — effect-step primitives and resolver.

Task 1 stub: only ``AbilityDef`` dataclass is defined here.  Effect steps
and ``resolve_ability`` are introduced in later tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EffectStep = Any  # refined in Task 7


@dataclass(frozen=True)
class AbilityDef:
    id: str
    name: str
    category: str
    cooldown: int
    charges: int
    preparation_turns: int = 0
    range_gu: float | None = None
    faction: str | None = None
    sprint6_dependency: bool = False
    steps: tuple[EffectStep, ...] = ()
    raw_effects: dict[str, Any] = field(default_factory=dict)
