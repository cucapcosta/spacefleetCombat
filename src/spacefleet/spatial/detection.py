"""Sensor detection — computes what an observer can see.

Pure functions with no I/O.  The CLI layer calls these to determine
what detection level an observer has on each target, then adjusts
the display accordingly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.core.types import DetectionLevel, Vector2D
from spacefleet.spatial.geometry import bearing_from_to, distance

if TYPE_CHECKING:
    from spacefleet.dice import DiceRoller
    from spacefleet.models.ship import Ship


def compute_detection_level(
    observer: Ship,
    target: Ship,
    *,
    force_min_level: DetectionLevel | None = None,
) -> DetectionLevel:
    """Compute what detection level *observer* has on *target*.

    Thresholds are fractions of the observer's ``sensor_range``:

    * **IDENTIFIED** — distance ≤ 75 %
    * **CONTACT**    — distance ≤ 100 %
    * **BLIP**       — distance ≤ 150 %
    * **UNDETECTED** — beyond 150 %

    If *force_min_level* is given and its value exceeds the computed
    level (e.g. fire-flash forces at least CONTACT), the higher level
    is returned instead.
    """
    dist = distance(observer.position, target.position)

    # Stance modifiers on detection range
    from spacefleet.data.stance_registry import StanceRegistry

    observer_mod = StanceRegistry.get_for(observer.stance).own_sensor_range_modifier
    target_mod = StanceRegistry.get_for(target.stance).detection_signature_modifier
    sr = observer.hull.sensor_range * observer_mod * target_mod

    if dist <= sr * 0.75:
        level = DetectionLevel.IDENTIFIED
    elif dist <= sr:
        level = DetectionLevel.CONTACT
    elif dist <= sr * 1.5:
        level = DetectionLevel.BLIP
    else:
        level = DetectionLevel.UNDETECTED

    if force_min_level is not None and force_min_level.value > level.value:
        level = force_min_level

    return level


def best_detection_level(
    observers: list[Ship],
    target: Ship,
    *,
    force_min_level: DetectionLevel | None = None,
) -> DetectionLevel:
    """Return the best detection level *any* observer has on *target*.

    Used for sensor sharing — all ships controlled by the same player
    pool their sensor data.  The returned level is the highest (most
    detailed) across all observers.
    """
    best = DetectionLevel.UNDETECTED
    for obs in observers:
        level = compute_detection_level(obs, target, force_min_level=force_min_level)
        if level.value > best.value:
            best = level
            if best == DetectionLevel.IDENTIFIED:
                break  # can't do better
    return best


def jitter_position(
    true_position: Vector2D,
    dice_roller: DiceRoller,
    jitter_radius: float = 10.0,
) -> Vector2D:
    """Return an approximate position within *jitter_radius* of the true one.

    Used to represent BLIP-level contacts whose position is uncertain.
    """
    angle_rad = math.radians(dice_roller.uniform(0.0, 360.0))
    dist = dice_roller.uniform(0.0, jitter_radius)
    return Vector2D(
        x=true_position.x + math.cos(angle_rad) * dist,
        y=true_position.y + math.sin(angle_rad) * dist,
    )


@dataclass
class ContactInfo:
    """Detection-aware view of a target as seen by an observer."""

    ship: Ship
    detection_level: DetectionLevel
    true_distance: float
    true_bearing: float
    display_position: Vector2D  # jittered for BLIP, true for CONTACT/IDENTIFIED
    display_name: str  # "Unknown contact" / "Escort-class" / full name
    targetable: bool  # False for BLIP, UNDETECTED, and friendlies
    accuracy_penalty: bool  # True for CONTACT (future use)
    is_friendly: bool = False  # True for same-faction ships (own fleet + allies)


def build_contact_info(
    observer: Ship,
    target: Ship,
    dice_roller: DiceRoller,
    *,
    force_min_level: DetectionLevel | None = None,
) -> ContactInfo | None:
    """Build a :class:`ContactInfo` for *target* as seen by *observer*.

    Returns ``None`` if the target is UNDETECTED.
    """
    level = compute_detection_level(
        observer,
        target,
        force_min_level=force_min_level,
    )

    if level == DetectionLevel.UNDETECTED:
        return None

    true_dist = distance(observer.position, target.position)
    true_brg = bearing_from_to(observer.position, target.position)

    if level == DetectionLevel.BLIP:
        return ContactInfo(
            ship=target,
            detection_level=level,
            true_distance=true_dist,
            true_bearing=true_brg,
            display_position=jitter_position(target.position, dice_roller),
            display_name="Unknown contact",
            targetable=False,
            accuracy_penalty=False,
        )

    if level == DetectionLevel.CONTACT:
        class_label = target.hull.classification.value.replace("_", " ").title()
        return ContactInfo(
            ship=target,
            detection_level=level,
            true_distance=true_dist,
            true_bearing=true_brg,
            display_position=target.position,
            display_name=f"{class_label}-class",
            targetable=True,
            accuracy_penalty=True,
        )

    # IDENTIFIED
    return ContactInfo(
        ship=target,
        detection_level=level,
        true_distance=true_dist,
        true_bearing=true_brg,
        display_position=target.position,
        display_name=target.name,
        targetable=True,
        accuracy_penalty=False,
    )
