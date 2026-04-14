"""Movement phase resolver.

Handles morale speed caps, applies speed/turn orders (spending
combustion through ``Ship.set_speed``), then drifts every alive ship.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.models.morale import speed_cap

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class MoveOrder:
    """One ship's movement intent for the phase."""

    target_speed: float | None = None
    turn_degrees: float | None = None
    turn_direction: str = ""  # "port" | "starboard" — for renderer


@dataclass
class MoveEvent:
    """Outcome event produced by the phase resolver."""

    kind: str  # "morale_cap" | "speed" | "turn" | "drift"
    ship_id: str
    detail: str = ""
    old_speed: float = 0.0
    new_speed: float = 0.0
    turn_direction: str = ""
    turn_degrees: float = 0.0
    heading_before: float = 0.0
    heading_after: float = 0.0


def resolve_movement_phase(
    ships: list[Ship],
    orders: dict[str, MoveOrder],
    *,
    drift_fraction: float = 0.5,
) -> list[MoveEvent]:
    """Apply morale caps + orders + drift; return events.

    Order is:

    1. Morale-driven speed cap (``models.morale.speed_cap``).
    2. Per-ship speed / turn orders (combustion spent via
       ``Ship.set_speed`` when over-burning).
    3. Half-turn drift for every alive ship.
    """
    events: list[MoveEvent] = []

    for ship in ships:
        if not ship.alive:
            continue
        cap = speed_cap(ship.morale_state(), ship.effective_speed_max)
        if ship.speed > cap:
            prev = ship.speed
            ship.speed = cap
            events.append(
                MoveEvent(
                    kind="morale_cap",
                    ship_id=ship.id,
                    old_speed=prev,
                    new_speed=cap,
                    detail=f"morale cap → {cap:.0f}",
                ),
            )

    for ship in ships:
        if not ship.alive:
            continue
        order = orders.get(ship.id)
        if order is None:
            continue

        if order.target_speed is not None:
            prev = ship.speed
            ship.set_speed(order.target_speed)
            events.append(
                MoveEvent(
                    kind="speed",
                    ship_id=ship.id,
                    old_speed=prev,
                    new_speed=ship.speed,
                    detail=f"speed → {ship.speed:.0f}",
                ),
            )

        if order.turn_degrees is not None and order.turn_degrees != 0.0:
            ship.apply_turn(order.turn_degrees)
            events.append(
                MoveEvent(
                    kind="turn",
                    ship_id=ship.id,
                    turn_direction=order.turn_direction,
                    turn_degrees=abs(order.turn_degrees),
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
                heading_before=before,
                heading_after=after,
                detail=f"hdg {before:.0f}→{after:.0f}",
            ),
        )

    return events
