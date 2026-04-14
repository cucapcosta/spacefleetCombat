"""Projectile impact resolution and lance ray-casting.

Handles the hit-determination pipeline when a projectile salvo reaches
a target, and the instant-hit ray-cast for lance weapons.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.combat.gunnery import (
    GUNNERY_COLUMNS,
    column_index,
    lookup_hits,
)
from spacefleet.combat.morale_effects import apply_hull_damage_morale
from spacefleet.combat.resolution import (
    AttackResult,
    HitDetail,
)
from spacefleet.core.types import WeaponType, heading_to_vector
from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice
from spacefleet.spatial.geometry import (
    distance,
    point_to_segment_distance,
    relative_bearing,
)

if TYPE_CHECKING:
    from spacefleet.models.projectile import Projectile
    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount

# Hit radius for collision detection (GU).  Ships are ~3.5 GU long;
# this gives a forgiving diameter-like detection zone.
HIT_RADIUS = 2.0


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _aspect_from_projectile_bearing(
    projectile_bearing: float,
    target: Ship,
) -> tuple[str, int]:
    """Determine target aspect using the projectile's bearing.

    The projectile is traveling at *projectile_bearing*.  The incoming
    direction (from the target's perspective) is the opposite bearing.
    We compute which face of the target is struck.

    Returns ``(aspect_name, column_shift)``.
    """
    # The fire comes FROM the opposite of the projectile's travel direction
    incoming_from = (projectile_bearing + 180.0) % 360.0
    rel = relative_bearing(target.heading, incoming_from)

    abs_rel = abs(rel)
    if abs_rel <= 45:
        return "closing", -1  # hit on the prow face → target "closing"
    if abs_rel <= 135:
        return "abeam", 0  # broadside hit
    return "running", 1  # stern hit


# ─────────────────────────────────────────────────────────────────
# Projectile impact (battery salvos)
# ─────────────────────────────────────────────────────────────────


def resolve_projectile_impact(
    projectile: Projectile,
    target: Ship,
    *,
    dice_roller: DiceRoller | None = None,
) -> AttackResult:
    """Resolve a battery projectile salvo hitting *target*.

    Uses the gunnery table pipeline but skips arc/range validation
    (arc was checked at fire time; the projectile physically arrived).
    Target aspect is computed from the projectile's bearing vs the
    target's current heading.
    """
    dr = dice_roller or default_dice
    weapon = projectile.weapon_mount

    result = AttackResult(
        attacker_name=projectile.attacker_name,
        weapon_name=weapon.weapon.name,
        weapon_type=WeaponType.BATTERY,
        weapon_strength=weapon.weapon.strength,
        target_name=target.name,
        distance=projectile.distance_traveled,
        in_arc=True,
        in_range=True,
    )

    # ── Effective firepower (halve at long range) ──
    fp = weapon.weapon.strength
    if projectile.distance_traveled > weapon.weapon.range * 0.5:
        fp = max(1, (fp + 1) // 2)
    result.effective_firepower = fp

    # ── Target aspect from projectile bearing ──
    aspect_name, aspect_shift = _aspect_from_projectile_bearing(
        projectile.bearing,
        target,
    )
    result.target_aspect = aspect_name
    col_idx = column_index(aspect_shift=aspect_shift, stance_shift=0)
    result.gunnery_column = GUNNERY_COLUMNS[col_idx]

    # ── Gunnery table lookup ──
    raw_hits = lookup_hits(strength=fp, column=col_idx)
    result.raw_hits = raw_hits

    if raw_hits == 0:
        result.message = "All shots miss!"
        return result

    # ── Damage pipeline: shields → armor → hull ──

    # Shields
    remaining = target.absorb_shields(raw_hits)
    result.shield_blocked = raw_hits - remaining

    # Armor — determine face struck by the incoming salvo
    incoming_from = (projectile.bearing + 180.0) % 360.0
    incoming_rel = relative_bearing(target.heading, incoming_from)
    armor = target.armor_for_bearing(incoming_rel)

    total_hull_damage = 0
    for _ in range(remaining):
        detail = HitDetail(armor_value=armor)
        roll = dr.d6()
        detail.armor_roll = roll
        if roll >= armor:
            detail.penetrated = True
            detail.hull_damage = weapon.weapon.damage_per_hit
            total_hull_damage += detail.hull_damage
        else:
            result.armor_saves += 1
        result.hit_details.append(detail)

    result.penetrating_hits = remaining - result.armor_saves
    result.hull_damage_dealt = total_hull_damage

    if total_hull_damage > 0:
        target.take_hull_damage(total_hull_damage)
        apply_hull_damage_morale(target, hull_damage=total_hull_damage)
        result.target_destroyed = not target.alive

    # Critical hits per penetrating hit (no Lock On bonus for projectiles)
    if result.penetrating_hits > 0 and target.alive:
        from spacefleet.combat.critical_hits import apply_critical_hit, roll_critical_hit

        for _ in range(result.penetrating_hits):
            if not target.alive:
                break
            crit = roll_critical_hit(target, dice_roller=dr)
            apply_critical_hit(target, crit)
            result.critical_hits.append(crit)
            if not target.alive:
                result.target_destroyed = True

    # Summary
    parts = [f"{raw_hits} hits"]
    if result.shield_blocked:
        parts.append(f"{result.shield_blocked} absorbed by shields")
    if result.armor_saves:
        parts.append(f"{result.armor_saves} deflected by armor")
    if total_hull_damage:
        parts.append(f"{total_hull_damage} hull damage")
    if result.critical_hits:
        parts.append(f"{len(result.critical_hits)} critical(s)")
    if result.target_destroyed:
        parts.append("TARGET DESTROYED")
    result.message = " \u2192 ".join(parts)

    return result


# ─────────────────────────────────────────────────────────────────
# Lance ray-cast (instant-hit)
# ─────────────────────────────────────────────────────────────────


def resolve_lance_ray(
    attacker: Ship,
    weapon: WeaponMount,
    bearing: float,
    targets: list[Ship],
    *,
    dice_roller: DiceRoller | None = None,
) -> AttackResult | None:
    """Fire a lance along *bearing* and resolve against the first target hit.

    Casts a ray from *attacker*'s position along *bearing* up to the
    weapon's range.  If an alive enemy target's centre is within
    ``HIT_RADIUS`` GU of the ray, the lance resolves against the
    nearest such target.

    Returns ``None`` if no target is found on the bearing.
    """
    dr = dice_roller or default_dice

    origin = attacker.position
    direction = heading_to_vector(bearing)
    ray_end = origin + direction * weapon.weapon.range

    # Find nearest target within HIT_RADIUS of the ray
    best_target: Ship | None = None
    best_dist = float("inf")

    for t in targets:
        if not t.alive:
            continue
        if t.faction == attacker.faction:
            continue

        seg_dist, _closest = point_to_segment_distance(
            t.position,
            origin,
            ray_end,
        )
        if seg_dist <= HIT_RADIUS:
            # Use distance from attacker to target for "nearest" ordering
            d = distance(origin, t.position)
            if d < best_dist:
                best_dist = d
                best_target = t

    if best_target is None:
        return None

    # ── Resolve lance attack against the found target ──
    result = AttackResult(
        attacker_name=attacker.name,
        weapon_name=weapon.weapon.name,
        weapon_type=WeaponType.LANCE,
        weapon_strength=weapon.weapon.strength,
        target_name=best_target.name,
        distance=best_dist,
        in_arc=True,
        in_range=True,
    )

    # Roll 1D6 per strength, 4+ hits
    rolls = dr.roll_d6(weapon.weapon.strength)
    result.lance_rolls = rolls
    raw_hits = sum(1 for r in rolls if r >= 4)
    result.raw_hits = raw_hits

    if raw_hits == 0:
        result.message = "All lance shots miss!"
        return result

    # Shields first, then bypass armor
    remaining = best_target.absorb_shields(raw_hits)
    result.shield_blocked = raw_hits - remaining

    result.penetrating_hits = remaining
    result.hull_damage_dealt = remaining * weapon.weapon.damage_per_hit

    if result.hull_damage_dealt > 0:
        best_target.take_hull_damage(result.hull_damage_dealt)
        result.target_destroyed = not best_target.alive

    # Summary
    parts = [f"Rolls: [{', '.join(str(r) for r in rolls)}]"]
    parts.append(f"{raw_hits} hits (4+ needed)")
    if result.shield_blocked:
        parts.append(f"{result.shield_blocked} absorbed by shields")
    if result.hull_damage_dealt:
        parts.append(f"{result.hull_damage_dealt} hull damage (bypasses armor)")
    if result.target_destroyed:
        parts.append("TARGET DESTROYED")
    result.message = " \u2192 ".join(parts)

    return result
