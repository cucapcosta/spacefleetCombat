"""PassiveBus — named-hook dispatcher for passive skill effects.

Built once per turn from state.fleets + state.ships.  Handlers contribute
to one of two hook kinds:

* **Aggregate** (default) — each handler receives ``ctx.value``, returns
  a modified value; results chain through all handlers.  Used for sums
  (speed bonus) or multipliers (morale loss reduction).
* **Override** — first handler returning a non-``None`` value wins.
  Used for threshold rules (``LANCE_HIT_THRESHOLD``,
  ``ANTI_MUTINY_CHECK``).

The distinction is made by the caller: aggregate dispatch passes a
starting ``ctx.value`` and returns the chained result; override
dispatch passes ``value=None`` and returns the first non-None.

Task 10 provides the skeleton; passive handler registration (universal,
faction, crew-tier, active-buff) is layered on in Tasks 11, 22, 23, 24,
25, 28.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.models.fleet import Fleet
    from spacefleet.models.ship import Ship


class PassiveHook(StrEnum):
    FLEET_SPEED_MAX = "fleet_speed_max"
    FLEET_SENSOR_RANGE = "fleet_sensor_range"
    FLEET_ARMOR_PROW = "fleet_armor_prow"
    BATTERY_FIREPOWER_BONUS = "battery_firepower_bonus"
    AHEAD_FULL_DICE = "ahead_full_dice"
    HIT_COLUMN_SHIFT = "hit_column_shift"
    LANCE_HIT_THRESHOLD = "lance_hit_threshold"
    END_OF_TURN_SHIELD_REGEN = "end_of_turn_shield_regen"
    END_OF_TURN_HULL_REGEN = "end_of_turn_hull_regen"
    MORALE_LOSS_APPLY = "morale_loss_apply"
    MORALE_STARTING_BONUS = "morale_starting_bonus"
    HULL_BREACH_APPLY = "hull_breach_apply"
    ANTI_MUTINY_CHECK = "anti_mutiny_check"
    ABILITY_COOLDOWN_REDUCTION = "ability_cooldown_reduction"
    ASSAULT_ACTION_BONUS = "assault_action_bonus"
    TORPEDO_SPEED_MULT = "torpedo_speed_mult"
    TORPEDO_RELOAD_REDUCTION = "torpedo_reload_reduction"
    TORPEDO_STRENGTH = "torpedo_strength"


@dataclass
class PassiveContext:
    ship: Ship | None
    fleet: Fleet | None
    state: CoreGameState
    value: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[PassiveContext], Any]


class PassiveBus:
    """Per-turn dispatcher.  Rebuilt after the command phase to pick up buffs."""

    def __init__(self) -> None:
        self._handlers: dict[PassiveHook, list[tuple[str, Handler]]] = {}

    def register(self, *, source: str, hook: PassiveHook, handler: Handler) -> None:
        self._handlers.setdefault(hook, []).append((source, handler))

    def dispatch(self, hook: PassiveHook, ctx: PassiveContext) -> Any:
        """Aggregate if ``ctx.value`` is not None; override otherwise."""
        handlers = self._handlers.get(hook, [])
        if ctx.value is None:
            for _src, fn in handlers:
                result = fn(ctx)
                if result is not None:
                    return result
            return None
        value = ctx.value
        for _src, fn in handlers:
            ctx.value = value
            value = fn(ctx)
        return value

    @classmethod
    def build(cls, state: CoreGameState) -> PassiveBus:
        """Build a bus from the state's fleets + ships.

        Handler registration for passives is delegated to helper functions
        that subsequent tasks introduce.
        """
        bus = cls()
        _register_morale_loss_handlers(bus, state)
        _register_speed_handlers(bus, state)
        _register_combat_handlers(bus, state)
        _register_endofturn_handlers(bus, state)
        _register_universal_passives(bus, state)
        _register_faction_passives(bus, state)
        _register_crew_tier_handlers(bus, state)

        from spacefleet.commander.doctrine_effects import register_doctrine_handlers

        register_doctrine_handlers(bus, state)
        return bus


def _register_morale_loss_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Register morale-loss passive handlers for veteran_crews and morale_immunity buffs."""
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue
        if "veteran_crews" in cmdr.passive_skill_ids:

            def _veteran(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                if ctx.ship is not None and ctx.ship.id in f.ship_ids:
                    return int(ctx.value * 0.75)
                return ctx.value

            bus.register(
                source=f"{fleet.id}:veteran_crews",
                hook=PassiveHook.MORALE_LOSS_APPLY,
                handler=_veteran,
            )
        for buff in cmdr.active_buffs:
            if buff.data.get("morale_immunity"):

                def _immunity(ctx: PassiveContext, fid: str | None = fleet.flagship_ship_id) -> Any:
                    if fid is not None and ctx.ship is not None and ctx.ship.id == fid:
                        return 0
                    return ctx.value

                bus.register(
                    source=f"{fleet.id}:{buff.id}:immunity",
                    hook=PassiveHook.MORALE_LOSS_APPLY,
                    handler=_immunity,
                )


def _register_speed_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Register fleet-speed-cap passive handlers (swift_maneuvers: +5)."""
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue
        if "swift_maneuvers" in cmdr.passive_skill_ids:

            def _swift(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                if ctx.ship is not None and ctx.ship.id in f.ship_ids:
                    return ctx.value + 5.0
                return ctx.value

            bus.register(
                source=f"{fleet.id}:swift_maneuvers",
                hook=PassiveHook.FLEET_SPEED_MAX,
                handler=_swift,
            )


def effective_speed_max_with_passives(ship: Ship, state: CoreGameState) -> float:
    """Ship's speed cap after applying FLEET_SPEED_MAX passives."""
    passives = getattr(state, "passives", None)
    if passives is None:
        return ship.effective_speed_max
    ctx = PassiveContext(
        ship=ship,
        fleet=state.fleet_of(ship),
        state=state,
        value=ship.effective_speed_max,
    )
    return float(passives.dispatch(PassiveHook.FLEET_SPEED_MAX, ctx))


def _in_fleet(ctx: PassiveContext, f: Fleet) -> bool:
    return ctx.ship is not None and ctx.ship.id in f.ship_ids


# ── Combat hooks (Task 22) ────────────────────────────────


def _register_combat_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Column-shift (concentrated_fire buff) + firepower (master_gunner)."""
    from spacefleet.spatial.geometry import distance

    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue

        def _conc_fire(ctx: PassiveContext, f: Fleet = fleet) -> Any:
            if not _in_fleet(ctx, f) or f.commander is None:
                return ctx.value
            target = ctx.extra.get("target")
            if target is None or ctx.ship is None:
                return ctx.value
            bonus = 0
            for buff in f.commander.active_buffs:
                if (
                    buff.data.get("kind") == "concentrated_fire"
                    and buff.data.get("target_ship_id") == target.id
                ):
                    rng = float(buff.data.get("range_gu", 1e9))
                    if distance(ctx.ship.position, target.position) <= rng:
                        bonus += int(buff.data.get("column_shift", 0))
            return ctx.value + bonus

        bus.register(
            source=f"{fleet.id}:concentrated_fire",
            hook=PassiveHook.HIT_COLUMN_SHIFT,
            handler=_conc_fire,
        )

        if "master_gunner" in cmdr.passive_skill_ids:

            def _master_gunner(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                if not _in_fleet(ctx, f) or ctx.ship is None:
                    return ctx.value
                target = ctx.extra.get("target")
                weapon = ctx.extra.get("weapon")
                if target is None or weapon is None:
                    return ctx.value
                if distance(ctx.ship.position, target.position) <= weapon.weapon.range * 0.5:
                    return ctx.value + 1
                return ctx.value

            bus.register(
                source=f"{fleet.id}:master_gunner",
                hook=PassiveHook.BATTERY_FIREPOWER_BONUS,
                handler=_master_gunner,
            )


# ── End-of-turn hooks (Task 23) ───────────────────────────


def _register_endofturn_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """shield_harmonics, dark_blessings (hull regen), iron_discipline (anti-mutiny)."""
    from spacefleet.spatial.geometry import distance

    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue

        if "shield_harmonics" in cmdr.passive_skill_ids:

            def _harmonics(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return ctx.value + 1 if _in_fleet(ctx, f) else ctx.value

            bus.register(
                source=f"{fleet.id}:shield_harmonics",
                hook=PassiveHook.END_OF_TURN_SHIELD_REGEN,
                handler=_harmonics,
            )

        if "dark_blessings" in cmdr.passive_skill_ids:

            def _dark_blessings(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return ctx.value + 1 if _in_fleet(ctx, f) else ctx.value

            bus.register(
                source=f"{fleet.id}:dark_blessings",
                hook=PassiveHook.END_OF_TURN_HULL_REGEN,
                handler=_dark_blessings,
            )

        if "iron_discipline" in cmdr.passive_skill_ids:

            def _iron(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                if not _in_fleet(ctx, f) or ctx.ship is None:
                    return None
                flag = f.flagship_in(ctx.state)
                if flag is None:
                    return None
                if distance(ctx.ship.position, flag.position) <= 40.0:
                    return True
                return None

            bus.register(
                source=f"{fleet.id}:iron_discipline",
                hook=PassiveHook.ANTI_MUTINY_CHECK,
                handler=_iron,
            )


# ── Universal passives (Task 24) ──────────────────────────


def _register_universal_passives(bus: PassiveBus, state: CoreGameState) -> None:
    """sensor_mastery, reinforced_bulkheads, + inert Sprint-6 torpedo passives."""
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue

        if "sensor_mastery" in cmdr.passive_skill_ids:

            def _sensor(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return ctx.value + 20.0 if _in_fleet(ctx, f) else ctx.value

            bus.register(
                source=f"{fleet.id}:sensor_mastery",
                hook=PassiveHook.FLEET_SENSOR_RANGE,
                handler=_sensor,
            )

        if "reinforced_bulkheads" in cmdr.passive_skill_ids:

            def _bulkheads(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return False if _in_fleet(ctx, f) else None

            bus.register(
                source=f"{fleet.id}:reinforced_bulkheads",
                hook=PassiveHook.HULL_BREACH_APPLY,
                handler=_bulkheads,
            )

        # Inert until Sprint 6 torpedoes exist — registration proves loadability.
        if "short_burn_torpedoes" in cmdr.passive_skill_ids:

            def _sbt(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return ctx.value * 1.5 if _in_fleet(ctx, f) else ctx.value

            bus.register(
                source=f"{fleet.id}:short_burn_torpedoes",
                hook=PassiveHook.TORPEDO_SPEED_MULT,
                handler=_sbt,
            )

        if "reload_drills" in cmdr.passive_skill_ids:

            def _reload(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return ctx.value - 1 if _in_fleet(ctx, f) else ctx.value

            bus.register(
                source=f"{fleet.id}:reload_drills",
                hook=PassiveHook.TORPEDO_RELOAD_REDUCTION,
                handler=_reload,
            )


# ── Faction passives (Task 25) ────────────────────────────


def _register_faction_passives(bus: PassiveBus, state: CoreGameState) -> None:
    """lance_mastery, prow_of_the_emperor, speed_of_chaos, boarding_expertise."""
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue

        if "lance_mastery" in cmdr.passive_skill_ids:

            def _lance_mastery(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return 3 if _in_fleet(ctx, f) else None

            bus.register(
                source=f"{fleet.id}:lance_mastery",
                hook=PassiveHook.LANCE_HIT_THRESHOLD,
                handler=_lance_mastery,
            )

        if "prow_of_the_emperor" in cmdr.passive_skill_ids:

            def _prow(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return ctx.value + 1 if _in_fleet(ctx, f) else ctx.value

            bus.register(
                source=f"{fleet.id}:prow_of_the_emperor",
                hook=PassiveHook.FLEET_ARMOR_PROW,
                handler=_prow,
            )

        if "speed_of_chaos" in cmdr.passive_skill_ids:

            def _speed_chaos(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return 3 if _in_fleet(ctx, f) else None

            bus.register(
                source=f"{fleet.id}:speed_of_chaos",
                hook=PassiveHook.AHEAD_FULL_DICE,
                handler=_speed_chaos,
            )

        if "boarding_expertise" in cmdr.passive_skill_ids:

            def _boarding(ctx: PassiveContext, f: Fleet = fleet) -> Any:
                return ctx.value + 1 if _in_fleet(ctx, f) else ctx.value

            bus.register(
                source=f"{fleet.id}:boarding_expertise",
                hook=PassiveHook.ASSAULT_ACTION_BONUS,
                handler=_boarding,
            )


# ── Crew-tier contributions (Task 28) ─────────────────────


def _register_crew_tier_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Per-ship firepower + per-flagship ability-cooldown contributions from crew tier."""
    from spacefleet.data.skill_registry import SkillRegistry

    for fleet in state.fleets.values():
        for ship in fleet.ships_in(state):
            tier = ship.crew_tier
            if tier <= 0:
                continue
            tdef = SkillRegistry.get_crew_tier(tier)
            if tdef is None:
                continue
            firepower = tdef.firepower_bonus
            if firepower:

                def _fp(ctx: PassiveContext, sid: str = ship.id, b: int = firepower) -> Any:
                    return (
                        ctx.value + b if ctx.ship is not None and ctx.ship.id == sid else ctx.value
                    )

                bus.register(
                    source=f"{ship.id}:crew_tier_fp",
                    hook=PassiveHook.BATTERY_FIREPOWER_BONUS,
                    handler=_fp,
                )

        flag = fleet.flagship_in(state)
        if flag is None:
            continue
        ftier = flag.crew_tier
        if ftier <= 0:
            continue
        ftdef = SkillRegistry.get_crew_tier(ftier)
        if ftdef is None or ftdef.cooldown_reduction <= 0:
            continue
        flag_id = flag.id
        reduction = ftdef.cooldown_reduction

        def _cooldown(ctx: PassiveContext, fid: str = flag_id, red: float = reduction) -> Any:
            if ctx.ship is not None and ctx.ship.id == fid:
                return ctx.value * (1.0 - red)
            return ctx.value

        bus.register(
            source=f"{fleet.id}:crew_tier_cooldown",
            hook=PassiveHook.ABILITY_COOLDOWN_REDUCTION,
            handler=_cooldown,
        )


# ── Public dispatch helpers (used by combat / end-of-turn) ─


def hit_column_shift(
    state: CoreGameState, attacker: Ship, target: Ship, weapon: Any, base: int = 0
) -> int:
    passives = getattr(state, "passives", None)
    if passives is None:
        return base
    ctx = PassiveContext(
        ship=attacker,
        fleet=state.fleet_of(attacker),
        state=state,
        value=base,
        extra={"target": target, "weapon": weapon},
    )
    return int(passives.dispatch(PassiveHook.HIT_COLUMN_SHIFT, ctx))


def battery_firepower_bonus(
    state: CoreGameState, attacker: Ship, target: Ship, weapon: Any, base: int = 0
) -> int:
    passives = getattr(state, "passives", None)
    if passives is None:
        return base
    ctx = PassiveContext(
        ship=attacker,
        fleet=state.fleet_of(attacker),
        state=state,
        value=base,
        extra={"target": target, "weapon": weapon},
    )
    return int(passives.dispatch(PassiveHook.BATTERY_FIREPOWER_BONUS, ctx))


def lance_hit_threshold(state: CoreGameState, attacker: Ship, base: int = 4) -> int:
    passives = getattr(state, "passives", None)
    if passives is None:
        return base
    ctx = PassiveContext(ship=attacker, fleet=state.fleet_of(attacker), state=state, value=None)
    result = passives.dispatch(PassiveHook.LANCE_HIT_THRESHOLD, ctx)
    return int(result) if result is not None else base


def hull_breach_allowed(state: CoreGameState, target: Ship, base: bool = True) -> bool:
    passives = getattr(state, "passives", None)
    if passives is None:
        return base
    ctx = PassiveContext(ship=target, fleet=state.fleet_of(target), state=state, value=None)
    result = passives.dispatch(PassiveHook.HULL_BREACH_APPLY, ctx)
    return base if result is None else bool(result)


def end_of_turn_shield_regen(state: CoreGameState, ship: Ship) -> int:
    passives = getattr(state, "passives", None)
    if passives is None:
        return 0
    ctx = PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=0)
    return int(passives.dispatch(PassiveHook.END_OF_TURN_SHIELD_REGEN, ctx))


def end_of_turn_hull_regen(state: CoreGameState, ship: Ship) -> int:
    passives = getattr(state, "passives", None)
    if passives is None:
        return 0
    ctx = PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=0)
    return int(passives.dispatch(PassiveHook.END_OF_TURN_HULL_REGEN, ctx))


def anti_mutiny_suppressed(state: CoreGameState, ship: Ship) -> bool:
    passives = getattr(state, "passives", None)
    if passives is None:
        return False
    ctx = PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=None)
    return passives.dispatch(PassiveHook.ANTI_MUTINY_CHECK, ctx) is True


def assault_action_bonus(state: CoreGameState, ship: Ship) -> int:
    passives = getattr(state, "passives", None)
    if passives is None:
        return 0
    ctx = PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=0)
    return int(passives.dispatch(PassiveHook.ASSAULT_ACTION_BONUS, ctx))


def ability_cooldown_after_passives(
    state: CoreGameState, flagship: Ship, base_cooldown: int
) -> int:
    from math import ceil

    passives = getattr(state, "passives", None)
    if passives is None:
        return base_cooldown
    ctx = PassiveContext(ship=flagship, fleet=state.fleet_of(flagship), state=state, value=1.0)
    mult = float(passives.dispatch(PassiveHook.ABILITY_COOLDOWN_REDUCTION, ctx))
    return int(ceil(base_cooldown * mult))
