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

from spacefleet.combat.fire_control import bearing_spread, lock_level
from spacefleet.combat.projectile_resolution import resolve_lance_ray
from spacefleet.commander.abilities import AreaHullDamageHitEvent
from spacefleet.commander.passive_skills import PassiveBus
from spacefleet.core.events import TurnEvent as TurnEvent  # re-exported for renderers
from spacefleet.core.game_loop import (
    apply_end_of_turn,
    check_projectile_collisions,
    cleanup_projectiles,
    move_projectiles,
)
from spacefleet.core.types import Stance
from spacefleet.models.projectile import Projectile
from spacefleet.phases.command_phase import (
    AbilityInterruptedEvent,
    resolve_command_phase,
)
from spacefleet.phases.movement_phase import MoveOrder, resolve_movement_phase
from spacefleet.spatial.geometry import absolute_bearing, relative_bearing_360
from spacefleet.spatial.geometry import distance as geo_distance

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.combat.boarding import BoardingResult
    from spacefleet.combat.critical_hits import CriticalResult
    from spacefleet.combat.resolution import AttackResult
    from spacefleet.core.types import Vector2D
    from spacefleet.models.ship import Ship
    from spacefleet.net.commands import AbilityOrder, Command
    from spacefleet.net.game_state import GameState

# ═══════════════════════════════════════════════════════════════
# Turn log — typed events for the renderer to format
# ═══════════════════════════════════════════════════════════════


# ``TurnEvent`` is defined in ``core.events`` (re-exported above) so phase
# resolvers can emit turn events without importing ``net``.


@dataclass
class LanceFireEvent(TurnEvent):
    ship: Ship
    weapon_name: str
    bearing: float  # prow-relative, as fired
    result: AttackResult | None  # None = miss (no target on bearing)


@dataclass
class SalvoLaunchEvent(TurnEvent):
    ship: Ship
    weapon_name: str
    bearing: float  # prow-relative, as fired (after gunnery spread)
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
    ability_orders: dict[str, AbilityOrder] | None = None,
    *,
    on_phase: Callable[[str, GameState], None] | None = None,
) -> TurnLog:
    """Resolve one full turn with simultaneous resolution.

    Parameters
    ----------
    state:
        Mutable game state — modified in place.
    commands:
        Mapping of ship_id → Command for every alive ship that
        submitted an order (human + AI).
    on_phase:
        Optional observer called with the state at each sub-phase boundary:
        ``"start"``, ``"after_fire"``, ``"after_move"`` and ``"end"``.

    Returns
    -------
    TurnLog with all events that happened (for rendering).
    """
    log = TurnLog(turn=state.turn)
    # Last turn's muzzle flashes: the scanner showed these ships as at least
    # CONTACT while orders were given, so fire-control locks honour that.
    revealed_by_fire = frozenset(state.fired_this_turn)
    state.fired_this_turn.clear()
    if on_phase is not None:
        on_phase("start", state)

    def emit(event: TurnEvent) -> None:
        log.events.append(event)
        state.events.publish(event)

    # ── 0. COMMAND SUB-PHASE ─────────────────────────────────
    # Build the passive bus from current fleets, resolve commander
    # abilities, then rebuild so buffs created this turn take effect.
    state.passives = PassiveBus.build(state)
    for cmd_ev in resolve_command_phase(state, ability_orders or {}, state.dice):
        emit(cmd_ev)
        if isinstance(cmd_ev, AreaHullDamageHitEvent) and cmd_ev.target_destroyed:
            _credit_destroyed_ship(
                state,
                cmd_ev.ship_id,
                killer_fleet_id=cmd_ev.source_fleet_id,
                emit=emit,
            )
    state.passives = PassiveBus.build(state)

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
                emit(
                    StanceChangeEvent(
                        ship=ship,
                        old_stance=old,
                        new_stance=Stance.STANDARD,
                        reason="firing broke silence",
                    )
                )

        state.fired_this_turn.add(ship_id)
        shots = cmd.args.get("shots")
        shot_args = shots if isinstance(shots, list) else [cmd.args]
        for shot in shot_args:
            slot_id: int = shot["slot"]
            # Orders carry prow-relative bearings; physics runs on absolute ones.
            relative: float = shot["bearing"]
            bearing = absolute_bearing(ship.heading, relative)
            weapon = next(w for w in ship.weapons if w.slot_id == slot_id)

            if weapon.weapon.speed <= 0:
                # Lance — instant-hit ray-cast
                result = resolve_lance_ray(
                    ship,
                    weapon,
                    bearing,
                    state.enemy_ships_of(ship),
                    dice_roller=state.dice,
                    state=state,
                )
                emit(
                    LanceFireEvent(
                        ship=ship,
                        weapon_name=weapon.weapon.name,
                        bearing=relative,
                        result=result,
                    )
                )
                if result is not None and result.target_destroyed:
                    assert result.target_ship_id is not None
                    _credit_destroyed_ship(
                        state, result.target_ship_id, killer_ship_id=ship_id, emit=emit
                    )
            else:
                # Battery — create projectile salvo, scattered by gunnery spread
                lock = lock_level(state, ship, shot.get("target"), revealed_by_fire)
                spread = bearing_spread(ship, weapon, state, lock)
                bearing = (bearing + state.dice.gauss(0.0, spread)) % 360.0
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
                emit(
                    SalvoLaunchEvent(
                        ship=ship,
                        weapon_name=weapon.weapon.name,
                        bearing=relative_bearing_360(ship.heading, bearing),
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
        # Doctrine boarding immunity (e.g. Space Marine Detachment)
        from spacefleet.data.doctrine_registry import DoctrineRegistry

        # Deliberate direct registry lookup (not a PassiveBus hook): boarding
        # immunity is a static doctrine property with no current need to be
        # overridable.
        t_doc = DoctrineRegistry.get_or_none(target.doctrine_id)
        if t_doc is not None and t_doc.board_immune:
            from spacefleet.commander.doctrine_effects import (
                BoardingRepelledByDoctrineEvent,
            )

            emit(BoardingRepelledByDoctrineEvent(attacker_id=ship.id, target_id=target.id))
            continue
        # Resolve boarding
        from spacefleet.combat.boarding import (
            apply_boarding_result,
            resolve_boarding,
        )
        from spacefleet.commander.passive_skills import assault_action_bonus

        assault_actions = ship.hull.assault_actions + assault_action_bonus(state, ship)
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
        emit(LightningStrikeEvent(attacker=ship, target=target, result=b_result))

        # Micro-warp interruption: a boarding strike on a flagship cancels
        # any in-preparation commander ability, restoring its spent charge.
        boarded_fleet = state.fleet_of(target)
        if (
            boarded_fleet is not None
            and boarded_fleet.commander is not None
            and boarded_fleet.flagship_ship_id == target.id
        ):
            for aid, st in list(boarded_fleet.commander.ability_state.items()):
                if st.pending_order is not None and st.preparation_turns_left > 0:
                    st.pending_order = None
                    st.preparation_turns_left = 0
                    st.remaining_charges += 1
                    emit(
                        AbilityInterruptedEvent(
                            ability_id=aid,
                            fleet_id=boarded_fleet.id,
                            reason="boarding",
                        )
                    )

    if on_phase is not None:
        on_phase("after_fire", state)

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
        state=state,
    )
    for ev in move_events:
        ship = state.ships[ev.ship_id]
        if ev.kind in ("morale_cap", "speed"):
            emit(
                SpeedChangeEvent(
                    ship=ship,
                    old_speed=ev.old_speed,
                    new_speed=ev.new_speed,
                ),
            )
        elif ev.kind == "turn":
            emit(
                TurnOrderEvent(
                    ship=ship,
                    direction=ev.turn_direction,
                    degrees=ev.turn_degrees,
                ),
            )
        elif ev.kind == "drift":
            emit(
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
        emit(SalvoMoveEvent(proj=proj, old_pos=old_pos, new_pos=new_pos))

    # Check projectile collisions
    impacts = check_projectile_collisions(
        movements,
        state.all_ships_list(),
        state.dice,
        state,
    )
    for proj, target, result in impacts:
        emit(SalvoImpactEvent(proj=proj, target=target, result=result))
        if result.target_destroyed:
            _credit_destroyed_ship(state, target.id, killer_ship_id=proj.attacker_id, emit=emit)

    # Cleanup expired projectiles
    expired = cleanup_projectiles(state.projectiles)
    impact_projs = {id(e.proj) for e in log.events if isinstance(e, SalvoImpactEvent)}
    for proj in expired:
        if id(proj) not in impact_projs:
            emit(SalvoExpiredEvent(proj=proj))

    if on_phase is not None:
        on_phase("after_move", state)

    # ── 3. END-OF-TURN SUB-PHASE ─────────────────────────────

    from spacefleet.commander.passive_skills import (
        anti_mutiny_suppressed,
        end_of_turn_hull_regen,
        end_of_turn_shield_regen,
    )

    for ship in state.alive_ships():
        # Anti-mutiny passive (iron_discipline): suppress mutiny near flagship.
        if ship.morale <= 0 and anti_mutiny_suppressed(state, ship):
            ship.morale = 1

        # Mutiny: shields stop regenerating
        if ship.morale <= 0:
            fire_dmg = ship.apply_fire_damage()
            shields = 0
        else:
            shields, fire_dmg = apply_end_of_turn(ship)
            # Passive shield regen (shield_harmonics)
            extra_shields = end_of_turn_shield_regen(state, ship)
            if extra_shields > 0:
                before = ship.shields_current
                ship.shields_current = min(ship.hull.shields, ship.shields_current + extra_shields)
                shields += ship.shields_current - before
            # Passive hull regen when crippled (dark_blessings)
            if ship.hull_current < ship.hull.hull_hits * 0.5:
                extra_hull = end_of_turn_hull_regen(state, ship)
                if extra_hull > 0:
                    ship.hull_current = min(ship.hull.hull_hits, ship.hull_current + extra_hull)

        if shields > 0 or fire_dmg > 0:
            emit(EndOfTurnEvent(ship=ship, shields_regen=shields, fire_damage=fire_dmg))
        if not ship.alive:
            _credit_destroyed_ship(state, ship.id, emit=emit)

        # Fire suppression upgrade — chance to self-extinguish one fire
        if ship.fires > 0:
            from spacefleet.commander.upgrade_effects import (
                FireSuppressedByUpgradeEvent,
                fire_extinguish_chance,
            )

            suppress_p = fire_extinguish_chance(ship)
            if suppress_p > 0 and state.dice.chance(suppress_p):
                ship.fires = max(0, ship.fires - 1)
                emit(FireSuppressedByUpgradeEvent(ship_id=ship.id, fires_remaining=ship.fires))

        # Fire extinguishing — leadership check
        if ship.fires > 0:
            roll = state.dice.d6()
            if roll <= ship.effective_leadership:
                ship.fires = max(0, ship.fires - 1)
                emit(
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
                emit(
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
        ship.regenerate_combustion(15 + ship.combustion_regen_bonus)

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
                emit(
                    MoraleChangeEvent(
                        ship=ship,
                        old_morale=old_m,
                        new_morale=ship.morale,
                        source="recovery",
                    )
                )

    # ── 4. BATTLE-END AWARDS ─────────────────────────────────
    if state.is_game_over() and not state.xp_awarded:
        state.xp_awarded = True
        _award_battle_end(state, emit)

    if on_phase is not None:
        on_phase("end", state)
    return log


# ── Helpers ──────────────────────────────────────────────────


def _award_battle_end(state: GameState, emit: Callable[[TurnEvent], None]) -> None:
    """On game over: award commander XP and bump surviving crews' veterancy."""
    from spacefleet.commander.progression import (
        apply_xp,
        bump_crew_veterancy,
        compute_battle_xp_for_fleet,
    )

    alive_factions = {s.faction for s in state.ships.values() if s.alive}
    winning_faction = next(iter(alive_factions)) if len(alive_factions) == 1 else None

    candidates = [fid for fid, n in state.kills.items() if n > 0]
    first_blood_fleet_id = min(candidates) if candidates else None

    for fleet_id, fleet in state.fleets.items():
        if fleet.commander is None:
            continue
        survived = bool(fleet.alive_ships_in(state))
        won = winning_faction is not None and fleet.commander.faction == winning_faction
        # Sprint 5 simplification: count all credited kills as escorts.
        xp = compute_battle_xp_for_fleet(
            fleet_kill_capitals=0,
            fleet_kill_escorts=state.kills.get(fleet_id, 0),
            won=won,
            survived=survived,
            first_blood=(fleet_id == first_blood_fleet_id),
        )
        for ev in apply_xp(fleet.commander, xp):
            emit(ev)
        for ship in fleet.alive_ships_in(state):
            for ev in bump_crew_veterancy(ship):
                emit(ev)


def _credit_destroyed_ship(
    state: GameState,
    target_ship_id: str,
    *,
    killer_ship_id: str | None = None,
    killer_fleet_id: str | None = None,
    emit: Callable[[TurnEvent], None],
) -> None:
    """Emit destruction effects once and credit an attributable enemy kill."""
    if target_ship_id in state.credited_destroyed_ship_ids:
        return
    destroyed = state.ships.get(target_ship_id)
    if destroyed is None or destroyed.alive:
        return

    state.credited_destroyed_ship_ids.add(target_ship_id)

    killer_faction = None
    owner = None
    if killer_ship_id is not None:
        killer = state.ships.get(killer_ship_id)
        if killer is not None:
            killer_faction = killer.faction
        owner = state.owner_of(killer_ship_id)
    elif killer_fleet_id is not None:
        fleet = state.fleets.get(killer_fleet_id)
        if fleet is not None:
            if fleet.commander is not None:
                killer_faction = fleet.commander.faction
            else:
                fleet_ships = fleet.ships_in(state)
                if fleet_ships:
                    killer_faction = fleet_ships[0].faction
        if killer_fleet_id in state.kills:
            owner = killer_fleet_id

    credited_owner = (
        owner
        if owner is not None and killer_faction is not None and killer_faction != destroyed.faction
        else None
    )
    if credited_owner is not None:
        state.kills[credited_owner] = state.kills.get(credited_owner, 0) + 1
    emit(DestroyedEvent(ship=destroyed, killer_player=credited_owner))

    # Morale effects from destruction on nearby ships
    for other in state.alive_ships():
        dist = geo_distance(other.position, destroyed.position)
        if dist > 30.0:
            continue
        if other.faction == destroyed.faction:
            # Ally destroyed nearby: -15 morale
            old_m = other.morale
            other.apply_morale_change(-15)
            if other.morale != old_m:
                emit(
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
                emit(
                    MoraleChangeEvent(
                        ship=other,
                        old_morale=old_m,
                        new_morale=other.morale,
                        source="enemy destroyed",
                    )
                )
