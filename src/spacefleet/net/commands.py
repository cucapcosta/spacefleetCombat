"""Command dataclass and server-side validation.

Every costed action a player can issue is represented as a :class:`Command`.
The :func:`validate_command` function validates a raw dict from the wire
against the authoritative game state — **never trust the client**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from spacefleet.spatial.geometry import is_in_arc

if TYPE_CHECKING:
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
    args: dict[str, Any] = msg.get("args", {})

    # Ownership check
    if owner_lookup.get(ship_id) != player_id:
        return f"You do not control ship '{ship_id}'."

    # Ship alive?
    if not ship.alive:
        return f"{ship.name} is destroyed."

    # ── Validate by action type ──

    if action == "fire":
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

    try:
        slot_id = int(slot_raw)
    except (ValueError, TypeError):
        return f"Invalid weapon slot: {slot_raw}"

    try:
        bearing = float(bearing_raw) % 360.0
    except (ValueError, TypeError):
        return f"Invalid bearing: {bearing_raw}"

    weapon = next((w for w in ship.weapons if w.slot_id == slot_id), None)
    if weapon is None:
        return f"No weapon in slot {slot_id}."

    if not weapon.can_fire:
        return f"{weapon.weapon.name} is on cooldown."

    if not is_in_arc(ship.heading, bearing, weapon.arc):
        return f"Bearing {bearing:.0f}\u00b0 is outside {weapon.arc.value} arc."

    return Command(
        ship_id=ship_id,
        action="fire",
        args={"slot": slot_id, "bearing": bearing},
    )


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
        return (
            f"Invalid subsystem: '{subsystem}'."
            f" Valid: {', '.join(sorted(valid_subsystems))}"
        )

    return Command(
        ship_id=ship_id,
        action="strike",
        args={"target": str(target_id), "subsystem": subsystem},
    )
