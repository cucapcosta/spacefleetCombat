"""Commander active abilities — declarative effect-step primitives.

Each ``AbilityDef`` carries a tuple of effect steps (tagged union).
``resolve_ability`` (Task 18) walks the steps in order, dispatching
each through a handler registry.  Events produced by the resolver are
returned to the caller (``resolve_command_phase``) for logging /
publication on the ``EventBus``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from spacefleet.core.events import TurnEvent

if TYPE_CHECKING:
    from spacefleet.commander.commander import Commander
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Faction, Vector2D
    from spacefleet.dice import DiceRoller
    from spacefleet.models.fleet import Fleet
    from spacefleet.models.ship import Ship
    from spacefleet.net.commands import AbilityOrder

# ── Effect steps ──────────────────────────────────────────


@dataclass(frozen=True)
class HullRepair:
    amount_dice: str  # "D3" | "D6"


@dataclass(frozen=True)
class ExtinguishFires:
    pass


@dataclass(frozen=True)
class RepairTempCritical:
    count: int


@dataclass(frozen=True)
class AreaMoraleRestore:
    range_gu: float
    amount: int
    cancel_mutiny: bool


@dataclass(frozen=True)
class AreaHullDamage:
    range_gu: float
    amount_dice: str
    affects_allies: bool


@dataclass(frozen=True)
class AreaMoraleDamage:
    range_gu: float
    amount: int
    affects_allies: bool


@dataclass(frozen=True)
class SpawnProbe:
    radius: float
    duration: int
    detection_level: int


@dataclass(frozen=True)
class ConcentratedFireBuff:
    range_gu: float
    column_shift: int
    duration: int


@dataclass(frozen=True)
class TimedFleetBuff:
    buff_id: str
    duration: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BonusTorpedoSalvo:
    range_gu: float


@dataclass(frozen=True)
class Teleport:
    pass


@dataclass(frozen=True)
class BonusBoardingAssault:
    actions: int
    extended_range_gu: float


EffectStep = (
    HullRepair
    | ExtinguishFires
    | RepairTempCritical
    | AreaMoraleRestore
    | AreaHullDamage
    | AreaMoraleDamage
    | SpawnProbe
    | ConcentratedFireBuff
    | TimedFleetBuff
    | BonusTorpedoSalvo
    | Teleport
    | BonusBoardingAssault
)


# ── AbilityDef ────────────────────────────────────────────


@dataclass(frozen=True)
class AbilityDef:
    id: str
    name: str
    category: str
    cooldown: int
    charges: int
    preparation_turns: int = 0
    range_gu: float | None = None
    faction: str | None = None
    sprint6_dependency: bool = False
    steps: tuple[EffectStep, ...] = ()
    raw_effects: dict[str, Any] = field(default_factory=dict)


# ── Events ────────────────────────────────────────────────


@dataclass
class AbilityUsedEvent(TurnEvent):
    ability_id: str
    fleet_id: str


@dataclass
class HullRepairedEvent(TurnEvent):
    ship_id: str
    amount: int


@dataclass
class FiresExtinguishedEvent(TurnEvent):
    ship_id: str
    count: int


@dataclass
class TemporaryCritsRepairedEvent(TurnEvent):
    ship_id: str
    count: int


@dataclass
class AreaMoraleRestoreHitEvent(TurnEvent):
    ship_id: str
    amount: int


@dataclass
class AreaMoraleHitEvent(TurnEvent):
    ship_id: str
    amount: int


@dataclass
class AreaHullDamageHitEvent(TurnEvent):
    ship_id: str
    hull_damage: int


@dataclass
class BuffAppliedEvent(TurnEvent):
    fleet_id: str
    buff_id: str


@dataclass
class TeleportEvent(TurnEvent):
    ship_id: str


@dataclass
class BoardingAssaultEvent(TurnEvent):
    attacker_id: str
    target_id: str
    crew_damage: int
    subsystem_hits: int


@dataclass
class PendingSprint6Event(TurnEvent):
    ability_id: str
    note: str = ""


# ── Step resolution ───────────────────────────────────────


@dataclass
class StepContext:
    """Context threaded into each effect-step resolver."""

    ability_id: str
    commander: Commander
    fleet: Fleet
    flagship: Ship
    state: CoreGameState
    order: AbilityOrder
    dice: DiceRoller


def _roll_dice_str(spec: str, dice: DiceRoller) -> int:
    spec = spec.strip().upper()
    if spec == "D3":
        return dice.d3()
    if spec == "D6":
        return dice.d6()
    raise ValueError(f"Unsupported dice spec: {spec}")


def _opposite_faction(f: Faction) -> Faction:
    from spacefleet.core.types import Faction

    return Faction.CHAOS_FLEET if f == Faction.IMPERIAL_NAVY else Faction.IMPERIAL_NAVY


def _order_center(ctx: StepContext) -> Vector2D:
    if ctx.order.target_position is not None:
        return ctx.order.target_position
    return ctx.flagship.position


def _ships_in_radius(
    state: CoreGameState,
    center: Vector2D,
    radius: float,
    *,
    faction: Faction | None,
) -> list[Ship]:
    from spacefleet.spatial.geometry import distance

    out: list[Ship] = []
    for ship in state.alive_ships():
        if distance(center, ship.position) > radius:
            continue
        if faction is not None and ship.faction != faction:
            continue
        out.append(ship)
    return out


def resolve_step(step: EffectStep, ctx: StepContext) -> list[TurnEvent]:
    """Resolve one effect step against the current state; return events."""
    if isinstance(step, HullRepair):
        amount = _roll_dice_str(step.amount_dice, ctx.dice)
        applied = min(amount, ctx.flagship.hull.hull_hits - ctx.flagship.hull_current)
        ctx.flagship.hull_current += applied
        return [HullRepairedEvent(ship_id=ctx.flagship.id, amount=applied)]

    if isinstance(step, ExtinguishFires):
        count = ctx.flagship.fires
        ctx.flagship.fires = 0
        return [FiresExtinguishedEvent(ship_id=ctx.flagship.id, count=count)]

    if isinstance(step, RepairTempCritical):
        n = min(step.count, len(ctx.flagship.crit_temporary_repairs))
        for _ in range(n):
            ctx.flagship.crit_temporary_repairs.pop()
        return [TemporaryCritsRepairedEvent(ship_id=ctx.flagship.id, count=n)]

    if isinstance(step, AreaMoraleRestore):
        out: list[TurnEvent] = []
        for target in _ships_in_radius(
            ctx.state, ctx.flagship.position, step.range_gu, faction=ctx.flagship.faction
        ):
            changed = target.apply_morale_change(step.amount, state=ctx.state)
            if changed:
                out.append(AreaMoraleRestoreHitEvent(ship_id=target.id, amount=changed))
        return out

    if isinstance(step, AreaMoraleDamage):
        out = []
        faction = None if step.affects_allies else _opposite_faction(ctx.flagship.faction)
        for target in _ships_in_radius(
            ctx.state, _order_center(ctx), step.range_gu, faction=faction
        ):
            changed = target.apply_morale_change(-step.amount, state=ctx.state)
            if changed:
                out.append(AreaMoraleHitEvent(ship_id=target.id, amount=changed))
        return out

    if isinstance(step, AreaHullDamage):
        from spacefleet.combat.damage import apply_damage_pipeline

        out = []
        amount = _roll_dice_str(step.amount_dice, ctx.dice)
        faction = None if step.affects_allies else _opposite_faction(ctx.flagship.faction)
        for target in _ships_in_radius(
            ctx.state, _order_center(ctx), step.range_gu, faction=faction
        ):
            report = apply_damage_pipeline(
                target=target,
                hits=amount,
                relative_bearing=0.0,
                damage_per_hit=1,
                ignores_armor=True,
                dice_roller=ctx.dice,
            )
            if report.hull_damage > 0:
                target.take_hull_damage(report.hull_damage)
            out.append(AreaHullDamageHitEvent(ship_id=target.id, hull_damage=report.hull_damage))
        return out

    if isinstance(step, ConcentratedFireBuff):
        from spacefleet.commander.commander import ActiveBuff

        target_id = ctx.order.target_ship_id
        if target_id is None:
            return []
        buff = ActiveBuff(
            id=f"concentrated_fire:{target_id}",
            source_ability_id=ctx.ability_id,
            turns_remaining=step.duration,
            data={
                "kind": "concentrated_fire",
                "target_ship_id": target_id,
                "range_gu": step.range_gu,
                "column_shift": step.column_shift,
            },
        )
        ctx.commander.active_buffs.append(buff)
        return [BuffAppliedEvent(fleet_id=ctx.fleet.id, buff_id=buff.id)]

    if isinstance(step, TimedFleetBuff):
        from spacefleet.commander.commander import ActiveBuff

        buff = ActiveBuff(
            id=step.buff_id,
            source_ability_id=ctx.ability_id,
            turns_remaining=step.duration,
            data=dict(step.data),
        )
        ctx.commander.active_buffs.append(buff)
        return [BuffAppliedEvent(fleet_id=ctx.fleet.id, buff_id=buff.id)]

    if isinstance(step, Teleport):
        if ctx.order.target_position is not None:
            ctx.flagship.position = ctx.order.target_position
        return [TeleportEvent(ship_id=ctx.flagship.id)]

    if isinstance(step, BonusBoardingAssault):
        from spacefleet.combat.boarding import apply_boarding_result, resolve_boarding

        target_id = ctx.order.target_ship_id
        if target_id is None:
            return []
        tgt = ctx.state.ships.get(target_id)
        if tgt is None or not tgt.alive:
            return []
        result = resolve_boarding(ctx.flagship, tgt, step.actions, dice_roller=ctx.dice)
        apply_boarding_result(tgt, result, dice_roller=ctx.dice)
        return [
            BoardingAssaultEvent(
                attacker_id=ctx.flagship.id,
                target_id=tgt.id,
                crew_damage=result.total_crew_damage,
                subsystem_hits=result.total_subsystem_hits,
            )
        ]

    if isinstance(step, SpawnProbe):
        return [
            PendingSprint6Event(
                ability_id=ctx.ability_id,
                note="augur probe deployment pending Sprint 6 detection system",
            )
        ]

    if isinstance(step, BonusTorpedoSalvo):
        return [
            PendingSprint6Event(
                ability_id=ctx.ability_id,
                note="torpedo barrage pending Sprint 6 torpedo system",
            )
        ]

    return []


def resolve_ability(*, ability_def: AbilityDef, ctx: StepContext) -> list[TurnEvent]:
    """Walk an ability's effect-step list, collecting emitted events."""
    events: list[TurnEvent] = [AbilityUsedEvent(ability_id=ability_def.id, fleet_id=ctx.fleet.id)]
    for step in ability_def.steps:
        events.extend(resolve_step(step, ctx))
    return events
