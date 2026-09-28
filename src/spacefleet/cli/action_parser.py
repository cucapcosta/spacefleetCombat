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


def parse_action_command(ship_id: str, tokens: list[str]) -> dict[str, object] | str:
    """Parse CLI tokens into a wire-compatible command mapping or an error."""
    if not tokens:
        return "No command entered."
    command, args = tokens[0].lower(), tokens[1:]

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
