"""Movement phase resolver.

Applies speed/turn orders, then drifts every alive ship a half turn.
Returns a list of typed events the renderer can format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class MoveOrder:
    """One ship's movement intent for the phase."""

    target_speed: float | None = None
    turn_degrees: float | None = None


@dataclass
class MoveEvent:
    """Outcome event produced by the phase resolver."""

    kind: str  # "speed" | "turn" | "drift" | "blocked"
    ship_id: str
    detail: str = ""


def resolve_movement_phase(
    ships: list[Ship],
    orders: dict[str, MoveOrder],
    *,
    drift_fraction: float = 0.5,
) -> list[MoveEvent]:
    """Apply orders + drift, returning the events that occurred.

    Each ship drifts ``speed × drift_fraction`` GU; the default ``0.5``
    matches ``Ship.apply_drift`` and the legacy ``net.turn_resolver``.
    """
    events: list[MoveEvent] = []

    for ship in ships:
        if not ship.alive:
            continue
        order = orders.get(ship.id)
        if order is None:
            continue

        if order.target_speed is not None:
            ship.set_speed(order.target_speed)
            events.append(
                MoveEvent(
                    kind="speed",
                    ship_id=ship.id,
                    detail=f"speed → {ship.speed:.0f}",
                ),
            )

        if order.turn_degrees is not None and order.turn_degrees != 0.0:
            ship.apply_turn(order.turn_degrees)
            events.append(
                MoveEvent(
                    kind="turn",
                    ship_id=ship.id,
                    detail=f"{order.turn_degrees:+.0f}°",
                ),
            )

    for ship in ships:
        if not ship.alive:
            continue
        before, after = ship.apply_drift(drift_fraction)
        events.append(
            MoveEvent(
                kind="drift",
                ship_id=ship.id,
                detail=f"hdg {before:.0f}→{after:.0f}",
            ),
        )

    return events
