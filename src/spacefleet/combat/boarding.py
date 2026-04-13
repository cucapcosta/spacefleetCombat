"""Boarding assault resolution — BFG2-style ranged boarding.

Two vectors:
- **Lightning Strike**: teleportarium attack, requires shields down, range ≤15 GU,
  player chooses target subsystem.
- **Boarding Torpedoes**: projectile-based, resolves on impact, random subsystem.

Both use the same D6-per-assault-action resolution table.
Boarding crits are temporary (auto-repair after 3 turns).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.combat.critical_hits import CriticalResult, apply_critical_hit, roll_critical_hit
from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship

VALID_SUBSYSTEMS = ("generator", "deck", "engines", "weapons")

LIGHTNING_STRIKE_RANGE = 15.0


@dataclass
class BoardingActionResult:
    """One assault action outcome."""

    roll: int
    outcome: str  # "repelled" | "crew_damage" | "subsystem_hit" | "both"
    subsystem_hit: str | None = None


@dataclass
class BoardingResult:
    """Full result of a boarding assault."""

    attacker_name: str
    target_name: str
    assault_actions: int
    action_results: list[BoardingActionResult] = field(default_factory=list)
    total_repelled: int = 0
    total_crew_damage: int = 0
    total_subsystem_hits: int = 0
    critical_results: list[CriticalResult] = field(default_factory=list)
    message: str = ""


def resolve_boarding(
    attacker: Ship,
    target: Ship,
    assault_actions: int,
    *,
    subsystem_choice: str | None = None,
    dice_roller: DiceRoller | None = None,
) -> BoardingResult:
    """Resolve a boarding assault.

    Each assault action rolls D6:
    - 1-2: Repelled
    - 3-4: Crew damage (morale -10)
    - 5: Subsystem hit
    - 6: Both crew damage AND subsystem hit

    *subsystem_choice*: if set, all subsystem hits target this subsystem
    (Lightning Strike). If None, random subsystem (boarding torpedoes).
    """
    dr = dice_roller or default_dice

    result = BoardingResult(
        attacker_name=attacker.name,
        target_name=target.name,
        assault_actions=assault_actions,
    )

    for _ in range(assault_actions):
        roll = dr.d6()

        if roll <= 2:
            ar = BoardingActionResult(roll=roll, outcome="repelled")
            result.total_repelled += 1
        elif roll <= 4:
            ar = BoardingActionResult(roll=roll, outcome="crew_damage")
            result.total_crew_damage += 1
        elif roll == 5:
            subsys = subsystem_choice or _random_subsystem(dr)
            ar = BoardingActionResult(
                roll=roll, outcome="subsystem_hit", subsystem_hit=subsys,
            )
            result.total_subsystem_hits += 1
        else:  # 6
            subsys = subsystem_choice or _random_subsystem(dr)
            ar = BoardingActionResult(
                roll=roll, outcome="both", subsystem_hit=subsys,
            )
            result.total_crew_damage += 1
            result.total_subsystem_hits += 1

        result.action_results.append(ar)

    # Build summary
    parts: list[str] = [f"{assault_actions} assault actions"]
    if result.total_repelled:
        parts.append(f"{result.total_repelled} repelled")
    if result.total_crew_damage:
        parts.append(f"{result.total_crew_damage} crew damage")
    if result.total_subsystem_hits:
        parts.append(f"{result.total_subsystem_hits} subsystem hit(s)")
    result.message = " — ".join(parts)

    return result


def apply_boarding_result(
    target: Ship,
    result: BoardingResult,
    *,
    dice_roller: DiceRoller | None = None,
) -> None:
    """Apply boarding results: morale damage + temporary subsystem crits."""
    dr = dice_roller or default_dice

    # Crew damage → morale penalty
    if result.total_crew_damage > 0:
        target.apply_morale_change(-10 * result.total_crew_damage)

    # Subsystem hits → temporary crits (3-turn auto-repair)
    for ar in result.action_results:
        if ar.subsystem_hit is not None:
            crit = roll_critical_hit(
                target,
                targeted_subsystem=ar.subsystem_hit,
                is_temporary=True,
                dice_roller=dr,
            )
            apply_critical_hit(target, crit)
            result.critical_results.append(crit)


def _random_subsystem(dr: DiceRoller) -> str:
    """Pick a random subsystem."""
    return VALID_SUBSYSTEMS[dr.randint(0, len(VALID_SUBSYSTEMS) - 1)]
