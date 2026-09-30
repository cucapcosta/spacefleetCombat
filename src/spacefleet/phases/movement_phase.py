"""Movement phase resolver.

Handles morale speed caps, applies speed/turn orders (spending
combustion through ``Ship.set_speed``), then drifts every alive ship.
A turn's movement is two halves; the ordered turn is split between them
and never carries over to the next turn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.models.morale import speed_cap

if TYPE_CHECKING:
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Vector2D
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


def apply_move_orders(
    ships: list[Ship],
    orders: dict[str, MoveOrder],
    *,
    state: CoreGameState | None = None,
) -> list[MoveEvent]:
    """Apply morale caps and speed / turn orders once, at the start of movement.

    1. Morale-driven speed cap (``models.morale.speed_cap``).
    2. Per-ship speed orders (combustion spent via ``Ship.set_speed`` when
       over-burning).
    3. Per-ship turn orders, clamped to ``Ship.max_turn_this_turn`` at the
       new speed.  Turns never carry over: any leftover ``pending_turn`` is
       dropped first.
    """
    events: list[MoveEvent] = []

    for ship in ships:
        if not ship.alive:
            continue
        ship.pending_turn = 0.0
        speed_max = ship.effective_speed_max
        if state is not None:
            from spacefleet.commander.passive_skills import (
                effective_speed_max_with_passives,
            )

            speed_max = effective_speed_max_with_passives(ship, state)
        cap = speed_cap(ship.morale_state(), speed_max)
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

        if order.turn_degrees:
            limit = ship.max_turn_this_turn(ship.speed)
            degrees = math.copysign(min(abs(order.turn_degrees), limit), order.turn_degrees)
            if degrees == 0.0:
                continue
            ship.apply_turn(degrees)
            events.append(
                MoveEvent(
                    kind="turn",
                    ship_id=ship.id,
                    turn_direction=order.turn_direction,
                    turn_degrees=abs(degrees),
                    detail=f"{degrees:+.0f}°",
                ),
            )

    return events


def drift_ship(
    ship: Ship,
    fraction: float,
    *,
    remaining: float = 1.0,
    substeps: int = 1,
) -> list[tuple[Vector2D, float]]:
    """Move *ship* for *fraction* of the turn, *remaining* of it still to go.

    Executes the matching share of the ordered turn (``pending_turn ×
    fraction / remaining``), so a turn split in halves turns half in each.
    Returns ``(position, heading)`` at the start and after each of the
    *substeps* equal straight-line-sampled steps.
    """
    turn = ship.pending_turn * fraction / remaining if remaining > 0 else 0.0
    path = [(ship.position, ship.heading)]
    for _ in range(substeps):
        ship.drift(fraction / substeps, turn / substeps)
        path.append((ship.position, ship.heading))
    return path


def resolve_movement_phase(
    ships: list[Ship],
    orders: dict[str, MoveOrder],
    *,
    drift_fraction: float = 1.0,
    state: CoreGameState | None = None,
) -> list[MoveEvent]:
    """Apply orders (:func:`apply_move_orders`) then drift; return events.

    Ships move for *drift_fraction* of the turn (a full turn by default),
    turning that share of their ordered turn.  Salvos are not involved; the
    turn resolver moves ships and salvos together via
    ``core.game_loop.advance_half``.
    """
    events = apply_move_orders(ships, orders, state=state)

    for ship in ships:
        if not ship.alive:
            continue
        path = drift_ship(ship, drift_fraction)
        if drift_fraction >= 1.0:
            ship.pending_turn = 0.0
        events.append(
            MoveEvent(
                kind="drift",
                ship_id=ship.id,
                heading_before=path[0][1],
                heading_after=path[-1][1],
                detail=f"hdg {path[0][1]:.0f}→{path[-1][1]:.0f}",
            ),
        )

    return events
