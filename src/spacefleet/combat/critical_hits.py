"""Critical hit system — 2D6 table with subsystem damage.

Every penetrating hit triggers a 2D6 roll on the critical table.
Lock On stance re-rolls a result of 7 (Hull Breach) once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.combat.morale_effects import apply_critical_hit_morale
from spacefleet.core.types import Arc
from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship

logger = logging.getLogger(__name__)


@dataclass
class CriticalResult:
    """Result of a single critical hit roll."""

    roll: int
    name: str
    description: str = ""
    effect: str = ""  # e.g. "hull_breach", "fire", "engine_damaged"
    extra_damage: int = 0
    fires_added: int = 0
    subsystem_hit: str | None = None  # "generator"/"deck"/"engines"/"weapons"
    weapon_disabled_slot: int | None = None
    speed_modifier: float | None = None
    leadership_penalty: int = 0
    shields_suppressed_turns: int = 0
    is_temporary: bool = False
    temporary_turns: int = 0


# ── Critical hit table (inline fallback) ─────────────────────

_CRIT_TABLE: dict[int, dict] = {  # type: ignore[type-arg]
    2: {
        "name": "Shields Collapsed",
        "description": "A power surge overloads the void shield generators.",
        "effect": "shields_collapse",
        "shields_suppressed_turns": 1,
    },
    3: {
        "name": "Thrusters Damaged",
        "description": "Maneuvering thrusters smashed — ship cannot turn.",
        "effect": "thrusters_damaged",
    },
    4: {
        "name": "Armament Damaged",
        "description": "A weapon system is knocked offline.",
        "effect": "weapon_destroyed",
    },
    5: {
        "name": "Prow Armament Damaged",
        "description": "Forward weapon systems wrecked by the hit.",
        "effect": "prow_weapons_destroyed",
    },
    6: {
        "name": "Engine Room Damaged",
        "description": "Main drive critically damaged — speed halved.",
        "effect": "engine_damaged",
        "speed_modifier": 0.5,
    },
    7: {
        "name": "Hull Breach",
        "description": "Hull torn open — additional structural damage.",
        "effect": "hull_breach",
        "extra_damage": 1,
    },
    8: {
        "name": "Engine Room Damaged",
        "description": "Main drive critically damaged — speed halved.",
        "effect": "engine_damaged",
        "speed_modifier": 0.5,
    },
    9: {
        "name": "Fire!",
        "description": "Fires break out across multiple decks.",
        "effect": "fire",
        "fires_added": 1,
    },
    10: {
        "name": "Bulkhead Collapse",
        "description": "Internal bulkheads collapse — massive structural damage.",
        "effect": "bulkhead_collapse",
        # extra_damage = D3, resolved at roll time
    },
    11: {
        "name": "Bridge Destroyed",
        "description": "Command bridge hit — leadership severely impaired.",
        "effect": "bridge_destroyed",
        "leadership_penalty": 3,
    },
    12: {
        "name": "Magazine Detonation!",
        "description": "Ammunition stores ignite in a catastrophic chain reaction!",
        "effect": "magazine_detonation",
        # extra_damage = D6 (+ D6 if torpedoes), resolved at roll time
    },
}


def _load_crit_table() -> dict[int, dict]:  # type: ignore[type-arg]
    """Try loading from YAML, fall back to inline."""
    try:
        from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_yaml_file

        if YAML_AVAILABLE:
            data_dir = get_data_dir()
            if data_dir is not None:
                path = data_dir / "critical_hits.yaml"
                raw = load_yaml_file(path)
                if raw and isinstance(raw, dict):
                    table = raw.get("critical_hit_table", {})
                    if table and isinstance(table, dict):
                        # YAML keys are ints (2-12)
                        return {int(k): v for k, v in table.items()}
    except Exception:
        logger.debug("Failed to load critical_hits.yaml, using inline", exc_info=True)
    return _CRIT_TABLE


_loaded_table: dict[int, dict] | None = None  # type: ignore[type-arg]


def _get_table() -> dict[int, dict]:  # type: ignore[type-arg]
    global _loaded_table  # noqa: PLW0603
    if _loaded_table is None:
        _loaded_table = _load_crit_table()
    return _loaded_table


# ── Core functions ────────────────────────────────────────────


def roll_critical_hit(
    target: Ship,
    *,
    lock_on_bonus: bool = False,
    targeted_subsystem: str | None = None,
    is_temporary: bool = False,
    dice_roller: DiceRoller | None = None,
) -> CriticalResult:
    """Roll on the 2D6 critical hit table.

    If *targeted_subsystem* is provided, skip the table and apply
    a direct subsystem hit (used by Lightning Strike boarding).

    If *lock_on_bonus* is True, re-roll a result of 7 once.

    If *is_temporary* is True, the crit auto-repairs after 3 turns
    (used for boarding crits).
    """
    dr = dice_roller or default_dice
    table = _get_table()

    if targeted_subsystem is not None:
        return _make_targeted_crit(targeted_subsystem, is_temporary=is_temporary)

    roll = dr.roll_2d6()

    # Lock On: re-roll result 7 (Hull Breach) once
    if lock_on_bonus and roll == 7:
        roll = dr.roll_2d6()

    entry = table.get(roll, table[7])  # fallback to 7 if missing

    result = CriticalResult(
        roll=roll,
        name=entry.get("name", "Unknown"),
        description=entry.get("description", ""),
        effect=entry.get("effect", ""),
        is_temporary=is_temporary,
        temporary_turns=3 if is_temporary else 0,
    )

    effect = result.effect

    if effect == "shields_collapse":
        raw = entry.get("shields_suppressed_turns", entry.get("duration", 1))
        result.shields_suppressed_turns = int(raw)

    elif effect == "engine_damaged":
        result.speed_modifier = float(entry.get("speed_modifier", 0.5))

    elif effect == "hull_breach":
        result.extra_damage = int(entry.get("extra_damage", 1))

    elif effect == "fire":
        result.fires_added = int(entry.get("fires_added", entry.get("damage_per_turn", 1)))

    elif effect == "bulkhead_collapse":
        result.extra_damage = dr.d3()

    elif effect == "bridge_destroyed":
        result.leadership_penalty = int(entry.get("leadership_penalty", 3))

    elif effect == "magazine_detonation":
        result.extra_damage = dr.d6()
        # Extra D6 if target carries torpedoes
        has_torpedoes = any(
            hasattr(w.weapon, "weapon_type") and w.weapon.weapon_type.value == "torpedo"
            for w in target.weapons
        )
        if has_torpedoes:
            result.extra_damage += dr.d6()

    elif effect == "weapon_destroyed":
        # Random weapon disabled
        if target.weapons:
            active = [w for w in target.weapons if w.can_fire]
            if active:
                idx = dr.randint(0, len(active) - 1)
                result.weapon_disabled_slot = active[idx].slot_id

    elif effect == "prow_weapons_destroyed":
        # All prow weapons
        result.subsystem_hit = "weapons"

    return result


def _make_targeted_crit(
    subsystem: str,
    *,
    is_temporary: bool = False,
) -> CriticalResult:
    """Create a crit result targeting a specific subsystem."""
    name_map = {
        "generator": ("Generator Disrupted", "shields_collapse"),
        "deck": ("Deck Breached", "deck_damaged"),
        "engines": ("Engines Damaged", "engine_damaged"),
        "weapons": ("Weapons Damaged", "weapon_destroyed"),
    }
    name, effect = name_map.get(subsystem, ("Subsystem Hit", subsystem))
    result = CriticalResult(
        roll=0,
        name=name,
        description=f"Targeted assault on {subsystem}.",
        effect=effect,
        subsystem_hit=subsystem,
        is_temporary=is_temporary,
        temporary_turns=3 if is_temporary else 0,
    )
    if effect == "shields_collapse":
        result.shields_suppressed_turns = 1
    elif effect == "engine_damaged":
        result.speed_modifier = 0.5
    return result


def apply_critical_hit(ship: Ship, result: CriticalResult) -> None:
    """Apply a critical hit's effects to a ship.  Also applies -5 morale."""
    effect = result.effect

    if effect == "shields_collapse":
        ship.shields_current = 0
        ship.crit_shields_suppressed_turns = max(
            ship.crit_shields_suppressed_turns,
            result.shields_suppressed_turns,
        )
        if result.is_temporary:
            ship.subsystem_generator = False
            ship.crit_temporary_repairs.append(("generator", result.temporary_turns))

    elif effect == "thrusters_damaged":
        ship.crit_thrusters_damaged = True
        if result.is_temporary:
            ship.crit_temporary_repairs.append(("thrusters", result.temporary_turns))

    elif effect == "engine_damaged":
        ship.crit_speed_modifier = min(
            ship.crit_speed_modifier,
            result.speed_modifier or 0.5,
        )
        ship.subsystem_engines = False
        if result.is_temporary:
            ship.crit_temporary_repairs.append(("engines", result.temporary_turns))

    elif effect == "hull_breach":
        if result.extra_damage > 0:
            ship.take_hull_damage(result.extra_damage)

    elif effect == "fire":
        ship.fires += result.fires_added

    elif effect == "bulkhead_collapse":
        if result.extra_damage > 0:
            ship.take_hull_damage(result.extra_damage)

    elif effect == "bridge_destroyed":
        ship.crit_leadership_penalty += result.leadership_penalty
        if result.is_temporary:
            ship.crit_temporary_repairs.append(("bridge", result.temporary_turns))

    elif effect == "magazine_detonation":
        if result.extra_damage > 0:
            ship.take_hull_damage(result.extra_damage)

    elif effect == "weapon_destroyed":
        if result.weapon_disabled_slot is not None:
            for w in ship.weapons:
                if w.slot_id == result.weapon_disabled_slot:
                    w.can_fire = False
                    break
            if result.is_temporary:
                ship.crit_temporary_repairs.append(
                    (f"weapon_{result.weapon_disabled_slot}", result.temporary_turns),
                )
        elif result.subsystem_hit == "weapons":
            # All weapons (boarding targeted) or prow weapons
            ship.subsystem_weapons = False
            if result.is_temporary:
                ship.crit_temporary_repairs.append(("weapons", result.temporary_turns))

    elif effect == "prow_weapons_destroyed":
        for w in ship.weapons:
            if w.arc == Arc.PROW:
                w.can_fire = False
        if result.is_temporary:
            ship.crit_temporary_repairs.append(("prow_weapons", result.temporary_turns))

    elif effect == "deck_damaged":
        ship.subsystem_deck = False
        if result.is_temporary:
            ship.crit_temporary_repairs.append(("deck", result.temporary_turns))

    # Morale penalty for every critical hit
    apply_critical_hit_morale(ship)
