"""Shared parsing for player ship actions."""

from __future__ import annotations

import math

from spacefleet.net.protocol import MSG_COMMAND


def _finite_number(raw: str, label: str) -> float | str:
    try:
        value = float(raw)
    except ValueError:
        return f"Invalid {label}: {raw!r}."
    if not math.isfinite(value):
        return f"Invalid {label}: value must be finite."
    return value


_PORT = ("port", "p", "left")
_STARBOARD = ("starboard", "stbd", "s", "right")
_MOVE_USAGE = "Usage: move <speed|-> [port|starboard <degrees>]."


def _parse_move(args: list[str]) -> dict[str, object] | str:
    """``move <speed|-> [port|starboard <deg>]`` → wire maneuver object."""
    if not args:
        return _MOVE_USAGE
    speed: float | None = None
    if args[0] != "-":
        parsed = _finite_number(args[0], "speed")
        if isinstance(parsed, str):
            return parsed
        speed = parsed
    turn = 0.0
    rest = args[1:]
    if rest:
        direction = rest[0].lower()
        if direction not in _PORT + _STARBOARD or len(rest) != 2:
            return _MOVE_USAGE
        degrees = _finite_number(rest[1], "degrees")
        if isinstance(degrees, str):
            return degrees
        if degrees < 0:
            return "Degrees must be positive. Use port or starboard for the side."
        turn = -degrees if direction in _PORT else degrees
    return {"speed": speed, "turn": turn}


def parse_action_command(ship_id: str, tokens: list[str]) -> dict[str, object] | str:
    """Parse CLI tokens into a wire-compatible command mapping or an error.

    Result shape: ``{"type": "command", "ship_id", "action", "args"}``.
    ``move`` is the free maneuver: ``action="move"``, ``args={}`` and
    ``"maneuver": {"speed": float | None, "turn": float}`` (``None`` keeps
    the current speed; turn is + starboard, - port).  The server stores it
    and attaches it to the ship's next fire/strike/pass.
    """
    if not tokens:
        return "No command entered."
    command, args = tokens[0].lower(), tokens[1:]

    if command == "move":
        maneuver = _parse_move(args)
        if isinstance(maneuver, str):
            return maneuver
        return {
            "type": MSG_COMMAND,
            "ship_id": ship_id,
            "action": "move",
            "args": {},
            "maneuver": maneuver,
        }
    if command == "fire":
        if len(args) < 2:
            return "Usage: fire <weapon#> <bearing> (relative to prow: 0 ahead, 90 starboard)."
        try:
            slot = int(args[0])
        except ValueError:
            return "Invalid fire arguments. Use: fire <weapon#> <bearing>."
        bearing = _finite_number(args[1], "bearing")
        if isinstance(bearing, str):
            return bearing
        command_args: dict[str, object] = {"slot": slot, "bearing": bearing}
    elif command == "ahead":
        if args:
            speed = _finite_number(args[0], "speed")
            if isinstance(speed, str):
                return speed
        else:
            speed = None
        command_args = {"speed": speed}
    elif command == "stop":
        command_args = {}
    elif command == "turn":
        if len(args) < 2:
            return "Usage: turn <port|starboard> <degrees>."
        degrees = _finite_number(args[1], "degrees")
        if isinstance(degrees, str):
            return degrees
        command_args = {"direction": args[0], "degrees": degrees}
    elif command == "pass":
        command_args = {}
    elif command == "strike":
        if len(args) < 2:
            return "Usage: strike <target_id> <subsystem>."
        command_args = {"target": args[0], "subsystem": args[1]}
    else:
        return f"Unknown command: {command!r}."

    return {
        "type": MSG_COMMAND,
        "ship_id": ship_id,
        "action": command,
        "args": command_args,
    }
