"""Capture a fog-of-war-filtered :class:`BattleSnapshot` from live game state.

The observer sees its own fleet in full; other ships appear at the best
detection level any of its alive ships has on them.  BLIP positions are
jittered with a private roller seeded from ``(turn, ship id)``, so the game's
own dice sequence is never touched and a BLIP stays put across the phases of
one turn.
"""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING

from spacefleet.core.types import DetectionLevel, ShipClass, Vector2D
from spacefleet.dice import DiceRoller
from spacefleet.spatial.detection import (
    best_detection_level,
    effective_sensor_range,
    jitter_position,
)
from spacefleet.spatial.geometry import distance
from spacefleet.tui.model.snapshot import BattleSnapshot, ProjectileView, ShipView

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship
    from spacefleet.net.game_state import GameState

CLASS_LETTERS: dict[ShipClass, str] = {
    ShipClass.ESCORT: "E",
    ShipClass.LIGHT_CRUISER: "L",
    ShipClass.CRUISER: "C",
    ShipClass.BATTLECRUISER: "B",
    ShipClass.BATTLESHIP: "S",
}


def snapshot_for(
    state: GameState,
    observer_player: str,
    phase: str,
    *,
    rng: DiceRoller | None = None,
    labels: dict[str, str] | None = None,
) -> BattleSnapshot:
    """Return what *observer_player* can see of *state* at *phase*.

    *rng* overrides the per-ship seeded roller used for BLIP jitter.
    *labels* is an optional persistent ship id -> label memo: an enemy seen
    at CONTACT or better keeps the label it first got (mutated in place).
    Without it, enemy labels are numbered among the enemies visible now.
    """
    own_ids = list(state.player_ships.get(observer_player, []))
    own_set = set(own_ids)
    observers = state.alive_ships_for(observer_player)

    views: list[ShipView] = [
        _full_view(state.ships[sid], f"{_letter(state.ships[sid])}{i + 1}")
        for i, sid in enumerate(own_ids)
    ]

    levels: dict[str, DetectionLevel] = {}
    enemy_index = 0
    for sid in sorted(state.ships):
        if sid in own_set:
            continue
        ship = state.ships[sid]
        level = (
            best_detection_level(observers, ship, state=state)
            if observers
            else DetectionLevel.UNDETECTED
        )
        levels[sid] = level
        if level == DetectionLevel.UNDETECTED:
            continue
        if level == DetectionLevel.BLIP:
            if ship.alive:
                roller = rng or _blip_roller(state.turn, sid)
                views.append(_blip_view(ship, jitter_position(ship.position, roller)))
            continue
        if labels is None:
            enemy_index += 1
            label = f"{_letter(ship)}{enemy_index}"
        else:
            label = labels.get(sid) or _next_free_label(labels, _letter(ship))
            labels[sid] = label
        if level == DetectionLevel.CONTACT:
            views.append(_contact_view(ship, label))
        else:
            views.append(_full_view(ship, label, is_player=False))

    projectiles = tuple(
        ProjectileView(
            id=p.id,
            position=_copy(p.position),
            bearing=p.bearing,
            attacker_id=p.attacker_id
            if p.attacker_id in own_set
            or levels.get(p.attacker_id, DetectionLevel.UNDETECTED).value
            >= DetectionLevel.CONTACT.value
            else None,
        )
        for p in state.projectiles
        if p.alive
        and any(
            distance(o.position, p.position) <= effective_sensor_range(o, state) for o in observers
        )
    )

    return BattleSnapshot(turn=state.turn, phase=phase, ships=tuple(views), projectiles=projectiles)


def _blip_roller(turn: int, ship_id: str) -> DiceRoller:
    return DiceRoller(seed=zlib.crc32(f"{turn}:{ship_id}".encode()))


def _next_free_label(labels: dict[str, str], letter: str) -> str:
    used = set(labels.values())
    n = 1
    while f"{letter}{n}" in used:
        n += 1
    return f"{letter}{n}"


def _letter(ship: Ship) -> str:
    return CLASS_LETTERS.get(ship.hull.classification, "?")


def _copy(v: Vector2D) -> Vector2D:
    return Vector2D(v.x, v.y)


def _full_view(ship: Ship, label: str, *, is_player: bool = True) -> ShipView:
    return ShipView(
        id=ship.id,
        label=label,
        name=ship.name,
        faction=ship.faction,
        class_letter=_letter(ship),
        position=_copy(ship.position),
        heading=ship.heading,
        detection=DetectionLevel.IDENTIFIED,
        is_player=is_player,
        alive=ship.alive,
        hull=ship.hull_current,
        hull_max=ship.hull_max,
        shields=ship.shields_current,
        shields_max=ship.shields_max,
        morale=ship.morale,
        morale_max=ship.morale_max,
        stance=ship.stance,
    )


def _contact_view(ship: Ship, label: str) -> ShipView:
    class_name = ship.hull.classification.value.replace("_", " ").title()
    return ShipView(
        id=ship.id,
        label=label,
        name=f"{class_name}-class",
        faction=ship.faction,
        class_letter=_letter(ship),
        position=_copy(ship.position),
        heading=ship.heading,
        detection=DetectionLevel.CONTACT,
        is_player=False,
        alive=ship.alive,
    )


def _blip_view(ship: Ship, position: Vector2D) -> ShipView:
    return ShipView(
        id=ship.id,
        label="?",
        name="Unknown contact",
        faction=ship.faction,
        class_letter="?",
        position=position,
        heading=None,
        detection=DetectionLevel.BLIP,
        is_player=False,
        alive=True,
    )
