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
class Command:
    """A validated action for a single ship."""

    ship_id: str
    action: str  # "fire" | "ahead" | "stop" | "turn" | "pass"
    args: dict[str, Any] = field(default_factory=dict)


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

    # Ownership check
    if owner_lookup.get(ship_id) != player_id:
        return f"You do not control ship '{ship_id}'."

    # Ship alive?
    if not ship.alive:
        return f"{ship.name} is destroyed."

    # ── Validate by action type ──

    if action == "fire":
        if "shots" in args:
            if "slot" in args or "bearing" in args:
                return "fire cannot combine 'shots' with 'slot' or 'bearing'."
            return _validate_fire_shots(ship_id, args["shots"], ship)
        return _validate_fire(ship_id, args, ship)
    if action == "ahead":
        return _validate_ahead(ship_id, args, ship)
    if action == "stop":
        return Command(ship_id=ship_id, action="stop", args={})
    if action == "turn":
        return _validate_turn(ship_id, args, ship)
    if action == "pass":
        return Command(ship_id=ship_id, action="pass", args={})
    if action == "strike":
        return _validate_strike(ship_id, args, ship)

    return f"Unknown action: '{action}'"


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


def _validate_ahead(
    ship_id: str,
    args: dict[str, Any],
    ship: Ship,
) -> Command | str:
    speed_raw = args.get("speed")

    if speed_raw is None:
        # No arg → full speed
        return Command(
            ship_id=ship_id,
            action="ahead",
            args={"speed": ship.speed_max},
        )

    try:
        speed = float(speed_raw)
    except (ValueError, TypeError):
        return f"Invalid speed: {speed_raw}"

    speed = max(0.0, min(ship.speed_max, speed))
    return Command(
        ship_id=ship_id,
        action="ahead",
        args={"speed": speed},
    )


def _validate_turn(
    ship_id: str,
    args: dict[str, Any],
    ship: Ship,
) -> Command | str:
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

    if degrees < 0:
        return "Degrees must be positive. Use direction for port/starboard."

    direction_label = "port" if direction in ("port", "p", "left") else "starboard"

    return Command(
        ship_id=ship_id,
        action="turn",
        args={"direction": direction_label, "degrees": degrees},
    )


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
