"""Effect-step resolvers (Tasks 13-18): repairs, AoE, buffs, teleport, boarding, stubs."""

from __future__ import annotations

from spacefleet.commander.abilities import (
    AbilityDef,
    AbilityUsedEvent,
    AreaHullDamage,
    AreaHullDamageHitEvent,
    AreaMoraleDamage,
    AreaMoraleHitEvent,
    AreaMoraleRestore,
    AreaMoraleRestoreHitEvent,
    BonusBoardingAssault,
    BonusTorpedoSalvo,
    BuffAppliedEvent,
    ConcentratedFireBuff,
    ExtinguishFires,
    FiresExtinguishedEvent,
    HullRepair,
    HullRepairedEvent,
    PendingSprint6Event,
    RepairTempCritical,
    SpawnProbe,
    StepContext,
    TeleportEvent,
    TimedFleetBuff,
    resolve_ability,
    resolve_step,
)
from spacefleet.commander.commander import Commander
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.dice import DiceRoller
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship
from spacefleet.net.commands import AbilityOrder


def _ship(sid: str, faction: Faction, pos: Vector2D) -> Ship:
    s = Ship.from_profile(sid, sid, HULK_HULL, make_hulk_weapons(), position=pos)
    s.faction = faction
    return s


def _ctx(
    state: CoreGameState,
    flagship: Ship,
    *,
    order: AbilityOrder | None = None,
    seed: int = 1,
) -> StepContext:
    cmdr = Commander(id="c1", name="A", faction=flagship.faction)
    fleet = Fleet(id="f1", commander=cmdr, ship_ids=[flagship.id], flagship_ship_id=flagship.id)
    state.fleets["f1"] = fleet
    return StepContext(
        ability_id="ab",
        commander=cmdr,
        fleet=fleet,
        flagship=flagship,
        state=state,
        order=order or AbilityOrder(fleet_id="f1", ability_id="ab"),
        dice=DiceRoller(seed=seed),
    )


def test_hull_repair_restores_up_to_missing() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    flag.hull_current = flag.hull.hull_hits - 10
    state.add_ship(flag)
    ctx = _ctx(state, flag)
    events = resolve_step(HullRepair(amount_dice="D6"), ctx)
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, HullRepairedEvent)
    assert 1 <= ev.amount <= 6
    assert flag.hull_current == flag.hull.hull_hits - 10 + ev.amount


def test_extinguish_fires_clears_all() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    flag.fires = 3
    state.add_ship(flag)
    events = resolve_step(ExtinguishFires(), _ctx(state, flag))
    assert flag.fires == 0
    assert isinstance(events[0], FiresExtinguishedEvent)
    assert events[0].count == 3


def test_repair_temp_critical_pops_entries() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    flag.crit_temporary_repairs = [("engine", 3), ("weapon", 2)]
    state.add_ship(flag)
    events = resolve_step(RepairTempCritical(count=1), _ctx(state, flag))
    assert len(flag.crit_temporary_repairs) == 1
    assert events[0].count == 1


def test_area_morale_restore_hits_allies_in_range() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    ally = _ship("ally", Faction.IMPERIAL_NAVY, Vector2D(5, 0))
    ally.morale = 10
    enemy = _ship("enemy", Faction.CHAOS_FLEET, Vector2D(5, 0))
    enemy.morale = 10
    for s in (flag, ally, enemy):
        state.add_ship(s)
    events = resolve_step(
        AreaMoraleRestore(range_gu=20.0, amount=15, cancel_mutiny=True), _ctx(state, flag)
    )
    assert ally.morale == 25
    assert enemy.morale == 10  # enemy untouched
    hit_ids = {e.ship_id for e in events if isinstance(e, AreaMoraleRestoreHitEvent)}
    assert "ally" in hit_ids and "enemy" not in hit_ids


def test_area_morale_damage_hits_enemies_only() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    enemy = _ship("enemy", Faction.CHAOS_FLEET, Vector2D(5, 0))
    enemy_morale_before = enemy.morale
    ally = _ship("ally", Faction.IMPERIAL_NAVY, Vector2D(5, 0))
    for s in (flag, enemy, ally):
        state.add_ship(s)
    order = AbilityOrder(fleet_id="f1", ability_id="ab", target_position=Vector2D(5, 0))
    events = resolve_step(
        AreaMoraleDamage(range_gu=20.0, amount=20, affects_allies=False),
        _ctx(state, flag, order=order),
    )
    assert enemy.morale == enemy_morale_before - 20
    assert any(isinstance(e, AreaMoraleHitEvent) and e.ship_id == "enemy" for e in events)
    assert all(e.ship_id != "ally" for e in events if isinstance(e, AreaMoraleHitEvent))


def test_area_hull_damage_overflows_shields() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    enemy = _ship("enemy", Faction.CHAOS_FLEET, Vector2D(3, 0))
    enemy.shields_current = 0  # no shields → all damage penetrates
    hull_before = enemy.hull_current
    for s in (flag, enemy):
        state.add_ship(s)
    order = AbilityOrder(fleet_id="f1", ability_id="ab", target_position=Vector2D(3, 0))
    events = resolve_step(
        AreaHullDamage(range_gu=20.0, amount_dice="D6", affects_allies=False),
        _ctx(state, flag, order=order),
    )
    hit = next(e for e in events if isinstance(e, AreaHullDamageHitEvent))
    assert hit.hull_damage >= 1
    assert hit.source_fleet_id == "f1"
    assert hit.target_destroyed is False
    assert enemy.hull_current == hull_before - hit.hull_damage


def test_concentrated_fire_buff_lands_on_commander() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    state.add_ship(flag)
    order = AbilityOrder(fleet_id="f1", ability_id="ab", target_ship_id="enemy")
    ctx = _ctx(state, flag, order=order)
    events = resolve_step(ConcentratedFireBuff(range_gu=30.0, column_shift=2, duration=2), ctx)
    assert len(ctx.commander.active_buffs) == 1
    buff = ctx.commander.active_buffs[0]
    assert buff.turns_remaining == 2
    assert buff.data["target_ship_id"] == "enemy"
    assert isinstance(events[0], BuffAppliedEvent)


def test_timed_fleet_buff_lands_with_data() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    state.add_ship(flag)
    ctx = _ctx(state, flag)
    resolve_step(TimedFleetBuff(buff_id="rally", duration=3, data={"morale_immunity": True}), ctx)
    buff = ctx.commander.active_buffs[0]
    assert buff.id == "rally"
    assert buff.turns_remaining == 3
    assert buff.data["morale_immunity"] is True


def test_teleport_moves_flagship() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    state.add_ship(flag)
    from spacefleet.commander.abilities import Teleport

    order = AbilityOrder(fleet_id="f1", ability_id="ab", target_position=Vector2D(40, 12))
    events = resolve_step(Teleport(), _ctx(state, flag, order=order))
    assert flag.position == Vector2D(40, 12)
    assert isinstance(events[0], TeleportEvent)


def test_bonus_boarding_assault_resolves() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    enemy = _ship("enemy", Faction.CHAOS_FLEET, Vector2D(2, 0))
    for s in (flag, enemy):
        state.add_ship(s)
    order = AbilityOrder(fleet_id="f1", ability_id="ab", target_ship_id="enemy")
    events = resolve_step(
        BonusBoardingAssault(actions=4, extended_range_gu=5.0),
        _ctx(state, flag, order=order, seed=7),
    )
    from spacefleet.commander.abilities import BoardingAssaultEvent

    assert isinstance(events[0], BoardingAssaultEvent)
    assert events[0].target_id == "enemy"


def test_sprint6_stubs_emit_pending_no_mutation() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    state.add_ship(flag)
    ctx = _ctx(state, flag)
    probe = resolve_step(SpawnProbe(radius=10, duration=3, detection_level=2), ctx)
    salvo = resolve_step(BonusTorpedoSalvo(range_gu=30.0), ctx)
    assert isinstance(probe[0], PendingSprint6Event)
    assert isinstance(salvo[0], PendingSprint6Event)


def test_resolve_ability_walks_steps() -> None:
    state = CoreGameState()
    flag = _ship("flag", Faction.IMPERIAL_NAVY, Vector2D(0, 0))
    flag.hull_current = flag.hull.hull_hits - 10
    flag.fires = 2
    state.add_ship(flag)
    ctx = _ctx(state, flag)
    ability = AbilityDef(
        id="emergency_repairs",
        name="Emergency Repairs",
        category="repair",
        cooldown=3,
        charges=1,
        steps=(HullRepair(amount_dice="D6"), ExtinguishFires()),
    )
    events = resolve_ability(ability_def=ability, ctx=ctx)
    assert isinstance(events[0], AbilityUsedEvent)
    assert any(isinstance(e, HullRepairedEvent) for e in events)
    assert any(isinstance(e, FiresExtinguishedEvent) for e in events)
    assert flag.fires == 0
