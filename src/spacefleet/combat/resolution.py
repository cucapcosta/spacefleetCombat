"""Combat resolution for the tech demo.

Implements weapon battery and lance fire, the gunnery table,
shield absorption, armor saves, and hull damage.

Critical hits and torpedo/nova cannon are stubbed — they will
be added in later sprints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.core.types import WeaponType
from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice
from spacefleet.spatial.geometry import (
    bearing_from_to,
    distance,
    is_in_arc,
    relative_bearing,
)

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount

# ─────────────────────────────────────────────────────────────────
# Gunnery table (hardcoded for demo; will load from YAML later)
# ─────────────────────────────────────────────────────────────────

GUNNERY_COLUMNS = ["far_closing", "closing", "abeam", "running", "far_running"]

GUNNERY_TABLE: dict[int, list[int]] = {
    1: [0, 0, 1, 1, 1],
    2: [0, 1, 1, 1, 2],
    3: [0, 1, 1, 2, 2],
    4: [1, 1, 2, 2, 3],
    5: [1, 1, 2, 3, 3],
    6: [1, 2, 2, 3, 4],
    7: [1, 2, 3, 3, 4],
    8: [1, 2, 3, 4, 5],
    9: [2, 2, 3, 4, 5],
    10: [2, 3, 4, 4, 6],
    11: [2, 3, 4, 5, 6],
    12: [2, 3, 4, 5, 7],
    13: [3, 3, 5, 6, 7],
    14: [3, 4, 5, 6, 8],
    15: [3, 4, 5, 7, 8],
    16: [3, 4, 6, 7, 9],
}


# ─────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────


@dataclass
class HitDetail:
    """One individual hit going through the armor-save step."""

    blocked_by_shield: bool = False
    armor_roll: int = 0
    armor_value: int = 0
    penetrated: bool = False
    hull_damage: int = 0


@dataclass
class AttackResult:
    """Full result of a single weapon firing at a target."""

    attacker_name: str
    weapon_name: str
    weapon_type: WeaponType
    target_name: str
    distance: float
    in_arc: bool
    in_range: bool

    # Weapon info
    weapon_strength: int = 0  # raw strength (guns / beams)

    # Battery-specific
    effective_firepower: int = 0
    target_aspect: str = ""
    gunnery_column: str = ""

    # Hit counts
    raw_hits: int = 0
    shield_blocked: int = 0
    armor_saves: int = 0
    penetrating_hits: int = 0
    hull_damage_dealt: int = 0

    hit_details: list[HitDetail] = field(default_factory=list)

    # Lance-specific
    lance_rolls: list[int] = field(default_factory=list)

    # Outcome
    target_destroyed: bool = False
    message: str = ""


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _get_target_aspect(attacker: Ship, target: Ship) -> tuple[str, int]:
    """Determine target aspect and gunnery column shift.

    We look at the bearing from the *target* to the *attacker*: that tells
    us which face the target is presenting.

    Returns ``(aspect_name, column_shift)`` where shift is
    ``-1`` closing, ``0`` abeam, ``+1`` running.
    """
    bearing_to_attacker = bearing_from_to(target.position, attacker.position)
    rel = relative_bearing(target.heading, bearing_to_attacker)

    abs_rel = abs(rel)
    if abs_rel <= 45:
        return "closing", -1  # target showing prow → harder
    if abs_rel <= 135:
        return "abeam", 0  # target showing broadside
    return "running", 1  # target showing stern → easier


# ─────────────────────────────────────────────────────────────────
# Battery resolution
# ─────────────────────────────────────────────────────────────────


def resolve_battery_attack(
    attacker: Ship,
    weapon: WeaponMount,
    target: Ship,
    *,
    dice_roller: DiceRoller | None = None,
) -> AttackResult:
    """Resolve a weapon-battery (macro-cannon) attack."""
    dr = dice_roller or default_dice

    result = AttackResult(
        attacker_name=attacker.name,
        weapon_name=weapon.weapon.name,
        weapon_type=WeaponType.BATTERY,
        weapon_strength=weapon.weapon.strength,
        target_name=target.name,
        distance=distance(attacker.position, target.position),
        in_arc=False,
        in_range=False,
    )

    # ── Step 1: arc check ──
    abs_bearing = bearing_from_to(attacker.position, target.position)
    if not is_in_arc(attacker.heading, abs_bearing, weapon.arc):
        result.message = f"Target is outside {weapon.arc.value} arc."
        return result
    result.in_arc = True

    # ── Step 2: range check ──
    dist = result.distance
    if dist > weapon.weapon.range:
        result.message = f"Target is out of range ({dist:.0f} GU > {weapon.weapon.range:.0f} GU)."
        return result
    result.in_range = True

    # ── Step 3: effective firepower (halve at long range) ──
    fp = weapon.weapon.strength
    if dist > weapon.weapon.range * 0.5:
        fp = max(1, (fp + 1) // 2)  # halve, round up
    result.effective_firepower = fp

    # ── Step 4: target aspect + gunnery column ──
    aspect_name, aspect_shift = _get_target_aspect(attacker, target)
    result.target_aspect = aspect_name

    col_idx = _clamp(2 + aspect_shift, 0, 4)  # abeam = index 2
    result.gunnery_column = GUNNERY_COLUMNS[col_idx]

    # ── Step 5: look up hits on the gunnery table ──
    table_fp = _clamp(fp, 1, max(GUNNERY_TABLE.keys()))
    raw_hits = GUNNERY_TABLE[table_fp][col_idx]
    result.raw_hits = raw_hits

    if raw_hits == 0:
        result.message = "All shots miss!"
        return result

    # ── Step 6: damage pipeline — shields → armor → hull ──

    # Shields
    remaining = target.absorb_shields(raw_hits)
    result.shield_blocked = raw_hits - remaining

    # Armor — determine which face the shots hit
    incoming_bearing = relative_bearing(
        target.heading,
        bearing_from_to(target.position, attacker.position),
    )
    armor = target.armor_for_bearing(incoming_bearing)

    total_hull_damage = 0
    for _ in range(remaining):
        detail = HitDetail(armor_value=armor)
        roll = dr.d6()
        detail.armor_roll = roll
        # D6 >= armor value → hit PENETRATES
        # Higher armor = fewer rolls penetrate = stronger face
        if roll >= armor:
            detail.penetrated = True
            detail.hull_damage = weapon.weapon.damage_per_hit
            total_hull_damage += detail.hull_damage
        else:
            result.armor_saves += 1
        result.hit_details.append(detail)

    result.penetrating_hits = remaining - result.armor_saves
    result.hull_damage_dealt = total_hull_damage

    # Apply hull damage
    if total_hull_damage > 0:
        target.take_hull_damage(total_hull_damage)
        result.target_destroyed = not target.alive

    # Build summary
    parts = [f"{raw_hits} hits"]
    if result.shield_blocked:
        parts.append(f"{result.shield_blocked} absorbed by shields")
    if result.armor_saves:
        parts.append(f"{result.armor_saves} deflected by armor")
    if total_hull_damage:
        parts.append(f"{total_hull_damage} hull damage")
    if result.target_destroyed:
        parts.append("TARGET DESTROYED")
    result.message = " → ".join(parts)

    return result


# ─────────────────────────────────────────────────────────────────
# Lance resolution
# ─────────────────────────────────────────────────────────────────


def resolve_lance_attack(
    attacker: Ship,
    weapon: WeaponMount,
    target: Ship,
    *,
    dice_roller: DiceRoller | None = None,
) -> AttackResult:
    """Resolve a lance weapon attack.

    Lances roll 1D6 per strength; 4+ = hit.
    Hits pass through shields but **bypass armor**.
    """
    dr = dice_roller or default_dice

    result = AttackResult(
        attacker_name=attacker.name,
        weapon_name=weapon.weapon.name,
        weapon_type=WeaponType.LANCE,
        weapon_strength=weapon.weapon.strength,
        target_name=target.name,
        distance=distance(attacker.position, target.position),
        in_arc=False,
        in_range=False,
    )

    # Arc check
    abs_bearing = bearing_from_to(attacker.position, target.position)
    if not is_in_arc(attacker.heading, abs_bearing, weapon.arc):
        result.message = f"Target is outside {weapon.arc.value} arc."
        return result
    result.in_arc = True

    # Range check
    if result.distance > weapon.weapon.range:
        result.message = (
            f"Target out of range ({result.distance:.0f} > {weapon.weapon.range:.0f} GU)."
        )
        return result
    result.in_range = True

    # Roll 1D6 per strength, 4+ hits
    rolls = dr.roll_d6(weapon.weapon.strength)
    result.lance_rolls = rolls
    raw_hits = sum(1 for r in rolls if r >= 4)
    result.raw_hits = raw_hits

    if raw_hits == 0:
        result.message = "All lance shots miss!"
        return result

    # Lances: shields absorb first, then bypass armor entirely
    remaining = target.absorb_shields(raw_hits)
    result.shield_blocked = raw_hits - remaining

    # Each remaining hit → direct hull damage (lances ignore armor)
    result.penetrating_hits = remaining
    result.hull_damage_dealt = remaining * weapon.weapon.damage_per_hit

    if result.hull_damage_dealt > 0:
        target.take_hull_damage(result.hull_damage_dealt)
        result.target_destroyed = not target.alive

    # Summary
    parts = [f"Rolls: [{', '.join(str(r) for r in rolls)}]"]
    parts.append(f"{raw_hits} hits (4+ needed)")
    if result.shield_blocked:
        parts.append(f"{result.shield_blocked} absorbed by shields")
    if result.hull_damage_dealt:
        parts.append(f"{result.hull_damage_dealt} hull damage (bypasses armor)")
    if result.target_destroyed:
        parts.append("TARGET DESTROYED")
    result.message = " → ".join(parts)

    return result


# ─────────────────────────────────────────────────────────────────
# Unified entry point
# ─────────────────────────────────────────────────────────────────


def resolve_attack(
    attacker: Ship,
    weapon: WeaponMount,
    target: Ship,
    *,
    dice_roller: DiceRoller | None = None,
) -> AttackResult:
    """Route to the correct resolver based on weapon type."""
    if weapon.weapon.weapon_type == WeaponType.BATTERY:
        return resolve_battery_attack(attacker, weapon, target, dice_roller=dice_roller)
    if weapon.weapon.weapon_type == WeaponType.LANCE:
        return resolve_lance_attack(attacker, weapon, target, dice_roller=dice_roller)
    # Torpedoes and nova cannon are not implemented for the demo
    return AttackResult(
        attacker_name=attacker.name,
        weapon_name=weapon.weapon.name,
        weapon_type=weapon.weapon.weapon_type,
        target_name=target.name,
        distance=distance(attacker.position, target.position),
        in_arc=False,
        in_range=False,
        message=f"{weapon.weapon.weapon_type.value} weapons not yet implemented.",
    )
