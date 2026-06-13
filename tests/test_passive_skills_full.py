"""Behavioural tests for combat/end-of-turn/faction/crew-tier passives (Tasks 22-25, 28)."""

from __future__ import annotations

from spacefleet.commander.commander import ActiveBuff, Commander
from spacefleet.commander.passive_skills import (
    PassiveBus,
    PassiveContext,
    PassiveHook,
    ability_cooldown_after_passives,
    anti_mutiny_suppressed,
    battery_firepower_bonus,
    end_of_turn_hull_regen,
    end_of_turn_shield_regen,
    hit_column_shift,
    hull_breach_allowed,
    lance_hit_threshold,
)
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def _ship(sid: str, faction: Faction, pos: Vector2D) -> Ship:
    s = Ship.from_profile(sid, sid, HULK_HULL, make_hulk_weapons(), position=pos)
    s.faction = faction
    return s


def _state_with(
    passives: list[str],
    *,
    faction: Faction = Faction.IMPERIAL_NAVY,
    ships: list[Ship] | None = None,
    buffs: list[ActiveBuff] | None = None,
) -> tuple[CoreGameState, Commander]:
    state = CoreGameState()
    ships = ships or [_ship("s1", faction, Vector2D(0, 0))]
    for s in ships:
        state.add_ship(s)
    cmdr = Commander(id="c", name="A", faction=faction, passive_skill_ids=passives)
    if buffs:
        cmdr.active_buffs.extend(buffs)
    state.fleets["f1"] = Fleet(
        id="f1",
        commander=cmdr,
        ship_ids=[s.id for s in ships],
        flagship_ship_id=ships[0].id,
    )
    state.passives = PassiveBus.build(state)
    return state, cmdr


# ── Task 22: combat hooks ─────────────────────────────────


def test_master_gunner_firepower_at_close_range() -> None:
    atk = _ship("atk", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    tgt = _ship("tgt", Faction.CHAOS_FLEET, Vector2D(2, 0))
    state, _ = _state_with(["master_gunner"], ships=[atk])
    state.add_ship(tgt)
    state.passives = PassiveBus.build(state)
    weapon = atk.weapons[0]
    assert battery_firepower_bonus(state, atk, tgt, weapon) == 1


def test_concentrated_fire_column_shift() -> None:
    atk = _ship("atk", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    tgt = _ship("tgt", Faction.CHAOS_FLEET, Vector2D(5, 0))
    buff = ActiveBuff(
        id="cf",
        source_ability_id="concentrated_fire",
        turns_remaining=2,
        data={
            "kind": "concentrated_fire",
            "target_ship_id": "tgt",
            "range_gu": 30.0,
            "column_shift": 2,
        },
    )
    state, _ = _state_with([], ships=[atk], buffs=[buff])
    state.add_ship(tgt)
    state.passives = PassiveBus.build(state)
    assert hit_column_shift(state, atk, tgt, atk.weapons[0]) == 2


def test_lance_mastery_lowers_threshold() -> None:
    state, _ = _state_with(["lance_mastery"], faction=Faction.CHAOS_FLEET)
    atk = state.ships["s1"]
    assert lance_hit_threshold(state, atk) == 3


def test_reinforced_bulkheads_blocks_hull_breach() -> None:
    state, _ = _state_with(["reinforced_bulkheads"])
    tgt = state.ships["s1"]
    assert hull_breach_allowed(state, tgt) is False


# ── Task 23/24: end-of-turn + universal ───────────────────


def test_shield_harmonics_extra_regen() -> None:
    state, _ = _state_with(["shield_harmonics"])
    assert end_of_turn_shield_regen(state, state.ships["s1"]) == 1


def test_dark_blessings_hull_regen() -> None:
    state, _ = _state_with(["dark_blessings"], faction=Faction.CHAOS_FLEET)
    assert end_of_turn_hull_regen(state, state.ships["s1"]) == 1


def test_iron_discipline_suppresses_mutiny_near_flagship() -> None:
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    near = _ship("near", Faction.IMPERIAL_NAVY, Vector2D(10, 0))
    state, _ = _state_with(["iron_discipline"], ships=[flag, near])
    near.morale = 0
    assert anti_mutiny_suppressed(state, near) is True


def test_iron_discipline_does_not_help_far_ship() -> None:
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    far = _ship("far", Faction.IMPERIAL_NAVY, Vector2D(100, 0))
    state, _ = _state_with(["iron_discipline"], ships=[flag, far])
    far.morale = 0
    assert anti_mutiny_suppressed(state, far) is False


def test_sensor_mastery_extends_range() -> None:
    state, _ = _state_with(["sensor_mastery"])
    ctx = PassiveContext(ship=state.ships["s1"], fleet=state.fleets["f1"], state=state, value=60.0)
    assert state.passives is not None
    assert state.passives.dispatch(PassiveHook.FLEET_SENSOR_RANGE, ctx) == 80.0


# ── Task 25: faction passives ─────────────────────────────


def test_prow_of_the_emperor_armor() -> None:
    state, _ = _state_with(["prow_of_the_emperor"])
    ctx = PassiveContext(ship=state.ships["s1"], fleet=state.fleets["f1"], state=state, value=0)
    assert state.passives is not None
    assert state.passives.dispatch(PassiveHook.FLEET_ARMOR_PROW, ctx) == 1


def test_speed_of_chaos_ahead_full_dice() -> None:
    state, _ = _state_with(["speed_of_chaos"], faction=Faction.CHAOS_FLEET)
    ctx = PassiveContext(ship=state.ships["s1"], fleet=state.fleets["f1"], state=state, value=None)
    assert state.passives is not None
    assert state.passives.dispatch(PassiveHook.AHEAD_FULL_DICE, ctx) == 3


def test_boarding_expertise_bonus() -> None:
    state, _ = _state_with(["boarding_expertise"])
    ctx = PassiveContext(ship=state.ships["s1"], fleet=state.fleets["f1"], state=state, value=2)
    assert state.passives is not None
    assert state.passives.dispatch(PassiveHook.ASSAULT_ACTION_BONUS, ctx) == 3


# ── Task 28: crew-tier contributions ──────────────────────


def test_crew_tier_firepower_and_cooldown() -> None:
    elite = _ship("elite", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    elite.battles_survived = 20  # tier 4 (Elite)
    tgt = _ship("tgt", Faction.CHAOS_FLEET, Vector2D(99, 0))
    state, _ = _state_with([], ships=[elite])
    state.add_ship(tgt)
    state.passives = PassiveBus.build(state)
    assert elite.crew_tier == 4
    # Elite tier grants +1 firepower (range-independent) ...
    assert battery_firepower_bonus(state, elite, tgt, elite.weapons[0]) == 1
    # ... and a 20% ability-cooldown reduction on the flagship.
    assert ability_cooldown_after_passives(state, elite, 5) == 4
