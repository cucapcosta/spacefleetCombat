"""Shield → armor → hull damage pipeline.

Owns the per-hit ``HitDetail`` record and the aggregate
``DamageReport`` returned by :func:`apply_damage_pipeline`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class HitDetail:
    """One individual hit going through the armor-save step."""

    blocked_by_shield: bool = False
    armor_roll: int = 0
    armor_value: int = 0
    penetrated: bool = False
    hull_damage: int = 0


@dataclass
class DamageReport:
    """Aggregate counts + per-hit details for one damage application."""

    shield_blocked: int = 0
    armor_saves: int = 0
    penetrating: int = 0
    hull_damage: int = 0
    details: list[HitDetail] = field(default_factory=list)


def apply_damage_pipeline(
    *,
    target: Ship,
    hits: int,
    relative_bearing: float,
    damage_per_hit: int,
    ignores_armor: bool = False,
    dice_roller: DiceRoller | None = None,
) -> DamageReport:
    """Drive the shield → armor → hull calculation for *hits* potential hits.

    Mutates *target* by consuming shields (``absorb_shields``).  Hull
    damage is **not** applied here — the returned :class:`DamageReport`
    is a proposal that callers may adjust (e.g. for Brace stance saves)
    before calling ``target.take_hull_damage(report.hull_damage)``
    themselves.  Morale changes are also applied separately by the
    caller.
    """
    dr = dice_roller or default_dice
    report = DamageReport()
    if hits <= 0:
        return report

    after_shields = target.absorb_shields(hits)
    report.shield_blocked = hits - after_shields

    for _ in range(report.shield_blocked):
        report.details.append(HitDetail(blocked_by_shield=True))

    if after_shields == 0:
        return report

    if ignores_armor:
        report.penetrating = after_shields
        report.hull_damage = after_shields * damage_per_hit
        for _ in range(after_shields):
            report.details.append(
                HitDetail(penetrated=True, hull_damage=damage_per_hit),
            )
        return report

    armor = target.armor_for_bearing(relative_bearing)
    for _ in range(after_shields):
        roll = dr.d6()
        detail = HitDetail(armor_roll=roll, armor_value=armor)
        if roll >= armor:
            detail.penetrated = True
            detail.hull_damage = damage_per_hit
            report.penetrating += 1
            report.hull_damage += damage_per_hit
        else:
            report.armor_saves += 1
        report.details.append(detail)

    return report
