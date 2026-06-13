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
