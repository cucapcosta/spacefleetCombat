"""Fire control — lead solutions and gunnery spread for projectile weapons.

Battery and torpedo salvos travel for one or more half-turn steps before
they can strike, so aiming at a target's current position misses anything
that moves.  :func:`lead_solution` predicts where a target holding its
current heading and speed will be, replaying the same discrete steps the
turn resolver uses (ships drift, then projectiles advance, then collision
sweep).  Turns and speed changes ordered this turn are hidden information
and are not predicted.

:func:`bearing_spread` gives the 1-sigma bearing error applied when a
projectile is launched.  Better crews, commanders, sensors and weapons
tighten it; a weak sensor lock on the target (CONTACT, or no lock at all)
widens it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.combat.projectile_resolution import HIT_RADIUS
from spacefleet.core.types import DetectionLevel, heading_to_vector
from spacefleet.spatial.geometry import bearing_from_to, distance

if TYPE_CHECKING:
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Vector2D
    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount

# Fraction of a turn ships drift and projectiles advance per resolver step.
STEP_FRACTION = 0.5

# 1-sigma bearing error (degrees) for a green crew with baseline gear.
BASE_SPREAD_DEG = 2.5
# Spread reduction per commander level above 1, and its cap.
COMMANDER_SPREAD_PER_LEVEL = 0.03
COMMANDER_SPREAD_CAP = 0.30
# Sensor upgrades can at most shave this fraction off the spread.
SENSOR_SPREAD_CAP = 0.30
# No combination of bonuses tightens spread below this fraction of base.
MIN_SPREAD_FACTOR = 0.35
# Spread multiplier by the firing side's detection of the locked target.
# Anything weaker than CONTACT (BLIP, undetected, manual bearing) fires unlocked.
LOCK_SPREAD: dict[DetectionLevel, float] = {
    DetectionLevel.IDENTIFIED: 1.0,
    DetectionLevel.CONTACT: 1.4,
}
UNLOCKED_SPREAD = 2.0


@dataclass(frozen=True)
class LeadSolution:
    """Where to aim a projectile so it meets a target holding course."""

    bearing: float
    intercept_distance: float  # GU from the shooter to the predicted impact
    steps: int  # resolver half-turn steps until impact


def lead_solution(
    origin: Vector2D,
    target_position: Vector2D,
    target_heading: float,
    target_speed: float,
    projectile_speed: float,
    max_range: float,
) -> LeadSolution | None:
    """Return the aim point for a projectile fired from *origin*, or None.

    Step *k* moves the target to ``target + v·k`` and sweeps the projectile
    over ``[speed·(k-1), speed·k]`` along its bearing (both scaled by
    :data:`STEP_FRACTION`).  Aiming straight at the target's step-*k*
    position hits when that position lies inside the step-*k* sweep.
    Returns None when the target stays out of reach within *max_range*.
    """
    if projectile_speed <= 0:
        return None
    velocity = heading_to_vector(target_heading) * (target_speed * STEP_FRACTION)
    sweep = projectile_speed * STEP_FRACTION
    max_steps = math.ceil(max_range / sweep)
    best: tuple[float, LeadSolution] | None = None
    for step in range(1, max_steps + 1):
        predicted = target_position + velocity * step
        reach = distance(origin, predicted)
        if reach > max_range:
            continue
        near = sweep * (step - 1)
        far = min(sweep * step, max_range)
        gap = max(near - reach, reach - far, 0.0)
        if gap > HIT_RADIUS:
            continue
        solution = LeadSolution(bearing_from_to(origin, predicted), reach, step)
        if gap == 0.0:
            return solution
        if best is None or gap < best[0]:
            best = (gap, solution)
    return None if best is None else best[1]


def aim_for(
    shooter: Ship, mount: WeaponMount, target: Ship, target_position: Vector2D
) -> LeadSolution | None:
    """Aim *mount* at *target* (seen at *target_position*).

    Lances hit instantly, so they aim straight at the target.
    """
    if mount.weapon.speed <= 0:
        reach = distance(shooter.position, target_position)
        if reach > mount.weapon.range:
            return None
        return LeadSolution(bearing_from_to(shooter.position, target_position), reach, 0)
    return lead_solution(
        shooter.position,
        target_position,
        target.heading,
        target.speed,
        mount.weapon.speed,
        mount.weapon.range,
    )


def lock_level(
    state: CoreGameState,
    shooter: Ship,
    target_id: str | None,
    revealed: set[str] | frozenset[str] = frozenset(),
) -> DetectionLevel:
    """Best detection the shooter's side has on *target_id* (sensor sharing).

    *revealed* holds ships that fired last turn: their muzzle flash
    guarantees at least CONTACT, matching what the scanner showed.
    """
    from spacefleet.spatial.detection import best_detection_level

    target = state.ships.get(target_id) if target_id is not None else None
    if target is None or not target.alive or target.faction == shooter.faction:
        return DetectionLevel.UNDETECTED
    observers = [s for s in state.ships.values() if s.alive and s.faction == shooter.faction]
    boost = DetectionLevel.CONTACT if target.id in revealed else None
    return best_detection_level(observers, target, force_min_level=boost, state=state)


def bearing_spread(
    ship: Ship,
    mount: WeaponMount,
    state: CoreGameState | None = None,
    lock: DetectionLevel = DetectionLevel.IDENTIFIED,
) -> float:
    """1-sigma bearing error (degrees) for a projectile launched by *mount*."""
    from spacefleet.data.hull_registry import baseline_sensor_range
    from spacefleet.data.skill_registry import SkillRegistry
    from spacefleet.spatial.detection import effective_sensor_range

    factor = 1.0
    tier = SkillRegistry.get_crew_tier(ship.crew_tier)
    if tier is not None:
        factor *= 1.0 - tier.accuracy_bonus
    factor *= 1.0 - mount.weapon.fire_control
    baseline = baseline_sensor_range(ship.hull.classification)
    sensors = effective_sensor_range(ship, state)
    if sensors > baseline > 0:
        bonus = (sensors - baseline) / baseline
        factor *= 1.0 - min(SENSOR_SPREAD_CAP, bonus)
    fleet = state.fleet_of(ship) if state is not None else None
    commander = fleet.commander if fleet is not None else None
    if commander is not None:
        bonus = COMMANDER_SPREAD_PER_LEVEL * max(0, commander.level - 1)
        factor *= 1.0 - min(COMMANDER_SPREAD_CAP, bonus)
    lock_factor = LOCK_SPREAD.get(lock, UNLOCKED_SPREAD)
    return BASE_SPREAD_DEG * max(MIN_SPREAD_FACTOR, factor) * lock_factor


def hit_probability(spread_deg: float, intercept_distance: float) -> float:
    """Chance that a spread-perturbed shot still passes within HIT_RADIUS."""
    if intercept_distance <= HIT_RADIUS or spread_deg <= 0:
        return 1.0
    tolerance = math.degrees(math.atan(HIT_RADIUS / intercept_distance))
    return math.erf(tolerance / (spread_deg * math.sqrt(2.0)))
