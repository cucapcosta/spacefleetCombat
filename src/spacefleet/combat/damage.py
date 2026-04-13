"""Shield → armor → hull damage pipeline.

Pure helper extracted from ``combat/resolution.py``.  Operates on the
target ship in place and returns a structured report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class DamageReport:
    """Aggregate counts produced by one damage application."""

    shield_blocked: int = 0
    armor_saves: int = 0
    penetrating: int = 0
    hull_damage: int = 0


def apply_damage_pipeline(
    *,
    target: Ship,
    hits: int,
    relative_bearing: float,
    damage_per_hit: int,
    ignores_armor: bool = False,
    dice_roller: DiceRoller | None = None,
) -> DamageReport:
    """Drive the shield → armor → hull chain for *hits* potential hits.

    Returns a :class:`DamageReport` and mutates *target* (shield + hull).
    Morale changes are applied separately by the caller.
    """
    dr = dice_roller or default_dice
    report = DamageReport()
    if hits <= 0:
        return report

    after_shields = target.absorb_shields(hits)
    report.shield_blocked = hits - after_shields

    if after_shields == 0:
        return report

    if ignores_armor:
        report.penetrating = after_shields
        report.hull_damage = after_shields * damage_per_hit
        if report.hull_damage > 0:
            target.take_hull_damage(report.hull_damage)
        return report

    armor = target.armor_for_bearing(relative_bearing)
    for _ in range(after_shields):
        roll = dr.d6()
        if roll >= armor:
            report.penetrating += 1
            report.hull_damage += damage_per_hit
        else:
            report.armor_saves += 1

    if report.hull_damage > 0:
        target.take_hull_damage(report.hull_damage)

    return report
