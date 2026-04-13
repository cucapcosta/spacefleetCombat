"""Shooting phase orchestrator.

Iterates fire orders, dispatches each through ``combat.resolution``,
and returns the full list of :class:`AttackResult` records for the
renderer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.combat.resolution import AttackResult, resolve_attack
from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class FireOrder:
    """One weapon firing order."""

    slot_id: int
    target_id: str


def resolve_shooting_phase(
    *,
    ships: list[Ship],
    orders: dict[str, list[FireOrder]],
    dice_roller: DiceRoller | None = None,
) -> list[AttackResult]:
    """Resolve every fire order in deterministic order.

    Returns the list of :class:`AttackResult` records (skipping orders
    referencing a dead attacker or missing target).
    """
    dr = dice_roller or default_dice
    by_id = {s.id: s for s in ships}
    results: list[AttackResult] = []

    for ship_id in sorted(orders):
        ship = by_id.get(ship_id)
        if ship is None or not ship.alive:
            continue
        for order in orders[ship_id]:
            target = by_id.get(order.target_id)
            if target is None or not target.alive:
                continue
            weapon = next(
                (w for w in ship.weapons if w.slot_id == order.slot_id),
                None,
            )
            if weapon is None:
                continue
            results.append(
                resolve_attack(ship, weapon, target, dice_roller=dr),
            )

    return results
