"""Per-turn order drafting and validation, independent of any UI.

Every validator returns either the validated value or a ``str`` giving the
reason it was rejected, so widgets can show the reason inline.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from spacefleet.cli.action_parser import parse_action_command
from spacefleet.combat.fire_control import aim_for
from spacefleet.commander.abilities import (
    AreaHullDamage,
    AreaMoraleDamage,
    BonusBoardingAssault,
    ConcentratedFireBuff,
    SpawnProbe,
    Teleport,
)
from spacefleet.core.types import DetectionLevel, Stance, Vector2D
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.net.commands import AbilityOrder, Command, validate_command
from spacefleet.net.server_renderer import ServerRenderer
from spacefleet.phases.command_phase import validate_ability_order
from spacefleet.phases.movement_phase import MoveOrder, resolve_movement_phase
from spacefleet.spatial.geometry import bearing_from_to, distance, relative_bearing_360

if TYPE_CHECKING:
    from spacefleet.campaign.battle import BattleSession
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.models.ship import Ship
    from spacefleet.spatial.detection import ContactInfo

Shot = dict[str, int | float | str]

# Stateless: previews copy the dice so the authoritative RNG never advances.
_RENDERER = ServerRenderer()


@dataclass(frozen=True)
class Aim:
    """Prow-relative bearing and distance one weapon would fire at.

    A None bearing means no intercept.

    *target_id* locks fire control on a contact; *lock* is how well it is seen.
    Manual bearings carry no lock and fire with the widest spread.
    """

    bearing: float | None
    distance: float | None
    target_id: str | None = None
    lock: DetectionLevel = DetectionLevel.UNDETECTED


@dataclass
class OrderDraft:
    """Orders queued so far this turn, keyed by ship id."""

    commands: dict[str, Command] = field(default_factory=dict)
    stances: dict[str, Stance] = field(default_factory=dict)
    ability: AbilityOrder | None = None


def alive_player_ids(session: BattleSession) -> list[str]:
    state = session.state
    return [
        ship_id for ship_id in state.player_ships[session.player_id] if state.ships[ship_id].alive
    ]


def relative_to(ship: Ship, position: Vector2D) -> float:
    return relative_bearing_360(ship.heading, bearing_from_to(ship.position, position))


# ── fire ────────────────────────────────────────────────────────────


def fire_blocker(
    session: BattleSession, ship: Ship, slot: int, *, aim: Aim, used_slots: set[int]
) -> tuple[str, str] | None:
    """Return ``(kind, message)`` explaining why *slot* cannot fire, or None."""
    if slot in used_slots:
        return "queued", "Already queued in this salvo."
    mount = next(mount for mount in ship.weapons if mount.slot_id == slot)
    if not mount.can_fire:
        if mount.cooldown > 0:
            return "cooldown", f"Unavailable: cooldown for {mount.cooldown} more turn(s)."
        return "damaged", "Unavailable: weapon disabled by damage."
    if aim.bearing is None:
        return "out of range", (
            f"Unavailable: no intercept within range {mount.weapon.range:g} GU."
        )
    validated = validate_command(
        {
            "ship_id": ship.id,
            "action": "fire",
            "args": {"slot": slot, "bearing": aim.bearing},
        },
        ship,
        session.player_id,
        session.state.owner_lookup(),
    )
    if isinstance(validated, str):
        kind = "out of arc" if "outside" in validated else "invalid"
        return kind, f"Unavailable: {validated}"
    if aim.distance is not None and aim.distance > mount.weapon.range:
        return "out of range", (
            f"Unavailable: target at {aim.distance:.0f} GU exceeds range {mount.weapon.range:g} GU."
        )
    return None


def fire_unavailable_reason(
    session: BattleSession, ship: Ship, slot: int, *, aim: Aim, used_slots: set[int]
) -> str | None:
    blocker = fire_blocker(session, ship, slot, aim=aim, used_slots=used_slots)
    return None if blocker is None else blocker[1]


def contact_aims(session: BattleSession, ship: Ship, contact: ContactInfo) -> dict[int, Aim]:
    """Per-weapon aim on *contact*: lead bearing for projectiles, direct for lances.

    BLIPs expose no course data, so they only get a direct bearing.
    """
    if not contact.targetable:
        bearing = relative_to(ship, contact.display_position)
        reach = distance(ship.position, contact.display_position)
        return {mount.slot_id: Aim(bearing, reach) for mount in ship.weapons}
    aims: dict[int, Aim] = {}
    for mount in ship.weapons:
        solution = aim_for(ship, mount, contact.ship, contact.display_position)
        if solution is not None:
            aims[mount.slot_id] = Aim(
                round(relative_bearing_360(ship.heading, solution.bearing), 2) % 360.0,
                solution.intercept_distance,
                contact.ship.id,
                contact.detection_level,
            )
        else:
            aims[mount.slot_id] = Aim(None, None)
    return aims


def contact_blockers(
    session: BattleSession, ship: Ship, contact: ContactInfo, used_slots: set[int]
) -> dict[int, tuple[str, str] | None]:
    aims = contact_aims(session, ship, contact)
    return {
        mount.slot_id: fire_blocker(
            session, ship, mount.slot_id, aim=aims[mount.slot_id], used_slots=used_slots
        )
        for mount in ship.weapons
    }


def blocker_summary(blockers: dict[int, tuple[str, str] | None]) -> str:
    counts: dict[str, int] = {}
    for blocker in blockers.values():
        if blocker is not None:
            counts[blocker[0]] = counts.get(blocker[0], 0) + 1
    return ", ".join(f"{count} {kind}" for kind, count in counts.items())


def validated_fire_salvo(session: BattleSession, ship: Ship, shots: list[Shot]) -> Command | str:
    return validate_command(
        {"ship_id": ship.id, "action": "fire", "args": {"shots": shots}},
        ship,
        session.player_id,
        session.state.owner_lookup(),
    )


# ── contacts ────────────────────────────────────────────────────────


def hostile_contacts(session: BattleSession, observer: Ship) -> list[ContactInfo]:
    """Hostiles *observer* can target by id (never BLIPs)."""
    return [
        contact
        for contact in _RENDERER.preview_contacts(observer, session.state, session.player_id)
        if not contact.is_friendly
        and contact.targetable
        and contact.detection_level is not DetectionLevel.BLIP
    ]


# ── commands and stances ────────────────────────────────────────────


def stance_rejection(ship: Ship, stance: Stance) -> str | None:
    if stance is ship.stance:
        return None
    if ship.stance_cooldown_remaining > 0:
        return f"Locked for {ship.stance_cooldown_remaining} more turn(s)."
    if not ship.subsystems.deck:
        return "Deck subsystem is damaged."
    if ship.morale <= 0:
        return "Crew has mutinied."
    return None


def validated_command(session: BattleSession, ship: Ship, tokens: list[str]) -> Command | str:
    """Parse CLI-style *tokens* (e.g. ``["turn", "port", "30"]``) and validate them."""
    raw = parse_action_command(ship.id, tokens)
    if isinstance(raw, str):
        return raw
    return validate_command(
        cast("dict[str, Any]", raw),
        ship,
        session.player_id,
        session.state.owner_lookup(),
    )


# ── movement preview ────────────────────────────────────────────────


def predict_move(
    ship: Ship,
    target_speed: float | None,
    turn_direction: str,
    turn_degrees: float,
    *,
    state: CoreGameState | None = None,
) -> tuple[Vector2D, float]:
    """Position and heading *ship* would end this turn's movement at.

    Runs the movement phase on a copy, so *ship* is untouched.  Pass *state*
    to include passive speed bonuses, as the turn resolver does.
    """
    ghost = copy.deepcopy(ship)
    order = MoveOrder(target_speed=target_speed)
    if turn_direction and turn_degrees:
        order.turn_degrees = -turn_degrees if turn_direction == "port" else turn_degrees
        order.turn_direction = turn_direction
    resolve_movement_phase([ghost], {ghost.id: order}, drift_fraction=0.5, state=state)
    return ghost.position, ghost.heading


# ── commander ability ───────────────────────────────────────────────


def ability_targeting(ability_id: str) -> tuple[bool, bool]:
    """``(needs_ship_target, needs_position_target)`` for *ability_id*."""
    definition = SkillRegistry.get_active(ability_id)
    if definition is None:
        return False, False
    ship_target = any(
        isinstance(step, (ConcentratedFireBuff, BonusBoardingAssault)) for step in definition.steps
    )
    position_target = any(
        isinstance(step, (Teleport, AreaHullDamage, AreaMoraleDamage, SpawnProbe))
        for step in definition.steps
    )
    return ship_target, position_target


def ability_ship_targets(session: BattleSession, ability_id: str) -> list[tuple[str, str]]:
    """``(ship_id, name)`` pairs *ability_id* may target, seen from the flagship."""
    definition = SkillRegistry.get_active(ability_id)
    state = session.state
    flagship = state.fleets[session.player_id].flagship_in(state)
    if definition is None or flagship is None:
        return []
    targets = [(ci.ship.id, ci.display_name) for ci in hostile_contacts(session, flagship)]
    if any(isinstance(step, ConcentratedFireBuff) for step in definition.steps):
        targets.extend(
            (ship_id, state.ships[ship_id].name) for ship_id in alive_player_ids(session)
        )
    return targets


def ability_order(
    session: BattleSession,
    ability_id: str,
    *,
    target_ship_id: str | None = None,
    target_position: Vector2D | None = None,
) -> AbilityOrder | str:
    """Build and validate the player's commander ability order."""
    definition = SkillRegistry.get_active(ability_id)
    if definition is None:
        return f"Unknown ability {ability_id!r}."
    ship_target, position_target = ability_targeting(ability_id)
    if ship_target:
        allowed = {ship_id for ship_id, _name in ability_ship_targets(session, ability_id)}
        if target_ship_id not in allowed:
            return "Choose a valid target ship."
    else:
        target_ship_id = None
    if position_target:
        if target_position is None:
            return "Choose a target position."
        if not math.isfinite(target_position.x) or not math.isfinite(target_position.y):
            return "Coordinates must be finite."
    else:
        target_position = None
    order = AbilityOrder(
        fleet_id=session.player_id,
        ability_id=ability_id,
        target_ship_id=target_ship_id,
        target_position=target_position,
    )
    fleet = session.state.fleets[session.player_id]
    commander = fleet.commander
    if commander is None:
        return "Fleet has no commander."
    rejection = validate_ability_order(
        session.state, fleet, commander, order, cooldown_will_tick=True
    )
    return order if rejection is None else rejection


# ── turn submission ─────────────────────────────────────────────────


def finalize(
    draft: OrderDraft, session: BattleSession
) -> tuple[dict[str, Command], dict[str, Stance], AbilityOrder | None] | str:
    """Complete *draft* for resolution: ``pass`` for idle ships, stances rechecked.

    Returns the reason as a string when a queued stance is no longer allowed.
    """
    state = session.state
    commands: dict[str, Command] = {}
    for ship_id in alive_player_ids(session):
        commands[ship_id] = draft.commands.get(ship_id) or Command(ship_id=ship_id, action="pass")
    stances: dict[str, Stance] = {}
    for ship_id, stance in draft.stances.items():
        ship = state.ships[ship_id]
        if not ship.alive:
            continue
        rejection = stance_rejection(ship, stance)
        if rejection is not None:
            return f"{ship.name}: stance {stance.value.replace('_', ' ')} rejected — {rejection}"
        stances[ship_id] = stance
    return commands, stances, draft.ability
