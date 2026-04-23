"""Commander active abilities — declarative effect-step primitives.

Each ``AbilityDef`` carries a tuple of effect steps (tagged union).
``resolve_ability`` (Task 18) walks the steps in order, dispatching
each through a handler registry.  Events produced by the resolver are
returned to the caller (``resolve_command_phase``) for logging /
publication on the ``EventBus``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Effect steps ──────────────────────────────────────────


@dataclass(frozen=True)
class HullRepair:
    amount_dice: str  # "D3" | "D6"


@dataclass(frozen=True)
class ExtinguishFires:
    pass


@dataclass(frozen=True)
class RepairTempCritical:
    count: int


@dataclass(frozen=True)
class AreaMoraleRestore:
    range_gu: float
    amount: int
    cancel_mutiny: bool


@dataclass(frozen=True)
class AreaHullDamage:
    range_gu: float
    amount_dice: str
    affects_allies: bool


@dataclass(frozen=True)
class AreaMoraleDamage:
    range_gu: float
    amount: int
    affects_allies: bool


@dataclass(frozen=True)
class SpawnProbe:
    radius: float
    duration: int
    detection_level: int


@dataclass(frozen=True)
class ConcentratedFireBuff:
    range_gu: float
    column_shift: int
    duration: int


@dataclass(frozen=True)
class TimedFleetBuff:
    buff_id: str
    duration: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BonusTorpedoSalvo:
    range_gu: float


@dataclass(frozen=True)
class Teleport:
    pass


@dataclass(frozen=True)
class BonusBoardingAssault:
    actions: int
    extended_range_gu: float


EffectStep = (
    HullRepair
    | ExtinguishFires
    | RepairTempCritical
    | AreaMoraleRestore
    | AreaHullDamage
    | AreaMoraleDamage
    | SpawnProbe
    | ConcentratedFireBuff
    | TimedFleetBuff
    | BonusTorpedoSalvo
    | Teleport
    | BonusBoardingAssault
)


# ── AbilityDef ────────────────────────────────────────────


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
