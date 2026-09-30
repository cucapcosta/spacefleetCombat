"""Command dataclass and server-side validation.

Every costed action a player can issue is represented as a :class:`Command`.
The :func:`validate_command` function validates a raw dict from the wire
against the authoritative game state — **never trust the client**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from spacefleet.spatial.geometry import absolute_bearing, arc_range_str, is_in_arc

if TYPE_CHECKING:
    from spacefleet.core.types import Vector2D
    from spacefleet.models.ship import Ship


@dataclass
class Maneuver:
    """Speed and heading change for one turn; free alongside the ship's action."""

    speed: float | None = None  # target speed; None keeps the current speed
    turn: float = 0.0  # degrees this turn; + starboard, - port; never carries over


@dataclass
class Command:
    """A validated order for a single ship: one action plus an optional maneuver.

    ``action`` is "fire" | "strike" | "pass".  The legacy movement actions
    "ahead" | "stop" | "turn" are still accepted on the wire and are
    normalised to a maneuver plus "pass" (see group E3).
    """

    ship_id: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    maneuver: Maneuver | None = None


def validate_command(
    msg: dict[str, Any],
    ship: Ship,
    player_id: str,
    owner_lookup: dict[str, str],
) -> Command | str:
    """Validate a command message from the client.

    Returns a :class:`Command` on success, or an error string on failure.

    Parameters
    ----------
    msg:
        Raw JSON dict from the client.
    ship:
        The ship the command targets (already looked up).
    player_id:
        The authenticated player sending this command.
    owner_lookup:
        Mapping of ship_id → player_id for ownership checks.
    """
    ship_id = msg.get("ship_id", "")
    action = msg.get("action", "")
    args_raw = msg.get("args", {})
    if not isinstance(args_raw, dict):
        return "Command args must be an object."
    args: dict[str, Any] = args_raw

    denied = _check_control(ship_id, ship, player_id, owner_lookup)
    if denied is not None:
        return denied

    maneuver_raw = msg.get("maneuver")
    requested = _parse_maneuver(maneuver_raw, ship) if maneuver_raw is not None else None
    if isinstance(requested, str):
        return requested

    # ── Legacy movement actions: a maneuver plus "pass" ──

    if action in _LEGACY_MOVES:
        legacy = _legacy_maneuver(action, args, ship, requested)
        if isinstance(legacy, str):
            return legacy
        return Command(ship_id=ship_id, action="pass", args={}, maneuver=legacy)

    # ── Validate by action type ──

    result: Command | str
    if action == "fire":
        if "shots" in args:
            if "slot" in args or "bearing" in args:
                return "fire cannot combine 'shots' with 'slot' or 'bearing'."
            result = _validate_fire_shots(ship_id, args["shots"], ship)
        else:
            result = _validate_fire(ship_id, args, ship)
    elif action == "pass":
        result = Command(ship_id=ship_id, action="pass", args={})
    elif action == "strike":
        result = _validate_strike(ship_id, args, ship)
    elif action == "move":
        return "move is a free maneuver; follow it with fire, strike or pass."
    else:
        return f"Unknown action: '{action}'"

    if isinstance(result, Command):
        result.maneuver = requested
    return result


def validate_move(
    msg: dict[str, Any],
    ship: Ship,
    player_id: str,
    owner_lookup: dict[str, str],
) -> Maneuver | str:
    """Validate a free ``move`` message and return its :class:`Maneuver`.

    Wire shape: ``{"action": "move", "ship_id": ..., "maneuver": {"speed":
    number | null, "turn": number}}``.  The maneuver rides on the ship's
    next costed command (see ``GameRoom``).
    """
    denied = _check_control(msg.get("ship_id", ""), ship, player_id, owner_lookup)
    if denied is not None:
        return denied
    maneuver_raw = msg.get("maneuver")
    if maneuver_raw is None:
        return "move requires a 'maneuver' object."
    return _parse_maneuver(maneuver_raw, ship)


def _check_control(
    ship_id: str,
    ship: Ship,
    player_id: str,
    owner_lookup: dict[str, str],
) -> str | None:
    if owner_lookup.get(ship_id) != player_id:
        return f"You do not control ship '{ship_id}'."
    if not ship.alive:
        return f"{ship.name} is destroyed."
    return None


# ── Maneuver ─────────────────────────────────────────────────

_LEGACY_MOVES = ("ahead", "stop", "turn")


def _maneuver_number(raw: object, label: str) -> float | str:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return f"Invalid maneuver {label}: {raw!r}"
    value = float(raw)
    if not math.isfinite(value):
        return f"Invalid maneuver {label}: value must be finite."
    return value


def _parse_maneuver(raw: object, ship: Ship) -> Maneuver | str:
    """Validate a wire ``{"speed": number | null, "turn": number}`` object."""
    if not isinstance(raw, dict):
        return "Command maneuver must be an object."

    speed: float | None = None
    if raw.get("speed") is not None:
        parsed = _maneuver_number(raw["speed"], "speed")
        if isinstance(parsed, str):
            return parsed
        if parsed < 0:
            return "Maneuver speed must be 0 or more."
        # Over-burn above the damaged cap is allowed up to the hull speed,
        # as with the legacy ``ahead``; combustion pays for it.
        speed = min(ship.speed_max, parsed)

    turn = _maneuver_number(raw.get("turn", 0.0), "turn")
    if isinstance(turn, str):
        return turn
    return _check_turn_limit(Maneuver(speed=speed, turn=turn), ship)


def _check_turn_limit(maneuver: Maneuver, ship: Ship) -> Maneuver | str:
    speed_after = ship.speed if maneuver.speed is None else maneuver.speed
    limit = ship.max_turn_this_turn(speed_after)
    if abs(maneuver.turn) > limit + 1e-9:
        return (
            f"Turn {abs(maneuver.turn):g}\u00b0 exceeds this ship's limit of "
            f"{limit:g}\u00b0 this turn."
        )
    return maneuver


def _legacy_maneuver(
    action: str,
    args: dict[str, Any],
    ship: Ship,
    base: Maneuver | None,
) -> Maneuver | str:
    """Turn a legacy ``ahead``/``stop``/``turn`` into a maneuver.

    The legacy order sets its own field; the other one comes from *base*
    (an explicit maneuver sent alongside), then the turn limit is checked.
    """
    maneuver = Maneuver() if base is None else Maneuver(base.speed, base.turn)
    if action == "ahead":
        speed = _validate_ahead(args, ship)
        if isinstance(speed, str):
            return speed
        maneuver.speed = speed
    elif action == "stop":
        maneuver.speed = 0.0
    else:
        turn = _validate_turn(args)
        if isinstance(turn, str):
            return turn
        maneuver.turn = turn
    return _check_turn_limit(maneuver, ship)


# ── Per-action validators ────────────────────────────────────


def _validate_fire(
    ship_id: str,
    args: dict[str, Any],
    ship: Ship,
) -> Command | str:
    slot_raw = args.get("slot")
    bearing_raw = args.get("bearing")

    if slot_raw is None or bearing_raw is None:
        return "fire requires 'slot' (int) and 'bearing' (float)."

    if isinstance(slot_raw, bool) or not isinstance(slot_raw, (int, str)):
        return f"Invalid weapon slot: {slot_raw}"
    try:
        slot_id = int(slot_raw)
    except ValueError:
        return f"Invalid weapon slot: {slot_raw}"

    try:
        bearing = float(bearing_raw)
    except OverflowError:
        return "Invalid bearing: value is too large."
    except (ValueError, TypeError):
        return f"Invalid bearing: {bearing_raw}"
    if not math.isfinite(bearing):
        return f"Invalid bearing: {bearing_raw}"
    bearing %= 360.0

    weapon = next((w for w in ship.weapons if w.slot_id == slot_id), None)
    if weapon is None:
        return f"No weapon in slot {slot_id}."

    if not weapon.can_fire:
        if weapon.cooldown > 0:
            return f"{weapon.weapon.name} is on cooldown."
        return f"{weapon.weapon.name} is unavailable."

    # Fire bearings are prow-relative (0° ahead, clockwise); the resolver
    # converts them with the heading the ship holds during the fire phase.
    if not is_in_arc(ship.heading, absolute_bearing(ship.heading, bearing), weapon.arc):
        return (
            f"Bearing {bearing:.0f}\u00b0 rel is outside {weapon.arc.value} arc "
            f"({arc_range_str(weapon.arc)})."
        )

    fire_args: dict[str, Any] = {"slot": slot_id, "bearing": bearing}
    # Optional fire-control lock: the resolver re-checks detection itself.
    target_raw = args.get("target")
    if target_raw is not None:
        if not isinstance(target_raw, str) or not target_raw:
            return f"Invalid fire target: {target_raw}"
        fire_args["target"] = target_raw

    return Command(ship_id=ship_id, action="fire", args=fire_args)


def _validate_fire_shots(
    ship_id: str,
    shots_raw: object,
    ship: Ship,
) -> Command | str:
    if not isinstance(shots_raw, list):
        return "fire 'shots' must be a list."
    if not shots_raw:
        return "fire 'shots' must not be empty."
    if len(shots_raw) > len(ship.weapons):
        return "fire cannot include more shots than mounted weapons."

    shots: list[dict[str, Any]] = []
    used_slots: set[int] = set()
    for index, shot_raw in enumerate(shots_raw, start=1):
        if not isinstance(shot_raw, dict):
            return f"Invalid fire shot {index}: expected an object."
        validated = _validate_fire(ship_id, shot_raw, ship)
        if isinstance(validated, str):
            return f"Invalid fire shot {index}: {validated}"
        slot_id: int = validated.args["slot"]
        if slot_id in used_slots:
            return f"Invalid fire shot {index}: weapon slot {slot_id} is duplicated."
        used_slots.add(slot_id)
        shots.append(validated.args)

    return Command(ship_id=ship_id, action="fire", args={"shots": shots})


def _validate_ahead(args: dict[str, Any], ship: Ship) -> float | str:
    """Target speed of a legacy ``ahead``; no arg means full speed."""
    speed_raw = args.get("speed")

    if speed_raw is None:
        return ship.speed_max

    try:
        speed = float(speed_raw)
    except (ValueError, TypeError):
        return f"Invalid speed: {speed_raw}"
    if not math.isfinite(speed):
        return f"Invalid speed: {speed_raw}"

    return max(0.0, min(ship.speed_max, speed))


def _validate_turn(args: dict[str, Any]) -> float | str:
    """Signed degrees of a legacy ``turn`` (+ starboard, - port)."""
    direction = args.get("direction", "")
    degrees_raw = args.get("degrees")

    if direction not in ("starboard", "stbd", "s", "right", "port", "p", "left"):
        return f"Invalid direction: '{direction}'. Use 'starboard' or 'port'."

    if degrees_raw is None:
        return "turn requires 'degrees'."

    try:
        degrees = float(degrees_raw)
    except (ValueError, TypeError):
        return f"Invalid degrees: {degrees_raw}"
    if not math.isfinite(degrees):
        return f"Invalid degrees: {degrees_raw}"

    if degrees < 0:
        return "Degrees must be positive. Use direction for port/starboard."

    return -degrees if direction in ("port", "p", "left") else degrees


def _validate_strike(
    ship_id: str,
    args: dict[str, Any],
    ship: Ship,
) -> Command | str:
    """Validate a Lightning Strike (ranged boarding) command."""
    target_id = args.get("target")
    subsystem = args.get("subsystem")

    if not target_id:
        return "strike requires 'target' (ship ID)."

    if ship.hull.assault_actions <= 0:
        return f"{ship.name} has no boarding capability."

    valid_subsystems = {"generator", "deck", "engines", "weapons"}
    if subsystem and subsystem not in valid_subsystems:
        return f"Invalid subsystem: '{subsystem}'. Valid: {', '.join(sorted(valid_subsystems))}"

    return Command(
        ship_id=ship_id,
        action="strike",
        args={"target": str(target_id), "subsystem": subsystem},
    )


@dataclass
class AbilityOrder:
    """A commander ability invocation.

    Separate from :class:`Command` — rides its own channel to
    ``resolve_turn`` and does not replace a ship's move/fire order.
    """

    fleet_id: str
    ability_id: str
    target_ship_id: str | None = None
    target_position: Vector2D | None = None
