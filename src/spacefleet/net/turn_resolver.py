"""Simultaneous turn resolution.

Collects commands from all ships, then resolves in order:
1. **Fire sub-phase** — all shots resolve (lances instant, batteries create projectiles)
2. **Movement sub-phase** — speed/turn applied, projectiles advance, ships drift
3. **End-of-turn sub-phase** — shields regen, fire damage, destroyed checks

The :func:`resolve_turn` function is the server's authoritative resolution
engine.  It calls the existing pure functions in ``core/game_loop.py``
and ``combat/`` unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.combat.projectile_resolution import resolve_lance_ray
from spacefleet.core.game_loop import (
    apply_end_of_turn,
    check_projectile_collisions,
    cleanup_projectiles,
    move_projectiles,
)
from spacefleet.core.types import Stance
from spacefleet.models.projectile import Projectile
from spacefleet.phases.movement_phase import MoveOrder, resolve_movement_phase
from spacefleet.spatial.geometry import distance as geo_distance

if TYPE_CHECKING:
    from spacefleet.combat.boarding import BoardingResult
    from spacefleet.combat.critical_hits import CriticalResult
    from spacefleet.combat.resolution import AttackResult
    from spacefleet.core.types import Vector2D
    from spacefleet.models.ship import Ship
    from spacefleet.net.commands import Command
    from spacefleet.net.game_state import GameState

# ═══════════════════════════════════════════════════════════════
# Turn log — typed events for the renderer to format
# ═══════════════════════════════════════════════════════════════


@dataclass
class TurnEvent:
    """Base class for all events in a turn."""

    pass


@dataclass
class LanceFireEvent(TurnEvent):
    ship: Ship
    weapon_name: str
    bearing: float
    result: AttackResult | None  # None = miss (no target on bearing)


@dataclass
class SalvoLaunchEvent(TurnEvent):
    ship: Ship
    weapon_name: str
    bearing: float
    speed: float
    max_range: float


@dataclass
class SalvoMoveEvent(TurnEvent):
    proj: Projectile
    old_pos: Vector2D
    new_pos: Vector2D


@dataclass
class SalvoImpactEvent(TurnEvent):
    proj: Projectile
    target: Ship
    result: AttackResult


@dataclass
class SalvoExpiredEvent(TurnEvent):
    proj: Projectile


@dataclass
class SpeedChangeEvent(TurnEvent):
    ship: Ship
    old_speed: float
    new_speed: float


@dataclass
class TurnOrderEvent(TurnEvent):
    ship: Ship
    direction: str
    degrees: float


@dataclass
class DriftEvent(TurnEvent):
    ship: Ship
    old_pos_str: str
    heading_before: float
    heading_after: float


@dataclass
class EndOfTurnEvent(TurnEvent):
    ship: Ship
    shields_regen: int
    fire_damage: int


@dataclass
class DestroyedEvent(TurnEvent):
    ship: Ship
    killer_player: str | None  # player_id of whoever gets credit


@dataclass
class RespawnEvent(TurnEvent):
    ship: Ship


@dataclass
class StanceChangeEvent(TurnEvent):
    ship: Ship
    old_stance: Stance
    new_stance: Stance
    reason: str = ""


@dataclass
class MoraleChangeEvent(TurnEvent):
    ship: Ship
    old_morale: int
    new_morale: int
    source: str = ""


@dataclass
class CriticalHitEvent(TurnEvent):
    ship: Ship
    attacker_name: str
    result: CriticalResult


@dataclass
class LightningStrikeEvent(TurnEvent):
    attacker: Ship
    target: Ship
    result: BoardingResult


@dataclass
class FireExtinguishedEvent(TurnEvent):
    ship: Ship
    roll: int
    fires_remaining: int


@dataclass
class TurnLog:
    """Record of everything that happened in a turn."""

    turn: int = 0
    events: list[TurnEvent] = field(default_factory=list)

    def add(self, event: TurnEvent) -> None:
        self.events.append(event)


# ═══════════════════════════════════════════════════════════════
# Main resolution function
# ═══════════════════════════════════════════════════════════════


def resolve_turn(
    state: GameState,
    commands: dict[str, Command],
) -> TurnLog:
    """Resolve one full turn with simultaneous resolution.

    Parameters
    ----------
    state:
        Mutable game state — modified in place.
    commands:
        Mapping of ship_id → Command for every alive ship that
        submitted an order (human + AI).

    Returns
    -------
    TurnLog with all events that happened (for rendering).
    """
    log = TurnLog(turn=state.turn)
    state.fired_this_turn.clear()

    # ── 1. FIRE SUB-PHASE ────────────────────────────────────
    # Sort by ship_id for deterministic ordering
    fire_cmds = sorted(
        [(sid, cmd) for sid, cmd in commands.items() if cmd.action == "fire"],
        key=lambda x: x[0],
    )

    for ship_id, cmd in fire_cmds:
        ship = state.get_ship(ship_id)
        if not ship.alive:
            continue

        # Running Silent breaks on fire attempt
        if ship.stance == Stance.RUNNING_SILENT:
            from spacefleet.data.stance_registry import StanceRegistry

            if StanceRegistry.get_for(Stance.RUNNING_SILENT).breaks_on_fire:
                old = ship.stance
                ship.stance = Stance.STANDARD
                ship.stance_cooldown_remaining = 0
                log.add(
                    StanceChangeEvent(
                        ship=ship,
                        old_stance=old,
                        new_stance=Stance.STANDARD,
                        reason="firing broke silence",
                    )
                )

        slot_id: int = cmd.args["slot"]
        bearing: float = cmd.args["bearing"]
        weapon = next(w for w in ship.weapons if w.slot_id == slot_id)

        state.fired_this_turn.add(ship_id)

        if weapon.weapon.speed <= 0:
            # Lance — instant-hit ray-cast
            result = resolve_lance_ray(
                ship,
                weapon,
                bearing,
                state.enemy_ships_of(ship),
                dice_roller=state.dice,
            )
            log.add(
                LanceFireEvent(
                    ship=ship,
                    weapon_name=weapon.weapon.name,
                    bearing=bearing,
                    result=result,
                )
            )
            if result is not None and result.target_destroyed:
                _credit_kill(state, ship_id, result.target_name, log)
        else:
            # Battery — create projectile salvo
            proj = Projectile(
                id=state.next_projectile_id(),
                position=ship.position,
                bearing=bearing,
                speed=weapon.weapon.speed,
                weapon_mount=weapon,
                attacker_id=ship.id,
                attacker_name=ship.name,
                attacker_faction=ship.faction,
                origin=ship.position,
                max_range=weapon.weapon.range,
            )
            state.projectiles.append(proj)
            log.add(
                SalvoLaunchEvent(
                    ship=ship,
                    weapon_name=weapon.weapon.name,
                    bearing=bearing,
                    speed=weapon.weapon.speed,
                    max_range=weapon.weapon.range,
                )
            )

    # ── 1b. LIGHTNING STRIKE SUB-PHASE ─────────────────────────
    strike_cmds = sorted(
        [(sid, cmd) for sid, cmd in commands.items() if cmd.action == "strike"],
        key=lambda x: x[0],
    )
    for ship_id, cmd in strike_cmds:
        ship = state.get_ship(ship_id)
        if not ship.alive:
            continue
        target_id = cmd.args.get("target", "")
        target = state.ships.get(target_id)
        if target is None or not target.alive:
            continue
        # Range check
        if geo_distance(ship.position, target.position) > 15.0:
            continue
        # Shields must be down
        if target.shields_current > 0:
            continue
        # Resolve boarding
        from spacefleet.combat.boarding import (
            apply_boarding_result,
            resolve_boarding,
        )

        assault_actions = ship.hull.assault_actions
        if assault_actions <= 0:
            continue
        subsys = cmd.args.get("subsystem")
        b_result = resolve_boarding(
            ship,
            target,
            assault_actions,
            subsystem_choice=subsys,
            dice_roller=state.dice,
        )
        apply_boarding_result(target, b_result, dice_roller=state.dice)
        log.add(LightningStrikeEvent(attacker=ship, target=target, result=b_result))

    # ── 2. MOVEMENT SUB-PHASE ────────────────────────────────
    move_orders: dict[str, MoveOrder] = {}
    for ship_id, cmd in commands.items():
        maybe_ship = state.ships.get(ship_id)
        if maybe_ship is None or not maybe_ship.alive:
            continue
        if cmd.action == "ahead":
            move_orders[ship_id] = MoveOrder(target_speed=cmd.args["speed"])
        elif cmd.action == "stop":
            move_orders[ship_id] = MoveOrder(target_speed=0.0)
        elif cmd.action == "turn":
            degrees = cmd.args["degrees"]
            if cmd.args["direction"] == "port":
                degrees = -degrees
            move_orders[ship_id] = MoveOrder(
                turn_degrees=degrees,
                turn_direction=cmd.args["direction"],
            )

    move_events = resolve_movement_phase(
        state.alive_ships(),
        move_orders,
        drift_fraction=0.5,
    )
    for ev in move_events:
        ship = state.ships[ev.ship_id]
        if ev.kind in ("morale_cap", "speed"):
            log.add(
                SpeedChangeEvent(
                    ship=ship,
                    old_speed=ev.old_speed,
                    new_speed=ev.new_speed,
                ),
            )
        elif ev.kind == "turn":
            log.add(
                TurnOrderEvent(
                    ship=ship,
                    direction=ev.turn_direction,
                    degrees=ev.turn_degrees,
                ),
            )
        elif ev.kind == "drift":
            log.add(
                DriftEvent(
                    ship=ship,
                    old_pos_str=repr(ship.position),
                    heading_before=ev.heading_before,
                    heading_after=ev.heading_after,
                ),
            )

    # Projectiles advance
    movements = move_projectiles(state.projectiles, fraction=0.5)
    for proj, old_pos, new_pos in movements:
        log.add(SalvoMoveEvent(proj=proj, old_pos=old_pos, new_pos=new_pos))

    # Check projectile collisions
    impacts = check_projectile_collisions(
        movements,
        state.all_ships_list(),
        state.dice,
    )
    for proj, target, result in impacts:
        log.add(SalvoImpactEvent(proj=proj, target=target, result=result))
        if result.target_destroyed:
            _credit_kill(state, proj.attacker_id, result.target_name, log)

    # Cleanup expired projectiles
    expired = cleanup_projectiles(state.projectiles)
    impact_projs = {id(e.proj) for e in log.events if isinstance(e, SalvoImpactEvent)}
    for proj in expired:
        if id(proj) not in impact_projs:
            log.add(SalvoExpiredEvent(proj=proj))

    # ── 3. END-OF-TURN SUB-PHASE ─────────────────────────────

    for ship in state.alive_ships():
        # Mutiny: shields stop regenerating
        if ship.morale <= 0:
            fire_dmg = ship.apply_fire_damage()
            shields = 0
        else:
            shields, fire_dmg = apply_end_of_turn(ship)

        if shields > 0 or fire_dmg > 0:
            log.add(EndOfTurnEvent(ship=ship, shields_regen=shields, fire_damage=fire_dmg))

        # Fire extinguishing — leadership check
        if ship.fires > 0:
            roll = state.dice.d6()
            if roll <= ship.effective_leadership:
                ship.fires = max(0, ship.fires - 1)
                log.add(
                    FireExtinguishedEvent(
                        ship=ship,
                        roll=roll,
                        fires_remaining=ship.fires,
                    )
                )

        # Morale loss from fires
        if ship.fires > 0:
            old_m = ship.morale
            ship.apply_morale_change(-3)
            if ship.morale != old_m:
                log.add(
                    MoraleChangeEvent(
                        ship=ship,
                        old_morale=old_m,
                        new_morale=ship.morale,
                        source="fire",
                    )
                )

        # Stance cooldown tick
        ship.tick_stance_cooldown()

        # Combustion regen
        ship.regenerate_combustion(15)

        # Tick critical hit state
        ship.tick_shields_suppressed()
        ship.tick_temporary_repairs()

        # Morale natural recovery if no enemies within 80 GU
        enemies_nearby = any(
            geo_distance(ship.position, e.position) <= 80.0 for e in state.enemy_ships_of(ship)
        )
        if not enemies_nearby and ship.morale < ship.morale_max:
            old_m = ship.morale
            ship.apply_morale_change(5)
            if ship.morale != old_m:
                log.add(
                    MoraleChangeEvent(
                        ship=ship,
                        old_morale=old_m,
                        new_morale=ship.morale,
                        source="recovery",
                    )
                )

    return log


# ── Helpers ──────────────────────────────────────────────────


def _credit_kill(
    state: GameState,
    killer_ship_id: str,
    target_name: str,
    log: TurnLog,
) -> None:
    """Credit a kill to the player who owns *killer_ship_id*."""
    owner = state.owner_of(killer_ship_id)
    if owner is not None:
        state.kills[owner] = state.kills.get(owner, 0) + 1
    # Find the destroyed ship
    destroyed: Ship | None = None
    for ship in state.ships.values():
        if ship.name == target_name and not ship.alive:
            destroyed = ship
            log.add(DestroyedEvent(ship=ship, killer_player=owner))
            break

    # Morale effects from destruction on nearby ships
    if destroyed is not None:
        for other in state.alive_ships():
            dist = geo_distance(other.position, destroyed.position)
            if dist > 30.0:
                continue
            if other.faction == destroyed.faction:
                # Ally destroyed nearby: -15 morale
                old_m = other.morale
                other.apply_morale_change(-15)
                if other.morale != old_m:
                    log.add(
                        MoraleChangeEvent(
                            ship=other,
                            old_morale=old_m,
                            new_morale=other.morale,
                            source="ally destroyed",
                        )
                    )
            else:
                # Enemy destroyed nearby: +5 morale
                old_m = other.morale
                other.apply_morale_change(5)
                if other.morale != old_m:
                    log.add(
                        MoraleChangeEvent(
                            ship=other,
                            old_morale=old_m,
                            new_morale=other.morale,
                            source="enemy destroyed",
                        )
                    )
