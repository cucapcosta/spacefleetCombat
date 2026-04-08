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
from spacefleet.spatial.geometry import distance as geo_distance

if TYPE_CHECKING:
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
                log.add(StanceChangeEvent(
                    ship=ship,
                    old_stance=old,
                    new_stance=Stance.STANDARD,
                    reason="firing broke silence",
                ))

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

    # ── 2. MOVEMENT SUB-PHASE ────────────────────────────────

    # Apply speed / turn commands
    for ship_id, cmd in sorted(commands.items()):
        ship = state.get_ship(ship_id)
        if not ship.alive:
            continue

        if cmd.action == "ahead":
            old_speed = ship.speed
            ship.set_speed(cmd.args["speed"])
            log.add(SpeedChangeEvent(ship=ship, old_speed=old_speed, new_speed=ship.speed))
        elif cmd.action == "stop":
            old_speed = ship.speed
            ship.set_speed(0.0)
            log.add(SpeedChangeEvent(ship=ship, old_speed=old_speed, new_speed=0.0))
        elif cmd.action == "turn":
            degrees = cmd.args["degrees"]
            if cmd.args["direction"] == "port":
                degrees = -degrees
            ship.apply_turn(degrees)
            log.add(
                TurnOrderEvent(
                    ship=ship,
                    direction=cmd.args["direction"],
                    degrees=cmd.args["degrees"],
                )
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

    # Drift all alive ships
    for ship in state.alive_ships():
        old_pos_str = repr(ship.position)
        h_before, h_after = ship.apply_drift(0.5)
        log.add(
            DriftEvent(
                ship=ship,
                old_pos_str=old_pos_str,
                heading_before=h_before,
                heading_after=h_after,
            )
        )

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

        # Morale loss from fires
        if ship.fires > 0:
            old_m = ship.morale
            ship.apply_morale_change(-3)
            if ship.morale != old_m:
                log.add(MoraleChangeEvent(
                    ship=ship, old_morale=old_m,
                    new_morale=ship.morale, source="fire",
                ))

        # Stance cooldown tick
        ship.tick_stance_cooldown()

        # Combustion regen
        ship.regenerate_combustion(15)

        # Morale natural recovery if no enemies within 80 GU
        enemies_nearby = any(
            geo_distance(ship.position, e.position) <= 80.0
            for e in state.enemy_ships_of(ship)
        )
        if not enemies_nearby and ship.morale < ship.morale_max:
            old_m = ship.morale
            ship.apply_morale_change(5)
            if ship.morale != old_m:
                log.add(MoraleChangeEvent(
                    ship=ship, old_morale=old_m,
                    new_morale=ship.morale, source="recovery",
                ))

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
                    log.add(MoraleChangeEvent(
                        ship=other, old_morale=old_m,
                        new_morale=other.morale, source="ally destroyed",
                    ))
            else:
                # Enemy destroyed nearby: +5 morale
                old_m = other.morale
                other.apply_morale_change(5)
                if other.morale != old_m:
                    log.add(MoraleChangeEvent(
                        ship=other, old_morale=old_m,
                        new_morale=other.morale, source="enemy destroyed",
                    ))
