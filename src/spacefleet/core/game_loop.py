"""Turn orchestration helpers.

Pure game-state functions with no I/O.  The CLI layer calls these
to advance the game; in the full implementation this becomes the
proper GameState-based turn pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.combat.projectile_resolution import (
    HIT_RADIUS,
    resolve_projectile_impact,
)
from spacefleet.core.types import heading_to_vector, normalize_angle

if TYPE_CHECKING:
    from spacefleet.combat.resolution import AttackResult
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Vector2D
    from spacefleet.dice import DiceRoller
    from spacefleet.models.projectile import Projectile
    from spacefleet.models.ship import Ship


SUBSTEPS = 4
"""Straight sub-steps per movement half (approximates a turning ship's arc)."""


@dataclass
class ProjectileImpact:
    """A salvo hitting a ship during a movement half."""

    projectile: Projectile
    target: Ship
    result: AttackResult
    time: float  # fraction of the whole turn (0..1)
    position: Vector2D  # target position at impact


@dataclass
class _Contact:
    time: float
    projectile: Projectile
    target: Ship
    proj_position: Vector2D
    proj_traveled: float
    ship_position: Vector2D
    ship_heading: float


def advance_half(
    ships: list[Ship],
    projectiles: list[Projectile],
    dice_roller: DiceRoller,
    state: CoreGameState | None = None,
    *,
    start: float = 0.0,
    fraction: float = 0.5,
    substeps: int = SUBSTEPS,
) -> list[ProjectileImpact]:
    """Move ships and salvos together for one movement half, resolving hits.

    The half runs from turn time *start* for *fraction* of the turn.  Each
    alive ship executes its share of ``pending_turn`` (all of what is left
    when the half ends the turn).  Ships and salvos advance
    simultaneously in *substeps* straight sub-steps; within each, the
    salvo–ship relative position is linear, so the first contact at
    ``HIT_RADIUS`` is solved exactly.  A salvo only hits while it is within
    ``max_range`` of travel and the target within ``max_range`` of the
    salvo's origin.

    Contacts are resolved in time order (tie: salvo id): a salvo hits at
    most once, and a ship destroyed earlier ignores later contacts.
    Returns the impacts with ``time`` as a fraction of the whole turn.
    """
    movers = [s for s in ships if s.alive]
    remaining = 1.0 - start
    turn_per_step = {s.id: s.pending_turn * fraction / remaining / substeps for s in movers}
    dt = fraction / substeps
    contacts: list[_Contact] = []

    for k in range(substeps):
        ship_start = {s.id: (s.position, s.heading) for s in movers}
        for s in movers:
            s.drift(dt, turn_per_step[s.id])
        flying = [(p, p.position, p.distance_traveled) for p in projectiles if p.alive]
        for p, _p0, _d0 in flying:
            p.advance(dt)

        for p, p0, d0 in flying:
            if d0 >= p.max_range:
                continue
            step = p.speed * dt
            vp = heading_to_vector(p.bearing) * step
            for s in movers:
                if s.faction == p.attacker_faction:
                    continue
                s0, h0 = ship_start[s.id]
                vs = s.position - s0
                u = _first_contact(p0 - s0, vp - vs, s0 - p.origin, vs, p.max_range)
                if u is None or d0 + step * u > p.max_range + 1e-9:
                    continue
                contacts.append(
                    _Contact(
                        time=start + (k + u) * dt,
                        projectile=p,
                        target=s,
                        proj_position=p0 + vp * u,
                        proj_traveled=min(p.max_range, d0 + step * u),
                        ship_position=s0 + vs * u,
                        ship_heading=normalize_angle(h0 + turn_per_step[s.id] * u),
                    )
                )

    impacts: list[ProjectileImpact] = []
    for c in sorted(contacts, key=lambda c: (c.time, c.projectile.id, c.target.id)):
        proj, target = c.projectile, c.target
        if not proj.alive or not target.alive:
            continue
        proj.position = c.proj_position
        proj.distance_traveled = c.proj_traveled
        # Resolve against the target as it was at the impact instant.
        end_position, end_heading = target.position, target.heading
        target.position, target.heading = c.ship_position, c.ship_heading
        try:
            result = resolve_projectile_impact(proj, target, dice_roller=dice_roller, state=state)
        finally:
            target.position, target.heading = end_position, end_heading
        proj.alive = False
        impacts.append(ProjectileImpact(proj, target, result, c.time, c.ship_position))
    return impacts


def _first_contact(
    r0: Vector2D,
    w: Vector2D,
    q0: Vector2D,
    vs: Vector2D,
    max_range: float,
) -> float | None:
    """First ``u ∈ [0, 1]`` with ``|r0 + w·u| ≤ HIT_RADIUS`` and ``|q0 + vs·u| ≤ max_range``.

    *r0*/*w* are the salvo's position/velocity relative to the ship over the
    sub-step; *q0*/*vs* the ship's position relative to the salvo origin and
    its velocity.  Returns ``None`` when the windows never overlap.
    """
    hit = _within(r0, w, HIT_RADIUS)
    reach = _within(q0, vs, max_range)
    if hit is None or reach is None:
        return None
    lo = max(0.0, hit[0], reach[0])
    hi = min(1.0, hit[1], reach[1])
    return lo if lo <= hi else None


def _within(p0: Vector2D, v: Vector2D, radius: float) -> tuple[float, float] | None:
    """Interval of ``u`` where ``|p0 + v·u| ≤ radius`` (unbounded when static)."""
    a = v.x * v.x + v.y * v.y
    b = 2.0 * (p0.x * v.x + p0.y * v.y)
    c = p0.x * p0.x + p0.y * p0.y - radius * radius
    if a < 1e-12:
        return (-math.inf, math.inf) if c <= 1e-9 else None
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    return ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a))


def cleanup_projectiles(projectiles: list[Projectile]) -> list[Projectile]:
    """Remove dead (expired or detonated) projectiles.

    Returns a list of expired projectiles (for display), and mutates
    the input list in-place to keep only alive ones.
    """
    for projectile in projectiles:
        if projectile.alive and projectile.distance_traveled >= projectile.max_range:
            projectile.alive = False
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
