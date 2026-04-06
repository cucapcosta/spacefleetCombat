"""Turn orchestration helpers.

Pure game-state functions with no I/O.  The CLI layer calls these
to advance the game; in the full implementation this becomes the
proper GameState-based turn pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.combat.projectile_resolution import (
    HIT_RADIUS,
    resolve_projectile_impact,
)
from spacefleet.spatial.geometry import distance, point_to_segment_distance

if TYPE_CHECKING:
    from spacefleet.combat.resolution import AttackResult
    from spacefleet.core.types import Vector2D
    from spacefleet.dice import DiceRoller
    from spacefleet.models.projectile import Projectile
    from spacefleet.models.ship import Ship


def drift_ships(ships: list[Ship], fraction: float = 0.5) -> None:
    """Move every alive ship along its heading for *fraction* of a turn.

    At ``fraction = 0.5`` each ship moves ``speed × 0.5`` GU —
    the standard half-turn drift between actions.
    """
    for ship in ships:
        if ship.alive:
            ship.apply_drift(fraction)


def move_projectiles(
    projectiles: list[Projectile],
    fraction: float = 0.5,
) -> list[tuple[Projectile, Vector2D, Vector2D]]:
    """Advance all alive projectiles by ``speed × fraction`` GU.

    Returns a list of ``(projectile, old_pos, new_pos)`` for collision
    checking.  Expired projectiles are marked ``alive = False``.
    """
    movements: list[tuple[Projectile, Vector2D, Vector2D]] = []
    for proj in projectiles:
        if not proj.alive:
            continue
        old_pos, new_pos = proj.advance(fraction)
        movements.append((proj, old_pos, new_pos))
    return movements


def check_projectile_collisions(
    movements: list[tuple[Projectile, Vector2D, Vector2D]],
    ships: list[Ship],
    dice_roller: DiceRoller,
) -> list[tuple[Projectile, Ship, AttackResult]]:
    """Check for projectile-ship collisions using line-segment sweep.

    For each alive projectile that moved from *old_pos* to *new_pos*,
    checks if any alive enemy ship's centre is within ``HIT_RADIUS``
    of the movement segment.  On collision, resolves the impact.

    Returns a list of ``(projectile, target, AttackResult)`` for display.
    """
    impacts: list[tuple[Projectile, Ship, AttackResult]] = []

    for proj, old_pos, new_pos in movements:
        if not proj.alive:
            continue

        # Find nearest enemy ship on this segment
        best_ship: Ship | None = None
        best_dist = float("inf")

        for ship in ships:
            if not ship.alive:
                continue
            # Skip friendly ships
            if ship.faction == proj.attacker_faction:
                continue

            seg_dist, _closest = point_to_segment_distance(
                ship.position,
                old_pos,
                new_pos,
            )
            if seg_dist <= HIT_RADIUS:
                d = distance(old_pos, ship.position)
                if d < best_dist:
                    best_dist = d
                    best_ship = ship

        if best_ship is not None:
            result = resolve_projectile_impact(
                proj,
                best_ship,
                dice_roller=dice_roller,
            )
            proj.alive = False
            impacts.append((proj, best_ship, result))

    return impacts


def cleanup_projectiles(projectiles: list[Projectile]) -> list[Projectile]:
    """Remove dead (expired or detonated) projectiles.

    Returns a list of expired projectiles (for display), and mutates
    the input list in-place to keep only alive ones.
    """
    expired = [p for p in projectiles if not p.alive]
    projectiles[:] = [p for p in projectiles if p.alive]
    return expired


def apply_end_of_turn(ship: Ship) -> tuple[int, int]:
    """Run end-of-turn effects on *ship*.

    Returns ``(shields_regenerated, fire_damage_taken)``.
    """
    shields = ship.regenerate_shields()
    fire_dmg = ship.apply_fire_damage()
    return shields, fire_dmg
