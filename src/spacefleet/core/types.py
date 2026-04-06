"""Core types for Spacefleet Combat."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Faction(Enum):
    IMPERIAL_NAVY = "imperial_navy"
    CHAOS_FLEET = "chaos_fleet"


class ShipClass(Enum):
    ESCORT = "escort"
    LIGHT_CRUISER = "light_cruiser"
    CRUISER = "cruiser"
    BATTLECRUISER = "battlecruiser"
    BATTLESHIP = "battleship"


class WeaponType(Enum):
    BATTERY = "battery"
    LANCE = "lance"
    TORPEDO = "torpedo"
    NOVA_CANNON = "nova_cannon"


class WeaponSize(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    TORPEDO = "torpedo"
    SPECIAL = "special"


class Arc(Enum):
    PROW = "prow"
    PORT = "port"
    STARBOARD = "starboard"
    DORSAL = "dorsal"
    AFT = "aft"


class DetectionLevel(Enum):
    UNDETECTED = 0
    BLIP = 1
    CONTACT = 2
    IDENTIFIED = 3


class ActionType(Enum):
    SHOOT = "shoot"
    MOVE_AHEAD = "move_ahead"
    STOP = "stop"
    TURN = "turn"
    PASS = "pass"


# ---------------------------------------------------------------------------
# Vector2D
# ---------------------------------------------------------------------------


@dataclass
class Vector2D:
    """2D vector / point on the battlefield."""

    x: float
    y: float

    # -- arithmetic --

    def __add__(self, other: Vector2D) -> Vector2D:
        return Vector2D(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vector2D) -> Vector2D:
        return Vector2D(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vector2D:
        return Vector2D(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vector2D:
        return self.__mul__(scalar)

    # -- queries --

    def length(self) -> float:
        return math.sqrt(self.x**2 + self.y**2)

    def distance_to(self, other: Vector2D) -> float:
        return (other - self).length()

    def normalized(self) -> Vector2D:
        mag = self.length()
        if mag == 0:
            return Vector2D(0.0, 0.0)
        return Vector2D(self.x / mag, self.y / mag)

    def __repr__(self) -> str:
        return f"({self.x:.1f}, {self.y:.1f})"


# ---------------------------------------------------------------------------
# Heading / angle helpers
# ---------------------------------------------------------------------------


def heading_to_vector(heading_degrees: float) -> Vector2D:
    """Convert heading (0° = north / +Y, clockwise) to a unit direction vector."""
    rad = math.radians(heading_degrees)
    return Vector2D(math.sin(rad), math.cos(rad))


def normalize_angle(degrees: float) -> float:
    """Normalize an angle into the [0, 360) range."""
    return degrees % 360
